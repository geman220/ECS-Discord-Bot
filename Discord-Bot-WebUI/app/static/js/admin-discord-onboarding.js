/**
 * ============================================================================
 * ADMIN DISCORD ONBOARDING - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles Discord onboarding page interactions using data-attribute hooks
 * Follows event delegation pattern with InitSystem registration
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';

// CSRF Token
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

// Store configuration from data attributes
let retryContactBaseUrl = '';

/**
 * Initialize Discord onboarding module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-discord-onboarding-config]');
    if (configEl) {
        retryContactBaseUrl = configEl.dataset.retryContactBaseUrl || '';
    }

    initializeEventDelegation();
}

/**
 * Initialize event delegation for all interactive elements
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch (action) {
            case 'retry-contact':
                const userId = target.dataset.userId;
                if (userId) {
                    retryContact(userId);
                }
                break;
            case 'refresh-overview':
            case 'refresh-empty':
                refreshOverview();
                break;
        }
    });
}

/**
 * Refresh overview page
 */
function refreshOverview() {
    location.reload();
}

/**
 * Retry contact for a user
 */
function retryContact(userId) {
    if (!confirm('This will enable bot contact retry for this user. Continue?')) return;

    // Build URL
    let url = '';
    if (retryContactBaseUrl) {
        url = retryContactBaseUrl.replace('0', userId);
    } else if (window.discordOnboardingConfig?.retryContactBaseUrl) {
        url = window.discordOnboardingConfig.retryContactBaseUrl.replace('0', userId);
    } else {
        url = `/admin_panel/discord/retry-onboarding-contact/${userId}`;
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        }
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(data.message, 'success');
                setTimeout(() => location.reload(), 1500);
            } else {
                showToast('Error: ' + data.error, 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Error retrying contact', 'danger');
        });
}

/**
 * Show toast notification
 */
function showToast(message, type) {
    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
        AdminPanel.showMobileToast(message, type);
    } else if (typeof Swal !== 'undefined') {
        Swal.fire({
            toast: true,
            position: 'top-end',
            icon: type === 'danger' ? 'error' : 'success',
            title: message,
            showConfirmButton: false,
            timer: 3000
        });
    }
}

// Register with InitSystem
InitSystem.register('admin-discord-onboarding', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin Discord onboarding page functionality'
});

// Fallback for non-module usage
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Export for ES modules
export {
    init,
    refreshOverview,
    retryContact
};

// Backward compatibility
window.adminDiscordOnboardingInit = init;
window.refreshOverview = refreshOverview;
window.retryContact = retryContact;
