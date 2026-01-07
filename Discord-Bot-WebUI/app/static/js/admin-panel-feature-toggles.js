/**
 * ============================================================================
 * FEATURE TOGGLES PAGE - JAVASCRIPT
 * ============================================================================
 *
 * Handles feature toggle interactions using data-attribute hooks
 * Follows event delegation pattern with state-driven styling
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
import { showToast } from './services/toast-service.js';

// CSRF Token
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

/**
 * Initialize feature toggles
 */
function initAdminPanelFeatureToggles() {
    initializeToggleHandlers();
    initializeFormHandlers();
}

/**
 * Initialize toggle switch handlers
 */
function initializeToggleHandlers() {
    // Event delegation for all toggle switches
    document.addEventListener('change', function(e) {
        const toggle = e.target.closest('[data-setting-toggle]');
        if (!toggle) return;

        const settingKey = toggle.dataset.settingKey;
        const isEnabled = toggle.checked;

        handleToggleChange(toggle, settingKey, isEnabled);
    });
}

/**
 * Handle toggle switch change
 */
function handleToggleChange(toggle, settingKey, isEnabled) {
    const statusLabel = toggle.parentElement.querySelector('[data-toggle-status]');
    const iconElement = document.querySelector(`[data-setting-row][data-setting-key="${settingKey}"] .c-setting-row__status-icon`);

    // Show loading state
    toggle.disabled = true;
    if (statusLabel) {
        statusLabel.textContent = 'Updating...';
    }

    // Send request to server
    fetch('/admin_panel/toggle_setting', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            key: settingKey
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update toggle and status to match server state
            toggle.checked = data.new_value;
            if (statusLabel) {
                statusLabel.textContent = data.new_value ? 'Enabled' : 'Disabled';
            }

            // Update the icon in the left column
            if (iconElement) {
                if (data.new_value) {
                    iconElement.classList.remove('ti-toggle-left', 'c-setting-row__status-icon--disabled');
                    iconElement.classList.add('ti-toggle-right', 'c-setting-row__status-icon--enabled');
                } else {
                    iconElement.classList.remove('ti-toggle-right', 'c-setting-row__status-icon--enabled');
                    iconElement.classList.add('ti-toggle-left', 'c-setting-row__status-icon--disabled');
                }
            }

            // Show success message
            showToast(data.message, 'success', { title: 'Setting Updated' });
        } else {
            // Revert the toggle and status
            toggle.checked = !isEnabled;
            if (statusLabel) {
                statusLabel.textContent = !isEnabled ? 'Enabled' : 'Disabled';
            }

            // Show error message
            showToast(data.message || 'Failed to update setting', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);

        // Revert the toggle and status
        toggle.checked = !isEnabled;
        if (statusLabel) {
            statusLabel.textContent = !isEnabled ? 'Enabled' : 'Disabled';
        }

        showToast('Failed to communicate with server', 'error');
    })
    .finally(() => {
        toggle.disabled = false;
    });
}

/**
 * Initialize form submission handlers
 */
function initializeFormHandlers() {
    // Event delegation for form submissions
    document.addEventListener('submit', function(e) {
        const form = e.target.closest('[data-setting-form]');
        if (!form) return;

        const submitBtn = form.querySelector('.c-setting-form__submit');
        if (!submitBtn) return;

        const originalIcon = submitBtn.innerHTML;

        // Show loading state
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">Loading...</span></div>';

        // Note: Form will submit normally, this is just for UI feedback
        // The backend will handle the actual update
    });
}

// showToast imported from services/toast-service.js

// Register with window.InitSystem
window.InitSystem.register('admin-panel-feature-toggles', initAdminPanelFeatureToggles, {
    priority: 30,
    reinitializable: true,
    description: 'Admin panel feature toggles'
});

// Fallback
// window.InitSystem handles initialization

// No window exports needed - InitSystem handles initialization
// showToast available via window.showToast from toast-service.js

// Named exports for ES modules
export {
    initAdminPanelFeatureToggles,
    initializeToggleHandlers,
    handleToggleChange,
    initializeFormHandlers,
    showToast
};
