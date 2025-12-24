/**
 * CSRF-Protected Fetch Utility
 *
 * Automatically adds CSRF token to all fetch requests with methods
 * that modify data (POST, PUT, DELETE, PATCH).
 *
 * Usage: Just use fetch() as normal - CSRF token is added automatically.
 *
 * The CSRF token is read from: <meta name="csrf-token" content="...">
 */

(function() {
    'use strict';

    // Store the original fetch
    const originalFetch = window.fetch;

    // Methods that require CSRF protection
    const CSRF_METHODS = ['POST', 'PUT', 'DELETE', 'PATCH'];

    /**
     * Get CSRF token from meta tag
     */
    function getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : null;
    }

    /**
     * Enhanced fetch that automatically adds CSRF token
     */
    window.fetch = function(url, options = {}) {
        // Determine the method (default is GET)
        const method = (options.method || 'GET').toUpperCase();

        // Only add CSRF token for methods that modify data
        if (CSRF_METHODS.includes(method)) {
            const csrfToken = getCSRFToken();

            if (csrfToken) {
                // Ensure headers object exists
                options.headers = options.headers || {};

                // Handle Headers object vs plain object
                if (options.headers instanceof Headers) {
                    if (!options.headers.has('X-CSRFToken')) {
                        options.headers.set('X-CSRFToken', csrfToken);
                    }
                } else {
                    // Plain object - only add if not already present
                    if (!options.headers['X-CSRFToken'] && !options.headers['x-csrftoken']) {
                        options.headers['X-CSRFToken'] = csrfToken;
                    }
                }
            }
        }

        // Call the original fetch
        return originalFetch.call(window, url, options);
    };

    // Also provide a named export for explicit usage
    window.fetchWithCSRF = window.fetch;

    console.debug('[CSRF] Fetch wrapper initialized');
})();
