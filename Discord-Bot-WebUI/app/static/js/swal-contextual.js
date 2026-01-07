'use strict';

/**
 * SweetAlert2 Contextual Helper
 *
 * Extends window.Swal.fire with smart contextual defaults for button text,
 * icons, and colors based on the action being performed.
 *
 * Usage:
 *   // Instead of window.Swal.fire({...})
 *   SwalContextual.confirm({
 *       title: 'Delete Item',
 *       text: 'Are you sure you want to delete this item?'
 *   }).then(result => { ... });
 *
 *   // Or use the shorthand methods:
 *   SwalContextual.delete('Are you sure?').then(...)
 *   SwalContextual.approve('Approve this user?').then(...)
 */

/**
 * Action configurations with smart defaults
 */
const ACTION_CONFIGS = {
    delete: {
        icon: 'warning',
        confirmButtonText: 'Delete',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Delete'
    },
    remove: {
        icon: 'warning',
        confirmButtonText: 'Remove',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Remove'
    },
    approve: {
        icon: 'question',
        confirmButtonText: 'Approve',
        confirmButtonColor: '#28a745',
        titlePrefix: 'Confirm Approval'
    },
    reject: {
        icon: 'warning',
        confirmButtonText: 'Reject',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Rejection'
    },
    deny: {
        icon: 'warning',
        confirmButtonText: 'Deny',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Denial'
    },
    send: {
        icon: 'question',
        confirmButtonText: 'Send',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Send'
    },
    sync: {
        icon: 'question',
        confirmButtonText: 'Sync',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Sync'
    },
    refresh: {
        icon: 'question',
        confirmButtonText: 'Refresh',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Refresh'
    },
    reset: {
        icon: 'warning',
        confirmButtonText: 'Reset',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Reset'
    },
    clear: {
        icon: 'warning',
        confirmButtonText: 'Clear',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Clear'
    },
    cancel: {
        icon: 'warning',
        confirmButtonText: 'Yes, Cancel',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Cancellation'
    },
    disable: {
        icon: 'warning',
        confirmButtonText: 'Disable',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Disable'
    },
    enable: {
        icon: 'question',
        confirmButtonText: 'Enable',
        confirmButtonColor: '#28a745',
        titlePrefix: 'Confirm Enable'
    },
    save: {
        icon: 'question',
        confirmButtonText: 'Save',
        confirmButtonColor: '#28a745',
        titlePrefix: 'Confirm Save'
    },
    submit: {
        icon: 'question',
        confirmButtonText: 'Submit',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Submit'
    },
    unlink: {
        icon: 'warning',
        confirmButtonText: 'Unlink',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Unlink'
    },
    revoke: {
        icon: 'warning',
        confirmButtonText: 'Revoke',
        confirmButtonColor: '#dc3545',
        titlePrefix: 'Confirm Revoke'
    },
    retry: {
        icon: 'question',
        confirmButtonText: 'Retry',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Retry'
    },
    resend: {
        icon: 'question',
        confirmButtonText: 'Resend',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Resend'
    },
    duplicate: {
        icon: 'question',
        confirmButtonText: 'Duplicate',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Duplicate'
    },
    assign: {
        icon: 'question',
        confirmButtonText: 'Assign',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Assignment'
    },
    schedule: {
        icon: 'question',
        confirmButtonText: 'Schedule',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Schedule'
    },
    fetch: {
        icon: 'question',
        confirmButtonText: 'Fetch',
        confirmButtonColor: '#3085d6',
        titlePrefix: 'Confirm Fetch'
    }
};

/**
 * Detect action type from text
 * @param {string} text - Text to analyze
 * @returns {string|null} Detected action or null
 */
function detectAction(text) {
    if (!text) return null;
    const lowerText = text.toLowerCase();

    // Check each action keyword
    for (const [action, config] of Object.entries(ACTION_CONFIGS)) {
        if (lowerText.includes(action)) {
            return action;
        }
    }
    return null;
}

/**
 * Build configuration with smart defaults
 * @param {Object} options - User options
 * @param {string} action - Detected action type
 * @returns {Object} Merged configuration
 */
function buildConfig(options, action) {
    const actionConfig = action ? ACTION_CONFIGS[action] : {};
    const defaults = {
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Confirm',
        cancelButtonText: 'Cancel',
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#6c757d',
        reverseButtons: true
    };

    // Merge: defaults < actionConfig < user options
    return {
        ...defaults,
        ...actionConfig,
        ...options,
        // Ensure title has prefix if not provided
        title: options.title || (actionConfig.titlePrefix || 'Confirm Action')
    };
}

/**
 * SwalContextual API
 */
const SwalContextual = {
    /**
     * Smart confirmation dialog that auto-detects action type
     * @param {Object} options - SweetAlert2 options
     * @returns {Promise} SweetAlert2 promise
     */
    confirm: function(options) {
        if (typeof window.Swal === 'undefined') {
            console.error('SweetAlert2 not loaded');
            return Promise.resolve({ isConfirmed: confirm(options.text || options.title) });
        }

        // Detect action from title or text
        const detectedAction = detectAction(options.title) || detectAction(options.text);
        const config = buildConfig(options, detectedAction);

        return window.Swal.fire(config);
    },

    /**
     * Success notification
     * @param {string} title - Alert title
     * @param {string} text - Alert text
     * @returns {Promise} SweetAlert2 promise
     */
    success: function(title, text) {
        return window.Swal.fire({
            icon: 'success',
            title: title,
            text: text,
            timer: 2000,
            showConfirmButton: false
        });
    },

    /**
     * Error notification
     * @param {string} title - Alert title
     * @param {string} text - Alert text
     * @returns {Promise} SweetAlert2 promise
     */
    error: function(title, text) {
        return window.Swal.fire({
            icon: 'error',
            title: title,
            text: text
        });
    },

    /**
     * Info notification
     * @param {string} title - Alert title
     * @param {string} text - Alert text
     * @returns {Promise} SweetAlert2 promise
     */
    info: function(title, text) {
        return window.Swal.fire({
            icon: 'info',
            title: title,
            text: text
        });
    },

    /**
     * Warning notification
     * @param {string} title - Alert title
     * @param {string} text - Alert text
     * @returns {Promise} SweetAlert2 promise
     */
    warning: function(title, text) {
        return window.Swal.fire({
            icon: 'warning',
            title: title,
            text: text
        });
    }
};

// Create shorthand methods for common actions
Object.keys(ACTION_CONFIGS).forEach(action => {
    SwalContextual[action] = function(text, options = {}) {
        return this.confirm({
            text: text,
            ...options
        });
    };
});

console.debug('[SwalContextual] Helper initialized');

// No window exports needed - all functions are used internally via ES modules
