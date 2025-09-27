/**
 * Gate Management System - Core JavaScript
 * Handles common functionality across the application
 */

// Global state management
window.GateMS = {
    user: null,
    location: null,
    isOnline: navigator.onLine,
    notifications: [],
    cache: new Map()
};

// Initialize app when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeApp();
    registerServiceWorker();
    setupOfflineHandling();
    loadUserData();
});

/**
 * Initialize core application functionality
 */
function initializeApp() {
    // Set up CSRF token for all requests
    setupCSRF();
    
    // Initialize PWA features
    setupPWA();
    
    // Set up global error handling
    setupErrorHandling();
    
    // Initialize touch gestures for mobile
    setupTouchGestures();
    
    console.log('🚀 Gate Management System initialized');
}

/**
 * Service Worker registration for PWA functionality
 */
async function registerServiceWorker() {
    if ('serviceWorker' in navigator) {
        try {
            const registration = await navigator.serviceWorker.register('/sw.js');
            console.log('✅ Service Worker registered:', registration);
            
            // Listen for updates
            registration.addEventListener('updatefound', () => {
                showNotification('info', 'Update Available', 'A new version is available. Refresh to update.');
            });
        } catch (error) {
            console.error('❌ Service Worker registration failed:', error);
        }
    }
}

/**
 * Setup PWA functionality
 */
function setupPWA() {
    // Handle install prompt
    let deferredPrompt;
    
    window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPrompt = e;
        
        // Show install button if not already installed
        const installBtn = document.getElementById('install-app-btn');
        if (installBtn) {
            installBtn.style.display = 'block';
            installBtn.addEventListener('click', async () => {
                if (deferredPrompt) {
                    deferredPrompt.prompt();
                    const { outcome } = await deferredPrompt.userChoice;
                    console.log(`PWA install ${outcome}`);
                    deferredPrompt = null;
                    installBtn.style.display = 'none';
                }
            });
        }
    });
    
    // Handle successful installation
    window.addEventListener('appinstalled', () => {
        showNotification('success', 'App Installed', 'Gate Management System has been installed successfully!');
    });
}

/**
 * Setup offline/online handling
 */
function setupOfflineHandling() {
    window.addEventListener('online', () => {
        window.GateMS.isOnline = true;
        showNotification('success', 'Back Online', 'Connection restored. Syncing data...');
        syncOfflineData();
    });
    
    window.addEventListener('offline', () => {
        window.GateMS.isOnline = false;
        showNotification('warning', 'Offline Mode', 'You\'re offline. Changes will be saved locally.');
    });
}

/**
 * Load current user data
 */
async function loadUserData() {
    try {
        const response = await fetch('/auth/me');
        if (response.ok) {
            const data = await response.json();
            window.GateMS.user = data.user;
        }
    } catch (error) {
        console.log('User not authenticated');
    }
}

/**
 * Setup CSRF protection
 */
function setupCSRF() {
    // Add CSRF token to all requests
    const originalFetch = window.fetch;
    window.fetch = function(url, options = {}) {
        if (options.method && options.method.toUpperCase() !== 'GET') {
            options.headers = {
                ...options.headers,
                'X-Requested-With': 'XMLHttpRequest'
            };
        }
        return originalFetch(url, options);
    };
}

/**
 * Global error handling
 */
function setupErrorHandling() {
    window.addEventListener('error', (event) => {
        console.error('Global error:', event.error);
        showNotification('error', 'Error', 'An unexpected error occurred');
    });
    
    window.addEventListener('unhandledrejection', (event) => {
        console.error('Unhandled promise rejection:', event.reason);
        showNotification('error', 'Error', 'A network error occurred');
    });
}

/**
 * Setup touch gestures for mobile
 */
function setupTouchGestures() {
    let touchStartX = 0;
    let touchStartY = 0;
    
    document.addEventListener('touchstart', (e) => {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
    });
    
    document.addEventListener('touchend', (e) => {
        if (!touchStartX || !touchStartY) return;
        
        const touchEndX = e.changedTouches[0].clientX;
        const touchEndY = e.changedTouches[0].clientY;
        
        const diffX = touchStartX - touchEndX;
        const diffY = touchStartY - touchEndY;
        
        // Horizontal swipe
        if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 50) {
            if (diffX > 0) {
                // Swipe left - could trigger navigation
                handleSwipeLeft();
            } else {
                // Swipe right - could trigger back navigation
                handleSwipeRight();
            }
        }
        
        touchStartX = 0;
        touchStartY = 0;
    });
}

function handleSwipeLeft() {
    // Could implement tab switching or navigation
}

function handleSwipeRight() {
    // Could implement back navigation
    if (window.history.length > 1) {
        window.history.back();
    }
}

/**
 * Notification system
 */
function showNotification(type, title, message, duration = 5000) {
    const toast = document.getElementById('notification-toast');
    const titleEl = document.getElementById('toast-title');
    const messageEl = document.getElementById('toast-message');
    const iconEl = document.getElementById('toast-icon');
    
    if (!toast) return;
    
    // Set content
    titleEl.textContent = title;
    messageEl.textContent = message;
    
    // Set icon based on type
    let iconHtml = '';
    let iconClass = '';
    
    switch (type) {
        case 'success':
            iconHtml = '<i data-feather="check-circle" class="w-5 h-5 text-green-600"></i>';
            iconClass = 'text-green-600';
            break;
        case 'error':
            iconHtml = '<i data-feather="x-circle" class="w-5 h-5 text-red-600"></i>';
            iconClass = 'text-red-600';
            break;
        case 'warning':
            iconHtml = '<i data-feather="alert-triangle" class="w-5 h-5 text-yellow-600"></i>';
            iconClass = 'text-yellow-600';
            break;
        case 'info':
        default:
            iconHtml = '<i data-feather="info" class="w-5 h-5 text-blue-600"></i>';
            iconClass = 'text-blue-600';
            break;
    }
    
    iconEl.innerHTML = iconHtml;
    iconEl.className = iconClass;
    
    // Show toast
    toast.classList.remove('hidden');
    toast.classList.add('fade-in');
    
    // Replace feather icons
    feather.replace();
    
    // Auto hide after duration
    if (duration > 0) {
        setTimeout(() => {
            hideNotification();
        }, duration);
    }
    
    // Store in notifications array
    window.GateMS.notifications.push({
        type, title, message, timestamp: new Date()
    });
}

function hideNotification() {
    const toast = document.getElementById('notification-toast');
    if (toast) {
        toast.classList.add('hidden');
        toast.classList.remove('fade-in');
    }
}

/**
 * Loading state management
 */
function showLoading(message = 'Loading...') {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.querySelector('span').textContent = message;
        overlay.classList.remove('hidden');
    }
}

function hideLoading() {
    const overlay = document.getElementById('loading-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
    }
}

/**
 * Logout functionality
 */
async function logout() {
    try {
        showLoading('Logging out...');
        
        const response = await fetch('/auth/logout', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        // Clear local data
        window.GateMS.user = null;
        localStorage.clear();
        sessionStorage.clear();
        
        // Redirect to login
        window.location.href = '/auth/login';
        
    } catch (error) {
        console.error('Logout error:', error);
        // Force redirect even if logout request fails
        window.location.href = '/auth/login';
    } finally {
        hideLoading();
    }
}

/**
 * QR Code scanner functionality
 */
function openQRScanner() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        showNotification('error', 'Camera Not Supported', 'QR scanning requires camera access');
        return;
    }
    
    window.location.href = '/qr/scan';
}

/**
 * Offline data synchronization
 */
async function syncOfflineData() {
    if (!window.GateMS.isOnline) return;
    
    try {
        // Get offline data from localStorage
        const offlineData = JSON.parse(localStorage.getItem('offlineData') || '[]');
        
        if (offlineData.length === 0) return;
        
        showLoading('Syncing offline data...');
        
        // Process each offline action
        for (const action of offlineData) {
            try {
                await fetch(action.url, {
                    method: action.method,
                    headers: action.headers,
                    body: action.body
                });
            } catch (error) {
                console.error('Failed to sync action:', action, error);
            }
        }
        
        // Clear offline data after successful sync
        localStorage.removeItem('offlineData');
        showNotification('success', 'Sync Complete', 'All offline changes have been synchronized');
        
    } catch (error) {
        console.error('Sync failed:', error);
        showNotification('error', 'Sync Failed', 'Some offline changes could not be synchronized');
    } finally {
        hideLoading();
    }
}

/**
 * Store action for offline sync
 */
function storeOfflineAction(url, method, headers, body) {
    if (window.GateMS.isOnline) return;
    
    const offlineData = JSON.parse(localStorage.getItem('offlineData') || '[]');
    offlineData.push({
        url, method, headers, body,
        timestamp: new Date().toISOString()
    });
    localStorage.setItem('offlineData', JSON.stringify(offlineData));
}

/**
 * Cache management
 */
function cacheData(key, data, ttl = 300000) { // 5 minutes default TTL
    window.GateMS.cache.set(key, {
        data,
        expires: Date.now() + ttl
    });
}

function getCachedData(key) {
    const cached = window.GateMS.cache.get(key);
    if (!cached) return null;
    
    if (Date.now() > cached.expires) {
        window.GateMS.cache.delete(key);
        return null;
    }
    
    return cached.data;
}

/**
 * Utility functions
 */

// Format date/time
function formatDateTime(dateString, options = {}) {
    const date = new Date(dateString);
    const defaultOptions = {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
    };
    
    return date.toLocaleDateString('en-US', { ...defaultOptions, ...options });
}

// Debounce function
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

// Throttle function
function throttle(func, limit) {
    let inThrottle;
    return function(...args) {
        if (!inThrottle) {
            func.apply(this, args);
            inThrottle = true;
            setTimeout(() => inThrottle = false, limit);
        }
    };
}

// Generate random ID
function generateId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2);
}

// Export to global scope
window.showNotification = showNotification;
window.hideNotification = hideNotification;
window.showLoading = showLoading;
window.hideLoading = hideLoading;
window.logout = logout;
window.openQRScanner = openQRScanner;
window.formatDateTime = formatDateTime;
window.debounce = debounce;
window.throttle = throttle;
window.generateId = generateId;