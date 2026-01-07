/**
 * Toast Service
 * Centralized toast/notification system for the application
 *
 * This service consolidates showToast implementations from:
 * - draft-system/ui-helpers.js
 * - auto_schedule_wizard.js
 * - auto-schedule-wizard/ui-helpers.js
 * - chat-widget.js
 * - message-management.js
 * - admin-panel-feature-toggles.js
 * - admin-manage-subs.js
 * - player-profile.js
 * - user-duplicates.js
 * - calendar-subscription.js
 * - calendar-league-events.js
 * - admin-wallet.js
 *
 * Benefits:
 * - Single consistent API for all toast notifications
 * - Automatic fallback chain: SweetAlert2 -> Toastr -> Bootstrap Toast -> Console
 * - Consistent styling and positioning
 * - Type-safe with JSDoc
 *
 * @module services/toast-service
 */

/**
 * @typedef {'success' | 'error' | 'warning' | 'info'} ToastType
 */

/**
 * @typedef {Object} ToastOptions
 * @property {string} [title] - Optional title for the toast
 * @property {number} [duration=3000] - Duration in milliseconds
 * @property {string} [position='top-end'] - Position for the toast
 * @property {boolean} [showCloseButton=true] - Whether to show close button
 */

/**
 * Map of type aliases to standard types
 * Handles variations like 'danger' -> 'error'
 */
const TYPE_MAP = {
    success: 'success',
    error: 'error',
    danger: 'error',
    warning: 'warning',
    info: 'info',
    notice: 'info'
};

/**
 * Normalize toast type to standard values
 * @param {string} type - Input type
 * @returns {ToastType}
 */
function normalizeType(type) {
    return TYPE_MAP[type?.toLowerCase()] || 'info';
}

/**
 * Get Bootstrap background class for toast type
 * @param {ToastType} type - Toast type
 * @returns {string}
 */
function getBootstrapClass(type) {
    const classMap = {
        success: 'bg-success',
        error: 'bg-danger',
        warning: 'bg-warning',
        info: 'bg-info'
    };
    return classMap[type] || 'bg-info';
}

/**
 * Get title for toast type if not provided
 * @param {ToastType} type - Toast type
 * @returns {string}
 */
function getDefaultTitle(type) {
    const titleMap = {
        success: 'Success',
        error: 'Error',
        warning: 'Warning',
        info: 'Notice'
    };
    return titleMap[type] || 'Notice';
}

/**
 * Show toast using SweetAlert2
 * @param {string} message - Toast message
 * @param {ToastType} type - Toast type
 * @param {ToastOptions} options - Additional options
 * @returns {boolean} - Whether the toast was shown
 */
function showSwalToast(message, type, options = {}) {
    if (typeof window.Swal === 'undefined') {
        return false;
    }

    window.Swal.fire({
        toast: true,
        position: options.position || 'top-end',
        icon: type,
        title: options.title || message,
        text: options.title ? message : undefined,
        showConfirmButton: false,
        timer: options.duration || 3000,
        timerProgressBar: true,
        showCloseButton: options.showCloseButton !== false
    });

    return true;
}

/**
 * Show toast using Toastr
 * @param {string} message - Toast message
 * @param {ToastType} type - Toast type
 * @param {ToastOptions} options - Additional options
 * @returns {boolean} - Whether the toast was shown
 */
function showToastrToast(message, type, options = {}) {
    if (typeof window.toastr === 'undefined') {
        return false;
    }

    const toastrType = type === 'error' ? 'error' : type;
    if (typeof window.toastr[toastrType] === 'function') {
        window.toastr[toastrType](message, options.title);
        return true;
    }

    return false;
}

/**
 * Show toast using Bootstrap Toast
 * @param {string} message - Toast message
 * @param {ToastType} type - Toast type
 * @param {ToastOptions} options - Additional options
 * @returns {boolean} - Whether the toast was shown
 */
function showBootstrapToast(message, type, options = {}) {
    // Get or create toast container
    let container = document.querySelector('[data-role="toast-container"]');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        container.setAttribute('data-role', 'toast-container');
        document.body.appendChild(container);
    }

    const bgClass = getBootstrapClass(type);
    const title = options.title || getDefaultTitle(type);
    const duration = options.duration || 3000;

    const toastId = `toast-${Date.now()}`;
    const toastHtml = `
        <div id="${toastId}" class="toast align-items-center text-white ${bgClass} border-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body">
                    ${title !== message ? `<strong>${title}</strong><br>` : ''}
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);

    const toastElement = document.getElementById(toastId);
    if (toastElement && typeof window.bootstrap !== 'undefined' && window.bootstrap.Toast) {
        const bsToast = new window.bootstrap.Toast(toastElement, {
            autohide: true,
            delay: duration
        });
        bsToast.show();

        // Remove from DOM after hidden
        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
        });

        return true;
    }

    // Fallback: manual display and removal
    toastElement.classList.add('show');
    setTimeout(() => {
        toastElement.classList.remove('show');
        setTimeout(() => toastElement.remove(), 300);
    }, duration);

    return true;
}

/**
 * Show toast using custom DOM element (fallback)
 * @param {string} message - Toast message
 * @param {ToastType} type - Toast type
 * @param {ToastOptions} options - Additional options
 */
function showDomToast(message, type, options = {}) {
    const duration = options.duration || 3000;
    const bgClass = getBootstrapClass(type);

    const toast = document.createElement('div');
    toast.className = `position-fixed top-0 end-0 m-3 p-3 rounded text-white ${bgClass}`;
    toast.style.cssText = 'z-index: 9999; min-width: 250px; animation: slideIn 0.3s ease;';
    toast.innerHTML = `
        <div class="d-flex justify-content-between align-items-center">
            <span>${message}</span>
            <button type="button" class="btn-close btn-close-white ms-2" onclick="this.parentElement.parentElement.remove()"></button>
        </div>
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

/**
 * Console fallback for toast
 * @param {string} message - Toast message
 * @param {ToastType} type - Toast type
 */
function showConsoleToast(message, type) {
    const logMethod = type === 'error' ? 'error' : type === 'warning' ? 'warn' : 'log';
    console[logMethod](`[Toast ${type.toUpperCase()}]:`, message);
}

/**
 * Main toast function - shows a toast notification
 *
 * Supports multiple signatures for backward compatibility:
 * - showToast(message, type)
 * - showToast(type, message) - legacy reversed order
 * - showToast(message, type, options)
 * - showToast(title, message, type) - 3 param legacy
 * - showToast(icon, title, text) - admin-panel-feature-toggles style
 *
 * @param {string} arg1 - Message, type, or title depending on signature
 * @param {string} [arg2] - Type, message, or text depending on signature
 * @param {string|ToastOptions} [arg3] - Type or options depending on signature
 */
export function showToast(arg1, arg2 = 'info', arg3 = {}) {
    let message, type, options;

    // Detect signature pattern
    if (typeof arg3 === 'string') {
        // 3-string signature: (title, message, type) or (icon, title, text)
        // Check if first arg looks like a type
        if (TYPE_MAP[arg1?.toLowerCase()]) {
            // (icon/type, title, text) - admin-panel-feature-toggles style
            type = normalizeType(arg1);
            message = arg3; // text is the message
            options = { title: arg2 };
        } else {
            // (title, message, type)
            type = normalizeType(arg3);
            message = arg2;
            options = { title: arg1 };
        }
    } else if (typeof arg2 === 'string') {
        // 2-string signature: detect order
        if (TYPE_MAP[arg1?.toLowerCase()] && !TYPE_MAP[arg2?.toLowerCase()]) {
            // (type, message) - reversed legacy order
            type = normalizeType(arg1);
            message = arg2;
        } else {
            // (message, type) - standard order
            message = arg1;
            type = normalizeType(arg2);
        }
        options = typeof arg3 === 'object' ? arg3 : {};
    } else {
        // Single arg or (message, options)
        message = arg1;
        type = 'info';
        options = typeof arg2 === 'object' ? arg2 : {};
    }

    // Try notification methods in order of preference
    if (showSwalToast(message, type, options)) return;
    if (showToastrToast(message, type, options)) return;
    if (showBootstrapToast(message, type, options)) return;

    // Final fallback: DOM element or console
    try {
        showDomToast(message, type, options);
    } catch (e) {
        showConsoleToast(message, type);
    }
}

/**
 * Show success toast
 * @param {string} message - Toast message
 * @param {ToastOptions} [options] - Additional options
 */
export function showSuccess(message, options = {}) {
    showToast(message, 'success', options);
}

/**
 * Show error toast
 * @param {string} message - Toast message
 * @param {ToastOptions} [options] - Additional options
 */
export function showError(message, options = {}) {
    showToast(message, 'error', options);
}

/**
 * Show warning toast
 * @param {string} message - Toast message
 * @param {ToastOptions} [options] - Additional options
 */
export function showWarning(message, options = {}) {
    showToast(message, 'warning', options);
}

/**
 * Show info toast
 * @param {string} message - Toast message
 * @param {ToastOptions} [options] - Additional options
 */
export function showInfo(message, options = {}) {
    showToast(message, 'info', options);
}

// Expose to window for backward compatibility
// This allows existing code using window.showToast to continue working
if (typeof window !== 'undefined') {
    window.showToast = showToast;
    window.ToastService = {
        show: showToast,
        success: showSuccess,
        error: showError,
        warning: showWarning,
        info: showInfo
    };
}

// Default export
export default {
    show: showToast,
    success: showSuccess,
    error: showError,
    warning: showWarning,
    info: showInfo
};
