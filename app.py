#!/usr/bin/env python3
"""
3 Strands Cattle Co. Dashboard
A futuristic dashboard for YoLink sensors, task management, and file sharing
"""

import os
import json
import hashlib
import secrets
import time
import requests
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dashboard.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max file size

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize extensions
db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# =============================================================================
# Database Models
# =============================================================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)

    # Relationships
    tasks_created = db.relationship('Task', backref='creator', lazy=True, foreign_keys='Task.created_by')
    tasks_assigned = db.relationship('Task', backref='assignee', lazy=True, foreign_keys='Task.assigned_to')
    files = db.relationship('File', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'is_admin': self.is_admin,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None
        }


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    status = db.Column(db.String(50), default='assigned')  # assigned, in_progress, review, complete
    priority = db.Column(db.String(20), default='medium')  # low, medium, high, urgent
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    due_date = db.Column(db.DateTime)
    column_order = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'status': self.status,
            'priority': self.priority,
            'created_by': self.created_by,
            'creator_name': self.creator.username if self.creator else None,
            'assigned_to': self.assigned_to,
            'assignee_name': self.assignee.username if self.assignee else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'column_order': self.column_order
        }


# Association table for file sharing
file_shares = db.Table('file_shares',
    db.Column('file_id', db.Integer, db.ForeignKey('file.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('shared_at', db.DateTime, default=datetime.utcnow)
)


class File(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    original_filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    mime_type = db.Column(db.String(100))
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_public = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Many-to-many relationship for sharing
    shared_with = db.relationship('User', secondary=file_shares, lazy='subquery',
                                   backref=db.backref('shared_files', lazy=True))

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.original_filename,
            'file_size': self.file_size,
            'mime_type': self.mime_type,
            'owner_id': self.owner_id,
            'owner_name': self.owner.username if self.owner else None,
            'is_public': self.is_public,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'shared_with': [u.username for u in self.shared_with]
        }


class YoLinkConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    uaid = db.Column(db.String(255))
    secret_key = db.Column(db.String(255))
    access_token = db.Column(db.Text)
    token_expires = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# =============================================================================
# User Loader
# =============================================================================

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# =============================================================================
# YoLink API Integration
# =============================================================================

class YoLinkAPI:
    BASE_URL = "https://api.yosmart.com/open/yolink/v2/api"
    TOKEN_URL = "https://api.yosmart.com/open/yolink/token"

    @staticmethod
    def get_config():
        return YoLinkConfig.query.first()

    @staticmethod
    def get_access_token():
        config = YoLinkAPI.get_config()
        if not config or not config.uaid or not config.secret_key:
            return None

        # Check if token is still valid
        if config.access_token and config.token_expires:
            if datetime.utcnow() < config.token_expires - timedelta(minutes=5):
                return config.access_token

        # Get new token
        try:
            response = requests.post(
                YoLinkAPI.TOKEN_URL,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                data={
                    'grant_type': 'client_credentials',
                    'client_id': config.uaid,
                    'client_secret': config.secret_key
                },
                timeout=30
            )

            if response.status_code == 200:
                data = response.json()
                config.access_token = data.get('access_token')
                expires_in = data.get('expires_in', 7200)
                config.token_expires = datetime.utcnow() + timedelta(seconds=expires_in)
                db.session.commit()
                return config.access_token
        except Exception as e:
            print(f"Error getting YoLink token: {e}")

        return None

    @staticmethod
    def api_request(method, params=None):
        token = YoLinkAPI.get_access_token()
        if not token:
            return {'error': 'YoLink not configured or authentication failed'}

        try:
            payload = {
                'method': method,
                'time': int(time.time() * 1000)
            }
            if params:
                payload.update(params)

            response = requests.post(
                YoLinkAPI.BASE_URL,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {token}'
                },
                json=payload,
                timeout=30
            )

            return response.json()
        except Exception as e:
            return {'error': str(e)}

    @staticmethod
    def get_home_info():
        return YoLinkAPI.api_request('Home.getGeneralInfo')

    @staticmethod
    def get_device_list():
        return YoLinkAPI.api_request('Home.getDeviceList')

    @staticmethod
    def get_device_state(device_id, device_type):
        return YoLinkAPI.api_request(f'{device_type}.getState', {
            'targetDevice': device_id
        })


# =============================================================================
# Routes - Authentication
# =============================================================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        data = request.get_json() if request.is_json else request.form
        username = data.get('username')
        password = data.get('password')

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)

            if request.is_json:
                return jsonify({'success': True, 'redirect': url_for('dashboard')})
            return redirect(url_for('dashboard'))

        if request.is_json:
            return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
        flash('Invalid username or password', 'error')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password required'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Username already exists'}), 400

    user = User(username=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'success': True, 'message': 'User registered successfully'})


# =============================================================================
# Routes - Dashboard
# =============================================================================

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)


# =============================================================================
# Routes - User Management (Admin)
# =============================================================================

@app.route('/api/users', methods=['GET'])
@login_required
def get_users():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    users = User.query.all()
    return jsonify([u.to_dict() for u in users])


@app.route('/api/users/list', methods=['GET'])
@login_required
def get_users_list():
    """Get list of users for task assignment"""
    users = User.query.all()
    return jsonify([{'id': u.id, 'username': u.username} for u in users])


@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    if user_id == current_user.id:
        return jsonify({'error': 'Cannot delete yourself'}), 400

    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()

    return jsonify({'success': True, 'message': 'User deleted'})


@app.route('/api/users/<int:user_id>/admin', methods=['PUT'])
@login_required
def toggle_admin(user_id):
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    user = User.query.get_or_404(user_id)
    data = request.get_json()
    user.is_admin = data.get('is_admin', False)
    db.session.commit()

    return jsonify({'success': True, 'user': user.to_dict()})


# =============================================================================
# Routes - Tasks (Trello-like)
# =============================================================================

@app.route('/api/tasks', methods=['GET'])
@login_required
def get_tasks():
    tasks = Task.query.order_by(Task.column_order).all()
    return jsonify([t.to_dict() for t in tasks])


@app.route('/api/tasks', methods=['POST'])
@login_required
def create_task():
    data = request.get_json()

    task = Task(
        title=data.get('title'),
        description=data.get('description'),
        status=data.get('status', 'assigned'),
        priority=data.get('priority', 'medium'),
        created_by=current_user.id,
        assigned_to=data.get('assigned_to'),
        due_date=datetime.fromisoformat(data['due_date']) if data.get('due_date') else None
    )

    db.session.add(task)
    db.session.commit()

    return jsonify({'success': True, 'task': task.to_dict()})


@app.route('/api/tasks/<int:task_id>', methods=['PUT'])
@login_required
def update_task(task_id):
    task = Task.query.get_or_404(task_id)
    data = request.get_json()

    if 'title' in data:
        task.title = data['title']
    if 'description' in data:
        task.description = data['description']
    if 'status' in data:
        task.status = data['status']
    if 'priority' in data:
        task.priority = data['priority']
    if 'assigned_to' in data:
        task.assigned_to = data['assigned_to']
    if 'due_date' in data:
        task.due_date = datetime.fromisoformat(data['due_date']) if data['due_date'] else None
    if 'column_order' in data:
        task.column_order = data['column_order']

    db.session.commit()

    return jsonify({'success': True, 'task': task.to_dict()})


@app.route('/api/tasks/<int:task_id>', methods=['DELETE'])
@login_required
def delete_task(task_id):
    task = Task.query.get_or_404(task_id)
    db.session.delete(task)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Task deleted'})


# =============================================================================
# Routes - File Management
# =============================================================================

ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'zip'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/api/files', methods=['GET'])
@login_required
def get_files():
    # Get user's own files
    own_files = File.query.filter_by(owner_id=current_user.id).all()

    # Get files shared with user
    shared_files = current_user.shared_files

    # Get public files
    public_files = File.query.filter_by(is_public=True).filter(File.owner_id != current_user.id).all()

    return jsonify({
        'own_files': [f.to_dict() for f in own_files],
        'shared_files': [f.to_dict() for f in shared_files],
        'public_files': [f.to_dict() for f in public_files]
    })


@app.route('/api/files/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    if file and allowed_file(file.filename):
        original_filename = secure_filename(file.filename)
        # Create unique filename
        unique_filename = f"{secrets.token_hex(16)}_{original_filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
        file.save(filepath)

        file_size = os.path.getsize(filepath)

        new_file = File(
            filename=unique_filename,
            original_filename=original_filename,
            file_size=file_size,
            mime_type=file.content_type,
            owner_id=current_user.id
        )

        db.session.add(new_file)
        db.session.commit()

        return jsonify({'success': True, 'file': new_file.to_dict()})

    return jsonify({'error': 'File type not allowed'}), 400


@app.route('/api/files/<int:file_id>/download')
@login_required
def download_file(file_id):
    file = File.query.get_or_404(file_id)

    # Check access
    if file.owner_id != current_user.id and not file.is_public and current_user not in file.shared_with:
        return jsonify({'error': 'Access denied'}), 403

    return send_from_directory(
        app.config['UPLOAD_FOLDER'],
        file.filename,
        as_attachment=True,
        download_name=file.original_filename
    )


@app.route('/api/files/<int:file_id>/share', methods=['POST'])
@login_required
def share_file(file_id):
    file = File.query.get_or_404(file_id)

    if file.owner_id != current_user.id:
        return jsonify({'error': 'Only owner can share'}), 403

    data = request.get_json()
    user_ids = data.get('user_ids', [])

    for user_id in user_ids:
        user = User.query.get(user_id)
        if user and user not in file.shared_with:
            file.shared_with.append(user)

    db.session.commit()

    return jsonify({'success': True, 'file': file.to_dict()})


@app.route('/api/files/<int:file_id>/public', methods=['PUT'])
@login_required
def toggle_public(file_id):
    file = File.query.get_or_404(file_id)

    if file.owner_id != current_user.id:
        return jsonify({'error': 'Only owner can change visibility'}), 403

    data = request.get_json()
    file.is_public = data.get('is_public', False)
    db.session.commit()

    return jsonify({'success': True, 'file': file.to_dict()})


@app.route('/api/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_file(file_id):
    file = File.query.get_or_404(file_id)

    if file.owner_id != current_user.id and not current_user.is_admin:
        return jsonify({'error': 'Access denied'}), 403

    # Delete physical file
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    db.session.delete(file)
    db.session.commit()

    return jsonify({'success': True, 'message': 'File deleted'})


# =============================================================================
# Routes - YoLink Sensors
# =============================================================================

@app.route('/api/yolink/config', methods=['GET'])
@login_required
def get_yolink_config():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    config = YoLinkConfig.query.first()
    if config:
        return jsonify({
            'configured': True,
            'uaid': config.uaid[:8] + '...' if config.uaid else None
        })
    return jsonify({'configured': False})


@app.route('/api/yolink/config', methods=['POST'])
@login_required
def set_yolink_config():
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    config = YoLinkConfig.query.first()

    if not config:
        config = YoLinkConfig()
        db.session.add(config)

    config.uaid = data.get('uaid')
    config.secret_key = data.get('secret_key')
    config.access_token = None  # Clear old token
    config.token_expires = None

    db.session.commit()

    return jsonify({'success': True, 'message': 'YoLink configuration saved'})


@app.route('/api/yolink/devices', methods=['GET'])
@login_required
def get_yolink_devices():
    result = YoLinkAPI.get_device_list()
    return jsonify(result)


@app.route('/api/yolink/home', methods=['GET'])
@login_required
def get_yolink_home():
    result = YoLinkAPI.get_home_info()
    return jsonify(result)


@app.route('/api/yolink/device/<device_id>/state', methods=['GET'])
@login_required
def get_device_state(device_id):
    device_type = request.args.get('type', 'THSensor')
    result = YoLinkAPI.get_device_state(device_id, device_type)
    return jsonify(result)


# =============================================================================
# Initialize Database
# =============================================================================

def init_db():
    with app.app_context():
        db.create_all()

        # Create default admin user if not exists
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', is_admin=True)
            admin.set_password('admin')
            db.session.add(admin)
            db.session.commit()
            print("Created default admin user (admin/admin)")


# =============================================================================
# Main
# =============================================================================

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
