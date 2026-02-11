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

# APNs Push Notification imports
try:
    import httpx
    import jwt as pyjwt
    APNS_AVAILABLE = True
except ImportError:
    APNS_AVAILABLE = False

# Firebase Cloud Messaging imports for Android
try:
    import google.auth.transport.requests
    from google.oauth2 import service_account
    FCM_AVAILABLE = True
except ImportError:
    FCM_AVAILABLE = False

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
    device_id = db.Column(db.String(100))  # Persistent UUID per device
    device_name = db.Column(db.String(200))  # e.g. "John's iPhone 15"
    platform = db.Column(db.String(20), default='ios')
    apns_environment = db.Column(db.String(20), default='production')  # 'sandbox' or 'production'
    # Extended device info
    os_version = db.Column(db.String(50))  # e.g. "17.2", "14"
    app_version = db.Column(db.String(50))  # e.g. "1.0.0"
    device_model = db.Column(db.String(100))  # e.g. "iPhone15,2", "Pixel 9 Pro"
    locale = db.Column(db.String(20))  # e.g. "en_US"
    timezone = db.Column(db.String(50))  # e.g. "America/New_York"
    is_active = db.Column(db.Boolean, default=True)
    registered_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)


class Announcement(db.Model):
    """Custom announcements pushed to the mobile app"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    message = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'message': self.message,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Event(db.Model):
    """Events for the mobile app and internal calendar"""
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    location = db.Column(db.String(500))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    start_date = db.Column(db.DateTime, nullable=False)
    end_date = db.Column(db.DateTime)
    icon = db.Column(db.String(100), default='leaf.fill')
    is_recurring = db.Column(db.Boolean, default=False)
    recurrence_rule = db.Column(db.String(50))  # 'weekly', 'biweekly', 'monthly'
    recurrence_end_date = db.Column(db.DateTime)  # When to stop generating instances
    is_active = db.Column(db.Boolean, default=True)
    is_popup = db.Column(db.Boolean, default=True)  # True = pop-up market (show in app), False = internal calendar only
    notify = db.Column(db.Boolean, default=True)  # Send automated notifications
    notified_morning = db.Column(db.Boolean, default=False)  # Has 7AM notification been sent
    notified_hour_before = db.Column(db.Boolean, default=False)  # Has 1hr before notification been sent
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description or '',
            'location': self.location or '',
            'latitude': self.latitude,
            'longitude': self.longitude,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'icon': self.icon,
            'is_recurring': self.is_recurring,
            'recurrence_rule': self.recurrence_rule,
            'recurrence_end_date': self.recurrence_end_date.isoformat() if self.recurrence_end_date else None,
            'is_active': self.is_active,
            'is_popup': self.is_popup if self.is_popup is not None else True,
            'notify': self.notify if self.notify is not None else True,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def get_recurring_instances(self, from_date=None, to_date=None):
        """Generate recurring event instances within a date range"""
        if not self.is_recurring or not self.recurrence_rule:
            return [self.to_dict()]

        if from_date is None:
            from_date = datetime.utcnow()
        if to_date is None:
            to_date = from_date + timedelta(days=90)  # Default 3 months ahead

        instances = []
        current_start = self.start_date
        event_duration = (self.end_date - self.start_date) if self.end_date else timedelta(hours=4)

        # Determine recurrence interval
        if self.recurrence_rule == 'weekly':
            delta = timedelta(weeks=1)
        elif self.recurrence_rule == 'biweekly':
            delta = timedelta(weeks=2)
        elif self.recurrence_rule == 'monthly':
            delta = None  # Handle monthly separately
        else:
            return [self.to_dict()]

        # Generate instances
        max_iterations = 100  # Safety limit
        iteration = 0
        while iteration < max_iterations:
            iteration += 1

            # Check if we've passed the recurrence end date
            if self.recurrence_end_date and current_start > self.recurrence_end_date:
                break

            # Check if we've passed our search window
            if current_start > to_date:
                break

            # Add instance if it's within our window
            if current_start >= from_date:
                instance = self.to_dict()
                instance['start_date'] = current_start.isoformat()
                instance['end_date'] = (current_start + event_duration).isoformat() if self.end_date else None
                instance['instance_id'] = f"{self.id}_{current_start.strftime('%Y%m%d')}"
                instances.append(instance)

            # Calculate next occurrence
            if self.recurrence_rule == 'monthly':
                # Add one month
                month = current_start.month + 1
                year = current_start.year
                if month > 12:
                    month = 1
                    year += 1
                try:
                    current_start = current_start.replace(year=year, month=month)
                except ValueError:
                    # Handle edge cases like Jan 31 -> Feb 28
                    import calendar
                    last_day = calendar.monthrange(year, month)[1]
                    current_start = current_start.replace(year=year, month=month, day=min(current_start.day, last_day))
            else:
                current_start += delta

        return instances


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
        """Parse raw EcoFlow data into a user-friendly format.

        Handles both Delta 2 Max and River 2 Pro which have different data structures.
        """
        if not data or 'error' in data:
            return data

        raw = data.get('data', data)

        # Calculate remaining time display
        # Try multiple possible fields for remain time
        remain_time = raw.get('pd.remainTime') or raw.get('bms_bmsStatus.remainTime') or raw.get('bms_emsStatus.dsgRemainTime', 0)
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
        watts_in = raw.get('pd.wattsInSum') or raw.get('inv.inputWatts', 0) or 0
        watts_out = raw.get('pd.wattsOutSum') or raw.get('inv.outputWatts', 0) or 0
        if watts_in > watts_out:
            state = 'charging'
        elif watts_out > 0:
            state = 'discharging'
        else:
            state = 'idle'

        # Battery temperature - try multiple fields (Delta uses bms_bmsStatus.temp, River may use others)
        battery_temp = raw.get('bms_bmsStatus.temp') or raw.get('bms_bmsStatus.maxCellTemp')

        # AC enabled - Delta uses inv.cfgAcEnabled, River uses mppt.cfgAcEnabled
        ac_enabled = raw.get('inv.cfgAcEnabled', raw.get('mppt.cfgAcEnabled', 0)) == 1

        # AC output watts - try multiple fields
        ac_output_watts = raw.get('inv.outputWatts') or raw.get('inv.inputWatts', 0) or 0

        # X-Boost - Delta uses inv.cfgAcXboost, River uses mppt.cfgAcXboost
        ac_xboost = raw.get('inv.cfgAcXboost', raw.get('mppt.cfgAcXboost', 0)) == 1

        # Fast charge watts - River 2 Pro doesn't report this, use rated power if available
        fast_charge_watts = raw.get('inv.FastChgWatts') or raw.get('inv.acChgRatedPower', 0) or 0

        # Solar input
        solar_in_watts = raw.get('mppt.inWatts', 0) or 0
        solar_in_vol = raw.get('mppt.inVol', 0) or 0

        return {
            'configured': True,
            'online': True,
            'soc': raw.get('pd.soc', 0),
            'watts_in': watts_in,
            'watts_out': watts_out,
            'state': state,
            'remain_time': remain_time,
            'remain_time_display': time_display,
            'ac_enabled': ac_enabled,
            'ac_output_watts': ac_output_watts,
            'ac_xboost': ac_xboost,
            'dc_enabled': raw.get('pd.dcOutState', raw.get('pd.carState', 0)) == 1,
            'battery_temp': battery_temp,
            'inv_temp': raw.get('inv.outTemp'),
            'solar_in_watts': solar_in_watts,
            'solar_in_volts': solar_in_vol / 10 if solar_in_vol else 0,
            'car_out_watts': raw.get('mppt.carOutWatts') or raw.get('pd.carWatts', 0) or 0,
            'car_state': raw.get('mppt.carState', raw.get('pd.carState', 0)) == 1,
            'beep_mode': raw.get('pd.beepMode', 0) == 0,  # 0 = normal, 1 = mute
            'brightness': raw.get('pd.brightLevel', 3),
            'standby_min': raw.get('pd.standbyMin', 0),
            'fast_charge_watts': fast_charge_watts,
            'slow_charge_watts': raw.get('inv.SlowChgWatts', 0) or 0,
            'max_charge_soc': raw.get('bms_emsStatus.maxChargeSoc', 100),
            'min_discharge_soc': raw.get('bms_emsStatus.minDsgSoc', 0),
            'backup_reserve': raw.get('pd.bpPowerSoc', 0),
            # Additional data for display
            'usb1_watts': raw.get('pd.usb1Watts', 0) or 0,
            'usb2_watts': raw.get('pd.usb2Watts', 0) or 0,
            'typec1_watts': raw.get('pd.typec1Watts', 0) or 0,
            'typec2_watts': raw.get('pd.typec2Watts', 0) or 0,
            'cycles': raw.get('bms_bmsStatus.cycles') or raw.get('bms_bmsInfo.bsmCycles', 0) or 0,
            'soh': raw.get('bms_bmsStatus.soh', 100),
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
# APNs Push Notifications
# =============================================================================

def send_push_notification(title, body, badge=1):
    """Send push notification to all registered iOS devices via APNs HTTP/2.

    Tries production endpoint first, falls back to sandbox if the token is
    rejected — this handles debug (Xcode) vs release (TestFlight/App Store)
    builds automatically without needing to track which environment each
    device registered from.
    """
    if not APNS_AVAILABLE:
        print("APNs not available - httpx/jwt packages not installed")
        return {'sent': 0, 'error': 'httpx or PyJWT not installed'}

    key_path = os.environ.get('APNS_KEY_PATH', './AuthKey_32CB49UN77.p8')
    key_id = os.environ.get('APNS_KEY_ID', '32CB49UN77')
    team_id = os.environ.get('APNS_TEAM_ID', 'GM432NV6J6')
    bundle_id = os.environ.get('APNS_BUNDLE_ID', 'com.threestrandscattle.app')

    if not os.path.exists(key_path):
        print(f"APNs key file not found: {key_path}")
        return {'sent': 0, 'error': f'Key file not found: {key_path}'}

    try:
        with open(key_path, 'r') as f:
            auth_key = f.read()

        # Build JWT token for APNs
        token_payload = {
            'iss': team_id,
            'iat': int(time.time()),
        }
        token = pyjwt.encode(token_payload, auth_key, algorithm='ES256', headers={'kid': key_id})
        if isinstance(token, bytes):
            token = token.decode('utf-8')

        PROD_HOST = 'https://api.push.apple.com'
        SANDBOX_HOST = 'https://api.sandbox.push.apple.com'

        # Get all active device tokens (filter to valid APNs hex tokens only)
        # Valid APNs tokens are exactly 64 hex characters (32 bytes)
        all_tokens = DeviceToken.query.filter_by(is_active=True, platform='ios').all()
        valid = [d for d in all_tokens if d.token and len(d.token) == 64
                 and all(c in '0123456789abcdef' for c in d.token.lower())]

        # Deduplicate: keep only one record per device_id (most recently seen)
        seen_devices = {}
        tokens = []
        for d in valid:
            key = d.device_id or d.token  # fall back to token if no device_id
            if key not in seen_devices or (d.last_seen and d.last_seen > seen_devices[key].last_seen):
                seen_devices[key] = d
        tokens = list(seen_devices.values())
        if not tokens:
            msg = f"No valid APNs tokens ({len(all_tokens)} total devices)"
            print(msg)
            return {'sent': 0, 'total_devices': len(all_tokens), 'valid_tokens': 0, 'error': msg}

        notification = {
            'aps': {
                'alert': {'title': title, 'body': body},
                'sound': 'default',
                'badge': badge,
                'content-available': 1,  # Enable background delivery
                'mutable-content': 1,  # Allow notification service extension processing
            }
        }

        sent = 0
        errors = []
        with httpx.Client(http1=False, http2=True) as client:
            for device in tokens:
                try:
                    headers = {
                        'authorization': f'bearer {token}',
                        'apns-topic': bundle_id,
                        'apns-push-type': 'alert',
                        'apns-priority': '10',
                        'apns-expiration': '0',  # Immediate delivery, no retry
                    }

                    # Use the environment the device registered with
                    env = getattr(device, 'apns_environment', 'production') or 'production'
                    host = SANDBOX_HOST if env == 'sandbox' else PROD_HOST
                    url = f"{host}/3/device/{device.token}"

                    print(f"APNs [{env}] sending to {device.token[:12]}...")
                    resp = client.post(url, json=notification, headers=headers)
                    print(f"APNs [{env}] {resp.status_code} for {device.token[:12]}...")

                    if resp.status_code == 200:
                        sent += 1
                        continue

                    # If wrong environment, try the other one
                    err_body = resp.text
                    if resp.status_code == 400 and 'BadDeviceToken' in err_body:
                        alt_env = 'sandbox' if env == 'production' else 'production'
                        alt_host = SANDBOX_HOST if alt_env == 'sandbox' else PROD_HOST
                        print(f"  BadDeviceToken, trying {alt_env}...")
                        url = f"{alt_host}/3/device/{device.token}"
                        resp = client.post(url, json=notification, headers=headers)
                        print(f"  {alt_env}: {resp.status_code}")

                        if resp.status_code == 200:
                            # Update device's environment for future pushes
                            device.apns_environment = alt_env
                            sent += 1
                            continue
                        err_body = resp.text

                    print(f"APNs FAILED for {device.token[:12]}...: {resp.status_code} {err_body}")
                    errors.append(f"{device.token[:12]}: {resp.status_code} {err_body}")
                    if resp.status_code in (400, 410):
                        device.is_active = False

                except Exception as e:
                    print(f"Failed to send to {device.token[:12]}...: {e}")
                    errors.append(str(e))

        db.session.commit()
        print(f"Push notifications sent: {sent}/{len(tokens)}")
        result = {'sent': sent, 'total_devices': len(all_tokens), 'valid_tokens': len(tokens)}
        if errors:
            result['errors'] = errors
        return result

    except Exception as e:
        print(f"APNs error: {e}")
        return {'sent': 0, 'error': str(e)}


def send_fcm_notification(title, body):
    """Send push notification to all registered Android devices via Firebase Cloud Messaging v1 API."""
    if not FCM_AVAILABLE:
        print("FCM not available - google-auth package not installed")
        return {'sent': 0, 'error': 'google-auth not installed'}

    # FCM service account key file path
    fcm_key_path = os.environ.get('FCM_KEY_PATH', './firebase-service-account.json')
    fcm_project_id = os.environ.get('FCM_PROJECT_ID', '')

    if not os.path.exists(fcm_key_path):
        print(f"FCM service account key not found: {fcm_key_path}")
        return {'sent': 0, 'error': f'FCM key file not found: {fcm_key_path}'}

    try:
        # Load service account credentials
        credentials = service_account.Credentials.from_service_account_file(
            fcm_key_path,
            scopes=['https://www.googleapis.com/auth/firebase.messaging']
        )

        # Get project ID from credentials if not set
        if not fcm_project_id:
            with open(fcm_key_path, 'r') as f:
                key_data = json.load(f)
                fcm_project_id = key_data.get('project_id', '')

        if not fcm_project_id:
            return {'sent': 0, 'error': 'FCM project ID not found'}

        # Refresh credentials to get access token
        auth_request = google.auth.transport.requests.Request()
        credentials.refresh(auth_request)
        access_token = credentials.token

        # Get all active Android device tokens
        all_tokens = DeviceToken.query.filter_by(is_active=True, platform='android').all()

        # Deduplicate: keep only one record per device_id (most recently seen)
        seen_devices = {}
        for d in all_tokens:
            key = d.device_id or d.token
            if key not in seen_devices or (d.last_seen and d.last_seen > seen_devices[key].last_seen):
                seen_devices[key] = d
        tokens = list(seen_devices.values())

        if not tokens:
            msg = f"No Android tokens ({len(all_tokens)} total devices)"
            print(msg)
            return {'sent': 0, 'total_devices': len(all_tokens), 'valid_tokens': 0, 'error': msg}

        fcm_url = f"https://fcm.googleapis.com/v1/projects/{fcm_project_id}/messages:send"

        sent = 0
        errors = []

        for device in tokens:
            try:
                message = {
                    "message": {
                        "token": device.token,
                        "notification": {
                            "title": title,
                            "body": body
                        },
                        "android": {
                            "priority": "high",
                            "notification": {
                                "sound": "default",
                                "channel_id": "general"
                            }
                        }
                    }
                }

                headers = {
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json'
                }

                print(f"FCM sending to {device.token[:20]}...")
                resp = requests.post(fcm_url, json=message, headers=headers)
                print(f"FCM {resp.status_code} for {device.token[:20]}...")

                if resp.status_code == 200:
                    sent += 1
                else:
                    err_body = resp.text
                    print(f"FCM FAILED for {device.token[:20]}...: {resp.status_code} {err_body}")
                    errors.append(f"{device.token[:20]}: {resp.status_code}")

                    # Mark invalid tokens as inactive
                    if resp.status_code in (400, 404):
                        try:
                            err_data = resp.json()
                            if 'UNREGISTERED' in str(err_data) or 'INVALID_ARGUMENT' in str(err_data):
                                device.is_active = False
                        except:
                            pass

            except Exception as e:
                print(f"Failed to send FCM to {device.token[:20]}...: {e}")
                errors.append(str(e))

        db.session.commit()
        print(f"FCM notifications sent: {sent}/{len(tokens)}")
        result = {'sent': sent, 'total_devices': len(all_tokens), 'valid_tokens': len(tokens)}
        if errors:
            result['errors'] = errors
        return result

    except Exception as e:
        print(f"FCM error: {e}")
        return {'sent': 0, 'error': str(e)}


def send_all_push_notifications(title, body, badge=1):
    """Send push notifications to both iOS (APNs) and Android (FCM) devices."""
    ios_result = send_push_notification(title, body, badge)
    android_result = send_fcm_notification(title, body)

    return {
        'ios': ios_result,
        'android': android_result,
        'total_sent': ios_result.get('sent', 0) + android_result.get('sent', 0)
    }


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
    """Return active pop-up events for the mobile app, expanding recurring events.

    Only returns events where is_popup=True (pop-up markets visible to app users).
    Internal calendar events (is_popup=False) are not returned.
    Past events (where end_date or start_date has passed) are filtered out.
    """
    # Only return pop-up events (is_popup=True) that are active
    events = Event.query.filter_by(is_active=True, is_popup=True).order_by(Event.start_date.asc()).all()

    # Expand recurring events into instances
    all_instances = []
    now = datetime.utcnow()
    future_limit = now + timedelta(days=90)  # Show events up to 3 months out

    for event in events:
        if event.is_recurring and event.recurrence_rule:
            instances = event.get_recurring_instances(from_date=now, to_date=future_limit)
            all_instances.extend(instances)
        else:
            event_dict = event.to_dict()
            # Filter out past events - use end_date if available, otherwise start_date
            event_end = event.end_date if event.end_date else event.start_date
            if event_end and event_end >= now:
                all_instances.append(event_dict)

    # Sort by start_date
    all_instances.sort(key=lambda x: x['start_date'] if x['start_date'] else '')

    return jsonify(all_instances)


@app.route('/api/public/pop-up-sales', methods=['GET'])
def public_pop_up_sales():
    """Return upcoming pop-up sales for the mobile app (iOS field mapping).

    DEPRECATED: Use /api/public/events instead. This endpoint now returns pop-up events.
    """
    # Only return pop-up events
    events = Event.query.filter_by(is_active=True, is_popup=True).filter(
        Event.start_date >= datetime.utcnow()
    ).order_by(Event.start_date.asc()).all()
    return jsonify([{
        'id': e.id,
        'title': e.title,
        'description': e.description,
        'address': e.location,
        'latitude': e.latitude or 0.0,
        'longitude': e.longitude or 0.0,
        'starts_at': e.start_date.isoformat() if e.start_date else None,
        'ends_at': e.end_date.isoformat() if e.end_date else None,
        'is_active': e.is_active,
    } for e in events])


@app.route('/api/public/announcements', methods=['GET'])
def public_announcements():
    """Return active announcements for the mobile app"""
    announcements = Announcement.query.filter_by(is_active=True).order_by(
        Announcement.created_at.desc()
    ).all()
    return jsonify([a.to_dict() for a in announcements])


@app.route('/api/public/notifications', methods=['GET'])
def public_notifications():
    """Return recent notifications for polling-based mobile apps (Android).

    Query params:
    - since: ISO timestamp to get notifications after (optional)
    - limit: max number of notifications to return (default 20)

    Returns a unified list of flash sales, announcements, and events
    created/updated since the given timestamp, sorted by date descending.
    """
    since_str = request.args.get('since')
    limit = min(request.args.get('limit', 20, type=int), 100)

    since = None
    if since_str:
        try:
            since = datetime.fromisoformat(since_str.replace('Z', '+00:00'))
        except:
            pass

    notifications = []

    # Get recent flash sales
    flash_query = AppFlashSale.query.filter_by(is_active=True)
    if since:
        flash_query = flash_query.filter(AppFlashSale.created_at > since)
    for sale in flash_query.order_by(AppFlashSale.created_at.desc()).limit(limit).all():
        discount = int(((sale.original_price - sale.sale_price) / sale.original_price) * 100) if sale.original_price > 0 else 0
        notifications.append({
            'id': f'flash_{sale.id}',
            'type': 'flash_sale',
            'title': '3 Strands Flash Sale!',
            'body': f"{sale.title} — {discount}% off! ${sale.sale_price:.2f}/lb",
            'created_at': sale.created_at.isoformat() if sale.created_at else None,
            'data': sale.to_dict()
        })

    # Get recent announcements
    ann_query = Announcement.query.filter_by(is_active=True)
    if since:
        ann_query = ann_query.filter(Announcement.created_at > since)
    for ann in ann_query.order_by(Announcement.created_at.desc()).limit(limit).all():
        notifications.append({
            'id': f'announcement_{ann.id}',
            'type': 'announcement',
            'title': ann.title,
            'body': ann.message,
            'created_at': ann.created_at.isoformat() if ann.created_at else None,
            'data': ann.to_dict()
        })

    # Get recent pop-up events (only is_popup=True events go to mobile app)
    event_query = Event.query.filter_by(is_active=True, is_popup=True)
    if since:
        event_query = event_query.filter(Event.created_at > since)
    for event in event_query.order_by(Event.created_at.desc()).limit(limit).all():
        date_str = event.start_date.strftime('%b %d') if event.start_date else ''
        notifications.append({
            'id': f'event_{event.id}',
            'type': 'event',
            'title': '3 Strands Pop-Up Market!',
            'body': f"{event.title} — {date_str}",
            'created_at': event.created_at.isoformat() if event.created_at else None,
            'data': event.to_dict()
        })

    # Sort all by created_at descending and limit
    notifications.sort(key=lambda x: x['created_at'] or '', reverse=True)
    notifications = notifications[:limit]

    return jsonify({
        'notifications': notifications,
        'server_time': datetime.utcnow().isoformat()
    })


@app.route('/api/public/register-device', methods=['POST'])
def public_register_device():
    """Register a device for push notifications"""
    data = request.get_json()
    if not data or not data.get('token'):
        return jsonify({'error': 'Token required'}), 400

    token = data['token']
    platform = data.get('platform', 'ios')
    device_id = data.get('device_id', '')
    device_name = data.get('device_name', '')
    # iOS app should send 'sandbox' for debug builds, 'production' for release/TestFlight
    apns_environment = data.get('apns_environment', 'production')
    # Extended device info
    os_version = data.get('os_version', '')
    app_version = data.get('app_version', '')
    device_model = data.get('device_model', '')
    locale = data.get('locale', '')
    timezone = data.get('timezone', '')

    def update_device_info(device):
        """Update device with latest info"""
        device.last_seen = datetime.utcnow()
        device.is_active = True
        device.apns_environment = apns_environment
        if device_name:
            device.device_name = device_name
        if os_version:
            device.os_version = os_version
        if app_version:
            device.app_version = app_version
        if device_model:
            device.device_model = device_model
        if locale:
            device.locale = locale
        if timezone:
            device.timezone = timezone

    try:
        # If device_id provided, find by device_id first (handles token changes)
        if device_id:
            existing = DeviceToken.query.filter_by(device_id=device_id).first()
            if existing:
                # Check if new token conflicts with a different device's record
                conflict = DeviceToken.query.filter(
                    DeviceToken.token == token,
                    DeviceToken.id != existing.id
                ).first()
                if conflict:
                    db.session.delete(conflict)

                # Clean up any other duplicate records for this device_id
                dupes = DeviceToken.query.filter(
                    DeviceToken.device_id == device_id,
                    DeviceToken.id != existing.id
                ).all()
                for dupe in dupes:
                    db.session.delete(dupe)

                existing.token = token
                update_device_info(existing)
                db.session.commit()
                return jsonify({'success': True, 'status': 'updated'})

        # Fall back to finding by token
        existing = DeviceToken.query.filter_by(token=token).first()
        if existing:
            if device_id and not existing.device_id:
                existing.device_id = device_id
            update_device_info(existing)
            db.session.commit()
            return jsonify({'success': True, 'status': 'updated'})

        device = DeviceToken(
            token=token,
            platform=platform,
            device_id=device_id,
            device_name=device_name,
            apns_environment=apns_environment,
            os_version=os_version,
            app_version=app_version,
            device_model=device_model,
            locale=locale,
            timezone=timezone
        )
        db.session.add(device)
        db.session.commit()
        return jsonify({'success': True, 'status': 'registered'})

    except Exception as e:
        db.session.rollback()
        import traceback
        traceback.print_exc()
        print(f"Device registration error: {e}")
        return jsonify({'error': f'Registration failed: {e}'}), 500


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

    # Send push notification for active sales
    push_result = None
    if sale.is_active:
        discount = int(((sale.original_price - sale.sale_price) / sale.original_price) * 100) if sale.original_price > 0 else 0
        action = "New" if not sale_id else "Updated"
        push_result = send_all_push_notifications(
            f"3 Strands Flash Sale!",
            f"{action}: {sale.title} — {discount}% off! ${sale.sale_price:.2f}/lb"
        )
        print(f"Flash sale push result: {push_result}")

    return jsonify({'success': True, 'sale': sale.to_dict(), 'push_result': push_result})


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
# Admin: Announcements Management
# =============================================================================

@app.route('/api/announcements', methods=['GET'])
@login_required
def get_announcements():
    """Get all announcements (admin view - includes inactive)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403
    announcements = Announcement.query.order_by(Announcement.created_at.desc()).all()
    return jsonify([a.to_dict() for a in announcements])


@app.route('/api/announcements', methods=['POST'])
@login_required
def create_announcement():
    """Create a new announcement and send push notification"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    title = data.get('title', '').strip()
    message = data.get('message', '').strip()
    if not title or not message:
        return jsonify({'error': 'Title and message are required'}), 400

    announcement = Announcement(title=title, message=message, is_active=True)
    db.session.add(announcement)
    db.session.commit()

    # Send push notification to all devices
    push_result = send_all_push_notifications(title, message)
    print(f"Announcement push result: {push_result}")

    return jsonify({'success': True, 'announcement': announcement.to_dict(), 'push_result': push_result})


@app.route('/api/announcements/<int:ann_id>', methods=['PATCH'])
@login_required
def toggle_announcement(ann_id):
    """Toggle announcement active status"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    announcement = Announcement.query.get(ann_id)
    if not announcement:
        return jsonify({'error': 'Announcement not found'}), 404

    data = request.get_json()
    if data and 'is_active' in data:
        announcement.is_active = data['is_active']

    db.session.commit()
    return jsonify({'success': True, 'announcement': announcement.to_dict()})


@app.route('/api/announcements/<int:ann_id>', methods=['DELETE'])
@login_required
def delete_announcement(ann_id):
    """Delete an announcement"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    announcement = Announcement.query.get(ann_id)
    if not announcement:
        return jsonify({'error': 'Announcement not found'}), 404

    db.session.delete(announcement)
    db.session.commit()
    return jsonify({'success': True})


# =============================================================================
# Admin: Events Management
# =============================================================================

@app.route('/api/events', methods=['GET'])
@login_required
def get_events():
    """Get all events (admin view - includes inactive)"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403
    events = Event.query.order_by(Event.start_date.desc()).all()
    return jsonify([e.to_dict() for e in events])


@app.route('/api/events', methods=['POST'])
@login_required
def create_or_update_event():
    """Create or update an event and send push notification on create"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400

    event_id = data.get('id')
    if event_id:
        event = Event.query.get(event_id)
        if not event:
            return jsonify({'error': 'Event not found'}), 404
    else:
        event = Event()
        db.session.add(event)

    event.title = data.get('title', event.title if event_id else 'New Event')
    event.description = data.get('description', '')
    event.location = data.get('location', '')
    event.icon = data.get('icon', 'leaf.fill')
    event.is_active = data.get('is_active', True)
    event.is_popup = data.get('is_popup', True)  # True = pop-up market (visible in app), False = calendar only
    event.notify = data.get('notify', True)
    event.is_recurring = data.get('is_recurring', False)
    event.recurrence_rule = data.get('recurrence_rule', '') if data.get('is_recurring') else None
    # Reset notification flags if date changed
    if data.get('start_date'):
        event.notified_morning = False
        event.notified_hour_before = False

    if data.get('latitude'):
        event.latitude = float(data['latitude'])
    if data.get('longitude'):
        event.longitude = float(data['longitude'])

    if data.get('start_date'):
        event.start_date = datetime.fromisoformat(data['start_date'].replace('Z', '+00:00').replace('+00:00', ''))
    if data.get('end_date'):
        event.end_date = datetime.fromisoformat(data['end_date'].replace('Z', '+00:00').replace('+00:00', ''))
    if data.get('recurrence_end_date'):
        event.recurrence_end_date = datetime.fromisoformat(data['recurrence_end_date'].replace('Z', '+00:00').replace('+00:00', ''))
    elif not data.get('is_recurring'):
        event.recurrence_end_date = None

    db.session.commit()

    # Send push notification for new active pop-up events only
    push_result = None
    if not event_id and event.is_active and event.is_popup:
        date_str = event.start_date.strftime('%b %d') if event.start_date else ''
        push_result = send_all_push_notifications(
            "3 Strands Pop-Up Market!",
            f"{event.title} — {date_str}"
        )
        print(f"Event push result: {push_result}")

    return jsonify({'success': True, 'event': event.to_dict(), 'push_result': push_result})


@app.route('/api/events/<int:event_id>', methods=['DELETE'])
@login_required
def delete_event(event_id):
    """Delete an event"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    event = Event.query.get(event_id)
    if not event:
        return jsonify({'error': 'Event not found'}), 404

    db.session.delete(event)
    db.session.commit()
    return jsonify({'success': True})


# =============================================================================
# Automated Event Notifications
# =============================================================================

def check_and_send_event_notifications():
    """Check for events that need notifications and send them.

    Called periodically (e.g., every 5 minutes).
    Sends notifications:
    - At 7:00 AM Eastern on the day of the event
    - 1 hour before the event start time

    Uses Eastern timezone (America/New_York) for 7AM check.
    """
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        from backports.zoneinfo import ZoneInfo

    eastern = ZoneInfo('America/New_York')
    now_utc = datetime.utcnow()
    now_eastern = datetime.now(eastern)

    # Get all active events with notifications enabled that haven't ended yet
    events = Event.query.filter(
        Event.is_active == True,
        Event.notify == True,
        Event.start_date >= now_utc - timedelta(hours=1)  # Include events that just started
    ).all()

    notifications_sent = []

    for event in events:
        # Convert event start to Eastern for day comparison
        event_start_eastern = event.start_date.replace(tzinfo=ZoneInfo('UTC')).astimezone(eastern)

        # Check for 7AM morning notification (same day, after 7AM, not yet sent)
        if not event.notified_morning:
            # Is today the event day?
            if event_start_eastern.date() == now_eastern.date():
                # Is it after 7AM Eastern?
                if now_eastern.hour >= 7:
                    # Send morning notification
                    date_str = event_start_eastern.strftime('%I:%M %p')
                    location_str = f" at {event.location}" if event.location else ""
                    result = send_all_push_notifications(
                        f"Today: {event.title}",
                        f"Join us today at {date_str}{location_str}!"
                    )
                    event.notified_morning = True
                    notifications_sent.append(f"Morning: {event.title}")
                    print(f"Sent morning notification for event {event.id}: {event.title}")

        # Check for 1-hour before notification
        if not event.notified_hour_before:
            # Is event starting within the next hour?
            time_until_start = (event.start_date - now_utc).total_seconds()
            if 0 < time_until_start <= 3600:  # Within 1 hour
                # Send 1-hour reminder
                location_str = f" at {event.location}" if event.location else ""
                result = send_all_push_notifications(
                    f"Starting Soon: {event.title}",
                    f"We're setting up now{location_str}. See you in about an hour!"
                )
                event.notified_hour_before = True
                notifications_sent.append(f"1hr before: {event.title}")
                print(f"Sent 1-hour reminder for event {event.id}: {event.title}")

    if notifications_sent:
        db.session.commit()

    return notifications_sent


@app.route('/api/check-event-notifications', methods=['POST'])
def check_event_notifications():
    """Endpoint to trigger event notification check.

    Can be called by a cron job or external scheduler.
    No authentication required - it only reads events and sends notifications.
    """
    sent = check_and_send_event_notifications()
    return jsonify({'success': True, 'notifications_sent': sent})


# Background notification checker - runs periodically when server is accessed
_last_notification_check = None

@app.before_request
def maybe_check_notifications():
    """Periodically check for event notifications (every 5 minutes)."""
    global _last_notification_check

    # Only check on certain routes to avoid overhead
    if request.endpoint not in ['dashboard', 'index', 'get_events', 'public_events']:
        return

    now = datetime.utcnow()
    if _last_notification_check is None or (now - _last_notification_check).total_seconds() > 300:
        _last_notification_check = now
        try:
            check_and_send_event_notifications()
        except Exception as e:
            print(f"Error checking event notifications: {e}")


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


@app.route('/api/apns/status', methods=['GET'])
@login_required
def get_apns_status():
    """Check if APNs push notifications are configured"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    key_path = os.environ.get('APNS_KEY_PATH', './AuthKey_32CB49UN77.p8')
    key_exists = os.path.exists(key_path)
    device_count = DeviceToken.query.filter_by(is_active=True, platform='ios').count()

    return jsonify({
        'available': APNS_AVAILABLE,
        'key_configured': key_exists,
        'key_id': os.environ.get('APNS_KEY_ID', '32CB49UN77'),
        'team_id': os.environ.get('APNS_TEAM_ID', 'GM432NV6J6'),
        'active_devices': device_count
    })


@app.route('/api/apns/test', methods=['POST'])
@login_required
def test_push_notification():
    """Send a test push notification to all registered devices"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    result = send_all_push_notifications(
        "3 Strands Test",
        "Push notifications are working! You'll receive alerts for flash sales and events."
    )
    return jsonify({'success': result.get('total_sent', 0) > 0, **result})


@app.route('/api/devices', methods=['GET'])
@login_required
def get_registered_devices():
    """Get registered push notification devices"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403

    devices = DeviceToken.query.order_by(DeviceToken.last_seen.desc()).all()
    return jsonify([{
        'id': d.id,
        'device_id': d.device_id or '',
        'device_name': d.device_name or '',
        'platform': d.platform,
        'os_version': d.os_version or '',
        'app_version': d.app_version or '',
        'device_model': d.device_model or '',
        'locale': d.locale or '',
        'timezone': d.timezone or '',
        'is_active': d.is_active,
        'registered_at': d.registered_at.isoformat() if d.registered_at else None,
        'last_seen': d.last_seen.isoformat() if d.last_seen else None,
        'token_preview': d.token[:12] + '...' if d.token else ''
    } for d in devices])


@app.route('/api/devices/reset', methods=['DELETE'])
@login_required
def reset_all_devices():
    """Clear all registered device tokens"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403
    count = DeviceToken.query.count()
    DeviceToken.query.delete()
    db.session.commit()
    return jsonify({'success': True, 'deleted': count})


@app.route('/api/devices/<int:device_id>', methods=['DELETE'])
@login_required
def delete_device(device_id):
    """Delete a single registered device"""
    if not current_user.is_admin:
        return jsonify({'error': 'Admin required'}), 403
    device = DeviceToken.query.get_or_404(device_id)
    db.session.delete(device)
    db.session.commit()
    return jsonify({'success': True})


# =============================================================================
# Initialize Database
# =============================================================================

def migrate_db():
    """Add missing columns to existing database"""
    with app.app_context():
        from sqlalchemy import inspect, text
        inspector = inspect(db.engine)

        # Migrate user table
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

        # Migrate device_token table
        if 'device_token' in inspector.get_table_names():
            existing_columns = [col['name'] for col in inspector.get_columns('device_token')]

            columns_to_add = {
                'device_id': 'VARCHAR(100)',
                'device_name': 'VARCHAR(200)',
                'apns_environment': 'VARCHAR(20)',
                'os_version': 'VARCHAR(50)',
                'app_version': 'VARCHAR(50)',
                'device_model': 'VARCHAR(100)',
                'locale': 'VARCHAR(20)',
                'timezone': 'VARCHAR(50)'
            }

            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        db.session.execute(text(f'ALTER TABLE device_token ADD COLUMN {col_name} {col_type}'))
                        db.session.commit()
                        print(f"Added column '{col_name}' to device_token table")
                    except Exception as e:
                        db.session.rollback()
                        print(f"Could not add column '{col_name}': {e}")

        # Migrate event table for recurrence and notification fields
        if 'event' in inspector.get_table_names():
            existing_columns = [col['name'] for col in inspector.get_columns('event')]

            columns_to_add = {
                'is_recurring': 'BOOLEAN',
                'recurrence_rule': 'VARCHAR(50)',
                'recurrence_end_date': 'DATETIME',
                'is_popup': 'BOOLEAN DEFAULT 1',
                'notify': 'BOOLEAN DEFAULT 1',
                'notified_morning': 'BOOLEAN DEFAULT 0',
                'notified_hour_before': 'BOOLEAN DEFAULT 0'
            }

            for col_name, col_type in columns_to_add.items():
                if col_name not in existing_columns:
                    try:
                        db.session.execute(text(f'ALTER TABLE event ADD COLUMN {col_name} {col_type}'))
                        db.session.commit()
                        print(f"Added column '{col_name}' to event table")
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

        # Seed Square config if not exists
        if not SquareConfig.query.first():
            square = SquareConfig(
                access_token='EAAAl23jxhQmIejnibi8LPDjN9LLCkW2JhrrfnknRYoq_CuY0Kb6jJ0NRu8ucheC',
                environment='production'
            )
            db.session.add(square)
            db.session.commit()
            print("Seeded Square API configuration")



# =============================================================================
# Main
# =============================================================================

# Always run init_db when module loads (for gunicorn/Docker)
init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8081)
