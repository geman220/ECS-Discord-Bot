// ECS Admin Panel Service Worker
// Provides offline support and caching for mobile users

const CACHE_NAME = 'ecs-admin-v1';
const STATIC_CACHE_NAME = 'ecs-admin-static-v1';
const DYNAMIC_CACHE_NAME = 'ecs-admin-dynamic-v1';

// Static assets to cache
const STATIC_ASSETS = [
    '/',
    '/admin-panel/',
    '/static/css/admin-mobile.css',
    '/static/js/bootstrap.bundle.min.js',
    '/static/css/bootstrap.min.css',
    // Add other critical assets
];

// API endpoints to cache
const API_CACHE_PATTERNS = [
    /\/admin-panel\/api\//,
    /\/admin-panel\/users\/analytics/,
    /\/admin-panel\/statistics/,
];

// Install event - cache static assets
self.addEventListener('install', event => {
    console.log('Service Worker installing...');
    
    event.waitUntil(
        caches.open(STATIC_CACHE_NAME)
            .then(cache => {
                console.log('Caching static assets...');
                return cache.addAll(STATIC_ASSETS);
            })
            .catch(error => {
                console.error('Failed to cache static assets:', error);
            })
    );
    
    // Skip waiting to activate immediately
    self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', event => {
    console.log('Service Worker activating...');
    
    event.waitUntil(
        caches.keys()
            .then(cacheNames => {
                return Promise.all(
                    cacheNames.map(cacheName => {
                        if (cacheName !== STATIC_CACHE_NAME && 
                            cacheName !== DYNAMIC_CACHE_NAME && 
                            cacheName !== CACHE_NAME) {
                            console.log('Deleting old cache:', cacheName);
                            return caches.delete(cacheName);
                        }
                    })
                );
            })
    );
    
    // Take control of all clients immediately
    self.clients.claim();
});

// Fetch event - implement caching strategies
self.addEventListener('fetch', event => {
    const { request } = event;
    const { url, method } = request;
    
    // Only handle GET requests
    if (method !== 'GET') {
        return;
    }
    
    // Skip chrome-extension and other non-http requests
    if (!url.startsWith('http')) {
        return;
    }
    
    // Handle different types of requests with appropriate strategies
    if (isStaticAsset(url)) {
        // Cache first for static assets
        event.respondWith(cacheFirst(request));
    } else if (isAPIRequest(url)) {
        // Network first for API requests with fallback
        event.respondWith(networkFirstWithFallback(request));
    } else if (isAdminPanelPage(url)) {
        // Stale while revalidate for admin panel pages
        event.respondWith(staleWhileRevalidate(request));
    } else {
        // Network only for other requests
        event.respondWith(fetch(request));
    }
});

// Cache first strategy (for static assets)
async function cacheFirst(request) {
    try {
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            return cachedResponse;
        }
        
        const networkResponse = await fetch(request);
        
        // Cache successful responses
        if (networkResponse.ok) {
            const cache = await caches.open(STATIC_CACHE_NAME);
            cache.put(request, networkResponse.clone());
        }
        
        return networkResponse;
    } catch (error) {
        console.error('Cache first failed:', error);
        
        // Return offline page for navigation requests
        if (request.mode === 'navigate') {
            return caches.match('/offline.html') || new Response('Offline', { status: 503 });
        }
        
        throw error;
    }
}

// Network first with fallback (for API requests)
async function networkFirstWithFallback(request) {
    try {
        const networkResponse = await fetch(request);
        
        // Cache successful API responses
        if (networkResponse.ok) {
            const cache = await caches.open(DYNAMIC_CACHE_NAME);
            cache.put(request, networkResponse.clone());
        }
        
        return networkResponse;
    } catch (error) {
        console.log('Network failed, trying cache:', request.url);
        
        const cachedResponse = await caches.match(request);
        if (cachedResponse) {
            // Add offline indicator header
            const response = cachedResponse.clone();
            response.headers.set('X-From-Cache', 'true');
            return response;
        }
        
        // Return offline response for API requests
        return new Response(JSON.stringify({
            error: 'Offline',
            message: 'This data is not available offline',
            offline: true
        }), {
            status: 503,
            headers: {
                'Content-Type': 'application/json',
                'X-Offline': 'true'
            }
        });
    }
}

// Stale while revalidate (for admin pages)
async function staleWhileRevalidate(request) {
    const cache = await caches.open(DYNAMIC_CACHE_NAME);
    const cachedResponse = await cache.match(request);
    
    // Fetch from network in the background
    const networkResponsePromise = fetch(request).then(response => {
        if (response.ok) {
            cache.put(request, response.clone());
        }
        return response;
    }).catch(error => {
        console.log('Background fetch failed:', error);
        return null;
    });
    
    // Return cached response immediately if available
    if (cachedResponse) {
        // Don't wait for network response
        networkResponsePromise.catch(() => {});
        return cachedResponse;
    }
    
    // If no cache, wait for network
    try {
        return await networkResponsePromise;
    } catch (error) {
        return new Response('Offline', { status: 503 });
    }
}

// Helper functions
function isStaticAsset(url) {
    return url.includes('/static/') || 
           url.includes('.css') || 
           url.includes('.js') || 
           url.includes('.png') || 
           url.includes('.jpg') || 
           url.includes('.svg') ||
           url.includes('.ico');
}

function isAPIRequest(url) {
    return API_CACHE_PATTERNS.some(pattern => pattern.test(url)) ||
           url.includes('/api/') ||
           url.includes('/admin-panel/') && (
               url.includes('/export') ||
               url.includes('/analytics') ||
               url.includes('/statistics')
           );
}

function isAdminPanelPage(url) {
    return url.includes('/admin-panel/') && !isAPIRequest(url);
}

// Background sync for failed POST requests
self.addEventListener('sync', event => {
    console.log('Background sync triggered:', event.tag);
    
    if (event.tag === 'admin-actions') {
        event.waitUntil(retryFailedActions());
    }
});

// Retry failed actions when back online
async function retryFailedActions() {
    try {
        const cache = await caches.open('failed-actions');
        const requests = await cache.keys();
        
        for (const request of requests) {
            try {
                const response = await fetch(request);
                if (response.ok) {
                    await cache.delete(request);
                    console.log('Retried action successfully:', request.url);
                }
            } catch (error) {
                console.log('Retry failed for:', request.url, error);
            }
        }
    } catch (error) {
        console.error('Failed to retry actions:', error);
    }
}

// Push notification handler
self.addEventListener('push', event => {
    console.log('Push notification received');
    
    const options = {
        body: 'Admin panel notification',
        icon: '/static/images/icon-192x192.png',
        badge: '/static/images/badge-72x72.png',
        tag: 'admin-notification',
        data: event.data ? event.data.json() : {},
        actions: [
            {
                action: 'view',
                title: 'View',
                icon: '/static/images/view-icon.png'
            },
            {
                action: 'dismiss',
                title: 'Dismiss',
                icon: '/static/images/dismiss-icon.png'
            }
        ],
        requireInteraction: true
    };
    
    if (event.data) {
        const data = event.data.json();
        options.body = data.body || options.body;
        options.title = data.title || 'ECS Admin Panel';
    }
    
    event.waitUntil(
        self.registration.showNotification('ECS Admin Panel', options)
    );
});

// Notification click handler
self.addEventListener('notificationclick', event => {
    event.notification.close();
    
    if (event.action === 'view') {
        event.waitUntil(
            clients.openWindow('/admin-panel/')
        );
    } else if (event.action === 'dismiss') {
        // Just close the notification
        return;
    } else {
        // Default action - open admin panel
        event.waitUntil(
            clients.openWindow('/admin-panel/')
        );
    }
});

// Message handler for communication with main thread
self.addEventListener('message', event => {
    const { type, data } = event.data;
    
    switch (type) {
        case 'SKIP_WAITING':
            self.skipWaiting();
            break;
        case 'GET_VERSION':
            event.ports[0].postMessage({ version: CACHE_NAME });
            break;
        case 'CLEAR_CACHE':
            clearCache().then(() => {
                event.ports[0].postMessage({ success: true });
            });
            break;
        case 'CACHE_FAILED_ACTION':
            cacheFailedAction(data).then(() => {
                event.ports[0].postMessage({ success: true });
            });
            break;
    }
});

// Clear all caches
async function clearCache() {
    const cacheNames = await caches.keys();
    await Promise.all(
        cacheNames.map(cacheName => caches.delete(cacheName))
    );
    console.log('All caches cleared');
}

// Cache failed action for retry
async function cacheFailedAction(requestData) {
    try {
        const cache = await caches.open('failed-actions');
        const request = new Request(requestData.url, {
            method: requestData.method,
            headers: requestData.headers,
            body: requestData.body
        });
        
        await cache.put(request, new Response('pending'));
        console.log('Cached failed action for retry:', requestData.url);
    } catch (error) {
        console.error('Failed to cache action:', error);
    }
}

// Periodic cleanup
setInterval(() => {
    console.log('Performing periodic cache cleanup...');
    cleanupOldCaches();
}, 24 * 60 * 60 * 1000); // Daily cleanup

async function cleanupOldCaches() {
    try {
        const cache = await caches.open(DYNAMIC_CACHE_NAME);
        const requests = await cache.keys();
        const oneWeekAgo = Date.now() - (7 * 24 * 60 * 60 * 1000);
        
        for (const request of requests) {
            const response = await cache.match(request);
            const dateHeader = response.headers.get('date');
            
            if (dateHeader && new Date(dateHeader).getTime() < oneWeekAgo) {
                await cache.delete(request);
                console.log('Cleaned up old cache entry:', request.url);
            }
        }
    } catch (error) {
        console.error('Cache cleanup failed:', error);
    }
}