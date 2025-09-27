/**
 * Gate Management System - Service Worker
 * Provides offline functionality and caching for PWA features
 */

const CACHE_NAME = 'gate-management-v1.0.0';
const OFFLINE_URL = '/offline.html';

// Files to cache for offline functionality
const CACHE_URLS = [
    '/',
    '/static/css/app.css',
    '/static/js/app.js',
    '/static/images/logo.png',
    '/static/images/icon-192.png',
    '/static/images/icon-512.png',
    '/offline.html',
    'https://cdn.tailwindcss.com',
    'https://unpkg.com/feather-icons/dist/feather.min.js',
    'https://cdn.jsdelivr.net/npm/chart.js',
    'https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js'
];

// API endpoints that should work offline (with cached data)
const OFFLINE_FALLBACK_PAGES = [
    '/dashboard',
    '/visitors',
    '/vehicles',
    '/qr/scan'
];

// Install event - cache resources
self.addEventListener('install', (event) => {
    console.log('🔧 Service Worker installing...');
    
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then((cache) => {
                console.log('📦 Caching app shell');
                return cache.addAll(CACHE_URLS);
            })
            .then(() => {
                console.log('✅ Service Worker installed');
                return self.skipWaiting();
            })
            .catch((error) => {
                console.error('❌ Service Worker install failed:', error);
            })
    );
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
    console.log('🚀 Service Worker activating...');
    
    event.waitUntil(
        caches.keys()
            .then((cacheNames) => {
                return Promise.all(
                    cacheNames.map((cacheName) => {
                        if (cacheName !== CACHE_NAME) {
                            console.log('🗑️ Deleting old cache:', cacheName);
                            return caches.delete(cacheName);
                        }
                    })
                );
            })
            .then(() => {
                console.log('✅ Service Worker activated');
                return self.clients.claim();
            })
    );
});

// Fetch event - serve cached content when offline
self.addEventListener('fetch', (event) => {
    const { request } = event;
    const url = new URL(request.url);
    
    // Skip non-GET requests
    if (request.method !== 'GET') {
        return;
    }
    
    // Handle different types of requests
    if (url.pathname.startsWith('/api/')) {
        // API requests - try network first, then cache
        event.respondWith(handleApiRequest(request));
    } else if (url.pathname.endsWith('.png') || url.pathname.endsWith('.jpg') || url.pathname.endsWith('.svg')) {
        // Image requests - cache first
        event.respondWith(handleImageRequest(request));
    } else if (OFFLINE_FALLBACK_PAGES.some(page => url.pathname.startsWith(page))) {
        // App pages - network first, fallback to cache
        event.respondWith(handlePageRequest(request));
    } else {
        // Other requests - cache first
        event.respondWith(handleStaticRequest(request));
    }
});

/**
 * Handle API requests - network first with offline storage
 */
async function handleApiRequest(request) {
    const url = new URL(request.url);
    
    try {
        // Try network first
        const response = await fetch(request);
        
        if (response.ok) {
            // Cache successful GET responses
            if (request.method === 'GET') {
                const cache = await caches.open(CACHE_NAME);
                cache.put(request, response.clone());
            }
            return response;
        }
        
        throw new Error('Network response was not ok');
        
    } catch (error) {
        console.log('📡 API request failed, checking cache:', url.pathname);
        
        // Try to get from cache
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }
        
        // Return offline response for specific endpoints
        if (url.pathname.includes('/dashboard/stats')) {
            return new Response(JSON.stringify({
                current_visitors: 0,
                current_vehicles: 0,
                todays_visitors: 0,
                todays_vehicles: 0,
                total_today: 0,
                total_week: 0,
                recent_visitors: [],
                recent_vehicles: [],
                offline: true
            }), {
                headers: { 'Content-Type': 'application/json' }
            });
        }
        
        if (url.pathname.includes('/dashboard/activity')) {
            return new Response(JSON.stringify({
                activity: [],
                offline: true
            }), {
                headers: { 'Content-Type': 'application/json' }
            });
        }
        
        // Return generic offline response
        return new Response(JSON.stringify({
            error: 'Offline',
            message: 'This feature requires an internet connection'
        }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
        });
    }
}

/**
 * Handle image requests - cache first
 */
async function handleImageRequest(request) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
        return cachedResponse;
    }
    
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        // Return placeholder image if offline
        return new Response('', { status: 404 });
    }
}

/**
 * Handle page requests - network first, cache fallback
 */
async function handlePageRequest(request) {
    try {
        // Try network first
        const response = await fetch(request);
        
        if (response.ok) {
            // Cache successful responses
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, response.clone());
            return response;
        }
        
        throw new Error('Network response was not ok');
        
    } catch (error) {
        console.log('📄 Page request failed, checking cache:', request.url);
        
        // Try cache
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }
        
        // Return offline page
        const offlineResponse = await caches.match(OFFLINE_URL);
        if (offlineResponse) {
            return offlineResponse;
        }
        
        // Fallback to basic offline response
        return new Response(generateOfflinePage(), {
            headers: { 'Content-Type': 'text/html' }
        });
    }
}

/**
 * Handle static requests - cache first
 */
async function handleStaticRequest(request) {
    const cachedResponse = await caches.match(request);
    if (cachedResponse) {
        return cachedResponse;
    }
    
    try {
        const response = await fetch(request);
        if (response.ok) {
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, response.clone());
        }
        return response;
    } catch (error) {
        // Return 404 for failed static requests
        return new Response('Not found', { status: 404 });
    }
}

/**
 * Generate basic offline page HTML
 */
function generateOfflinePage() {
    return `
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Offline - Gate Management System</title>
            <style>
                body {
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    margin: 0;
                    padding: 20px;
                    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                    min-height: 100vh;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    color: white;
                }
                .container {
                    text-align: center;
                    background: rgba(255, 255, 255, 0.1);
                    backdrop-filter: blur(10px);
                    border-radius: 20px;
                    padding: 40px;
                    max-width: 400px;
                }
                .icon {
                    font-size: 64px;
                    margin-bottom: 20px;
                }
                h1 { margin-bottom: 10px; }
                p { margin-bottom: 20px; opacity: 0.9; }
                button {
                    background: rgba(255, 255, 255, 0.2);
                    border: 1px solid rgba(255, 255, 255, 0.3);
                    color: white;
                    padding: 12px 24px;
                    border-radius: 10px;
                    cursor: pointer;
                    font-size: 16px;
                    transition: all 0.3s ease;
                }
                button:hover {
                    background: rgba(255, 255, 255, 0.3);
                }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="icon">📱</div>
                <h1>You're Offline</h1>
                <p>Gate Management System is available offline with limited functionality.</p>
                <button onclick="window.location.reload()">Try Again</button>
            </div>
        </body>
        </html>
    `;
}

// Background sync for offline actions
self.addEventListener('sync', (event) => {
    console.log('🔄 Background sync triggered:', event.tag);
    
    if (event.tag === 'background-sync') {
        event.waitUntil(syncOfflineData());
    }
});

/**
 * Sync offline data when connection is restored
 */
async function syncOfflineData() {
    try {
        // Get stored offline actions
        const offlineData = await getStoredOfflineData();
        
        if (!offlineData || offlineData.length === 0) {
            return;
        }
        
        console.log('🔄 Syncing offline data:', offlineData.length, 'items');
        
        // Process each offline action
        for (const action of offlineData) {
            try {
                await fetch(action.url, {
                    method: action.method,
                    headers: action.headers,
                    body: action.body
                });
                
                console.log('✅ Synced offline action:', action.url);
            } catch (error) {
                console.error('❌ Failed to sync action:', action.url, error);
            }
        }
        
        // Clear offline data after sync
        await clearOfflineData();
        
        // Notify all clients about successful sync
        const clients = await self.clients.matchAll();
        clients.forEach(client => {
            client.postMessage({
                type: 'SYNC_COMPLETE',
                message: 'Offline data synchronized successfully'
            });
        });
        
    } catch (error) {
        console.error('❌ Background sync failed:', error);
    }
}

/**
 * Get stored offline data (placeholder - would integrate with IndexedDB)
 */
async function getStoredOfflineData() {
    // In a real implementation, this would read from IndexedDB
    return [];
}

/**
 * Clear offline data after successful sync
 */
async function clearOfflineData() {
    // In a real implementation, this would clear IndexedDB
}

// Push notification handling
self.addEventListener('push', (event) => {
    console.log('🔔 Push notification received');
    
    const options = {
        body: event.data ? event.data.text() : 'New notification from Gate Management System',
        icon: '/static/images/icon-192.png',
        badge: '/static/images/icon-192.png',
        vibrate: [100, 50, 100],
        data: {
            dateOfArrival: Date.now(),
            primaryKey: 1
        },
        actions: [
            {
                action: 'explore',
                title: 'View Details',
                icon: '/static/images/icon-192.png'
            },
            {
                action: 'close',
                title: 'Close',
                icon: '/static/images/icon-192.png'
            }
        ]
    };
    
    event.waitUntil(
        self.registration.showNotification('Gate Management System', options)
    );
});

// Handle notification clicks
self.addEventListener('notificationclick', (event) => {
    console.log('🔔 Notification clicked:', event.action);
    
    event.notification.close();
    
    if (event.action === 'explore') {
        event.waitUntil(
            clients.openWindow('/dashboard')
        );
    }
});

console.log('🔧 Service Worker loaded');