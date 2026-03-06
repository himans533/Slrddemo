/**
 * Common Utility Functions for Admin and Employee Dashboards
 */

/**
 * Escapes HTML characters to prevent XSS
 */
function escapeHtml(text) {
    if (text === null || text === undefined) return "";
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Gets initials from a full name (up to 2 characters)
 */
function getInitials(name) {
    if (!name) return "UA";
    return name
        .trim()
        .split(/\s+/)
        .map((n) => n[0])
        .join("")
        .substring(0, 2)
        .toUpperCase();
}

/**
 * Toggles dark mode and updates the theme icon
 */
function toggleTheme(bodyClass = 'dark-mode', iconId = 'themeIcon') {
    const isDark = document.body.classList.toggle(bodyClass);
    localStorage.setItem("theme", isDark ? "dark" : "light");

    // Support both ID and common class selector
    const icon = document.getElementById(iconId) || document.querySelector('.theme-toggle i') || document.querySelector('#themeToggle i');
    if (icon) {
        icon.className = isDark ? "fas fa-sun" : "fas fa-moon";
    }
    return isDark;
}

/**
 * Applies the saved theme on page load
 */
function applySavedTheme(bodyClass = 'dark-mode', iconId = 'themeIcon') {
    const savedTheme = localStorage.getItem("theme");
    if (savedTheme === "dark") {
        document.body.classList.add(bodyClass);
    } else {
        document.body.classList.remove(bodyClass);
    }

    const icon = document.getElementById(iconId) || document.querySelector('.theme-toggle i') || document.querySelector('#themeToggle i');
    if (icon) {
        const isDark = document.body.classList.contains(bodyClass);
        icon.className = isDark ? "fas fa-sun" : "fas fa-moon";
    }
}

/**
 * Opens a modal by adding the 'active' class
 */
function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add("active");
    } else {
        console.error(`Modal with ID '${modalId}' not found`);
    }
}

/**
 * Closes a modal by removing the 'active' class
 */
function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove("active");
    }
}

/**
 * Handles user logout
 */
async function handleLogout(tokenKeys = ['admin_token', 'employee_token'], redirectUrl = '/login') {
    try {
        const token = localStorage.getItem(tokenKeys[0]) || localStorage.getItem(tokenKeys[1]);
        const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

        await fetch("/api/user/logout", {
            method: "POST",
            headers: {
                ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
                ...(csrf ? { 'X-CSRF-Token': csrf } : {})
            }
        });
    } catch (err) {
        console.warn('Logout API call failed:', err);
    } finally {
        tokenKeys.forEach(key => localStorage.removeItem(key));
        localStorage.removeItem('employee_user');
        localStorage.removeItem('csrf_token');
        sessionStorage.removeItem('admin_token');
        window.location.replace(redirectUrl);
    }
}

/**
 * Toggles a panel's 'open' or 'active' class
 */
function togglePanel(panelId, activeClass = 'open') {
    const panel = document.getElementById(panelId);
    if (panel) {
        panel.classList.toggle(activeClass);
    }
}

/**
 * Displays a toast notification
 */
function showToast(message, type = "info", containerId = "toastContainer") {
    let container = document.getElementById(containerId);

    // If container doesn't exist, fallback to showNotification style or create a container
    if (!container) {
        const notification = document.createElement('div');
        notification.textContent = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            border-radius: 4px;
            background-color: ${type === 'error' ? '#dc3545' : type === 'success' ? '#28a745' : '#17a2b8'};
            color: white;
            z-index: 10000;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            font-size: 14px;
            transition: opacity 0.3s ease;
        `;
        document.body.appendChild(notification);
        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
        return;
    }

    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 500);
    }, 4000);
}

/**
 * Generates standard headers including Bearer token and CSRF
 */
function getCommonHeaders(tokenKey = 'admin_token') {
    const token = localStorage.getItem(tokenKey);
    const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    return {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...(csrf ? { 'X-CSRF-Token': csrf, 'X-CSRFToken': csrf } : {})
    };
}

/**
 * Formats a date string to a human-readable format
 */
function formatDate(dateString) {
    if (!dateString) return "No date";
    const date = new Date(dateString);
    return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
    });
}


/**
 * Returns a human-readable 'time ago' string
 */
function formatTimeAgo(dateString) {
    if (!dateString) return "Just now";
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
}

/**
 * Get authorization headers for API calls (with token fallback)
 */
function getHeaders(tokenKey = 'admin_token') {
    const token = localStorage.getItem(tokenKey) || localStorage.getItem('employee_token') || localStorage.getItem('admin_token');
    const csrf = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    return {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json',
        ...(csrf ? { 'X-CSRF-Token': csrf, 'X-CSRFToken': csrf } : {})
    };
}

/**
 * Get status color for UI display
 */
function getStatusColor(status) {
    if (!status) return '#95a5a6';
    const statusLower = status.toLowerCase();
    if (statusLower.includes('completed') || statusLower.includes('done')) return '#27ae60';
    if (statusLower.includes('progress') || statusLower.includes('in progress')) return '#3498db';
    if (statusLower.includes('pending')) return '#f39c12';
    if (statusLower.includes('overdue') || statusLower.includes('delayed')) return '#e74c3c';
    return '#95a5a6';
}

/**
 * Get priority color for UI display
 */
function getPriorityColor(priority) {
    if (!priority) return '#95a5a6';
    const priorityLower = priority.toLowerCase();
    if (priorityLower.includes('high')) return '#e74c3c';
    if (priorityLower.includes('medium')) return '#f39c12';
    if (priorityLower.includes('low')) return '#3498db';
    return '#95a5a6';
}

/**
 * Show notification (legacy compatibility)
 */
function showNotification(message, type = 'info') {
    showToast(message, type);
}

/**
 * Toggle a panel's visibility state
 */
function toggleActivityPanel(panelId = 'activityPanel', activeClass = 'active') {
    const panel = document.getElementById(panelId);
    if (panel) {
        panel.classList.toggle(activeClass);
    }
}

/**
 * Switch between tabs
 */
function switchTab(tabId, containerClass = 'tab-content', activeClass = 'active') {
    // Hide all tabs
    const tabs = document.querySelectorAll(`.${containerClass}`);
    tabs.forEach(tab => tab.classList.remove(activeClass));

    // Show selected tab
    const selectedTab = document.getElementById(tabId);
    if (selectedTab) {
        selectedTab.classList.add(activeClass);
    }
}

/**
 * Confirm action before proceeding
 */
function confirmAction(message = 'Are you sure?') {
    return confirm(message);
}

/**
 * Parse ISO date string to readable format
 */
function parseDate(dateString) {
    if (!dateString) return null;
    return new Date(dateString);
}

/**
 * Check if user has specific role
 */
function hasRole(userRole, requiredRole) {
    if (!userRole || !requiredRole) return false;
    return userRole.toLowerCase().includes(requiredRole.toLowerCase());
}

/**
 * Debounce function for search/input
 */
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
