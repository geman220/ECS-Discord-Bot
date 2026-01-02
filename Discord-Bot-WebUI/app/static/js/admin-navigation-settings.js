/**
 * ============================================================================
 * ADMIN NAVIGATION SETTINGS - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles navigation settings page interactions using data-attribute hooks
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
let saveSettingsUrl = '';

/**
 * Initialize navigation settings module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-navigation-settings-config]');
    if (configEl) {
        saveSettingsUrl = configEl.dataset.saveSettingsUrl || '';
    }

    initializeEventDelegation();
    initializeToggleHandlers();
}

/**
 * Initialize event delegation for button clicks
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch (action) {
            case 'reset-defaults':
                resetToDefaults();
                break;
            case 'save-all':
                saveAllSettings();
                break;
        }
    });
}

/**
 * Initialize toggle switch handlers
 */
function initializeToggleHandlers() {
    document.querySelectorAll('.nav-toggle').forEach(toggle => {
        toggle.addEventListener('change', function() {
            const setting = this.dataset.setting;
            const enabled = this.checked;

            saveSetting(setting, enabled);
            updatePreview(setting, enabled);
            updateCardBorder(this);
        });
    });
}

/**
 * Save a single setting
 */
function saveSetting(setting, enabled) {
    const data = {};
    data[setting] = enabled;

    const url = saveSettingsUrl || window.navigationSettingsConfig?.saveSettingsUrl || window.location.pathname;

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('Setting saved', 'success');
        } else {
            showToast('Failed to save setting', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('Error saving setting', 'error');
    });
}

/**
 * Save all settings at once
 */
function saveAllSettings() {
    const data = {};
    document.querySelectorAll('.nav-toggle').forEach(toggle => {
        data[toggle.dataset.setting] = toggle.checked;
    });

    const url = saveSettingsUrl || window.navigationSettingsConfig?.saveSettingsUrl || window.location.pathname;

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showToast('All settings saved successfully', 'success');
        } else {
            showToast('Failed to save settings', 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showToast('Error saving settings', 'error');
    });
}

/**
 * Reset all settings to defaults
 */
function resetToDefaults() {
    if (typeof Swal === 'undefined') {
        if (!confirm('This will enable all navigation items. Are you sure?')) return;
        performReset();
        return;
    }

    Swal.fire({
        title: 'Reset to Defaults?',
        text: 'This will enable all navigation items. Are you sure?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info') : '#3085d6',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, reset'
    }).then((result) => {
        if (result.isConfirmed) {
            performReset();
        }
    });
}

/**
 * Perform the actual reset
 */
function performReset() {
    document.querySelectorAll('.nav-toggle').forEach(toggle => {
        toggle.checked = true;
        updatePreview(toggle.dataset.setting, true);
        updateCardBorder(toggle);
    });
    saveAllSettings();
}

/**
 * Update the preview list item visibility
 */
function updatePreview(setting, enabled) {
    const previewItem = document.querySelector(`.preview-item[data-key="${setting}"]`);
    if (previewItem) {
        previewItem.style.display = enabled ? 'list-item' : 'none';
    }
}

/**
 * Update card border based on toggle state
 */
function updateCardBorder(toggle) {
    const card = toggle.closest('.card, .c-card');
    if (!card) return;

    if (toggle.checked) {
        card.classList.remove('border-secondary');
        card.classList.add('border-success');
    } else {
        card.classList.remove('border-success');
        card.classList.add('border-secondary');
    }
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
            icon: type === 'error' ? 'error' : 'success',
            title: message,
            showConfirmButton: false,
            timer: 3000
        });
    }
}

// Register with InitSystem
InitSystem.register('admin-navigation-settings', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin navigation settings page functionality'
});

// Fallback
// InitSystem handles initialization

// Export for ES modules
export {
    init,
    saveSetting,
    saveAllSettings,
    resetToDefaults,
    updatePreview,
    updateCardBorder
};

// Backward compatibility
window.adminNavigationSettingsInit = init;
window.saveSetting = saveSetting;
window.saveAllSettings = saveAllSettings;
window.resetToDefaults = resetToDefaults;
window.updatePreview = updatePreview;
window.updateCardBorder = updateCardBorder;
