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
 * Get Tailwind background class for toast type
 * @param {ToastType} type - Toast type
 * @returns {string}
 */
function getTailwindBgClass(type) {
    const classMap = {
        success: 'bg-green-600 dark:bg-green-700',
        error: 'bg-red-600 dark:bg-red-700',
        warning: 'bg-yellow-500 dark:bg-yellow-600',
        info: 'bg-blue-600 dark:bg-blue-700'
    };
    return classMap[type] || 'bg-blue-600 dark:bg-blue-700';
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
 * Show toast using Tailwind-styled toast (fallback when SweetAlert2 unavailable)
 * @param {string} message - Toast message
 * @param {ToastType} type - Toast type
 * @param {ToastOptions} options - Additional options
 * @returns {boolean} - Whether the toast was shown
 */
function showTailwindToast(message, type, options = {}) {
    // Get or create toast container
    let container = document.querySelector('[data-role="toast-container"]');
    if (!container) {
        container = document.createElement('div');
        container.className = 'fixed top-4 right-4 z-50 flex flex-col gap-2';
        container.setAttribute('data-role', 'toast-container');
        document.body.appendChild(container);
    }

    const bgClass = getTailwindBgClass(type);
    const title = options.title || getDefaultTitle(type);
    const duration = options.duration || 3000;

    const toastId = `toast-${Date.now()}`;
    const toastHtml = `
        <div id="${toastId}" class="flex items-center p-4 text-white ${bgClass} rounded-lg shadow-lg max-w-sm transform transition-all duration-300 translate-x-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="flex-1 text-sm font-medium">
                ${title !== message ? `<span class="font-bold">${title}</span><br>` : ''}
                ${message}
            </div>
            <button type="button" onclick="this.closest('[role=alert]').remove()" class="ml-3 -mr-1 -my-1 p-1.5 rounded-lg hover:bg-white/20 focus:ring-2 focus:ring-white/50" aria-label="Close">
                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path></svg>
            </button>
        </div>
    `;

    container.insertAdjacentHTML('beforeend', toastHtml);

    const toastElement = document.getElementById(toastId);

    // Auto-remove after duration
    setTimeout(() => {
        if (toastElement) {
            toastElement.classList.add('translate-x-full', 'opacity-0');
            setTimeout(() => toastElement.remove(), 300);
        }
    }, duration);

    return true;
}

/**
 * Show toast using custom DOM element (final fallback)
 * @param {string} message - Toast message
 * @param {ToastType} type - Toast type
 * @param {ToastOptions} options - Additional options
 */
function showDomToast(message, type, options = {}) {
    const duration = options.duration || 3000;
    const bgClass = getTailwindBgClass(type);

    const toast = document.createElement('div');
    toast.className = `fixed top-4 right-4 z-50 p-4 rounded-lg text-white min-w-64 shadow-lg ${bgClass}`;
    toast.innerHTML = `
        <div class="flex justify-between items-center gap-3">
            <span class="text-sm">${message}</span>
            <button type="button" class="p-1 hover:bg-white/20 rounded" onclick="this.parentElement.parentElement.remove()">
                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" clip-rule="evenodd"></path></svg>
            </button>
        </div>
    `;

    document.body.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('opacity-0', 'transition-opacity', 'duration-300');
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
    if (showTailwindToast(message, type, options)) return;

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
