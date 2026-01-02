/**
 * ============================================================================
 * ADMIN PUSH NOTIFICATIONS DASHBOARD - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles push notifications dashboard page interactions using data-attribute hooks
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

/**
 * Initialize push notifications dashboard module
 */
function init() {
    initializeProgressBars();
    initializeEventDelegation();
}

/**
 * Apply dynamic widths from data attributes
 */
function initializeProgressBars() {
    document.querySelectorAll('[data-width]').forEach(el => {
        el.style.width = el.dataset.width;
    });
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
            case 'refresh-notifications':
                refreshNotifications();
                break;
        }
    });
}

/**
 * Refresh notifications - simple page reload
 */
function refreshNotifications() {
    location.reload();
}

// Register with InitSystem
InitSystem.register('admin-push-notifications-dashboard', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin push notifications dashboard functionality'
});

// Fallback
// InitSystem handles initialization

// Export for ES modules
export {
    init,
    refreshNotifications
};

// Backward compatibility
window.adminPushNotificationsDashboardInit = init;
window.refreshNotifications = refreshNotifications;
