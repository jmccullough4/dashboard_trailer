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


class SensorReading(db.Model):
    """Store sensor readings locally for history charts"""
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.String(100), nullable=False, index=True)
    device_name = db.Column(db.String(255))
    device_type = db.Column(db.String(50))
    temperature = db.Column(db.Float)
    humidity = db.Column(db.Float)
    battery = db.Column(db.Integer)
    signal = db.Column(db.Integer)
    state = db.Column(db.String(50))
    online = db.Column(db.Boolean, default=True)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'device_id': self.device_id,
            'device_name': self.device_name,
            'device_type': self.device_type,
            'temperature': self.temperature,
            'humidity': self.humidity,
            'battery': self.battery,
            'signal': self.signal,
            'state': self.state,
            'online': self.online,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None
        }


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
    def api_request(method, params=None, target_device=None):
        token = YoLinkAPI.get_access_token()
        if not token:
            return {'error': 'YoLink not configured or authentication failed'}

        try:
            payload = {
                'method': method,
                'time': int(time.time() * 1000)
            }
            if target_device:
                payload['targetDevice'] = target_device
            if params:
                payload['params'] = params

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
    def get_device_state(device_id, device_token, device_type):
        """Get device state with proper targetDevice format"""
        target_device = {
            'deviceId': device_id,
            'token': device_token
        }
        return YoLinkAPI.api_request(f'{device_type}.getState', target_device=target_device)


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
    """Get all devices with their current state"""
    result = YoLinkAPI.get_device_list()

    if 'error' in result:
        return jsonify(result)

    # Process devices and fetch their states
    if result.get('data') and result['data'].get('devices'):
        devices = result['data']['devices']
        enhanced_devices = []

        for device in devices:
            device_id = device.get('deviceId')
            device_token = device.get('token')
            device_type = device.get('type', 'THSensor')
            device_name = device.get('name', 'Unknown')

            # Fetch current state for each device
            state_result = YoLinkAPI.get_device_state(device_id, device_token, device_type)

            device_info = {
                'deviceId': device_id,
                'token': device_token,
                'name': device_name,
                'type': device_type,
                'modelName': device.get('modelName'),
                'online': False,
                'state': {}
            }

            # Extract state data - if we successfully get state, device is online
            if state_result.get('code') == '000000' and state_result.get('data'):
                state_data = state_result['data']
                state = state_data.get('state', {})
                device_info['state'] = state

                # Device is online if we got valid state data
                # Check multiple possible online indicators
                if 'online' in state:
                    device_info['online'] = state['online']
                elif state:
                    # If we have state data with readings, device is online
                    device_info['online'] = True

                # Also check reportAt - if recent, device is online
                report_at = state_data.get('reportAt') or state.get('reportAt')
                if report_at:
                    device_info['reportAt'] = report_at

                # Store reading in database for history
                store_sensor_reading(device_id, device_name, device_type, state)

            enhanced_devices.append(device_info)

        result['data']['devices'] = enhanced_devices

    return jsonify(result)


@app.route('/api/yolink/debug/<device_id>', methods=['GET'])
@login_required
def debug_device(device_id):
    """Debug endpoint to see raw API response for a device"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    device_token = request.args.get('token')
    device_type = request.args.get('type', 'THSensor')

    if not device_token:
        # Try to find the device in the device list
        device_list = YoLinkAPI.get_device_list()
        if device_list.get('data') and device_list['data'].get('devices'):
            for d in device_list['data']['devices']:
                if d.get('deviceId') == device_id:
                    device_token = d.get('token')
                    device_type = d.get('type', device_type)
                    break

    if not device_token:
        return jsonify({'error': 'Device not found or token not provided'}), 404

    state_result = YoLinkAPI.get_device_state(device_id, device_token, device_type)

    return jsonify({
        'device_id': device_id,
        'device_type': device_type,
        'raw_response': state_result
    })


@app.route('/api/yolink/debug', methods=['GET'])
@login_required
def debug_all_devices():
    """Debug endpoint to see all devices and their raw state responses"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    device_list = YoLinkAPI.get_device_list()

    if 'error' in device_list:
        return jsonify(device_list)

    debug_info = {
        'device_list_response': device_list,
        'devices_detail': []
    }

    if device_list.get('data') and device_list['data'].get('devices'):
        for device in device_list['data']['devices']:
            device_id = device.get('deviceId')
            device_token = device.get('token')
            device_type = device.get('type', 'THSensor')

            state_result = YoLinkAPI.get_device_state(device_id, device_token, device_type)

            debug_info['devices_detail'].append({
                'device_id': device_id,
                'name': device.get('name'),
                'type': device_type,
                'token': device_token[:10] + '...' if device_token else None,
                'state_response': state_result
            })

    return jsonify(debug_info)


def store_sensor_reading(device_id, device_name, device_type, state):
    """Store a sensor reading for history tracking"""
    try:
        # Check if we already have a recent reading (within 5 minutes)
        recent = SensorReading.query.filter(
            SensorReading.device_id == device_id,
            SensorReading.recorded_at > datetime.utcnow() - timedelta(minutes=5)
        ).first()

        if recent:
            return  # Skip if recent reading exists

        reading = SensorReading(
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            temperature=state.get('temperature'),
            humidity=state.get('humidity'),
            battery=state.get('battery'),
            signal=state.get('loraInfo', {}).get('signal') if isinstance(state.get('loraInfo'), dict) else None,
            state=state.get('state') or state.get('alertType'),
            online=state.get('online', True)
        )
        db.session.add(reading)
        db.session.commit()
    except Exception as e:
        print(f"Error storing sensor reading: {e}")
        db.session.rollback()


@app.route('/api/yolink/home', methods=['GET'])
@login_required
def get_yolink_home():
    result = YoLinkAPI.get_home_info()
    return jsonify(result)


@app.route('/api/yolink/device/<device_id>/state', methods=['GET'])
@login_required
def get_device_state_route(device_id):
    device_token = request.args.get('token')
    device_type = request.args.get('type', 'THSensor')

    if not device_token:
        return jsonify({'error': 'Device token required'}), 400

    result = YoLinkAPI.get_device_state(device_id, device_token, device_type)
    return jsonify(result)


@app.route('/api/yolink/device/<device_id>/history', methods=['GET'])
@login_required
def get_device_history(device_id):
    """Get historical readings for a device"""
    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 500, type=int)

    # Cap at reasonable limits
    hours = min(hours, 168)  # Max 1 week
    limit = min(limit, 1000)

    since = datetime.utcnow() - timedelta(hours=hours)

    readings = SensorReading.query.filter(
        SensorReading.device_id == device_id,
        SensorReading.recorded_at > since
    ).order_by(SensorReading.recorded_at.asc()).limit(limit).all()

    return jsonify({
        'device_id': device_id,
        'hours': hours,
        'count': len(readings),
        'readings': [r.to_dict() for r in readings]
    })


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
