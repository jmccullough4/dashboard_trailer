#!/usr/bin/env python3
"""
3 Strands Cattle Co. Dashboard
A futuristic dashboard for YoLink sensors, task management, and file sharing
"""

import os
import io
import json
import hashlib
import secrets
import time
import requests
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, send_from_directory, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# PDF Generation imports
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False

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
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    first_name = db.Column(db.String(80), nullable=True)
    last_name = db.Column(db.String(80), nullable=True)
    phone = db.Column(db.String(20), nullable=True)
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

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        elif self.first_name:
            return self.first_name
        return self.username

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'phone': self.phone,
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


class EcoFlowConfig(db.Model):
    """EcoFlow API configuration"""
    id = db.Column(db.Integer, primary_key=True)
    access_key = db.Column(db.String(255))
    secret_key = db.Column(db.String(255))
    device_sn = db.Column(db.String(100))  # Device serial number
    device_name = db.Column(db.String(255), default='Delta 2 Max')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class EcoFlowReading(db.Model):
    """Store EcoFlow battery readings for history"""
    id = db.Column(db.Integer, primary_key=True)
    device_sn = db.Column(db.String(100), nullable=False, index=True)
    soc = db.Column(db.Integer)  # Battery percentage
    watts_in = db.Column(db.Integer)  # Input power (charging)
    watts_out = db.Column(db.Integer)  # Output power (discharging)
    ac_out_watts = db.Column(db.Integer)  # AC output power
    ac_enabled = db.Column(db.Boolean)  # AC output enabled
    remain_time = db.Column(db.Integer)  # Remaining time in minutes
    battery_temp = db.Column(db.Integer)  # Battery temperature
    solar_in_watts = db.Column(db.Integer)  # Solar input power
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            'id': self.id,
            'device_sn': self.device_sn,
            'soc': self.soc,
            'watts_in': self.watts_in,
            'watts_out': self.watts_out,
            'ac_out_watts': self.ac_out_watts,
            'ac_enabled': self.ac_enabled,
            'remain_time': self.remain_time,
            'battery_temp': self.battery_temp,
            'solar_in_watts': self.solar_in_watts,
            'recorded_at': self.recorded_at.isoformat() if self.recorded_at else None
        }


class SquareConfig(db.Model):
    """Square API configuration"""
    id = db.Column(db.Integer, primary_key=True)
    access_token = db.Column(db.String(255))
    location_id = db.Column(db.String(100))
    environment = db.Column(db.String(20), default='production')  # sandbox or production
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppFlashSale(db.Model):
    """Flash sales pushed to the mobile app"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    cut_type = db.Column(db.String(50), default='Custom Box')
    original_price = db.Column(db.Float, nullable=False)
    sale_price = db.Column(db.Float, nullable=False)
    weight_lbs = db.Column(db.Float, default=1.0)
    starts_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    image_system_name = db.Column(db.String(100), default='flame.fill')
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description or '',
            'cut_type': self.cut_type,
            'original_price': self.original_price,
            'sale_price': self.sale_price,
            'weight_lbs': self.weight_lbs,
            'starts_at': self.starts_at.isoformat() if self.starts_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'image_system_name': self.image_system_name,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class PopUpLocation(db.Model):
    """Pop-up locations / farmers market events"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    location = db.Column(db.String(500), nullable=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime)
    icon = db.Column(db.String(100), default='leaf.fill')
    is_recurring = db.Column(db.Boolean, default=False)
    recurrence_rule = db.Column(db.String(50))  # e.g. 'weekly_sunday', 'weekly_friday'
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'location': self.location,
            'latitude': self.latitude,
            'longitude': self.longitude,
            'date': self.date.isoformat() if self.date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'icon': self.icon,
            'is_recurring': self.is_recurring,
            'recurrence_rule': self.recurrence_rule,
            'is_active': self.is_active
        }


class DeviceToken(db.Model):
    """Push notification device tokens"""
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(500), unique=True, nullable=False)
    platform = db.Column(db.String(20), default='ios')
    is_active = db.Column(db.Boolean, default=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)


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
    def api_request(method, params=None, target_device=None, device_token=None):
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
            if device_token:
                payload['token'] = device_token
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
        """Get device state using correct YoLink API v2 format.

        Per YoLink API: targetDevice is just the deviceId string,
        and token is a separate field at the root level of the payload.
        """
        return YoLinkAPI.api_request(
            f'{device_type}.getState',
            target_device=device_id,  # Just the deviceId string
            device_token=device_token  # Token as separate root field
        )


# =============================================================================
# EcoFlow API Integration
# =============================================================================

class EcoFlowAPI:
    """EcoFlow Developer API integration for Delta 2 Max"""
    BASE_URL = "https://api.ecoflow.com/iot-open/sign/device/quota"

    @staticmethod
    def get_config():
        return EcoFlowConfig.query.first()

    @staticmethod
    def get_all_configs():
        return EcoFlowConfig.query.all()

    @staticmethod
    def get_config_by_id(config_id):
        return EcoFlowConfig.query.get(config_id)

    @staticmethod
    def generate_signature(access_key, secret_key, nonce, timestamp):
        """Generate HMAC signature for EcoFlow API authentication"""
        import hmac
        # EcoFlow uses a specific signing method
        sign_str = f"accessKey={access_key}&nonce={nonce}&timestamp={timestamp}"
        signature = hmac.new(
            secret_key.encode('utf-8'),
            sign_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    @staticmethod
    def get_all_quotas(config=None):
        """Get all device quotas (full status)"""
        if config is None:
            config = EcoFlowAPI.get_config()
        if not config or not config.access_key or not config.secret_key or not config.device_sn:
            return {'error': 'EcoFlow not configured', 'configured': False}

        try:
            import time
            nonce = str(int(time.time() * 1000))
            timestamp = str(int(time.time() * 1000))

            signature = EcoFlowAPI.generate_signature(
                config.access_key, config.secret_key, nonce, timestamp
            )

            headers = {
                'Content-Type': 'application/json',
                'accessKey': config.access_key,
                'nonce': nonce,
                'timestamp': timestamp,
                'sign': signature
            }

            response = requests.get(
                f"{EcoFlowAPI.BASE_URL}/all",
                headers=headers,
                params={'sn': config.device_sn},
                timeout=30
            )

            data = response.json()

            # Store reading if successful
            if data.get('code') == '0' and data.get('data'):
                EcoFlowAPI.store_reading(config.device_sn, data['data'])

            return data
        except requests.exceptions.RequestException as e:
            return {'error': f'Network error: {str(e)}', 'configured': True}
        except Exception as e:
            return {'error': str(e), 'configured': True}

    @staticmethod
    def get_quotas(quotas_list, config=None):
        """Get specific quotas from device"""
        if config is None:
            config = EcoFlowAPI.get_config()
        if not config or not config.access_key or not config.secret_key or not config.device_sn:
            return {'error': 'EcoFlow not configured', 'configured': False}

        try:
            import time
            nonce = str(int(time.time() * 1000))
            timestamp = str(int(time.time() * 1000))

            signature = EcoFlowAPI.generate_signature(
                config.access_key, config.secret_key, nonce, timestamp
            )

            headers = {
                'Content-Type': 'application/json',
                'accessKey': config.access_key,
                'nonce': nonce,
                'timestamp': timestamp,
                'sign': signature
            }

            payload = {
                'sn': config.device_sn,
                'params': {
                    'quotas': quotas_list
                }
            }

            response = requests.get(
                EcoFlowAPI.BASE_URL,
                headers=headers,
                json=payload,
                timeout=30
            )

            return response.json()
        except Exception as e:
            return {'error': str(e), 'configured': True}

    @staticmethod
    def set_quota(module_type, operate_type, params, config=None):
        """Set device quota (control device)"""
        if config is None:
            config = EcoFlowAPI.get_config()
        if not config or not config.access_key or not config.secret_key or not config.device_sn:
            return {'error': 'EcoFlow not configured', 'configured': False}

        try:
            import time
            nonce = str(int(time.time() * 1000))
            timestamp = str(int(time.time() * 1000))

            signature = EcoFlowAPI.generate_signature(
                config.access_key, config.secret_key, nonce, timestamp
            )

            headers = {
                'Content-Type': 'application/json',
                'accessKey': config.access_key,
                'nonce': nonce,
                'timestamp': timestamp,
                'sign': signature
            }

            payload = {
                'id': int(time.time()),
                'sn': config.device_sn,
                'version': '1.0',
                'moduleType': module_type,
                'operateType': operate_type,
                'params': params
            }

            response = requests.put(
                EcoFlowAPI.BASE_URL,
                headers=headers,
                json=payload,
                timeout=30
            )

            return response.json()
        except Exception as e:
            return {'error': str(e), 'configured': True}

    @staticmethod
    def store_reading(device_sn, data):
        """Store EcoFlow reading in database"""
        try:
            reading = EcoFlowReading(
                device_sn=device_sn,
                soc=data.get('pd.soc') or data.get('bms_bmsStatus.soc'),
                watts_in=data.get('pd.wattsInSum'),
                watts_out=data.get('pd.wattsOutSum'),
                ac_out_watts=data.get('inv.outputWatts'),
                ac_enabled=data.get('inv.cfgAcEnabled') == 1,
                remain_time=data.get('pd.remainTime'),
                battery_temp=data.get('bms_bmsStatus.temp'),
                solar_in_watts=data.get('mppt.inWatts')
            )
            db.session.add(reading)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Error storing EcoFlow reading: {e}")

    @staticmethod
    def parse_status(data):
        """Parse raw EcoFlow data into a user-friendly format"""
        if not data or 'error' in data:
            return data

        raw = data.get('data', data)

        # Calculate remaining time display
        remain_time = raw.get('pd.remainTime', 0)
        if remain_time and remain_time != 5999:
            hours = abs(remain_time) // 60
            mins = abs(remain_time) % 60
            if remain_time > 0:
                time_display = f"{hours}h {mins}m until full"
            else:
                time_display = f"{hours}h {mins}m remaining"
        else:
            time_display = "Calculating..."

        # Determine charging/discharging state
        watts_in = raw.get('pd.wattsInSum', 0)
        watts_out = raw.get('pd.wattsOutSum', 0)
        if watts_in > watts_out:
            state = 'charging'
        elif watts_out > 0:
            state = 'discharging'
        else:
            state = 'idle'

        return {
            'configured': True,
            'online': True,
            'soc': raw.get('pd.soc', 0),
            'watts_in': watts_in,
            'watts_out': watts_out,
            'state': state,
            'remain_time': remain_time,
            'remain_time_display': time_display,
            'ac_enabled': raw.get('inv.cfgAcEnabled', 0) == 1,
            'ac_output_watts': raw.get('inv.outputWatts', 0),
            'ac_xboost': raw.get('inv.cfgAcXboost', 0) == 1,
            'dc_enabled': raw.get('pd.dcOutState', 0) == 1,
            'battery_temp': raw.get('bms_bmsStatus.temp'),
            'inv_temp': raw.get('inv.outTemp'),
            'solar_in_watts': raw.get('mppt.inWatts', 0),
            'solar_in_volts': (raw.get('mppt.inVol', 0) or 0) / 10,
            'car_out_watts': raw.get('mppt.carOutWatts', 0),
            'car_state': raw.get('mppt.carState', 0) == 1,
            'beep_mode': raw.get('pd.beepMode', 0) == 0,  # 0 = normal, 1 = mute
            'brightness': raw.get('pd.brightLevel', 3),
            'standby_min': raw.get('pd.standbyMin', 0),
            'fast_charge_watts': raw.get('inv.FastChgWatts', 0),
            'slow_charge_watts': raw.get('inv.SlowChgWatts', 0),
            'max_charge_soc': raw.get('bms_emsStatus.maxChargeSoc', 100),
            'min_discharge_soc': raw.get('bms_emsStatus.minDsgSoc', 0),
            'backup_reserve': raw.get('pd.bpPowerSoc', 0)
        }


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
        login_id = data.get('username')  # Can be username or email
        password = data.get('password')

        # Try to find user by username or email
        user = User.query.filter_by(username=login_id).first()
        if not user:
            user = User.query.filter_by(email=login_id).first()

        if user and user.check_password(password):
            user.last_login = datetime.utcnow()
            db.session.commit()
            login_user(user)

            if request.is_json:
                return jsonify({'success': True, 'redirect': url_for('dashboard')})
            return redirect(url_for('dashboard'))

        if request.is_json:
            return jsonify({'success': False, 'error': 'Invalid credentials'}), 401
        flash('Invalid username/email or password', 'error')

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
    email = data.get('email')
    first_name = data.get('first_name')
    last_name = data.get('last_name')
    phone = data.get('phone')

    if not username or not password:
        return jsonify({'success': False, 'error': 'Username and password required'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'Username already exists'}), 400

    if email and User.query.filter_by(email=email).first():
        return jsonify({'success': False, 'error': 'Email already exists'}), 400

    user = User(
        username=username,
        email=email if email else None,
        first_name=first_name,
        last_name=last_name,
        phone=phone
    )
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


@app.route('/api/users/<int:user_id>', methods=['GET'])
@login_required
def get_user(user_id):
    """Get a single user's details"""
    if not current_user.is_admin and current_user.id != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    """Update an existing user's details"""
    if not current_user.is_admin and current_user.id != user_id:
        return jsonify({'error': 'Unauthorized'}), 403

    user = User.query.get_or_404(user_id)
    data = request.get_json()

    # Update allowed fields
    if 'first_name' in data:
        user.first_name = data['first_name']
    if 'last_name' in data:
        user.last_name = data['last_name']
    if 'email' in data:
        # Check for duplicate email
        if data['email'] and data['email'] != user.email:
            existing = User.query.filter_by(email=data['email']).first()
            if existing and existing.id != user_id:
                return jsonify({'success': False, 'error': 'Email already in use'}), 400
        user.email = data['email'] if data['email'] else None
    if 'phone' in data:
        user.phone = data['phone']

    # Only admin can change username
    if current_user.is_admin and 'username' in data:
        if data['username'] != user.username:
            existing = User.query.filter_by(username=data['username']).first()
            if existing and existing.id != user_id:
                return jsonify({'success': False, 'error': 'Username already in use'}), 400
            user.username = data['username']

    # Password change (optional)
    if 'password' in data and data['password']:
        user.set_password(data['password'])

    db.session.commit()

    return jsonify({'success': True, 'user': user.to_dict(), 'message': 'User updated successfully'})


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

                # Check online status at multiple levels (Hub has it at data level, sensors in state)
                if state_data.get('online') is not None:
                    device_info['online'] = state_data['online']
                elif state.get('online') is not None:
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
# Routes - EcoFlow Power Station
# =============================================================================

@app.route('/api/ecoflow/config', methods=['GET'])
@login_required
def get_ecoflow_config():
    """Get all EcoFlow configurations"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    configs = EcoFlowConfig.query.all()
    if configs:
        return jsonify({
            'configured': True,
            'devices': [{
                'id': c.id,
                'device_sn': c.device_sn,
                'device_name': c.device_name,
                'has_access_key': bool(c.access_key),
                'has_secret_key': bool(c.secret_key)
            } for c in configs]
        })
    return jsonify({'configured': False, 'devices': []})


@app.route('/api/ecoflow/config', methods=['POST'])
@login_required
def save_ecoflow_config():
    """Save EcoFlow configuration (create or update)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    config_id = data.get('id')

    if config_id:
        config = EcoFlowConfig.query.get(config_id)
        if not config:
            return jsonify({'error': 'Device not found'}), 404
    else:
        config = EcoFlowConfig()
        db.session.add(config)

    if 'access_key' in data and data['access_key']:
        config.access_key = data['access_key']
    if 'secret_key' in data and data['secret_key']:
        config.secret_key = data['secret_key']
    if 'device_sn' in data:
        config.device_sn = data['device_sn']
    if 'device_name' in data:
        config.device_name = data['device_name']

    db.session.commit()

    return jsonify({'success': True, 'id': config.id, 'message': 'EcoFlow configuration saved'})


@app.route('/api/ecoflow/config/<int:config_id>', methods=['DELETE'])
@login_required
def delete_ecoflow_config(config_id):
    """Delete an EcoFlow device configuration"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    config = EcoFlowConfig.query.get(config_id)
    if not config:
        return jsonify({'error': 'Device not found'}), 404

    # Also delete associated readings
    EcoFlowReading.query.filter_by(device_sn=config.device_sn).delete()
    db.session.delete(config)
    db.session.commit()

    return jsonify({'success': True, 'message': 'Device removed'})


@app.route('/api/ecoflow/status', methods=['GET'])
@login_required
def get_ecoflow_status():
    """Get status of all configured EcoFlow devices"""
    configs = EcoFlowConfig.query.all()
    if not configs:
        return jsonify({
            'configured': False,
            'devices': []
        })

    devices = []
    for config in configs:
        if not config.access_key:
            devices.append({
                'id': config.id,
                'configured': False,
                'device_name': config.device_name or 'Delta 2 Max',
                'device_sn': config.device_sn,
                'error': 'Missing API credentials'
            })
            continue

        raw_data = EcoFlowAPI.get_all_quotas(config=config)

        if 'error' in raw_data:
            devices.append({
                'id': config.id,
                'configured': True,
                'device_name': config.device_name or 'Delta 2 Max',
                'device_sn': config.device_sn,
                'error': raw_data['error'],
                'online': False
            })
            continue

        parsed = EcoFlowAPI.parse_status(raw_data)
        parsed['id'] = config.id
        parsed['device_name'] = config.device_name or 'Delta 2 Max'
        parsed['device_sn'] = config.device_sn
        devices.append(parsed)

    return jsonify({
        'configured': True,
        'devices': devices
    })


@app.route('/api/ecoflow/control/ac', methods=['POST'])
@login_required
def control_ecoflow_ac():
    """Toggle AC output on/off"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    config = EcoFlowAPI.get_config_by_id(data.get('device_id')) if data.get('device_id') else EcoFlowAPI.get_config()
    enabled = data.get('enabled', False)
    xboost = data.get('xboost', False)

    result = EcoFlowAPI.set_quota(
        module_type=3,
        operate_type='acOutCfg',
        params={
            'enabled': 1 if enabled else 0,
            'xboost': 1 if xboost else 0,
            'out_voltage': 4294967295,
            'out_freq': 2
        },
        config=config
    )

    return jsonify(result)


@app.route('/api/ecoflow/control/dc', methods=['POST'])
@login_required
def control_ecoflow_dc():
    """Toggle DC (USB) output on/off"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    config = EcoFlowAPI.get_config_by_id(data.get('device_id')) if data.get('device_id') else EcoFlowAPI.get_config()
    enabled = data.get('enabled', False)

    result = EcoFlowAPI.set_quota(
        module_type=1,
        operate_type='dcOutCfg',
        params={'enabled': 1 if enabled else 0},
        config=config
    )

    return jsonify(result)


@app.route('/api/ecoflow/control/charging', methods=['POST'])
@login_required
def control_ecoflow_charging():
    """Set charging parameters"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    config = EcoFlowAPI.get_config_by_id(data.get('device_id')) if data.get('device_id') else EcoFlowAPI.get_config()

    result = EcoFlowAPI.set_quota(
        module_type=3,
        operate_type='acChgCfg',
        params={
            'fastChgWatts': data.get('fast_charge_watts', 2400),
            'slowChgWatts': data.get('slow_charge_watts', 400),
            'chgPauseFlag': 0
        },
        config=config
    )

    return jsonify(result)


@app.route('/api/ecoflow/control/backup', methods=['POST'])
@login_required
def control_ecoflow_backup():
    """Set backup reserve level"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    data = request.get_json()
    config = EcoFlowAPI.get_config_by_id(data.get('device_id')) if data.get('device_id') else EcoFlowAPI.get_config()
    backup_soc = data.get('backup_soc', 20)

    result = EcoFlowAPI.set_quota(
        module_type=1,
        operate_type='watthConfig',
        params={
            'isConfig': 0,
            'bpPowerSoc': backup_soc,
            'minDsgSoc': 255,
            'minChgSoc': 255
        },
        config=config
    )

    return jsonify(result)


@app.route('/api/ecoflow/history', methods=['GET'])
@login_required
def get_ecoflow_history():
    """Get historical EcoFlow readings"""
    hours = request.args.get('hours', 24, type=int)
    limit = request.args.get('limit', 500, type=int)

    hours = min(hours, 168)  # Max 1 week
    limit = min(limit, 1000)

    since = datetime.utcnow() - timedelta(hours=hours)

    readings = EcoFlowReading.query.filter(
        EcoFlowReading.recorded_at > since
    ).order_by(EcoFlowReading.recorded_at.asc()).limit(limit).all()

    return jsonify({
        'hours': hours,
        'count': len(readings),
        'readings': [r.to_dict() for r in readings]
    })


@app.route('/api/reports/fda-temperature', methods=['GET'])
@login_required
def generate_fda_report():
    """Generate FDA-compliant temperature monitoring report as PDF"""
    if not PDF_AVAILABLE:
        return jsonify({'error': 'PDF generation not available. Install reportlab package.'}), 500

    # Get date range from query params
    days = request.args.get('days', 7, type=int)
    days = min(days, 365)  # Max 1 year

    since = datetime.utcnow() - timedelta(days=days)
    end_date = datetime.utcnow()

    # Get only temperature sensor readings (THSensor)
    readings = SensorReading.query.filter(
        SensorReading.recorded_at > since,
        SensorReading.device_type == 'THSensor'
    ).order_by(SensorReading.device_name, SensorReading.recorded_at).all()

    # Group readings by device
    devices = {}
    for reading in readings:
        if reading.device_name not in devices:
            devices[reading.device_name] = {
                'readings': [],
                'device_id': reading.device_id,
                'device_type': reading.device_type
            }
        devices[reading.device_name]['readings'].append(reading)

    # Create PDF in memory
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75*inch,
        leftMargin=0.75*inch,
        topMargin=0.75*inch,
        bottomMargin=0.75*inch
    )

    # Build the document
    story = []
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=6,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#8B4513')
    )

    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Normal'],
        fontSize=14,
        spaceAfter=20,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#666666')
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        spaceBefore=20,
        spaceAfter=10,
        textColor=colors.HexColor('#8B4513')
    )

    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=10,
        spaceAfter=6
    )

    # Check for logo
    logo_path = os.path.join(app.static_folder, 'logo.png')
    if os.path.exists(logo_path):
        try:
            logo = Image(logo_path, width=1.5*inch, height=1.5*inch)
            logo.hAlign = 'CENTER'
            story.append(logo)
            story.append(Spacer(1, 0.25*inch))
        except Exception:
            pass

    # Header
    story.append(Paragraph("3 STRANDS CATTLE CO.", title_style))
    story.append(Paragraph("FDA Temperature Monitoring Compliance Report", subtitle_style))

    # Report info
    report_date = datetime.now().strftime('%B %d, %Y at %I:%M %p')
    story.append(Paragraph(f"<b>Report Generated:</b> {report_date}", normal_style))
    story.append(Paragraph(f"<b>Generated By:</b> {current_user.full_name}", normal_style))
    if current_user.email:
        story.append(Paragraph(f"<b>Contact Email:</b> {current_user.email}", normal_style))
    if current_user.phone:
        story.append(Paragraph(f"<b>Contact Phone:</b> {current_user.phone}", normal_style))
    story.append(Paragraph(f"<b>Report Period:</b> {since.strftime('%B %d, %Y')} - {end_date.strftime('%B %d, %Y')} ({days} days)", normal_style))
    story.append(Paragraph(f"<b>Total Readings:</b> {len(readings)}", normal_style))
    story.append(Paragraph(f"<b>Temperature Sensors:</b> {len(devices)}", normal_style))
    story.append(Spacer(1, 0.25*inch))

    # Compliance statement
    story.append(Paragraph("COMPLIANCE STATEMENT", heading_style))
    compliance_text = """This report documents temperature monitoring data collected from sensors
    installed at 3 Strands Cattle Co. facilities. Temperature readings are automatically recorded
    and stored to ensure compliance with FDA Food Safety Modernization Act (FSMA) requirements
    for cold chain monitoring and documentation."""
    story.append(Paragraph(compliance_text, normal_style))
    story.append(Spacer(1, 0.25*inch))

    # Helper function to format temperature in both C and F
    def format_temp_dual(temp_c):
        """Format temperature showing both Celsius and Fahrenheit"""
        if temp_c is None:
            return "N/A"
        temp_f = (temp_c * 9/5) + 32
        return f"{temp_c:.1f}°C / {temp_f:.1f}°F"

    # Try to import matplotlib for graphs
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        GRAPHS_AVAILABLE = True
    except ImportError:
        GRAPHS_AVAILABLE = False

    # Device summaries
    for device_name, device_data in devices.items():
        device_readings = device_data['readings']

        if not device_readings:
            continue

        story.append(Paragraph(f"SENSOR: {device_name.upper()}", heading_style))

        # Calculate statistics (temperatures stored in Celsius)
        temps = [r.temperature for r in device_readings if r.temperature is not None]
        if temps:
            min_temp = min(temps)
            max_temp = max(temps)
            avg_temp = sum(temps) / len(temps)

            stats_data = [
                ['Statistic', 'Value'],
                ['Device ID', device_data['device_id']],
                ['Device Type', 'Temperature Sensor'],
                ['Total Readings', str(len(device_readings))],
                ['First Reading', device_readings[0].recorded_at.strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['Last Reading', device_readings[-1].recorded_at.strftime('%Y-%m-%d %H:%M:%S UTC')],
                ['Minimum Temperature', format_temp_dual(min_temp)],
                ['Maximum Temperature', format_temp_dual(max_temp)],
                ['Average Temperature', format_temp_dual(avg_temp)],
            ]

            stats_table = Table(stats_data, colWidths=[2.5*inch, 4*inch])
            stats_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#8B4513')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
                ('TOPPADDING', (0, 0), (-1, 0), 8),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#FFF8DC')),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#D2B48C')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            story.append(stats_table)

            # Generate temperature graph if matplotlib is available
            if GRAPHS_AVAILABLE and len(device_readings) > 1:
                story.append(Spacer(1, 0.2*inch))
                story.append(Paragraph("<b>Temperature History Graph</b>", normal_style))

                try:
                    # Create the graph
                    fig, ax = plt.subplots(figsize=(7, 3), dpi=100)

                    dates = [r.recorded_at for r in device_readings if r.temperature is not None]
                    temps_c = [r.temperature for r in device_readings if r.temperature is not None]
                    temps_f = [(t * 9/5) + 32 for t in temps_c]

                    # Plot both C and F on dual axes
                    ax.plot(dates, temps_f, color='#ff6b6b', linewidth=1.5, label='°F', marker='o', markersize=2)
                    ax.set_ylabel('Temperature (°F)', color='#ff6b6b')
                    ax.tick_params(axis='y', labelcolor='#ff6b6b')

                    # Secondary axis for Celsius
                    ax2 = ax.twinx()
                    ax2.plot(dates, temps_c, color='#00d4ff', linewidth=1.5, label='°C', linestyle='--')
                    ax2.set_ylabel('Temperature (°C)', color='#00d4ff')
                    ax2.tick_params(axis='y', labelcolor='#00d4ff')

                    # Formatting
                    ax.set_xlabel('Date/Time')
                    ax.set_title(f'{device_name} - Temperature Over Time', fontsize=10, fontweight='bold')
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M'))
                    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
                    plt.xticks(rotation=45, ha='right', fontsize=8)
                    ax.grid(True, alpha=0.3)

                    # Add legend
                    lines1, labels1 = ax.get_legend_handles_labels()
                    lines2, labels2 = ax2.get_legend_handles_labels()
                    ax.legend(lines1 + lines2, labels1 + labels2, loc='upper right', fontsize=8)

                    plt.tight_layout()

                    # Save to buffer
                    graph_buffer = io.BytesIO()
                    plt.savefig(graph_buffer, format='png', bbox_inches='tight', facecolor='white')
                    plt.close(fig)
                    graph_buffer.seek(0)

                    # Add graph to PDF
                    graph_img = Image(graph_buffer, width=6.5*inch, height=2.5*inch)
                    story.append(graph_img)
                except Exception as e:
                    story.append(Paragraph(f"<i>Graph generation failed: {str(e)}</i>", normal_style))

        # Sample of readings (last 20)
        story.append(Spacer(1, 0.15*inch))
        story.append(Paragraph("<b>Recent Temperature Readings (Sample)</b>", normal_style))

        sample_readings = device_readings[-20:] if len(device_readings) > 20 else device_readings
        readings_data = [['Date/Time (UTC)', 'Temperature', 'Humidity']]

        for reading in sample_readings:
            temp_str = format_temp_dual(reading.temperature)
            humidity_str = f"{reading.humidity}%" if reading.humidity and reading.humidity > 0 else "N/A"
            readings_data.append([
                reading.recorded_at.strftime('%Y-%m-%d %H:%M'),
                temp_str,
                humidity_str
            ])

        readings_table = Table(readings_data, colWidths=[2*inch, 2.5*inch, 2*inch])
        readings_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D2691E')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 6),
            ('TOPPADDING', (0, 0), (-1, 0), 6),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#FFFAF0')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DEB887')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.HexColor('#FFFAF0'), colors.HexColor('#FFF8DC')]),
        ]))
        story.append(readings_table)
        story.append(Spacer(1, 0.25*inch))

    # Footer
    story.append(Spacer(1, 0.5*inch))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.gray
    )
    story.append(Paragraph("─" * 80, footer_style))
    story.append(Paragraph("This report was automatically generated by 3 Strands Cattle Co. Command Center", footer_style))
    story.append(Paragraph("For questions regarding this report, please contact the generator listed above.", footer_style))

    # Build the PDF
    doc.build(story)

    # Return PDF
    buffer.seek(0)
    filename = f"FDA_Temperature_Report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

    return Response(
        buffer.getvalue(),
        mimetype='application/pdf',
        headers={
            'Content-Disposition': f'attachment; filename={filename}',
            'Content-Type': 'application/pdf'
        }
    )


# =============================================================================
# Version and Update Routes
# =============================================================================

import subprocess


def is_running_in_docker():
    """Detect if running inside a Docker container"""
    # Check for .dockerenv file
    if os.path.exists('/.dockerenv'):
        return True
    # Check cgroup for docker
    try:
        with open('/proc/1/cgroup', 'r') as f:
            return 'docker' in f.read()
    except Exception:
        pass
    return False


def get_git_version():
    """Get current git commit info"""
    in_docker = is_running_in_docker()

    try:
        # Get short commit hash
        commit_hash = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()

        # Get commit date
        commit_date = subprocess.check_output(
            ['git', 'log', '-1', '--format=%ci'],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()

        # Get branch name
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            stderr=subprocess.DEVNULL
        ).decode('utf-8').strip()

        return {
            'commit': commit_hash,
            'date': commit_date,
            'branch': branch,
            'version': f"v1.0.0-{commit_hash}",
            'docker': in_docker
        }
    except Exception as e:
        return {
            'commit': 'unknown',
            'date': 'unknown',
            'branch': 'unknown',
            'version': 'v1.0.0',
            'docker': in_docker,
            'error': str(e)
        }


@app.route('/api/version', methods=['GET'])
@login_required
def get_version():
    """Get current application version"""
    return jsonify(get_git_version())


@app.route('/api/updates/check', methods=['GET'])
@login_required
def check_for_updates():
    """Check if updates are available from GitHub"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        app_dir = os.path.dirname(os.path.abspath(__file__))

        # Fetch latest from remote
        subprocess.run(
            ['git', 'fetch', 'origin'],
            cwd=app_dir,
            capture_output=True,
            timeout=30
        )

        # Get current commit
        current = subprocess.check_output(
            ['git', 'rev-parse', 'HEAD'],
            cwd=app_dir
        ).decode('utf-8').strip()

        # Get current branch
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=app_dir
        ).decode('utf-8').strip()

        # Get remote commit
        remote = subprocess.check_output(
            ['git', 'rev-parse', f'origin/{branch}'],
            cwd=app_dir
        ).decode('utf-8').strip()

        # Check if behind
        behind_count = subprocess.check_output(
            ['git', 'rev-list', '--count', f'HEAD..origin/{branch}'],
            cwd=app_dir
        ).decode('utf-8').strip()

        # Get commit messages for pending updates
        pending_commits = []
        if int(behind_count) > 0:
            log_output = subprocess.check_output(
                ['git', 'log', '--oneline', f'HEAD..origin/{branch}'],
                cwd=app_dir
            ).decode('utf-8').strip()
            pending_commits = log_output.split('\n') if log_output else []

        return jsonify({
            'update_available': current != remote,
            'current_commit': current[:7],
            'remote_commit': remote[:7],
            'behind_count': int(behind_count),
            'branch': branch,
            'pending_commits': pending_commits
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timeout checking for updates'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/updates/apply', methods=['POST'])
@login_required
def apply_update():
    """Apply pending updates from GitHub"""
    if not current_user.is_admin:
        return jsonify({'error': 'Unauthorized'}), 403

    try:
        app_dir = os.path.dirname(os.path.abspath(__file__))

        # Pull latest changes
        result = subprocess.run(
            ['git', 'pull', 'origin'],
            cwd=app_dir,
            capture_output=True,
            timeout=60
        )

        if result.returncode != 0:
            return jsonify({
                'success': False,
                'error': result.stderr.decode('utf-8')
            }), 500

        # Get new version info
        new_version = get_git_version()

        return jsonify({
            'success': True,
            'message': 'Update applied successfully',
            'output': result.stdout.decode('utf-8'),
            'new_version': new_version,
            'restart_required': True
        })
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timeout applying update'}), 504
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =============================================================================
# Square Catalog API Integration
# =============================================================================

class SquareAPI:
    PRODUCTION_URL = "https://connect.squareup.com/v2"
    SANDBOX_URL = "https://connect.squareupsandbox.com/v2"

    @staticmethod
    def get_config():
        return SquareConfig.query.first()

    @staticmethod
    def get_base_url(config=None):
        if not config:
            config = SquareAPI.get_config()
        if config and config.environment == 'sandbox':
            return SquareAPI.SANDBOX_URL
        return SquareAPI.PRODUCTION_URL

    @staticmethod
    def get_catalog():
        config = SquareAPI.get_config()
        if not config or not config.access_token:
            return None

        base_url = SquareAPI.get_base_url(config)
        headers = {
            'Square-Version': '2024-01-18',
            'Authorization': f'Bearer {config.access_token}',
            'Content-Type': 'application/json'
        }

        try:
            # Fetch catalog items
            items = []
            cursor = None
            while True:
                params = {'types': 'ITEM'}
                if cursor:
                    params['cursor'] = cursor
                resp = requests.get(f'{base_url}/catalog/list', headers=headers, params=params, timeout=15)
                if resp.status_code != 200:
                    print(f"Square API error: {resp.status_code} {resp.text}")
                    return None
                data = resp.json()
                for obj in data.get('objects', []):
                    item_data = obj.get('item_data', {})
                    variations = []
                    for var in item_data.get('variations', []):
                        var_data = var.get('item_variation_data', {})
                        price_money = var_data.get('price_money', {})
                        variations.append({
                            'id': var.get('id', ''),
                            'name': var_data.get('name', ''),
                            'price_cents': price_money.get('amount') if price_money else None
                        })
                    items.append({
                        'id': obj.get('id', ''),
                        'name': item_data.get('name', ''),
                        'description': item_data.get('description', ''),
                        'category': item_data.get('category', {}).get('name', ''),
                        'variations': variations
                    })
                cursor = data.get('cursor')
                if not cursor:
                    break
            return items
        except Exception as e:
            print(f"Square catalog fetch error: {e}")
            return None


# =============================================================================
# Public API Endpoints (No Auth Required - for Mobile App)
# =============================================================================

@app.route('/api/public/flash-sales', methods=['GET'])
def public_flash_sales():
    """Return active flash sales for the mobile app"""
    sales = AppFlashSale.query.filter_by(is_active=True).order_by(AppFlashSale.expires_at.asc()).all()
    return jsonify([s.to_dict() for s in sales])


@app.route('/api/public/catalog', methods=['GET'])
def public_catalog():
    """Return Square catalog items for the mobile app"""
    items = SquareAPI.get_catalog()
    if items is None:
        return jsonify({'items': [], 'source': 'unavailable'})
    return jsonify({'items': items, 'source': 'square'})


@app.route('/api/public/events', methods=['GET'])
def public_events():
    """Return upcoming pop-up locations/events for the mobile app"""
    events = PopUpLocation.query.filter_by(is_active=True).filter(
        PopUpLocation.date >= datetime.utcnow()
    ).order_by(PopUpLocation.date.asc()).all()
    return jsonify([e.to_dict() for e in events])


@app.route('/api/public/register-device', methods=['POST'])
def public_register_device():
    """Register a device for push notifications"""
    data = request.get_json()
    if not data or not data.get('token'):
        return jsonify({'error': 'Token required'}), 400

    token = data['token']
    platform = data.get('platform', 'ios')

    existing = DeviceToken.query.filter_by(token=token).first()
    if existing:
        existing.last_seen = datetime.utcnow()
        existing.is_active = True
        db.session.commit()
        return jsonify({'success': True, 'status': 'updated'})

    device = DeviceToken(token=token, platform=platform)
    db.session.add(device)
    db.session.commit()
    return jsonify({'success': True, 'status': 'registered'})


# =============================================================================
# Admin: Flash Sales Management
# =============================================================================

@app.route('/api/flash-sales', methods=['GET'])
@login_required
def get_flash_sales():
    """Get all flash sales (admin view - includes inactive)"""
    sales = AppFlashSale.query.order_by(AppFlashSale.created_at.desc()).all()
    return jsonify([s.to_dict() for s in sales])


@app.route('/api/flash-sales', methods=['POST'])
@login_required
def create_flash_sale():
    """Create or update a flash sale"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    sale_id = data.get('id')
    if sale_id:
        sale = AppFlashSale.query.get(sale_id)
        if not sale:
            return jsonify({'error': 'Sale not found'}), 404
    else:
        sale = AppFlashSale()
        db.session.add(sale)

    sale.title = data.get('title', sale.title if sale_id else 'Flash Sale')
    sale.description = data.get('description', '')
    sale.cut_type = data.get('cut_type', 'Custom Box')
    sale.original_price = float(data.get('original_price', 0))
    sale.sale_price = float(data.get('sale_price', 0))
    sale.weight_lbs = float(data.get('weight_lbs', 1.0))
    sale.image_system_name = data.get('image_system_name', 'flame.fill')
    sale.is_active = data.get('is_active', True)

    if data.get('starts_at'):
        sale.starts_at = datetime.fromisoformat(data['starts_at'].replace('Z', '+00:00').replace('+00:00', ''))
    if data.get('expires_at'):
        sale.expires_at = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00').replace('+00:00', ''))
    else:
        sale.expires_at = datetime.utcnow() + timedelta(hours=24)

    db.session.commit()
    return jsonify({'success': True, 'sale': sale.to_dict()})


@app.route('/api/flash-sales/<int:sale_id>', methods=['DELETE'])
@login_required
def delete_flash_sale(sale_id):
    """Delete a flash sale"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    sale = AppFlashSale.query.get(sale_id)
    if not sale:
        return jsonify({'error': 'Sale not found'}), 404

    db.session.delete(sale)
    db.session.commit()
    return jsonify({'success': True})


# =============================================================================
# Admin: Pop-Up Locations Management
# =============================================================================

@app.route('/api/popup-locations', methods=['GET'])
@login_required
def get_popup_locations():
    """Get all pop-up locations"""
    locations = PopUpLocation.query.order_by(PopUpLocation.date.desc()).all()
    return jsonify([l.to_dict() for l in locations])


@app.route('/api/popup-locations', methods=['POST'])
@login_required
def create_popup_location():
    """Create or update a pop-up location"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    loc_id = data.get('id')
    if loc_id:
        loc = PopUpLocation.query.get(loc_id)
        if not loc:
            return jsonify({'error': 'Location not found'}), 404
    else:
        loc = PopUpLocation()
        db.session.add(loc)

    loc.title = data.get('title', loc.title if loc_id else 'Pop-Up Location')
    loc.location = data.get('location', loc.location if loc_id else '')
    if data.get('latitude') is not None:
        loc.latitude = float(data['latitude']) if data['latitude'] != '' else None
    if data.get('longitude') is not None:
        loc.longitude = float(data['longitude']) if data['longitude'] != '' else None
    loc.icon = data.get('icon', 'leaf.fill')
    loc.is_recurring = data.get('is_recurring', False)
    loc.recurrence_rule = data.get('recurrence_rule', '')
    loc.is_active = data.get('is_active', True)

    if data.get('date'):
        loc.date = datetime.fromisoformat(data['date'].replace('Z', '+00:00').replace('+00:00', ''))
    if data.get('end_date'):
        loc.end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00').replace('+00:00', ''))

    db.session.commit()
    return jsonify({'success': True, 'location': loc.to_dict()})


@app.route('/api/popup-locations/<int:loc_id>', methods=['DELETE'])
@login_required
def delete_popup_location(loc_id):
    """Delete a pop-up location"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    loc = PopUpLocation.query.get(loc_id)
    if not loc:
        return jsonify({'error': 'Location not found'}), 404

    db.session.delete(loc)
    db.session.commit()
    return jsonify({'success': True})


# =============================================================================
# Admin: Square Configuration
# =============================================================================

@app.route('/api/square/config', methods=['GET'])
@login_required
def get_square_config():
    """Get Square API configuration"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    config = SquareConfig.query.first()
    if not config:
        return jsonify({'configured': False})
    return jsonify({
        'configured': True,
        'location_id': config.location_id or '',
        'environment': config.environment,
        'has_token': bool(config.access_token)
    })


@app.route('/api/square/config', methods=['POST'])
@login_required
def save_square_config():
    """Save Square API configuration"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    data = request.get_json()
    config = SquareConfig.query.first()
    if not config:
        config = SquareConfig()
        db.session.add(config)

    if data.get('access_token'):
        config.access_token = data['access_token']
    if data.get('location_id'):
        config.location_id = data['location_id']
    if data.get('environment'):
        config.environment = data['environment']

    db.session.commit()
    return jsonify({'success': True})


@app.route('/api/geocode', methods=['POST'])
@login_required
def geocode_address():
    """Geocode an address to lat/lng using OpenStreetMap Nominatim"""
    data = request.get_json()
    address = data.get('address', '')
    if not address:
        return jsonify({'error': 'Address required'}), 400

    try:
        resp = requests.get('https://nominatim.openstreetmap.org/search', params={
            'q': address,
            'format': 'json',
            'limit': 1
        }, headers={'User-Agent': '3StrandsCattleCo-Dashboard/1.0'}, timeout=10)
        results = resp.json()
        if results:
            return jsonify({
                'success': True,
                'latitude': float(results[0]['lat']),
                'longitude': float(results[0]['lon']),
                'display_name': results[0].get('display_name', '')
            })
        return jsonify({'success': False, 'error': 'Address not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/reverse-geocode', methods=['POST'])
@login_required
def reverse_geocode():
    """Reverse geocode lat/lng to an address using OpenStreetMap Nominatim"""
    data = request.get_json()
    lat = data.get('latitude')
    lng = data.get('longitude')
    if lat is None or lng is None:
        return jsonify({'error': 'Latitude and longitude required'}), 400

    try:
        resp = requests.get('https://nominatim.openstreetmap.org/reverse', params={
            'lat': lat,
            'lon': lng,
            'format': 'json'
        }, headers={'User-Agent': '3StrandsCattleCo-Dashboard/1.0'}, timeout=10)
        result = resp.json()
        if result and 'display_name' in result:
            return jsonify({
                'success': True,
                'address': result['display_name']
            })
        return jsonify({'success': False, 'error': 'Location not found'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/devices', methods=['GET'])
@login_required
def get_registered_devices():
    """Get registered push notification devices"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    devices = DeviceToken.query.order_by(DeviceToken.registered_at.desc()).all()
    return jsonify([{
        'id': d.id,
        'platform': d.platform,
        'is_active': d.is_active,
        'registered_at': d.registered_at.isoformat() if d.registered_at else None,
        'last_seen': d.last_seen.isoformat() if d.last_seen else None,
        'token_preview': d.token[:12] + '...' if d.token else ''
    } for d in devices])


# =============================================================================
# Initialize Database
# =============================================================================

def migrate_db():
    """Add missing columns to existing database"""
    with app.app_context():
        # Check and add missing columns to user table
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)

        if 'user' in inspector.get_table_names():
            existing_columns = [col['name'] for col in inspector.get_columns('user')]

            columns_to_add = {
                'email': 'VARCHAR(120)',
                'first_name': 'VARCHAR(80)',
                'last_name': 'VARCHAR(80)',
                'phone': 'VARCHAR(20)'
            }

            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        db.session.execute(text(f'ALTER TABLE user ADD COLUMN {col_name} {col_type}'))
                        db.session.commit()
                        print(f"Added column '{col_name}' to user table")
                    except Exception as e:
                        db.session.rollback()
                        print(f"Could not add column '{col_name}': {e}")


def init_db():
    with app.app_context():
        # Run migrations for existing databases FIRST
        migrate_db()

        # Then create any new tables
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

# Always run init_db when module loads (for gunicorn/Docker)
init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8081)
