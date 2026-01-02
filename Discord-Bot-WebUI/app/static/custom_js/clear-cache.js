/**
 * Cache Clearing Utility
 * Handles force clearing of browser cache for mobile experience updates
 *
 * IMPORTANT: This should only run on a dedicated cache-clearing page, not globally.
 * The function is exposed globally but NOT auto-executed - triggered via data-action="clear-cache".
 */
'use strict';

import { EventDelegation } from '../js/event-delegation/core.js';

/**
 * Call this function manually when cache clearing is needed.
 * Example: <button data-action="clear-cache">Clear Cache</button>
 */
function clearCacheAndRedirect() {
    // Files that exist in the production bundle
    const filesToClear = [
        '/static/gen/production.min.css',
        '/static/gen/production.min.js'
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

// ========================================================================
// EXPORTS
// ========================================================================

export { clearCacheAndRedirect };

// Expose globally for external use
window.clearCacheAndRedirect = clearCacheAndRedirect;

// Note: window.EventDelegation handler 'clear-cache' is registered in monitoring-handlers.js
// This file exposes clearCacheAndRedirect globally for that handler to use
