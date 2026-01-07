'use strict';

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

// Store the original fetch
const originalFetch = window.fetch;

// Methods that require CSRF protection
const CSRF_METHODS = ['POST', 'PUT', 'DELETE', 'PATCH'];

/**
 * Get CSRF token from meta tag
 * @returns {string|null} CSRF token or null if not found
 */
function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : null;
}

/**
 * Enhanced fetch that automatically adds CSRF token
 * @param {string|Request} url - URL or Request object
 * @param {RequestInit} options - Fetch options
 * @returns {Promise<Response>} Fetch response promise
 */
function fetchWithCSRF(url, options = {}) {
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
}

// Override window.fetch with CSRF-protected version
window.fetch = fetchWithCSRF;

// Backward compatibility - keep window.getCSRFToken and window.fetchWithCSRF for legacy code
window.getCSRFToken = getCSRFToken;
window.fetchWithCSRF = fetchWithCSRF;

console.debug('[CSRF] Fetch wrapper initialized');
