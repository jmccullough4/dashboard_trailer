# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

3 Strands Cattle Co. Ranch Command Center - a Flask-based dashboard for managing IoT sensors, tasks, files, and mobile app content for a cattle ranch business. The application integrates with multiple external APIs and supports an iOS companion app.

## Development Commands

```bash
# Local development
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py

# Docker (production)
docker-compose up -d

# Access at http://localhost:8081
# Default login: admin/admin
```

## Architecture

### Single-file Flask Application (`app.py`)

The entire backend is contained in `app.py` (~2900 lines) organized into sections:

1. **Database Models** (lines ~60-360): SQLAlchemy models
   - `User` - authentication with admin roles
   - `Task` - Trello-style task board
   - `File` - file sharing with user permissions
   - `YoLinkConfig`, `SensorReading` - YoLink sensor data
   - `EcoFlowConfig`, `EcoFlowReading` - EcoFlow battery monitoring
   - `SquareConfig` - Square POS integration
   - `AppFlashSale`, `PopUpLocation`, `Announcement` - mobile app content
   - `DeviceToken` - iOS push notification tokens

2. **API Integration Classes**:
   - `YoLinkAPI` - IoT sensor data (temperature, humidity, door sensors)
   - `EcoFlowAPI` - Delta 2 Max battery station monitoring/control
   - `SquareAPI` - Product catalog from Square POS

3. **Route Sections** (authenticated unless noted):
   - Authentication routes (`/login`, `/logout`, `/register`)
   - Admin routes (`/api/users/*`) - user management
   - Task routes (`/api/tasks/*`) - CRUD for task board
   - File routes (`/api/files/*`) - upload/download/share
   - YoLink routes (`/api/yolink/*`) - sensor data
   - EcoFlow routes (`/api/ecoflow/*`) - battery status/control
   - Version/Update routes (`/api/version`, `/api/updates/*`) - git-based updates
   - **Public routes** (`/api/public/*`) - no auth, for iOS app
   - Admin routes for mobile content (`/api/admin/flash-sales/*`, etc.)

4. **Push Notifications**: APNs HTTP/2 implementation supporting both production and sandbox environments

### Database

SQLite (`instance/dashboard.db`) with automatic migrations in `migrate_db()` and `init_db()`.

### Frontend

Jinja2 templates (`templates/`) with static assets in `static/css/` and `static/js/`.

## Key Patterns

- All API routes return JSON with `{'success': True/False, ...}` pattern
- Admin-only routes check `current_user.is_admin`
- File uploads stored in `uploads/` with unique hashed filenames
- External API configs stored in database, not environment variables
- Sensor readings cached locally for history charts (5-minute intervals)

## Environment Variables

- `SECRET_KEY` - Flask session key (auto-generated if not set)
- `APNS_KEY_PATH`, `APNS_KEY_ID`, `APNS_TEAM_ID`, `APNS_BUNDLE_ID` - iOS push notifications
