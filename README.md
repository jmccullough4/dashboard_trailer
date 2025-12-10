# 3 Strands Cattle Co. - Ranch Command Center

A futuristic dashboard for managing YoLink sensors, tasks, and files for 3 Strands Cattle Co.

## Features

- **YoLink Sensor Integration**: Real-time monitoring of all your YoLink sensors (temperature, humidity, door sensors, motion detectors, etc.)
- **Trello-like Task Board**: Drag-and-drop task management with columns: Assigned, In Progress, Review, Complete
- **File Sharing**: Upload, download, and share files with team members (private by default)
- **User Management**: Admin panel for managing users and permissions
- **Futuristic UI**: Beautiful dark theme with gold accents and animations

## Quick Start

### Option 1: Docker (Recommended)

```bash
docker-compose up -d
```

Access the dashboard at `http://localhost:8081`

### Option 2: Local Development

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

## Default Login

- **Username**: `admin`
- **Password**: `admin`

> **Important**: Change the admin password after first login!

## YoLink Configuration

1. Log in as admin
2. Go to Settings (gear icon in sidebar)
3. Enter your YoLink UAID and Secret Key
4. Click Save Configuration
5. Your sensors will appear in the Sensors section

### Getting YoLink Credentials

1. Log in to the [YoLink Developer Portal](https://www.yosmart.com/)
2. Navigate to your account settings
3. Copy your UAID and Secret Key

## Features Guide

### Sensors Dashboard
- View all connected YoLink sensors
- Real-time temperature, humidity, battery levels
- Online/offline status indicators
- Click Refresh to update sensor data

### Task Board
- **Create Tasks**: Click "New Task" to add tasks
- **Assign Members**: Assign tasks to team members
- **Priority Levels**: Low, Medium, High, Urgent
- **Due Dates**: Set task deadlines
- **Drag & Drop**: Move tasks between columns

### File Manager
- **Upload**: Click "Upload File" to add files
- **Share**: Share files with specific users
- **Public/Private**: Toggle file visibility
- **Download**: Download any accessible file

### Admin Panel (Admin Only)
- View all users
- Promote/demote admins
- Delete users
- Create new accounts

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Flask secret key | Random generated |
| `FLASK_ENV` | Environment mode | production |

## Project Structure

```
dashboard_trailer/
├── app.py              # Main Flask application
├── requirements.txt    # Python dependencies
├── Dockerfile          # Docker configuration
├── docker-compose.yml  # Docker Compose config
├── templates/
│   ├── login.html     # Login page
│   └── dashboard.html # Main dashboard
├── static/
│   ├── css/
│   │   └── dashboard.css
│   └── js/
│       └── dashboard.js
└── uploads/           # User uploaded files
```

## API Endpoints

### Authentication
- `POST /login` - User login
- `GET /logout` - User logout
- `POST /register` - Register new user (via admin)

### Tasks
- `GET /api/tasks` - Get all tasks
- `POST /api/tasks` - Create task
- `PUT /api/tasks/<id>` - Update task
- `DELETE /api/tasks/<id>` - Delete task

### Files
- `GET /api/files` - Get user's files
- `POST /api/files/upload` - Upload file
- `GET /api/files/<id>/download` - Download file
- `POST /api/files/<id>/share` - Share file
- `PUT /api/files/<id>/public` - Toggle public
- `DELETE /api/files/<id>` - Delete file

### YoLink
- `GET /api/yolink/devices` - Get all devices
- `GET /api/yolink/device/<id>/state` - Get device state
- `POST /api/yolink/config` - Save YoLink config

### Users (Admin)
- `GET /api/users` - Get all users
- `DELETE /api/users/<id>` - Delete user
- `PUT /api/users/<id>/admin` - Toggle admin

## Security Notes

- Change the default admin password immediately
- Use a strong `SECRET_KEY` in production
- Keep your YoLink credentials secure
- Files are private by default

## License

Proprietary - 3 Strands Cattle Co.
