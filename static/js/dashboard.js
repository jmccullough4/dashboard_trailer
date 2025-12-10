// =============================================================================
// 3 Strands Cattle Co. Dashboard - JavaScript
// =============================================================================

// Global state
let allUsers = [];
let allTasks = [];
let allSensors = [];
let currentSensor = null;
let temperatureChart = null;
let humidityChart = null;

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initNavigation();
    initDateTime();
    initDragAndDrop();
    loadUsers();
    loadSensors();
    loadTasks();
    loadFiles();

    // Form handlers
    document.getElementById('taskForm').addEventListener('submit', handleTaskSubmit);
    document.getElementById('registerForm').addEventListener('submit', handleRegisterSubmit);
    document.getElementById('shareForm').addEventListener('submit', handleShareSubmit);
});

// =============================================================================
// Navigation
// =============================================================================

function initNavigation() {
    const navItems = document.querySelectorAll('.nav-item');
    const sections = document.querySelectorAll('.section');
    const pageTitle = document.getElementById('pageTitle');
    const menuToggle = document.getElementById('menuToggle');
    const sidebar = document.getElementById('sidebar');

    const titles = {
        'sensors': 'Sensor Dashboard',
        'tasks': 'Task Board',
        'files': 'File Manager',
        'admin': 'User Management',
        'settings': 'System Settings'
    };

    navItems.forEach(item => {
        item.addEventListener('click', function(e) {
            e.preventDefault();
            const section = this.dataset.section;

            navItems.forEach(i => i.classList.remove('active'));
            this.classList.add('active');

            sections.forEach(s => s.classList.remove('active'));
            document.getElementById(`${section}-section`).classList.add('active');

            pageTitle.textContent = titles[section] || 'Dashboard';

            // Close sidebar on mobile
            if (window.innerWidth <= 768) {
                sidebar.classList.remove('open');
            }
        });
    });

    menuToggle.addEventListener('click', function() {
        sidebar.classList.toggle('open');
    });

    // Close sidebar when clicking outside on mobile
    document.addEventListener('click', function(e) {
        if (window.innerWidth <= 768 &&
            !sidebar.contains(e.target) &&
            !menuToggle.contains(e.target)) {
            sidebar.classList.remove('open');
        }
    });
}

function initDateTime() {
    const datetimeEl = document.getElementById('datetime');

    function updateDateTime() {
        const now = new Date();
        const options = {
            weekday: 'short',
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        };
        datetimeEl.textContent = now.toLocaleDateString('en-US', options);
    }

    updateDateTime();
    setInterval(updateDateTime, 60000);
}

// =============================================================================
// Toast Notifications
// =============================================================================

function showToast(message, type = 'success') {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.className = `toast ${type} show`;

    setTimeout(() => {
        toast.classList.remove('show');
    }, 3000);
}

// =============================================================================
// Users
// =============================================================================

async function loadUsers() {
    try {
        const response = await fetch('/api/users/list');
        allUsers = await response.json();
        populateAssigneeDropdown();
    } catch (error) {
        console.error('Error loading users:', error);
    }
}

function populateAssigneeDropdown() {
    const select = document.getElementById('taskAssignee');
    select.innerHTML = '<option value="">Unassigned</option>';
    allUsers.forEach(user => {
        select.innerHTML += `<option value="${user.id}">${user.username}</option>`;
    });
}

async function loadAdminUsers() {
    if (!currentUser.isAdmin) return;

    try {
        const response = await fetch('/api/users');
        const users = await response.json();
        renderUsersTable(users);
    } catch (error) {
        console.error('Error loading admin users:', error);
    }
}

function renderUsersTable(users) {
    const tbody = document.getElementById('usersTableBody');
    tbody.innerHTML = '';

    users.forEach(user => {
        const row = document.createElement('tr');
        row.innerHTML = `
            <td>${user.username}</td>
            <td>
                <span class="role-badge ${user.is_admin ? 'admin' : 'user'}">
                    ${user.is_admin ? 'Admin' : 'User'}
                </span>
            </td>
            <td>${user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}</td>
            <td>${user.last_login ? new Date(user.last_login).toLocaleString() : 'Never'}</td>
            <td>
                ${user.id !== currentUser.id ? `
                    <button class="btn btn-sm btn-secondary" onclick="toggleUserAdmin(${user.id}, ${!user.is_admin})">
                        ${user.is_admin ? 'Remove Admin' : 'Make Admin'}
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="deleteUser(${user.id})">
                        Delete
                    </button>
                ` : '<em style="color: var(--text-muted)">Current User</em>'}
            </td>
        `;
        tbody.appendChild(row);
    });
}

async function toggleUserAdmin(userId, makeAdmin) {
    try {
        const response = await fetch(`/api/users/${userId}/admin`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_admin: makeAdmin })
        });

        if (response.ok) {
            showToast(`User ${makeAdmin ? 'promoted to admin' : 'demoted from admin'}`);
            loadAdminUsers();
        } else {
            showToast('Failed to update user', 'error');
        }
    } catch (error) {
        showToast('Error updating user', 'error');
    }
}

async function deleteUser(userId) {
    if (!confirm('Are you sure you want to delete this user?')) return;

    try {
        const response = await fetch(`/api/users/${userId}`, { method: 'DELETE' });

        if (response.ok) {
            showToast('User deleted successfully');
            loadAdminUsers();
            loadUsers();
        } else {
            const data = await response.json();
            showToast(data.error || 'Failed to delete user', 'error');
        }
    } catch (error) {
        showToast('Error deleting user', 'error');
    }
}

function showRegisterModal() {
    document.getElementById('registerModal').classList.add('show');
    document.getElementById('newUsername').value = '';
    document.getElementById('newPassword').value = '';
}

function closeRegisterModal() {
    document.getElementById('registerModal').classList.remove('show');
}

async function handleRegisterSubmit(e) {
    e.preventDefault();

    const username = document.getElementById('newUsername').value;
    const password = document.getElementById('newPassword').value;

    try {
        const response = await fetch('/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password })
        });

        const data = await response.json();

        if (data.success) {
            showToast('User created successfully');
            closeRegisterModal();
            loadAdminUsers();
            loadUsers();
        } else {
            showToast(data.error || 'Failed to create user', 'error');
        }
    } catch (error) {
        showToast('Error creating user', 'error');
    }
}

// =============================================================================
// Sensors
// =============================================================================

async function loadSensors() {
    const grid = document.getElementById('sensorsGrid');

    try {
        const response = await fetch('/api/yolink/devices');
        const data = await response.json();

        if (data.error) {
            grid.innerHTML = `
                <div class="no-sensors">
                    <i class="fas fa-satellite-dish"></i>
                    <p>${data.error}</p>
                    ${currentUser.isAdmin ? '<p>Configure YoLink in Settings to connect your sensors.</p>' : ''}
                </div>
            `;
            return;
        }

        if (data.data && data.data.devices && data.data.devices.length > 0) {
            allSensors = data.data.devices;
            renderSensors(allSensors);
        } else {
            grid.innerHTML = `
                <div class="no-sensors">
                    <i class="fas fa-satellite-dish"></i>
                    <p>No sensors found</p>
                    <p>Add sensors to your YoLink account to see them here.</p>
                </div>
            `;
        }
    } catch (error) {
        grid.innerHTML = `
            <div class="no-sensors">
                <i class="fas fa-exclamation-triangle"></i>
                <p>Failed to load sensors</p>
                <button class="btn btn-primary" onclick="loadSensors()">Retry</button>
            </div>
        `;
    }
}

function renderSensors(devices) {
    const grid = document.getElementById('sensorsGrid');
    grid.innerHTML = '';

    devices.forEach(device => {
        const state = device.state || {};
        const isOnline = device.online !== false;

        const card = document.createElement('div');
        card.className = 'sensor-card';
        card.onclick = () => showSensorModal(device.deviceId);

        card.innerHTML = `
            <div class="sensor-header">
                <div class="sensor-icon">
                    <i class="fas ${getSensorIcon(device.type)}"></i>
                </div>
                <span class="sensor-status ${isOnline ? 'online' : 'offline'}">
                    ${isOnline ? 'Online' : 'Offline'}
                </span>
            </div>
            <h4 class="sensor-name">${device.name || 'Unknown Sensor'}</h4>
            <p class="sensor-type">${getSensorTypeLabel(device.type)}</p>
            <div class="sensor-readings">
                ${formatSensorReadings(state, device.type)}
            </div>
        `;
        grid.appendChild(card);
    });
}

function getSensorIcon(type) {
    const icons = {
        'THSensor': 'fa-thermometer-half',
        'MotionSensor': 'fa-walking',
        'DoorSensor': 'fa-door-open',
        'LeakSensor': 'fa-water',
        'Hub': 'fa-wifi',
        'Outlet': 'fa-plug',
        'Switch': 'fa-toggle-on',
        'Siren': 'fa-bell',
        'Lock': 'fa-lock',
        'GarageDoor': 'fa-warehouse'
    };
    return icons[type] || 'fa-microchip';
}

function getSensorTypeLabel(type) {
    const labels = {
        'THSensor': 'Temp Sensor',
        'MotionSensor': 'Motion Sensor',
        'DoorSensor': 'Door Sensor',
        'LeakSensor': 'Leak Sensor',
        'Hub': 'Hub',
        'Outlet': 'Smart Outlet',
        'Switch': 'Smart Switch',
        'Siren': 'Siren',
        'Lock': 'Smart Lock',
        'GarageDoor': 'Garage Door'
    };
    return labels[type] || type;
}

function convertBatteryLevel(level) {
    // YoLink returns battery as 0-4 scale, convert to percentage
    const percentages = {
        4: 100,
        3: 75,
        2: 50,
        1: 25,
        0: 0
    };
    return percentages[level] !== undefined ? percentages[level] : level;
}

function formatSensorReadings(state, type) {
    let html = '';

    if (state.temperature !== undefined) {
        // Check if sensor is in Fahrenheit mode (mode: "f") or Celsius (mode: "c")
        // If already in Fahrenheit, don't convert
        let tempF;
        if (state.mode === 'f') {
            tempF = state.temperature;
        } else {
            tempF = (state.temperature * 9/5) + 32;
        }
        html += `
            <div class="reading">
                <span class="reading-value">${tempF.toFixed(1)}°F</span>
                <span class="reading-label">Temperature</span>
            </div>
        `;
    }

    if (state.humidity !== undefined && state.humidity > 0) {
        html += `
            <div class="reading">
                <span class="reading-value">${state.humidity}%</span>
                <span class="reading-label">Humidity</span>
            </div>
        `;
    }

    if (state.battery !== undefined) {
        const batteryPercent = convertBatteryLevel(state.battery);
        html += `
            <div class="reading">
                <span class="reading-value">${batteryPercent}%</span>
                <span class="reading-label">Battery</span>
            </div>
        `;
    }

    if (state.state !== undefined) {
        html += `
            <div class="reading">
                <span class="reading-value">${state.state}</span>
                <span class="reading-label">Status</span>
            </div>
        `;
    }

    if (state.alertType !== undefined) {
        html += `
            <div class="reading">
                <span class="reading-value">${state.alertType || 'Normal'}</span>
                <span class="reading-label">Alert</span>
            </div>
        `;
    }

    return html || '<div class="reading"><span class="reading-label">No data available</span></div>';
}

function refreshSensors() {
    const grid = document.getElementById('sensorsGrid');
    grid.innerHTML = `
        <div class="loading-state">
            <i class="fas fa-spinner fa-spin"></i>
            <p>Refreshing sensors...</p>
        </div>
    `;
    loadSensors();
}

// =============================================================================
// Tasks (Trello-like)
// =============================================================================

async function loadTasks() {
    try {
        const response = await fetch('/api/tasks');
        allTasks = await response.json();
        renderTasks();
    } catch (error) {
        console.error('Error loading tasks:', error);
        showToast('Failed to load tasks', 'error');
    }
}

function renderTasks() {
    const statuses = ['assigned', 'in_progress', 'review', 'complete'];

    statuses.forEach(status => {
        const container = document.getElementById(`tasks-${status}`);
        const countEl = document.getElementById(`count-${status}`);
        const tasks = allTasks.filter(t => t.status === status);

        countEl.textContent = tasks.length;
        container.innerHTML = '';

        tasks.forEach(task => {
            const card = createTaskCard(task);
            container.appendChild(card);
        });
    });
}

function createTaskCard(task) {
    const card = document.createElement('div');
    card.className = 'task-card';
    card.draggable = true;
    card.dataset.taskId = task.id;

    const dueDate = task.due_date ? new Date(task.due_date) : null;
    const isOverdue = dueDate && dueDate < new Date() && task.status !== 'complete';

    card.innerHTML = `
        <div class="task-priority ${task.priority}"></div>
        <h5 class="task-title">${escapeHtml(task.title)}</h5>
        ${task.description ? `<p class="task-description">${escapeHtml(task.description)}</p>` : ''}
        <div class="task-meta">
            <span class="task-assignee">
                <i class="fas fa-user"></i>
                ${task.assignee_name || 'Unassigned'}
            </span>
            ${dueDate ? `
                <span class="task-due" style="${isOverdue ? 'color: var(--neon-red)' : ''}">
                    <i class="fas fa-clock"></i>
                    ${dueDate.toLocaleDateString()}
                </span>
            ` : ''}
        </div>
        <div class="task-actions">
            <button class="task-action-btn" onclick="editTask(${task.id})">Edit</button>
            <button class="task-action-btn delete" onclick="deleteTask(${task.id})">Delete</button>
        </div>
    `;

    // Drag events
    card.addEventListener('dragstart', handleDragStart);
    card.addEventListener('dragend', handleDragEnd);

    return card;
}

function showTaskModal(taskId = null) {
    const modal = document.getElementById('taskModal');
    const title = document.getElementById('taskModalTitle');
    const form = document.getElementById('taskForm');

    form.reset();
    document.getElementById('taskId').value = '';

    if (taskId) {
        const task = allTasks.find(t => t.id === taskId);
        if (task) {
            title.textContent = 'Edit Task';
            document.getElementById('taskId').value = task.id;
            document.getElementById('taskTitle').value = task.title;
            document.getElementById('taskDescription').value = task.description || '';
            document.getElementById('taskPriority').value = task.priority;
            document.getElementById('taskAssignee').value = task.assigned_to || '';
            if (task.due_date) {
                document.getElementById('taskDueDate').value = task.due_date.slice(0, 16);
            }
        }
    } else {
        title.textContent = 'New Task';
    }

    modal.classList.add('show');
}

function closeTaskModal() {
    document.getElementById('taskModal').classList.remove('show');
}

function editTask(taskId) {
    showTaskModal(taskId);
}

async function handleTaskSubmit(e) {
    e.preventDefault();

    const taskId = document.getElementById('taskId').value;
    const taskData = {
        title: document.getElementById('taskTitle').value,
        description: document.getElementById('taskDescription').value,
        priority: document.getElementById('taskPriority').value,
        assigned_to: document.getElementById('taskAssignee').value || null,
        due_date: document.getElementById('taskDueDate').value || null
    };

    try {
        const url = taskId ? `/api/tasks/${taskId}` : '/api/tasks';
        const method = taskId ? 'PUT' : 'POST';

        const response = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(taskData)
        });

        if (response.ok) {
            showToast(taskId ? 'Task updated' : 'Task created');
            closeTaskModal();
            loadTasks();
        } else {
            showToast('Failed to save task', 'error');
        }
    } catch (error) {
        showToast('Error saving task', 'error');
    }
}

async function deleteTask(taskId) {
    if (!confirm('Are you sure you want to delete this task?')) return;

    try {
        const response = await fetch(`/api/tasks/${taskId}`, { method: 'DELETE' });

        if (response.ok) {
            showToast('Task deleted');
            loadTasks();
        } else {
            showToast('Failed to delete task', 'error');
        }
    } catch (error) {
        showToast('Error deleting task', 'error');
    }
}

// Drag and Drop
function initDragAndDrop() {
    const columns = document.querySelectorAll('.task-list');

    columns.forEach(column => {
        column.addEventListener('dragover', handleDragOver);
        column.addEventListener('drop', handleDrop);
        column.addEventListener('dragleave', handleDragLeave);
    });
}

function handleDragStart(e) {
    e.target.classList.add('dragging');
    e.dataTransfer.setData('text/plain', e.target.dataset.taskId);
}

function handleDragEnd(e) {
    e.target.classList.remove('dragging');
    document.querySelectorAll('.task-list').forEach(col => {
        col.style.background = '';
    });
}

function handleDragOver(e) {
    e.preventDefault();
    e.currentTarget.style.background = 'rgba(212, 168, 83, 0.1)';
}

function handleDragLeave(e) {
    e.currentTarget.style.background = '';
}

async function handleDrop(e) {
    e.preventDefault();
    e.currentTarget.style.background = '';

    const taskId = e.dataTransfer.getData('text/plain');
    const newStatus = e.currentTarget.parentElement.dataset.status;

    try {
        const response = await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });

        if (response.ok) {
            loadTasks();
        }
    } catch (error) {
        showToast('Failed to update task', 'error');
    }
}

// =============================================================================
// Files
// =============================================================================

async function loadFiles() {
    try {
        const response = await fetch('/api/files');
        const data = await response.json();

        renderFiles('myFiles', data.own_files, true);
        renderFiles('sharedFiles', data.shared_files, false);
        renderFiles('publicFiles', data.public_files, false);
    } catch (error) {
        console.error('Error loading files:', error);
    }
}

function renderFiles(containerId, files, isOwner) {
    const container = document.getElementById(containerId);

    if (!files || files.length === 0) {
        container.innerHTML = '<div class="empty-state">No files</div>';
        return;
    }

    container.innerHTML = '';
    files.forEach(file => {
        const card = document.createElement('div');
        card.className = 'file-card';
        card.innerHTML = `
            <div class="file-icon">
                <i class="fas ${getFileIcon(file.mime_type)}"></i>
            </div>
            <p class="file-name">${escapeHtml(file.filename)}</p>
            <p class="file-size">${formatFileSize(file.file_size)}</p>
            <div class="file-actions">
                <button class="file-btn" onclick="downloadFile(${file.id})">
                    <i class="fas fa-download"></i>
                </button>
                ${isOwner ? `
                    <button class="file-btn" onclick="showShareModal(${file.id})">
                        <i class="fas fa-share"></i>
                    </button>
                    <button class="file-btn" onclick="deleteFile(${file.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                ` : ''}
            </div>
        `;
        container.appendChild(card);
    });
}

function getFileIcon(mimeType) {
    if (!mimeType) return 'fa-file';
    if (mimeType.startsWith('image/')) return 'fa-file-image';
    if (mimeType.includes('pdf')) return 'fa-file-pdf';
    if (mimeType.includes('word') || mimeType.includes('document')) return 'fa-file-word';
    if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) return 'fa-file-excel';
    if (mimeType.includes('zip') || mimeType.includes('archive')) return 'fa-file-archive';
    if (mimeType.startsWith('text/')) return 'fa-file-alt';
    return 'fa-file';
}

function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

async function uploadFile(input) {
    const file = input.files[0];
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/files/upload', {
            method: 'POST',
            body: formData
        });

        const data = await response.json();

        if (data.success) {
            showToast('File uploaded successfully');
            loadFiles();
        } else {
            showToast(data.error || 'Upload failed', 'error');
        }
    } catch (error) {
        showToast('Error uploading file', 'error');
    }

    input.value = '';
}

function downloadFile(fileId) {
    window.location.href = `/api/files/${fileId}/download`;
}

async function deleteFile(fileId) {
    if (!confirm('Are you sure you want to delete this file?')) return;

    try {
        const response = await fetch(`/api/files/${fileId}`, { method: 'DELETE' });

        if (response.ok) {
            showToast('File deleted');
            loadFiles();
        } else {
            showToast('Failed to delete file', 'error');
        }
    } catch (error) {
        showToast('Error deleting file', 'error');
    }
}

function showShareModal(fileId) {
    const modal = document.getElementById('shareModal');
    document.getElementById('shareFileId').value = fileId;

    // Populate users list
    const usersList = document.getElementById('shareUsersList');
    usersList.innerHTML = '';

    allUsers.forEach(user => {
        if (user.id !== currentUser.id) {
            usersList.innerHTML += `
                <label>
                    <input type="checkbox" value="${user.id}">
                    <span>${user.username}</span>
                </label>
            `;
        }
    });

    modal.classList.add('show');
}

function closeShareModal() {
    document.getElementById('shareModal').classList.remove('show');
}

async function handleShareSubmit(e) {
    e.preventDefault();

    const fileId = document.getElementById('shareFileId').value;
    const isPublic = document.getElementById('sharePublic').checked;
    const checkboxes = document.querySelectorAll('#shareUsersList input:checked');
    const userIds = Array.from(checkboxes).map(cb => parseInt(cb.value));

    try {
        // Update public status
        await fetch(`/api/files/${fileId}/public`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_public: isPublic })
        });

        // Share with users
        if (userIds.length > 0) {
            await fetch(`/api/files/${fileId}/share`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ user_ids: userIds })
            });
        }

        showToast('Sharing settings updated');
        closeShareModal();
        loadFiles();
    } catch (error) {
        showToast('Error updating sharing', 'error');
    }
}

// =============================================================================
// YoLink Settings
// =============================================================================

async function saveYoLinkConfig() {
    const uaid = document.getElementById('yolinkUaid').value;
    const secretKey = document.getElementById('yolinkSecret').value;

    if (!uaid || !secretKey) {
        showToast('Please enter both UAID and Secret Key', 'error');
        return;
    }

    try {
        const response = await fetch('/api/yolink/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ uaid, secret_key: secretKey })
        });

        const data = await response.json();

        if (data.success) {
            showToast('YoLink configuration saved');
            document.getElementById('configStatus').textContent = 'Configuration saved. Sensors will reload.';
            loadSensors();
        } else {
            showToast(data.error || 'Failed to save configuration', 'error');
        }
    } catch (error) {
        showToast('Error saving configuration', 'error');
    }
}

// =============================================================================
// Utilities
// =============================================================================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Load admin data when switching to admin section
document.addEventListener('DOMContentLoaded', function() {
    const adminNav = document.querySelector('[data-section="admin"]');
    if (adminNav) {
        adminNav.addEventListener('click', loadAdminUsers);
    }
});

// =============================================================================
// Sensor Detail Modal & Charts
// =============================================================================

function showSensorModal(deviceId) {
    const device = allSensors.find(d => d.deviceId === deviceId);
    if (!device) return;

    currentSensor = device;
    const modal = document.getElementById('sensorModal');
    const title = document.getElementById('sensorModalTitle');
    const state = device.state || {};

    title.textContent = device.name || 'Sensor Details';

    // Update current stats
    if (state.temperature !== undefined) {
        const tempF = (state.temperature * 9/5) + 32;
        document.getElementById('currentTemp').textContent = `${tempF.toFixed(1)}°F`;
    } else {
        document.getElementById('currentTemp').textContent = '--';
    }

    if (state.humidity !== undefined) {
        document.getElementById('currentHumidity').textContent = `${state.humidity}%`;
    } else {
        document.getElementById('currentHumidity').textContent = '--';
    }

    if (state.battery !== undefined) {
        const batteryPercent = convertBatteryLevel(state.battery);
        document.getElementById('currentBattery').textContent = `${batteryPercent}%`;
    } else {
        document.getElementById('currentBattery').textContent = '--';
    }

    const signal = state.loraInfo?.signal;
    if (signal !== undefined) {
        document.getElementById('currentSignal').textContent = `${signal} dBm`;
    } else {
        document.getElementById('currentSignal').textContent = '--';
    }

    modal.classList.add('show');

    // Load history with default 24 hours
    loadSensorHistory(24);
}

function closeSensorModal() {
    document.getElementById('sensorModal').classList.remove('show');
    currentSensor = null;

    // Destroy charts
    if (temperatureChart) {
        temperatureChart.destroy();
        temperatureChart = null;
    }
    if (humidityChart) {
        humidityChart.destroy();
        humidityChart = null;
    }
}

// =============================================================================
// FDA Report Functions
// =============================================================================

function showFdaReportModal() {
    document.getElementById('fdaReportModal').classList.add('show');
}

function closeFdaReportModal() {
    document.getElementById('fdaReportModal').classList.remove('show');
}

function downloadFdaReport() {
    const days = document.getElementById('fdaReportDays').value;
    showToast('Generating FDA report...', 'info');

    // Create a temporary link to trigger the download
    const link = document.createElement('a');
    link.href = `/api/reports/fda-temperature?days=${days}`;
    link.target = '_blank';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    closeFdaReportModal();
    showToast('FDA report download started!', 'success');
}

async function loadSensorHistory(hours) {
    if (!currentSensor) return;

    // Update active button
    document.querySelectorAll('.chart-controls .btn').forEach(btn => {
        btn.classList.remove('active');
        if (btn.textContent.includes(hours === 6 ? '6 Hours' :
            hours === 24 ? '24 Hours' :
            hours === 72 ? '3 Days' : '1 Week')) {
            btn.classList.add('active');
        }
    });

    try {
        const response = await fetch(`/api/yolink/device/${currentSensor.deviceId}/history?hours=${hours}`);
        const data = await response.json();

        renderCharts(data.readings);
    } catch (error) {
        console.error('Error loading sensor history:', error);
        showToast('Failed to load sensor history', 'error');
    }
}

function renderCharts(readings) {
    // Destroy existing charts
    if (temperatureChart) {
        temperatureChart.destroy();
    }
    if (humidityChart) {
        humidityChart.destroy();
    }

    if (!readings || readings.length === 0) {
        // Show no data message
        const tempCtx = document.getElementById('temperatureChart').getContext('2d');
        const humCtx = document.getElementById('humidityChart').getContext('2d');

        temperatureChart = new Chart(tempCtx, {
            type: 'line',
            data: { datasets: [] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'No temperature data available. Refresh sensors to start recording.',
                        color: '#8b7355'
                    }
                }
            }
        });

        humidityChart = new Chart(humCtx, {
            type: 'line',
            data: { datasets: [] },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'No humidity data available. Refresh sensors to start recording.',
                        color: '#8b7355'
                    }
                }
            }
        });
        return;
    }

    // Prepare data
    const labels = readings.map(r => new Date(r.recorded_at));
    const tempData = readings.map(r => r.temperature !== null ? (r.temperature * 9/5) + 32 : null);
    const humData = readings.map(r => r.humidity);

    const chartOptions = {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
            mode: 'index',
            intersect: false
        },
        scales: {
            x: {
                type: 'time',
                time: {
                    displayFormats: {
                        hour: 'MMM d, h:mm a',
                        day: 'MMM d'
                    }
                },
                grid: {
                    color: 'rgba(212, 168, 83, 0.1)'
                },
                ticks: {
                    color: '#8b7355'
                }
            },
            y: {
                grid: {
                    color: 'rgba(212, 168, 83, 0.1)'
                },
                ticks: {
                    color: '#8b7355'
                }
            }
        },
        plugins: {
            legend: {
                labels: {
                    color: '#e8d5b7'
                }
            },
            tooltip: {
                backgroundColor: 'rgba(26, 18, 9, 0.95)',
                borderColor: '#d4a853',
                borderWidth: 1,
                titleColor: '#d4a853',
                bodyColor: '#e8d5b7'
            }
        }
    };

    // Temperature Chart
    const tempCtx = document.getElementById('temperatureChart').getContext('2d');
    temperatureChart = new Chart(tempCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Temperature (°F)',
                data: tempData,
                borderColor: '#ff6b6b',
                backgroundColor: 'rgba(255, 107, 107, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.3,
                pointRadius: 3,
                pointHoverRadius: 6,
                pointBackgroundColor: '#ff6b6b'
            }]
        },
        options: {
            ...chartOptions,
            plugins: {
                ...chartOptions.plugins,
                title: {
                    display: true,
                    text: 'Temperature History',
                    color: '#d4a853',
                    font: {
                        family: 'Orbitron',
                        size: 14
                    }
                }
            }
        }
    });

    // Humidity Chart
    const humCtx = document.getElementById('humidityChart').getContext('2d');
    humidityChart = new Chart(humCtx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Humidity (%)',
                data: humData,
                borderColor: '#00d4ff',
                backgroundColor: 'rgba(0, 212, 255, 0.1)',
                borderWidth: 2,
                fill: true,
                tension: 0.3,
                pointRadius: 3,
                pointHoverRadius: 6,
                pointBackgroundColor: '#00d4ff'
            }]
        },
        options: {
            ...chartOptions,
            plugins: {
                ...chartOptions.plugins,
                title: {
                    display: true,
                    text: 'Humidity History',
                    color: '#d4a853',
                    font: {
                        family: 'Orbitron',
                        size: 14
                    }
                }
            },
            scales: {
                ...chartOptions.scales,
                y: {
                    ...chartOptions.scales.y,
                    min: 0,
                    max: 100
                }
            }
        }
    });
}
