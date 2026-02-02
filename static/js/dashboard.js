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
let autoRefreshInterval = null;
let countdownInterval = null;
let refreshCountdown = 60;
const AUTO_REFRESH_SECONDS = 60;

// Temperature unit preference (stored in localStorage)
let useCelsius = localStorage.getItem('tempUnit') === 'C';

// =============================================================================
// Initialization
// =============================================================================

document.addEventListener('DOMContentLoaded', function() {
    initNavigation();
    initDateTime();
    initDragAndDrop();
    initTempToggle();
    loadUsers();
    loadSensors();
    loadEcoFlow();
    loadTasks();
    loadFiles();
    startAutoRefresh();
    loadVersion();

    // Form handlers
    document.getElementById('taskForm').addEventListener('submit', handleTaskSubmit);
    document.getElementById('registerForm').addEventListener('submit', handleRegisterSubmit);
    document.getElementById('shareForm').addEventListener('submit', handleShareSubmit);
    document.getElementById('editUserForm').addEventListener('submit', handleEditUserSubmit);
});

// Initialize temperature toggle from saved preference
function initTempToggle() {
    const toggle = document.getElementById('tempUnitToggle');
    if (toggle) {
        toggle.checked = useCelsius;
    }
}

// Toggle temperature unit
function toggleTempUnit() {
    const toggle = document.getElementById('tempUnitToggle');
    useCelsius = toggle.checked;
    localStorage.setItem('tempUnit', useCelsius ? 'C' : 'F');
    // Re-render sensors with new unit
    if (allSensors.length > 0) {
        renderSensors(allSensors);
        renderNetworkDiagram(allSensors);
    }
    // Re-render EcoFlow display with new unit
    if (ecoflowDevices.length > 0) {
        renderPowerStationCards(ecoflowDevices);
    }
}

// Start auto-refresh
function startAutoRefresh() {
    refreshCountdown = AUTO_REFRESH_SECONDS;
    updateCountdownDisplay();

    // Clear existing intervals
    if (autoRefreshInterval) clearInterval(autoRefreshInterval);
    if (countdownInterval) clearInterval(countdownInterval);

    // Countdown timer
    countdownInterval = setInterval(() => {
        refreshCountdown--;
        updateCountdownDisplay();
        if (refreshCountdown <= 0) {
            refreshCountdown = AUTO_REFRESH_SECONDS;
            loadSensors(true); // Silent refresh
        }
    }, 1000);
}

function updateCountdownDisplay() {
    const el = document.getElementById('refreshCountdown');
    if (el) {
        el.textContent = refreshCountdown;
    }
}

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
        'appcontrol': 'App Command & Control',
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

            // Lazy-load App C&C data
            if (section === 'appcontrol') {
                loadFlashSales();
                loadPopUpLocations();
                loadAppControlStats();
            }

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
        const fullName = user.full_name || user.username;
        const displayName = user.first_name || user.last_name
            ? `${user.username} (${fullName})`
            : user.username;

        row.innerHTML = `
            <td>
                <div>${displayName}</div>
                ${user.email ? `<small style="color: var(--text-muted)">${user.email}</small>` : ''}
            </td>
            <td>
                <span class="role-badge ${user.is_admin ? 'admin' : 'user'}">
                    ${user.is_admin ? 'Admin' : 'User'}
                </span>
            </td>
            <td>${user.created_at ? new Date(user.created_at).toLocaleDateString() : '-'}</td>
            <td>${user.last_login ? new Date(user.last_login).toLocaleString() : 'Never'}</td>
            <td>
                <button class="btn btn-sm btn-primary" onclick="showEditUserModal(${user.id})">
                    <i class="fas fa-edit"></i> Edit
                </button>
                ${user.id !== currentUser.id ? `
                    <button class="btn btn-sm btn-secondary" onclick="toggleUserAdmin(${user.id}, ${!user.is_admin})">
                        ${user.is_admin ? 'Remove Admin' : 'Make Admin'}
                    </button>
                    <button class="btn btn-sm btn-danger" onclick="deleteUser(${user.id})">
                        Delete
                    </button>
                ` : ''}
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
    document.getElementById('newEmail').value = '';
    document.getElementById('newFirstName').value = '';
    document.getElementById('newLastName').value = '';
    document.getElementById('newPhone').value = '';
}

function closeRegisterModal() {
    document.getElementById('registerModal').classList.remove('show');
}

async function handleRegisterSubmit(e) {
    e.preventDefault();

    const username = document.getElementById('newUsername').value;
    const password = document.getElementById('newPassword').value;
    const email = document.getElementById('newEmail').value;
    const first_name = document.getElementById('newFirstName').value;
    const last_name = document.getElementById('newLastName').value;
    const phone = document.getElementById('newPhone').value;

    try {
        const response = await fetch('/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, password, email, first_name, last_name, phone })
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

// Edit User Modal Functions
async function showEditUserModal(userId) {
    try {
        const response = await fetch(`/api/users/${userId}`);
        if (!response.ok) {
            showToast('Failed to load user details', 'error');
            return;
        }

        const user = await response.json();

        // Populate the form
        document.getElementById('editUserId').value = user.id;
        document.getElementById('editUsername').value = user.username || '';
        document.getElementById('editFirstName').value = user.first_name || '';
        document.getElementById('editLastName').value = user.last_name || '';
        document.getElementById('editEmail').value = user.email || '';
        document.getElementById('editPhone').value = user.phone || '';
        document.getElementById('editPassword').value = '';

        // Show the modal
        document.getElementById('editUserModal').classList.add('show');
    } catch (error) {
        console.error('Error loading user:', error);
        showToast('Error loading user details', 'error');
    }
}

function closeEditUserModal() {
    document.getElementById('editUserModal').classList.remove('show');
}

async function handleEditUserSubmit(e) {
    e.preventDefault();

    const userId = document.getElementById('editUserId').value;
    const userData = {
        username: document.getElementById('editUsername').value,
        first_name: document.getElementById('editFirstName').value,
        last_name: document.getElementById('editLastName').value,
        email: document.getElementById('editEmail').value,
        phone: document.getElementById('editPhone').value
    };

    // Only include password if one was entered
    const password = document.getElementById('editPassword').value;
    if (password) {
        userData.password = password;
    }

    try {
        const response = await fetch(`/api/users/${userId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(userData)
        });

        const data = await response.json();

        if (data.success) {
            showToast('User updated successfully');
            closeEditUserModal();
            loadAdminUsers();
            loadUsers();
        } else {
            showToast(data.error || 'Failed to update user', 'error');
        }
    } catch (error) {
        console.error('Error updating user:', error);
        showToast('Error updating user', 'error');
    }
}

// =============================================================================
// Sensors
// =============================================================================

async function loadSensors(silent = false) {
    const grid = document.getElementById('sensorsGrid');

    if (!silent) {
        grid.innerHTML = `
            <div class="loading-state">
                <i class="fas fa-spinner fa-spin"></i>
                <p>Loading sensors...</p>
            </div>
        `;
    }

    try {
        const response = await fetch('/api/yolink/devices');
        const data = await response.json();

        if (data.error) {
            grid.innerHTML = `
                <div class="no-sensors">
                    <i class="fas fa-satellite-dish"></i>
                    <p>${data.error}</p>
                    ${currentUser.isAdmin ? '<p>Configure in Settings to connect your sensors.</p>' : ''}
                </div>
            `;
            updateHubStatus(false);
            return;
        }

        if (data.data && data.data.devices && data.data.devices.length > 0) {
            allSensors = data.data.devices;
            renderNetworkDiagram(allSensors);
        } else {
            grid.innerHTML = `
                <div class="no-sensors">
                    <i class="fas fa-satellite-dish"></i>
                    <p>No sensors found</p>
                    <p>Add sensors to your account to see them here.</p>
                </div>
            `;
            updateHubStatus(false);
        }
    } catch (error) {
        if (!silent) {
            grid.innerHTML = `
                <div class="no-sensors">
                    <i class="fas fa-exclamation-triangle"></i>
                    <p>Failed to load sensors</p>
                    <button class="btn btn-primary" onclick="loadSensors()">Retry</button>
                </div>
            `;
        }
        updateHubStatus(false);
    }
}

function refreshSensors() {
    refreshCountdown = AUTO_REFRESH_SECONDS;
    loadSensors(false);
}

// Update hub status in sensors card
function updateHubStatus(online) {
    const hubStatus = document.getElementById('hubStatus');
    if (hubStatus) {
        hubStatus.textContent = online ? 'Connected' : 'Offline';
        hubStatus.className = 'hub-status-badge' + (online ? ' online' : ' offline');
    }
}

// Render sensors in card format
function renderNetworkDiagram(devices) {
    const sensorsList = document.getElementById('sensorsList');
    const sensorsLoading = document.getElementById('sensorsLoading');
    const sensorsEmpty = document.getElementById('sensorsEmpty');

    if (!sensorsList) return;

    // Find hub and sensors
    const hub = devices.find(d => d.type === 'Hub');
    const sensors = devices.filter(d => d.type !== 'Hub');

    // Update hub status
    updateHubStatus(hub ? hub.online : false);

    // Hide loading
    if (sensorsLoading) sensorsLoading.style.display = 'none';

    // Check if we have sensors
    if (sensors.length === 0) {
        sensorsList.style.display = 'none';
        if (sensorsEmpty) sensorsEmpty.style.display = 'flex';
        return;
    }

    // Show sensors list
    sensorsList.style.display = 'flex';
    if (sensorsEmpty) sensorsEmpty.style.display = 'none';
    sensorsList.innerHTML = '';

    // Create sensor items
    sensors.forEach(device => {
        const state = device.state || {};
        const isOnline = device.online !== false;
        const temp = getDisplayTemperature(state.temperature, state.mode);
        const lastUpdate = device.reportAt ? formatTimeAgo(device.reportAt) : 'Unknown';
        const unit = useCelsius ? '°C' : '°F';

        // Battery level and class
        const batteryPercent = convertBatteryLevel(state.battery);
        let batteryClass = '';
        if (batteryPercent !== undefined) {
            if (batteryPercent <= 10) batteryClass = 'critical';
            else if (batteryPercent <= 25) batteryClass = 'low';
        }

        const item = document.createElement('div');
        item.className = `sensor-item ${isOnline ? '' : 'offline'}`;
        item.onclick = () => showSensorModal(device.deviceId);

        item.innerHTML = `
            <div class="sensor-item-icon">
                <i class="fas fa-thermometer-half"></i>
            </div>
            <div class="sensor-item-info">
                <div class="sensor-item-name">${device.name}</div>
                <div class="sensor-item-status">
                    <span class="status-dot"></span>
                    <span>${isOnline ? 'Online' : 'Offline'} • ${lastUpdate}</span>
                </div>
            </div>
            <div class="sensor-item-readings">
                <div class="sensor-temp">${temp !== null ? temp + unit : '--'}</div>
                ${state.humidity !== undefined && state.humidity > 0 ? `
                    <div class="sensor-humidity"><i class="fas fa-tint"></i> ${state.humidity}%</div>
                ` : ''}
                ${batteryPercent !== undefined ? `
                    <div class="sensor-battery ${batteryClass}"><i class="fas fa-battery-half"></i> ${batteryPercent}%</div>
                ` : ''}
            </div>
        `;

        sensorsList.appendChild(item);
    });
}

// Get display temperature based on unit preference
// YoLink API always returns temperature in Celsius
function getDisplayTemperature(temp, mode) {
    if (temp === undefined || temp === null) return null;

    // YoLink always reports in Celsius - mode is just display preference in app
    const tempC = temp;
    const tempF = (temp * 9/5) + 32;

    if (useCelsius) {
        return tempC.toFixed(1);
    } else {
        return tempF.toFixed(1);
    }
}

// Format time ago
function formatTimeAgo(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const seconds = Math.floor((now - date) / 1000);

    if (seconds < 60) return 'Just now';
    if (seconds < 3600) return Math.floor(seconds / 60) + 'm ago';
    if (seconds < 86400) return Math.floor(seconds / 3600) + 'h ago';
    return Math.floor(seconds / 86400) + 'd ago';
}

function renderSensors(devices) {
    const grid = document.getElementById('sensorsGrid');
    grid.innerHTML = '';

    // Filter out hub for sensor grid (hub is shown in network diagram)
    const sensors = devices.filter(d => d.type !== 'Hub');

    sensors.forEach(device => {
        const state = device.state || {};
        const isOnline = device.online !== false;
        const lastUpdate = device.reportAt ? formatTimeAgo(device.reportAt) : 'Unknown';

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
            <div class="sensor-updated">
                <i class="fas fa-clock"></i> ${lastUpdate}
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
        const temp = getDisplayTemperature(state.temperature, state.mode);
        const unit = useCelsius ? '°C' : '°F';
        html += `
            <div class="reading">
                <span class="reading-value">${temp}${unit}</span>
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

    // Define status flow for move buttons
    const statusFlow = ['assigned', 'in_progress', 'review', 'complete'];
    const statusLabels = {
        'assigned': 'Assigned',
        'in_progress': 'In Progress',
        'review': 'Review',
        'complete': 'Complete'
    };
    const currentIndex = statusFlow.indexOf(task.status);
    const prevStatus = currentIndex > 0 ? statusFlow[currentIndex - 1] : null;
    const nextStatus = currentIndex < statusFlow.length - 1 ? statusFlow[currentIndex + 1] : null;

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
        <div class="task-move-buttons">
            ${prevStatus ? `
                <button class="task-move-btn prev" onclick="moveTask(${task.id}, '${prevStatus}')" title="Move to ${statusLabels[prevStatus]}">
                    <i class="fas fa-arrow-left"></i> ${statusLabels[prevStatus]}
                </button>
            ` : '<span class="task-move-placeholder"></span>'}
            ${nextStatus ? `
                <button class="task-move-btn next" onclick="moveTask(${task.id}, '${nextStatus}')" title="Move to ${statusLabels[nextStatus]}">
                    ${statusLabels[nextStatus]} <i class="fas fa-arrow-right"></i>
                </button>
            ` : '<span class="task-move-placeholder"></span>'}
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

async function moveTask(taskId, newStatus) {
    const statusLabels = {
        'assigned': 'Assigned',
        'in_progress': 'In Progress',
        'review': 'Review',
        'complete': 'Complete'
    };

    try {
        const response = await fetch(`/api/tasks/${taskId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: newStatus })
        });

        if (response.ok) {
            showToast(`Task moved to ${statusLabels[newStatus]}`);
            loadTasks();
        } else {
            showToast('Failed to move task', 'error');
        }
    } catch (error) {
        showToast('Error moving task', 'error');
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

    // Get stat card elements
    const tempCard = document.getElementById('currentTemp').closest('.stat-card');
    const humidityCard = document.getElementById('currentHumidity').closest('.stat-card');
    const batteryCard = document.getElementById('currentBattery').closest('.stat-card');
    const signalCard = document.getElementById('currentSignal').closest('.stat-card');

    // Update current stats - only show if data exists
    if (state.temperature !== undefined) {
        // YoLink always reports in Celsius - convert based on user preference
        const temp = getDisplayTemperature(state.temperature, state.mode);
        const unit = useCelsius ? '°C' : '°F';
        document.getElementById('currentTemp').textContent = `${temp}${unit}`;
        tempCard.style.display = '';
    } else {
        tempCard.style.display = 'none';
    }

    if (state.humidity !== undefined && state.humidity > 0) {
        document.getElementById('currentHumidity').textContent = `${state.humidity}%`;
        humidityCard.style.display = '';
    } else {
        humidityCard.style.display = 'none';
    }

    if (state.battery !== undefined) {
        const batteryPercent = convertBatteryLevel(state.battery);
        document.getElementById('currentBattery').textContent = `${batteryPercent}%`;
        batteryCard.style.display = '';
    } else {
        batteryCard.style.display = 'none';
    }

    const signal = state.loraInfo?.signal;
    if (signal !== undefined) {
        document.getElementById('currentSignal').textContent = `${signal} dBm`;
        signalCard.style.display = '';
    } else {
        signalCard.style.display = 'none';
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

    // Prepare data - YoLink stores readings in Celsius
    const labels = readings.map(r => new Date(r.recorded_at));
    const tempData = readings.map(r => {
        if (r.temperature === null) return null;
        return useCelsius ? r.temperature : (r.temperature * 9/5) + 32;
    });
    const humData = readings.map(r => r.humidity);
    const tempUnit = useCelsius ? '°C' : '°F';

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
                label: `Temperature (${tempUnit})`,
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

// =============================================================================
// EcoFlow Power Stations (Multi-Device)
// =============================================================================

let ecoflowDevices = [];
let ecoflowConfigured = false;

async function loadEcoFlow() {
    const container = document.getElementById('powerStationsContainer');
    if (!container) return;

    try {
        const response = await fetch('/api/ecoflow/status');
        const data = await response.json();

        if (!data.configured || !data.devices || data.devices.length === 0) {
            ecoflowConfigured = false;
            ecoflowDevices = [];
            renderPowerStationCards([]);
            return;
        }

        ecoflowConfigured = true;
        ecoflowDevices = data.devices;
        renderPowerStationCards(data.devices);
    } catch (error) {
        console.error('Error loading EcoFlow status:', error);
        renderPowerStationCards([]);
    }
}

function renderPowerStationCards(devices) {
    const container = document.getElementById('powerStationsContainer');
    if (!container) return;
    container.innerHTML = '';

    // Render each device card
    devices.forEach(device => {
        const card = createPowerStationCard(device);
        container.appendChild(card);
    });

    // Add "Add Power Station" card (admin only)
    if (currentUser.isAdmin) {
        const addCard = document.createElement('div');
        addCard.className = 'power-station-card add-card';
        addCard.onclick = () => showEcoFlowConfigModal();
        addCard.innerHTML = `
            <div class="add-card-content">
                <i class="fas fa-plus-circle"></i>
                <span>Add Power Station</span>
            </div>
        `;
        container.appendChild(addCard);
    }
}

function createPowerStationCard(device) {
    const card = document.createElement('div');
    card.className = 'power-station-card';
    card.dataset.deviceId = device.id;

    const isOnline = device.online !== false && !device.error;
    const soc = device.soc || 0;

    // Battery bar color
    let batteryGradient = 'linear-gradient(90deg, #00d4aa, #00ff88)';
    if (soc <= 20) batteryGradient = 'linear-gradient(90deg, #ff3366, #ff6b6b)';
    else if (soc <= 50) batteryGradient = 'linear-gradient(90deg, #ffa500, #ffd700)';

    // State info
    let stateIcon = 'fa-circle', stateText = 'Idle', stateClass = 'idle';
    if (device.state === 'charging') { stateIcon = 'fa-bolt'; stateText = 'Charging'; stateClass = 'charging'; }
    else if (device.state === 'discharging') { stateIcon = 'fa-arrow-down'; stateText = 'Discharging'; stateClass = 'discharging'; }

    // Battery icon
    let battIconClass = 'fa-battery-three-quarters';
    if (soc >= 75) battIconClass = 'fa-battery-full';
    else if (soc >= 50) battIconClass = 'fa-battery-three-quarters';
    else if (soc >= 25) battIconClass = 'fa-battery-half';
    else if (soc >= 10) battIconClass = 'fa-battery-quarter';
    else battIconClass = 'fa-battery-empty';

    // Battery temp
    let battTempDisplay = '--';
    if (device.battery_temp !== null && device.battery_temp !== undefined) {
        const tempValue = useCelsius ? device.battery_temp : (device.battery_temp * 9/5) + 32;
        const unit = useCelsius ? '°C' : '°F';
        battTempDisplay = `${tempValue.toFixed(1)}${unit}`;
    }

    if (device.error && !device.online) {
        // Error/offline state
        card.innerHTML = `
            <div class="power-card-header">
                <div class="power-card-title">
                    <i class="fas fa-car-battery"></i>
                    <span>${escapeHtml(device.device_name || 'Power Station')}</span>
                </div>
                <div class="power-card-status">
                    <span class="ecoflow-status offline">Offline</span>
                    ${currentUser.isAdmin ? `
                        <button class="btn btn-sm btn-icon" onclick="showEcoFlowConfigModal(${device.id})" title="Configure">
                            <i class="fas fa-cog"></i>
                        </button>
                        <button class="btn btn-sm btn-icon btn-danger-icon" onclick="removeEcoFlowDevice(${device.id})" title="Remove">
                            <i class="fas fa-trash"></i>
                        </button>
                    ` : ''}
                </div>
            </div>
            <div class="ecoflow-error-state">
                <i class="fas fa-exclamation-triangle"></i>
                <p>${escapeHtml(device.error || 'Unable to connect')}</p>
            </div>
        `;
        return card;
    }

    card.innerHTML = `
        <div class="power-card-header">
            <div class="power-card-title">
                <i class="fas fa-car-battery"></i>
                <span>${escapeHtml(device.device_name || 'Power Station')}</span>
            </div>
            <div class="power-card-status">
                <span class="ecoflow-status ${isOnline ? 'online' : 'offline'}">${isOnline ? 'Online' : 'Offline'}</span>
                ${currentUser.isAdmin ? `
                    <button class="btn btn-sm btn-icon" onclick="showEcoFlowConfigModal(${device.id})" title="Configure">
                        <i class="fas fa-cog"></i>
                    </button>
                    <button class="btn btn-sm btn-icon btn-danger-icon" onclick="removeEcoFlowDevice(${device.id})" title="Remove">
                        <i class="fas fa-trash"></i>
                    </button>
                ` : ''}
            </div>
        </div>

        <!-- Battery gauge -->
        <div class="compact-battery-gauge">
            <div class="battery-level" style="width: ${soc}%; background: ${batteryGradient}"></div>
            <div class="battery-percentage">${soc}%</div>
        </div>
        <div class="battery-state-row">
            <span class="ecoflow-state ${stateClass}">
                <i class="fas ${stateIcon}"></i> ${stateText}
            </span>
            <span class="ecoflow-time">${device.remain_time_display || '--'}</span>
        </div>

        <!-- Power flow -->
        <div class="compact-power-flow">
            <div class="power-in">
                <i class="fas fa-arrow-down"></i>
                <span>${device.watts_in || 0}W</span>
                <small>In</small>
            </div>
            <div class="power-battery-icon">
                <i class="fas ${battIconClass} ${device.state === 'charging' ? 'charging' : ''}"></i>
            </div>
            <div class="power-out">
                <i class="fas fa-arrow-up"></i>
                <span>${device.watts_out || 0}W</span>
                <small>Out</small>
            </div>
        </div>

        ${device.solar_in_watts > 0 ? `
            <div class="solar-input">
                <i class="fas fa-sun"></i> Solar: <span>${device.solar_in_watts}W</span>
            </div>
        ` : ''}

        <!-- Stats -->
        <div class="compact-stats">
            <div class="compact-stat">
                <i class="fas fa-thermometer-half"></i>
                <span class="stat-value">${battTempDisplay}</span>
                <span class="stat-label">Batt Temp</span>
            </div>
            <div class="compact-stat">
                <i class="fas fa-bolt"></i>
                <span class="stat-value">${device.fast_charge_watts ? device.fast_charge_watts + 'W' : '--'}</span>
                <span class="stat-label">Max Input</span>
            </div>
            <div class="compact-stat">
                <i class="fas fa-shield-alt"></i>
                <span class="stat-value">${device.backup_reserve ? device.backup_reserve + '%' : '--'}</span>
                <span class="stat-label">Reserve</span>
            </div>
        </div>
    `;

    return card;
}

async function refreshEcoFlow() {
    const btn = event?.target?.closest('button');
    if (btn) {
        btn.classList.add('spinning');
        btn.disabled = true;
    }

    await loadEcoFlow();

    if (btn) {
        btn.classList.remove('spinning');
        btn.disabled = false;
    }

    showToast('Power stations refreshed');
}

async function removeEcoFlowDevice(deviceId) {
    if (!confirm('Are you sure you want to remove this power station?')) return;

    try {
        const response = await fetch(`/api/ecoflow/config/${deviceId}`, { method: 'DELETE' });
        const data = await response.json();

        if (data.success) {
            showToast('Power station removed');
            loadEcoFlow();
        } else {
            showToast(data.error || 'Failed to remove device', 'error');
        }
    } catch (error) {
        showToast('Error removing device', 'error');
    }
}

function showEcoFlowConfigModal(deviceId = null) {
    // Reset form
    document.getElementById('ecoflowConfigId').value = deviceId || '';
    document.getElementById('ecoflowDeviceNameInput').value = '';
    document.getElementById('ecoflowDeviceSn').value = '';
    document.getElementById('ecoflowAccessKey').value = '';
    document.getElementById('ecoflowSecretKey').value = '';

    const modalTitle = document.getElementById('ecoflowConfigModalTitle');
    if (modalTitle) {
        modalTitle.textContent = deviceId ? 'Edit Power Station' : 'Add Power Station';
    }

    // If editing, load existing config
    if (deviceId) {
        fetch('/api/ecoflow/config')
            .then(response => response.json())
            .then(data => {
                if (data.devices) {
                    const device = data.devices.find(d => d.id === deviceId);
                    if (device) {
                        document.getElementById('ecoflowDeviceNameInput').value = device.device_name || '';
                        document.getElementById('ecoflowDeviceSn').value = device.device_sn || '';
                    }
                }
            })
            .catch(() => {});
    }

    document.getElementById('ecoflowConfigModal').classList.add('show');
}

function closeEcoFlowConfigModal() {
    document.getElementById('ecoflowConfigModal').classList.remove('show');
}

async function saveEcoFlowConfig(event) {
    event.preventDefault();

    const configId = document.getElementById('ecoflowConfigId').value;
    const config = {
        device_name: document.getElementById('ecoflowDeviceNameInput').value,
        device_sn: document.getElementById('ecoflowDeviceSn').value,
        access_key: document.getElementById('ecoflowAccessKey').value,
        secret_key: document.getElementById('ecoflowSecretKey').value
    };

    if (configId) {
        config.id = parseInt(configId);
    }

    try {
        const response = await fetch('/api/ecoflow/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(config)
        });

        const data = await response.json();

        if (data.success) {
            showToast(configId ? 'Power station updated' : 'Power station added');
            closeEcoFlowConfigModal();
            loadEcoFlow();
        } else {
            showToast(data.error || 'Failed to save configuration', 'error');
        }
    } catch (error) {
        showToast('Error saving configuration', 'error');
    }
}


// =============================================================================
// Version and Update System
// =============================================================================

let currentVersion = null;
let pendingUpdate = null;

async function loadVersion() {
    try {
        const response = await fetch('/api/version');
        const data = await response.json();
        currentVersion = data;

        const versionText = document.getElementById('versionText');
        if (versionText) {
            let versionDisplay = data.version || 'v1.0.0';
            if (data.docker) {
                versionDisplay += ' (Docker)';
            }
            versionText.textContent = versionDisplay;
            versionText.title = `Branch: ${data.branch}\nCommit: ${data.commit}\nDate: ${data.date}${data.docker ? '\nRunning in Docker' : ''}`;
        }
    } catch (error) {
        console.error('Error loading version:', error);
        const versionText = document.getElementById('versionText');
        if (versionText) {
            versionText.textContent = 'v1.0.0';
        }
    }
}

async function checkForUpdates() {
    const btn = document.getElementById('updateCheckBtn');
    if (btn) {
        btn.classList.add('checking');
    }

    try {
        const response = await fetch('/api/updates/check');
        const data = await response.json();

        if (data.error) {
            showToast(data.error, 'error');
            return;
        }

        if (data.update_available) {
            pendingUpdate = data;

            // Update button state
            if (btn) {
                btn.classList.remove('checking');
                btn.classList.add('has-update');
            }

            // Update version info
            const versionInfo = document.getElementById('versionInfo');
            if (versionInfo) {
                versionInfo.classList.add('update-available');
            }

            // Show update modal
            showUpdateModal(data);
        } else {
            showToast('You are running the latest version!', 'success');
        }
    } catch (error) {
        console.error('Error checking for updates:', error);
        showToast('Failed to check for updates', 'error');
    } finally {
        if (btn) {
            btn.classList.remove('checking');
        }
    }
}

function showUpdateModal(updateInfo) {
    document.getElementById('updateCurrentVersion').textContent = updateInfo.current_commit;
    document.getElementById('updateNewVersion').textContent = updateInfo.remote_commit;
    document.getElementById('commitCount').textContent = updateInfo.behind_count;

    const commitList = document.getElementById('commitList');
    commitList.innerHTML = '';

    updateInfo.pending_commits.forEach(commit => {
        const li = document.createElement('li');
        li.textContent = commit;
        commitList.appendChild(li);
    });

    document.getElementById('updateModal').classList.add('show');
}

function closeUpdateModal() {
    document.getElementById('updateModal').classList.remove('show');
}

async function applyUpdate() {
    closeUpdateModal();

    // Show update overlay
    const overlay = document.getElementById('updateOverlay');
    const progressBar = document.getElementById('updateProgressBar');
    const statusText = document.getElementById('updateStatus');

    overlay.classList.add('active');

    // Animate progress bar
    let progress = 0;
    const progressInterval = setInterval(() => {
        progress += Math.random() * 15;
        if (progress > 90) progress = 90;
        progressBar.style.width = progress + '%';
    }, 300);

    statusText.textContent = 'Downloading updates...';

    try {
        // Simulate some delay for visual effect
        await new Promise(resolve => setTimeout(resolve, 1000));

        statusText.textContent = 'Applying updates...';

        const response = await fetch('/api/updates/apply', { method: 'POST' });
        const data = await response.json();

        clearInterval(progressInterval);

        if (data.success) {
            progressBar.style.width = '100%';
            statusText.textContent = 'Update complete! Restarting...';

            // Wait a moment then reload
            await new Promise(resolve => setTimeout(resolve, 2000));

            // Show success state
            overlay.classList.add('success');
            statusText.textContent = 'Reloading application...';

            // Reload the page after animation
            await new Promise(resolve => setTimeout(resolve, 1500));
            window.location.reload(true);
        } else {
            progressBar.style.width = '0%';
            statusText.textContent = 'Update failed: ' + (data.error || 'Unknown error');

            // Hide overlay after error display
            await new Promise(resolve => setTimeout(resolve, 3000));
            overlay.classList.remove('active');
            showToast('Update failed: ' + (data.error || 'Unknown error'), 'error');
        }
    } catch (error) {
        clearInterval(progressInterval);
        progressBar.style.width = '0%';
        statusText.textContent = 'Update failed: Network error';

        // Hide overlay after error display
        await new Promise(resolve => setTimeout(resolve, 3000));
        overlay.classList.remove('active');
        showToast('Update failed: Network error', 'error');
    }
}

// =============================================================================
// App Command & Control - Flash Sales
// =============================================================================

async function loadFlashSales() {
    try {
        const response = await fetch('/api/flash-sales');
        const sales = await response.json();
        renderFlashSalesTable(sales);
    } catch (error) {
        console.error('Error loading flash sales:', error);
    }
}

function renderFlashSalesTable(sales) {
    const tbody = document.getElementById('flashSalesTableBody');
    const empty = document.getElementById('flashSalesEmpty');
    if (!tbody) return;

    if (sales.length === 0) {
        tbody.innerHTML = '';
        if (empty) empty.style.display = 'flex';
        return;
    }
    if (empty) empty.style.display = 'none';

    tbody.innerHTML = sales.map(sale => {
        const expires = new Date(sale.expires_at);
        const isExpired = expires < new Date();
        const statusClass = !sale.is_active ? 'inactive' : isExpired ? 'expired' : 'active';
        const statusText = !sale.is_active ? 'Inactive' : isExpired ? 'Expired' : 'Live';
        const discount = sale.original_price > 0 ? Math.round(((sale.original_price - sale.sale_price) / sale.original_price) * 100) : 0;

        return `<tr>
            <td><strong>${escapeHtml(sale.title)}</strong></td>
            <td>${escapeHtml(sale.cut_type)}</td>
            <td>$${sale.original_price.toFixed(2)}</td>
            <td><span class="sale-price-badge">$${sale.sale_price.toFixed(2)} <small>(-${discount}%)</small></span></td>
            <td>${expires.toLocaleDateString()} ${expires.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}</td>
            <td><span class="cc-status ${statusClass}">${statusText}</span></td>
            <td>
                <button class="btn btn-sm btn-icon" onclick="editFlashSale(${sale.id})" title="Edit"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-icon btn-danger-icon" onclick="deleteFlashSale(${sale.id})" title="Delete"><i class="fas fa-trash"></i></button>
            </td>
        </tr>`;
    }).join('');
}

function showFlashSaleModal(saleId = null) {
    document.getElementById('flashSaleId').value = '';
    document.getElementById('flashSaleTitle').value = '';
    document.getElementById('flashSaleDescription').value = '';
    document.getElementById('flashSaleCutType').value = 'Custom Box';
    document.getElementById('flashSaleWeight').value = '1.0';
    document.getElementById('flashSaleOrigPrice').value = '';
    document.getElementById('flashSaleSalePrice').value = '';
    document.getElementById('flashSaleIcon').value = 'flame.fill';
    document.getElementById('flashSaleActive').checked = true;

    // Default: starts now, expires in 24h
    const now = new Date();
    const tomorrow = new Date(now.getTime() + 24 * 60 * 60 * 1000);
    document.getElementById('flashSaleStartsAt').value = toLocalISOString(now);
    document.getElementById('flashSaleExpiresAt').value = toLocalISOString(tomorrow);

    document.getElementById('flashSaleModalTitle').innerHTML = '<i class="fas fa-bolt"></i> New Flash Sale';
    document.getElementById('flashSaleModal').classList.add('show');
}

function closeFlashSaleModal() {
    document.getElementById('flashSaleModal').classList.remove('show');
}

async function editFlashSale(saleId) {
    try {
        const response = await fetch('/api/flash-sales');
        const sales = await response.json();
        const sale = sales.find(s => s.id === saleId);
        if (!sale) return;

        document.getElementById('flashSaleId').value = sale.id;
        document.getElementById('flashSaleTitle').value = sale.title;
        document.getElementById('flashSaleDescription').value = sale.description;
        document.getElementById('flashSaleCutType').value = sale.cut_type;
        document.getElementById('flashSaleWeight').value = sale.weight_lbs;
        document.getElementById('flashSaleOrigPrice').value = sale.original_price;
        document.getElementById('flashSaleSalePrice').value = sale.sale_price;
        document.getElementById('flashSaleIcon').value = sale.image_system_name;
        document.getElementById('flashSaleActive').checked = sale.is_active;

        if (sale.starts_at) document.getElementById('flashSaleStartsAt').value = toLocalISOString(new Date(sale.starts_at));
        if (sale.expires_at) document.getElementById('flashSaleExpiresAt').value = toLocalISOString(new Date(sale.expires_at));

        document.getElementById('flashSaleModalTitle').innerHTML = '<i class="fas fa-bolt"></i> Edit Flash Sale';
        document.getElementById('flashSaleModal').classList.add('show');
    } catch (error) {
        showToast('Error loading sale details', 'error');
    }
}

async function saveFlashSale(event) {
    event.preventDefault();
    const saleId = document.getElementById('flashSaleId').value;
    const data = {
        title: document.getElementById('flashSaleTitle').value,
        description: document.getElementById('flashSaleDescription').value,
        cut_type: document.getElementById('flashSaleCutType').value,
        weight_lbs: parseFloat(document.getElementById('flashSaleWeight').value),
        original_price: parseFloat(document.getElementById('flashSaleOrigPrice').value),
        sale_price: parseFloat(document.getElementById('flashSaleSalePrice').value),
        starts_at: document.getElementById('flashSaleStartsAt').value,
        expires_at: document.getElementById('flashSaleExpiresAt').value,
        image_system_name: document.getElementById('flashSaleIcon').value,
        is_active: document.getElementById('flashSaleActive').checked
    };
    if (saleId) data.id = parseInt(saleId);

    try {
        const response = await fetch('/api/flash-sales', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.success) {
            showToast(saleId ? 'Flash sale updated' : 'Flash sale pushed to app');
            closeFlashSaleModal();
            loadFlashSales();
        } else {
            showToast(result.error || 'Failed to save', 'error');
        }
    } catch (error) {
        showToast('Error saving flash sale', 'error');
    }
}

async function deleteFlashSale(saleId) {
    if (!confirm('Delete this flash sale?')) return;
    try {
        const response = await fetch(`/api/flash-sales/${saleId}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.success) {
            showToast('Flash sale deleted');
            loadFlashSales();
        } else {
            showToast(data.error || 'Failed to delete', 'error');
        }
    } catch (error) {
        showToast('Error deleting flash sale', 'error');
    }
}

// =============================================================================
// App Command & Control - Pop-Up Locations
// =============================================================================

async function loadPopUpLocations() {
    try {
        const response = await fetch('/api/popup-locations');
        const locations = await response.json();
        renderPopUpTable(locations);
    } catch (error) {
        console.error('Error loading pop-up locations:', error);
    }
}

function renderPopUpTable(locations) {
    const tbody = document.getElementById('popUpTableBody');
    const empty = document.getElementById('popUpEmpty');
    if (!tbody) return;

    if (locations.length === 0) {
        tbody.innerHTML = '';
        if (empty) empty.style.display = 'flex';
        return;
    }
    if (empty) empty.style.display = 'none';

    tbody.innerHTML = locations.map(loc => {
        const date = new Date(loc.date);
        const endDate = loc.end_date ? new Date(loc.end_date) : null;
        const isPast = date < new Date();
        const statusClass = !loc.is_active ? 'inactive' : isPast ? 'expired' : 'active';
        const statusText = !loc.is_active ? 'Inactive' : isPast ? 'Past' : 'Upcoming';
        const timeStr = endDate
            ? `${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})} - ${endDate.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`
            : date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'});

        const hasCoords = loc.latitude && loc.longitude;
        const coordsStr = hasCoords
            ? `<a href="https://maps.google.com/?q=${loc.latitude},${loc.longitude}" target="_blank" class="coords-link" title="Open in Google Maps">${loc.latitude.toFixed(4)}, ${loc.longitude.toFixed(4)}</a>`
            : '<span class="text-muted">--</span>';

        return `<tr>
            <td><strong>${escapeHtml(loc.title)}</strong></td>
            <td>${escapeHtml(loc.location)}</td>
            <td>${coordsStr}</td>
            <td>${date.toLocaleDateString()}</td>
            <td>${timeStr}</td>
            <td><span class="cc-status ${statusClass}">${statusText}</span></td>
            <td>
                <button class="btn btn-sm btn-icon" onclick="editPopUpLocation(${loc.id})" title="Edit"><i class="fas fa-edit"></i></button>
                <button class="btn btn-sm btn-icon btn-danger-icon" onclick="deletePopUpLocation(${loc.id})" title="Delete"><i class="fas fa-trash"></i></button>
            </td>
        </tr>`;
    }).join('');
}

function showPopUpModal(locId = null) {
    document.getElementById('popUpId').value = '';
    document.getElementById('popUpTitle').value = '';
    document.getElementById('popUpLocation').value = '';
    document.getElementById('popUpLatitude').value = '';
    document.getElementById('popUpLongitude').value = '';
    document.getElementById('popUpIcon').value = 'leaf.fill';
    document.getElementById('popUpActive').checked = true;
    document.getElementById('popUpDate').value = '';
    document.getElementById('popUpEndDate').value = '';
    clearGeocodeStatus();

    document.getElementById('popUpModalTitle').innerHTML = '<i class="fas fa-map-marker-alt"></i> New Pop-Up Location';
    document.getElementById('popUpModal').classList.add('show');
}

function closePopUpModal() {
    document.getElementById('popUpModal').classList.remove('show');
}

async function editPopUpLocation(locId) {
    try {
        const response = await fetch('/api/popup-locations');
        const locations = await response.json();
        const loc = locations.find(l => l.id === locId);
        if (!loc) return;

        document.getElementById('popUpId').value = loc.id;
        document.getElementById('popUpTitle').value = loc.title;
        document.getElementById('popUpLocation').value = loc.location;
        document.getElementById('popUpLatitude').value = loc.latitude || '';
        document.getElementById('popUpLongitude').value = loc.longitude || '';
        document.getElementById('popUpIcon').value = loc.icon;
        document.getElementById('popUpActive').checked = loc.is_active;
        clearGeocodeStatus();

        if (loc.date) document.getElementById('popUpDate').value = toLocalISOString(new Date(loc.date));
        if (loc.end_date) document.getElementById('popUpEndDate').value = toLocalISOString(new Date(loc.end_date));

        document.getElementById('popUpModalTitle').innerHTML = '<i class="fas fa-map-marker-alt"></i> Edit Pop-Up Location';
        document.getElementById('popUpModal').classList.add('show');
    } catch (error) {
        showToast('Error loading location details', 'error');
    }
}

async function geocodePopUpAddress() {
    const address = document.getElementById('popUpLocation').value.trim();
    if (!address) { showToast('Enter an address first', 'error'); return; }

    setGeocodeStatus('Looking up coordinates...', 'loading');
    try {
        const response = await fetch('/api/geocode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address })
        });
        const data = await response.json();
        if (data.success) {
            document.getElementById('popUpLatitude').value = data.latitude.toFixed(6);
            document.getElementById('popUpLongitude').value = data.longitude.toFixed(6);
            setGeocodeStatus(`Found: ${data.display_name}`, 'success');
        } else {
            setGeocodeStatus(data.error || 'Address not found', 'error');
        }
    } catch (error) {
        setGeocodeStatus('Geocode request failed', 'error');
    }
}

async function reverseGeocodePopUp() {
    const lat = document.getElementById('popUpLatitude').value;
    const lng = document.getElementById('popUpLongitude').value;
    if (!lat || !lng) { showToast('Enter lat/lng first', 'error'); return; }

    setGeocodeStatus('Looking up address...', 'loading');
    try {
        const response = await fetch('/api/reverse-geocode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ latitude: parseFloat(lat), longitude: parseFloat(lng) })
        });
        const data = await response.json();
        if (data.success) {
            document.getElementById('popUpLocation').value = data.address;
            setGeocodeStatus('Address found from coordinates', 'success');
        } else {
            setGeocodeStatus(data.error || 'Location not found', 'error');
        }
    } catch (error) {
        setGeocodeStatus('Reverse geocode failed', 'error');
    }
}

function setGeocodeStatus(msg, type) {
    const el = document.getElementById('geocodeStatus');
    if (!el) return;
    el.textContent = msg;
    el.className = 'geocode-status ' + type;
    el.style.display = 'block';
}

function clearGeocodeStatus() {
    const el = document.getElementById('geocodeStatus');
    if (el) { el.textContent = ''; el.style.display = 'none'; }
}

async function savePopUpLocation(event) {
    event.preventDefault();
    const locId = document.getElementById('popUpId').value;
    const data = {
        title: document.getElementById('popUpTitle').value,
        location: document.getElementById('popUpLocation').value,
        latitude: document.getElementById('popUpLatitude').value || null,
        longitude: document.getElementById('popUpLongitude').value || null,
        date: document.getElementById('popUpDate').value,
        end_date: document.getElementById('popUpEndDate').value || null,
        icon: document.getElementById('popUpIcon').value,
        is_active: document.getElementById('popUpActive').checked
    };
    if (locId) data.id = parseInt(locId);

    try {
        const response = await fetch('/api/popup-locations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.success) {
            showToast(locId ? 'Location updated' : 'Location added');
            closePopUpModal();
            loadPopUpLocations();
        } else {
            showToast(result.error || 'Failed to save', 'error');
        }
    } catch (error) {
        showToast('Error saving location', 'error');
    }
}

async function deletePopUpLocation(locId) {
    if (!confirm('Delete this pop-up location?')) return;
    try {
        const response = await fetch(`/api/popup-locations/${locId}`, { method: 'DELETE' });
        const data = await response.json();
        if (data.success) {
            showToast('Location deleted');
            loadPopUpLocations();
        } else {
            showToast(data.error || 'Failed to delete', 'error');
        }
    } catch (error) {
        showToast('Error deleting location', 'error');
    }
}

// =============================================================================
// App Command & Control - Square Config & Stats
// =============================================================================

async function loadAppControlStats() {
    // Load Square status
    try {
        const resp = await fetch('/api/square/config');
        const data = await resp.json();
        const el = document.getElementById('squareStatus');
        if (el) {
            el.textContent = data.configured && data.has_token ? 'Connected' : 'Not Configured';
            el.className = 'cc-stat-value ' + (data.configured && data.has_token ? 'connected' : '');
        }
    } catch (e) {}

    // Load device count
    try {
        const resp = await fetch('/api/devices');
        const devices = await resp.json();
        const el = document.getElementById('deviceCount');
        if (el) el.textContent = Array.isArray(devices) ? devices.length : '0';
    } catch (e) {}

    // Load APNs status
    try {
        const resp = await fetch('/api/apns/status');
        const data = await resp.json();
        const el = document.getElementById('apnsStatus');
        if (el) {
            if (!data.available) {
                el.textContent = 'Not Installed';
            } else if (!data.key_configured) {
                el.textContent = 'Key Missing';
            } else {
                el.textContent = `Ready (${data.active_devices} devices)`;
                el.className = 'cc-stat-value connected';
            }
        }
    } catch (e) {}
}

async function testPushNotification() {
    if (!confirm('Send a test push notification to all registered devices?')) return;
    try {
        const resp = await fetch('/api/apns/test', { method: 'POST' });
        const data = await resp.json();
        if (data.success) {
            showToast(`Test push sent to ${data.sent} device(s)`);
        } else {
            showToast(data.error || 'Failed to send', 'error');
        }
    } catch (e) {
        showToast('Error sending test push', 'error');
    }
}

function showSquareConfigModal() {
    fetch('/api/square/config')
        .then(r => r.json())
        .then(data => {
            if (data.configured) {
                document.getElementById('squareLocationId').value = data.location_id || '';
                document.getElementById('squareEnvironment').value = data.environment || 'production';
            }
        })
        .catch(() => {});
    document.getElementById('squareConfigModal').classList.add('show');
}

function closeSquareConfigModal() {
    document.getElementById('squareConfigModal').classList.remove('show');
}

async function saveSquareConfig(event) {
    event.preventDefault();
    const data = {
        access_token: document.getElementById('squareAccessToken').value,
        location_id: document.getElementById('squareLocationId').value,
        environment: document.getElementById('squareEnvironment').value
    };

    try {
        const response = await fetch('/api/square/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        const result = await response.json();
        if (result.success) {
            showToast('Square configuration saved');
            closeSquareConfigModal();
            loadAppControlStats();
        } else {
            showToast(result.error || 'Failed to save', 'error');
        }
    } catch (error) {
        showToast('Error saving configuration', 'error');
    }
}

// Helper: convert Date to local datetime-local input value
function toLocalISOString(date) {
    const offset = date.getTimezoneOffset();
    const local = new Date(date.getTime() - offset * 60 * 1000);
    return local.toISOString().slice(0, 16);
}
