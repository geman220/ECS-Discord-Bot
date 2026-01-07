'use strict';

/**
 * CSRF Token Utilities
 *
 * Standardized CSRF token handling for all API requests.
 * Provides a single pattern for including CSRF tokens in fetch requests.
 *
 * @module utils/csrf
 */

/**
 * Get CSRF token from meta tag or cookie
 * @returns {string|null} CSRF token or null if not found
 */
export function getCSRFToken() {
    // Try meta tag first (preferred method)
    const metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag) {
        return metaTag.getAttribute('content');
    }

    // Fall back to input field (for forms)
    const inputField = document.querySelector('input[name="csrf_token"]');
    if (inputField) {
        return inputField.value;
    }

    // Fall back to cookie
    const cookies = document.cookie.split(';');
    for (const cookie of cookies) {
        const [name, value] = cookie.trim().split('=');
        if (name === 'csrf_token' || name === 'csrftoken') {
            return decodeURIComponent(value);
        }
    }

    console.warn('[csrf] No CSRF token found');
    return null;
}

/**
 * Get headers object with CSRF token included
 * @param {object} additionalHeaders - Additional headers to include
 * @returns {object} Headers object with CSRF token
 */
export function getCSRFHeaders(additionalHeaders = {}) {
    const token = getCSRFToken();
    const headers = {
        'Content-Type': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        ...additionalHeaders
    };

    if (token) {
        headers['X-CSRFToken'] = token;
        headers['X-CSRF-Token'] = token; // Some frameworks use different header names
    }

    return headers;
}

/**
 * Enhanced fetch with automatic CSRF token inclusion
 * @param {string} url - URL to fetch
 * @param {object} options - Fetch options
 * @returns {Promise<Response>} Fetch response
 */
export async function csrfFetch(url, options = {}) {
    const method = (options.method || 'GET').toUpperCase();

    // Only add CSRF for state-changing methods
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(method)) {
        options.headers = getCSRFHeaders(options.headers || {});
    } else {
        options.headers = {
            'X-Requested-With': 'XMLHttpRequest',
            ...(options.headers || {})
        };
    }

    return fetch(url, options);
}

/**
 * POST request with CSRF protection
 * @param {string} url - URL to post to
 * @param {object} data - Data to send (will be JSON stringified)
 * @param {object} options - Additional fetch options
 * @returns {Promise<Response>} Fetch response
 */
export async function csrfPost(url, data = {}, options = {}) {
    return csrfFetch(url, {
        method: 'POST',
        body: JSON.stringify(data),
        ...options
    });
}

/**
 * PUT request with CSRF protection
 * @param {string} url - URL to put to
 * @param {object} data - Data to send (will be JSON stringified)
 * @param {object} options - Additional fetch options
 * @returns {Promise<Response>} Fetch response
 */
export async function csrfPut(url, data = {}, options = {}) {
    return csrfFetch(url, {
        method: 'PUT',
        body: JSON.stringify(data),
        ...options
    });
}

/**
 * DELETE request with CSRF protection
 * @param {string} url - URL to delete
 * @param {object} options - Additional fetch options
 * @returns {Promise<Response>} Fetch response
 */
export async function csrfDelete(url, options = {}) {
    return csrfFetch(url, {
        method: 'DELETE',
        ...options
    });
}

/**
 * Add CSRF token to form data
 * @param {FormData} formData - Form data to add token to
 * @returns {FormData} Form data with CSRF token
 */
export function addCSRFToFormData(formData) {
    const token = getCSRFToken();
    if (token && !formData.has('csrf_token')) {
        formData.append('csrf_token', token);
    }
    return formData;
}

/**
 * Check if response indicates CSRF failure
 * @param {Response} response - Fetch response
 * @returns {boolean} Whether response indicates CSRF failure
 */
export function isCSRFError(response) {
    // Common CSRF error status codes
    if (response.status === 403 || response.status === 419) {
        return true;
    }
    return false;
}

/**
 * Handle CSRF errors with retry
 * @param {Function} requestFn - Function that makes the request
 * @param {number} maxRetries - Maximum number of retries
 * @returns {Promise<Response>} Fetch response
 */
export async function withCSRFRetry(requestFn, maxRetries = 1) {
    let lastError;

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
        try {
            const response = await requestFn();

            if (isCSRFError(response) && attempt < maxRetries) {
                // Token might be stale, try to refresh page's token
                console.warn('[csrf] CSRF error detected, retrying...');
                continue;
            }

            return response;
        } catch (error) {
            lastError = error;
        }
    }

    throw lastError;
}

// Export default object for convenience
export default {
    getCSRFToken,
    getCSRFHeaders,
    csrfFetch,
    csrfPost,
    csrfPut,
    csrfDelete,
    addCSRFToFormData,
    isCSRFError,
    withCSRFRetry
};

// Also expose globally for non-module scripts
if (typeof window !== 'undefined') {
    window.CSRF = {
        getToken: getCSRFToken,
        getHeaders: getCSRFHeaders,
        fetch: csrfFetch,
        post: csrfPost,
        put: csrfPut,
        delete: csrfDelete
    };
}
