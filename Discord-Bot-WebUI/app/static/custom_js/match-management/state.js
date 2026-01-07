'use strict';

/**
 * Match Management State
 * Module state and CSRF token management
 * @module match-management/state
 */

let _initialized = false;
let csrfToken = '';

// Track in-flight requests to prevent duplicates
const pendingTaskRequests = new Set();

/**
 * Check if module is initialized
 * @returns {boolean}
 */
export function isInitialized() {
    return _initialized;
}

/**
 * Set initialization state
 * @param {boolean} value
 */
export function setInitialized(value) {
    _initialized = value;
}

/**
 * Get CSRF token
 * @returns {string}
 */
export function getCSRFToken() {
    return csrfToken;
}

/**
 * Initialize CSRF token from meta tag or input
 */
export function initializeCSRFToken() {
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
        csrfToken = csrfMeta.getAttribute('content');
    } else {
        const csrfInput = document.querySelector('input[name="csrf_token"]');
        if (csrfInput) {
            csrfToken = csrfInput.value;
        }
    }
}

/**
 * Check if request is pending for match
 * @param {string|number} matchId
 * @returns {boolean}
 */
export function isRequestPending(matchId) {
    return pendingTaskRequests.has(matchId);
}

/**
 * Add pending request
 * @param {string|number} matchId
 */
export function addPendingRequest(matchId) {
    pendingTaskRequests.add(matchId);
}

/**
 * Remove pending request
 * @param {string|number} matchId
 */
export function removePendingRequest(matchId) {
    pendingTaskRequests.delete(matchId);
}

/**
 * Check if current page is match management admin page
 * @returns {boolean}
 */
export function isMatchManagementPage() {
    return !!(
        document.getElementById('lastUpdated') ||
        document.querySelector('[data-page="match-management"]') ||
        window.location.pathname.includes('/admin/match_management')
    );
}
