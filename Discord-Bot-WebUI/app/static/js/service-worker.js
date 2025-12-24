// ECS Soccer League PWA Service Worker
const CACHE_NAME = 'ecs-soccer-v2'; // Updated: v1 → v2 (route fixes + file path corrections)

// Assets to cache on install
const PRECACHE_ASSETS = [
  '/',
  // Note: Core CSS files removed - loaded dynamically per page
  // '/static/css/core.css', // Doesn't exist
  // '/static/css/theme-default.css', // Doesn't exist
  '/static/vendor/fonts/tabler-icons.css',
  '/static/vendor/fonts/fontawesome.css',
  '/static/js/config.js',
  '/static/js/helpers.js',
  '/static/js/menu.js',
  '/static/vendor/js/bootstrap.bundle.js', // Fixed: was bootstrap.js
  '/static/vendor/libs/jquery/jquery.js',
  '/static/custom_js/rsvp.js',
  '/static/custom_js/report_match.js',
  '/static/img/default_player.png',
  '/static/img/default_logo.png',
  '/static/img/undraw_goal_-0-v5v.svg',
  '/static/img/undraw_notify_re_65on.svg',
  '/static/manifest.json'
];

// Install service worker and cache core assets
self.addEventListener('install', event => {
  // console.log('[Service Worker] Installing new version');
  
  // Skip waiting to ensure the new service worker activates immediately
  self.skipWaiting();
  
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        // console.log('[Service Worker] Caching app shell and content');
        return cache.addAll(PRECACHE_ASSETS);
      })
  );
});

// Activate new service worker and clean up old caches
self.addEventListener('activate', event => {
  // console.log('[Service Worker] Activating new service worker');
  
  const cacheWhitelist = [CACHE_NAME];
  
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheWhitelist.indexOf(cacheName) === -1) {
            // console.log('[Service Worker] Deleting old cache:', cacheName);
            return caches.delete(cacheName);
          }
        })
      );
    })
  );
  
  // Immediately claim clients
  return self.clients.claim();
});

// Network-first strategy for data requests, cache-first for static assets
self.addEventListener('fetch', event => {
  // Don't try to handle non-GET requests or API calls
  if (event.request.method !== 'GET' || 
      (event.request.url.includes('/api/') || 
       event.request.url.includes('/socket.io/') ||
       event.request.url.includes('/_dash-update-component'))) {
    return;
  }
  
  // For HTML pages, always try network first
  if (event.request.headers.get('Accept').includes('text/html')) {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          // If successful, clone and cache
          let responseClone = response.clone();
          caches.open(CACHE_NAME).then(cache => {
            cache.put(event.request, responseClone);
          });
          return response;
        })
        .catch(() => {
          // If network fails, try the cache
          return caches.match(event.request)
            .then(cachedResponse => {
              if (cachedResponse) {
                return cachedResponse;
              }
              // If no cache, return the offline page
              return caches.match('/');
            });
        })
    );
    return;
  }
  
  // For static assets, try cache first
  if (
    event.request.url.match(/\.(css|js|png|jpg|jpeg|svg|gif|woff|woff2|ttf|eot)$/) ||
    event.request.url.includes('/static/')
  ) {
    event.respondWith(
      caches.match(event.request)
        .then(cachedResponse => {
          // Return cached version or fetch from network
          return cachedResponse || fetch(event.request)
            .then(response => {
              // Cache the fetched response
              let responseClone = response.clone();
              caches.open(CACHE_NAME).then(cache => {
                cache.put(event.request, responseClone);
              });
              return response;
            });
        })
    );
    return;
  }
  
  // For all other requests, try network first, then cache
  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Clone the response to use it and cache it
        let responseClone = response.clone();
        caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, responseClone);
        });
        return response;
      })
      .catch(() => {
        // If network fails, try the cache
        return caches.match(event.request);
      })
  );
});

// Handle push notifications (if needed)
self.addEventListener('push', event => {
  // console.log('[Service Worker] Push message received:', event);
  
  const title = 'ECS Soccer League';
  const options = {
    body: event.data ? event.data.text() : 'New notification',
    icon: '/static/img/icons/icon-192x192.png',
    badge: '/static/img/icons/icon-72x72.png',
    vibrate: [100, 50, 100],
    data: {
      url: '/'
    }
  };
  
  event.waitUntil(
    self.registration.showNotification(title, options)
  );
});

// Handle notification clicks
self.addEventListener('notificationclick', event => {
  // console.log('[Service Worker] Notification click: ', event);
  
  event.notification.close();
  
  const url = event.notification.data.url || '/';
  
  event.waitUntil(
    clients.matchAll({type: 'window'})
      .then(windowClients => {
        // Check if there is already a window open
        for (let client of windowClients) {
          if (client.url === url && 'focus' in client) {
            return client.focus();
          }
        }
        // If not, open a new window
        if (clients.openWindow) {
          return clients.openWindow(url);
        }
      })
  );
});

// Background sync for offline functionality (if needed)
self.addEventListener('sync', event => {
  if (event.tag === 'rsvp-sync') {
    event.waitUntil(
      // Implement the sync logic here to send cached RSVPs
      // console.log('[Service Worker] Syncing RSVPs')
    );
  }
});