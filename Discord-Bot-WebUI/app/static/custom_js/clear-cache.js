/**
 * Cache Clearing Utility
 * Handles force clearing of browser cache for mobile experience updates
 */

document.addEventListener('DOMContentLoaded', function() {
    clearCacheAndRedirect();
});

function clearCacheAndRedirect() {
    // Key files that need to be refreshed
    const filesToClear = [
        '/static/css/ecs-core.css',
        '/static/css/ecs-components.css',
        '/static/css/ecs-utilities.css'
    ];

    // Create a new cache version
    const cacheVersion = new Date().getTime();

    // Force reload each file with cache busting
    const fetchPromises = filesToClear.map(file => {
        return fetch(file + '?v=' + cacheVersion, {
            cache: 'reload',
            mode: 'no-cors'
        });
    });

    // Try to clear the cache using the Cache API if available
    if ('caches' in window) {
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    return caches.delete(cacheName);
                })
            );
        });
    }

    // Wait for all fetches to complete, then redirect
    Promise.all(fetchPromises)
        .then(() => {
            // Clear service worker if present
            if ('serviceWorker' in navigator) {
                navigator.serviceWorker.getRegistrations().then(registrations => {
                    for (let registration of registrations) {
                        registration.unregister();
                    }
                });
            }

            // Clear localStorage items related to cached content
            localStorage.removeItem('cache_version');

            // Add a small delay before redirecting
            setTimeout(() => {
                window.location.href = '/';
            }, 2000);
        })
        .catch(() => {
            // If fetching fails, redirect anyway
            setTimeout(() => {
                window.location.href = '/';
            }, 2000);
        });
}
