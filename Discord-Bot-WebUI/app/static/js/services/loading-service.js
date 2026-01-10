/**
 * Loading Service
 * Centralized loading indicator system for the application
 *
 * This service consolidates loading implementations from:
 * - draft-system/ui-helpers.js (overlay-based)
 * - admin-panel-base/utilities.js (element class-based)
 * - auto-schedule-wizard/ui-helpers.js (modal-based)
 * - auto_schedule_wizard.js (modal-based duplicate)
 * - user-management-comprehensive.js (SweetAlert2-based)
 * - messages-inbox.js (element toggle)
 *
 * Supports multiple loading patterns:
 * 1. Global overlay (SweetAlert2)
 * 2. Element-specific loading states
 * 3. Modal-based loading dialogs
 * 4. Component-specific overlays
 *
 * @module services/loading-service
 */

/**
 * @typedef {'overlay' | 'element' | 'modal' | 'swal'} LoadingType
 */

/**
 * @typedef {Object} LoadingOptions
 * @property {string} [title='Loading...'] - Title for the loading indicator
 * @property {string} [message] - Optional message text
 * @property {HTMLElement} [target] - Target element for element-based loading
 * @property {string} [selector] - CSS selector for target element
 * @property {LoadingType} [type='swal'] - Type of loading indicator
 * @property {boolean} [backdrop=true] - Whether to show backdrop (for modals/overlays)
 */

// Track active loading states
const activeLoadings = new Map();
let loadingCounter = 0;

/**
 * Get dark mode status for SweetAlert styling
 * @returns {boolean}
 */
function isDarkMode() {
    return document.documentElement.classList.contains('dark');
}

/**
 * Get SweetAlert options with dark mode support
 * @param {Object} options - Base options
 * @returns {Object}
 */
function getSwalOptions(options) {
    const dark = isDarkMode();
    return {
        ...options,
        background: dark ? '#1f2937' : '#ffffff',
        color: dark ? '#f3f4f6' : '#111827'
    };
}

/**
 * Show loading using SweetAlert2 (global overlay)
 * @param {LoadingOptions} options - Loading options
 * @returns {string} - Loading ID for tracking
 */
function showSwalLoading(options = {}) {
    const id = `swal-${++loadingCounter}`;

    if (typeof window.Swal !== 'undefined') {
        const dark = isDarkMode();
        const spinnerColor = dark ? 'border-gray-300' : 'border-ecs-green';

        window.Swal.fire(getSwalOptions({
            title: options.title || 'Loading...',
            html: options.message
                ? `<div class="flex flex-col items-center"><div class="w-8 h-8 border-4 ${spinnerColor} border-t-transparent rounded-full animate-spin mb-3"></div><p class="text-gray-600 dark:text-gray-400">${options.message}</p></div>`
                : `<div class="flex justify-center"><div class="w-8 h-8 border-4 ${spinnerColor} border-t-transparent rounded-full animate-spin"></div></div>`,
            allowOutsideClick: false,
            allowEscapeKey: false,
            showConfirmButton: false,
            didOpen: () => {
                // Store reference to close later
                activeLoadings.set(id, { type: 'swal' });
            }
        }));
    } else {
        // Fallback to modal if Swal not available
        return showModalLoading(options);
    }

    return id;
}

/**
 * Show loading using Flowbite modal (Tailwind-based)
 * @param {LoadingOptions} options - Loading options
 * @returns {string} - Loading ID for tracking
 */
function showModalLoading(options = {}) {
    const id = `modal-${++loadingCounter}`;
    const title = options.title || 'Loading...';
    const message = options.message || 'Please wait...';

    // Remove existing loading modal if present
    const existingModal = document.getElementById('loadingModal');
    if (existingModal) {
        existingModal.remove();
    }

    const modalHtml = `
        <div id="loadingModal" tabindex="-1" class="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto overflow-x-hidden">
            <div class="fixed inset-0 bg-gray-900/50 dark:bg-gray-900/80"></div>
            <div class="relative p-4 w-full max-w-md">
                <div class="relative bg-white rounded-lg shadow dark:bg-gray-800">
                    <div class="p-6 text-center">
                        <div class="w-12 h-12 border-4 border-ecs-green border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
                        <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-2">${title}</h3>
                        <p class="text-sm text-gray-500 dark:text-gray-400">${message}</p>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
    document.body.classList.add('overflow-hidden');

    const modal = document.getElementById('loadingModal');
    if (modal) {
        activeLoadings.set(id, { type: 'modal', element: modal });
    }

    return id;
}

/**
 * Show loading on specific element (adds class)
 * @param {HTMLElement|string} target - Element or selector
 * @param {LoadingOptions} options - Loading options
 * @returns {string} - Loading ID for tracking
 */
function showElementLoading(target, options = {}) {
    const id = `element-${++loadingCounter}`;

    const element = typeof target === 'string'
        ? document.querySelector(target)
        : target;

    if (element) {
        element.classList.add('is-loading');
        element.dataset.loading = 'true';

        // Optionally add spinner overlay
        if (options.showSpinner !== false) {
            const spinner = document.createElement('div');
            spinner.className = 'loading-spinner-overlay absolute inset-0 flex items-center justify-center bg-white/80 dark:bg-gray-900/80 z-10';
            spinner.innerHTML = '<div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin"></div>';

            // Ensure element has position for overlay
            const computedStyle = window.getComputedStyle(element);
            if (computedStyle.position === 'static') {
                element.style.position = 'relative';
                element.dataset.positionWasStatic = 'true';
            }

            element.appendChild(spinner);
        }

        activeLoadings.set(id, { type: 'element', element, options });
    }

    return id;
}

/**
 * Show component-specific loading overlay
 * @param {string} componentSelector - Selector for the component's loading overlay
 * @param {LoadingOptions} options - Loading options
 * @returns {string} - Loading ID for tracking
 */
function showOverlayLoading(componentSelector, options = {}) {
    const id = `overlay-${++loadingCounter}`;

    const overlay = document.querySelector(componentSelector);
    if (overlay) {
        overlay.classList.add('is-visible');
        overlay.classList.remove('is-hidden');
        activeLoadings.set(id, { type: 'overlay', element: overlay });
    }

    return id;
}

/**
 * Hide loading by ID
 * @param {string} id - Loading ID returned from show functions
 */
function hideLoadingById(id) {
    const loading = activeLoadings.get(id);
    if (!loading) return;

    switch (loading.type) {
        case 'swal':
            if (typeof window.Swal !== 'undefined') {
                window.Swal.close();
            }
            break;

        case 'modal':
            if (loading.instance) {
                loading.instance.hide();
            }
            if (loading.element) {
                loading.element.remove();
            }
            document.body.classList.remove('overflow-hidden');
            break;

        case 'element':
            if (loading.element) {
                loading.element.classList.remove('is-loading');
                loading.element.dataset.loading = 'false';

                const spinner = loading.element.querySelector('.loading-spinner-overlay');
                if (spinner) spinner.remove();

                if (loading.element.dataset.positionWasStatic === 'true') {
                    loading.element.style.position = '';
                    delete loading.element.dataset.positionWasStatic;
                }
            }
            break;

        case 'overlay':
            if (loading.element) {
                loading.element.classList.add('is-hidden');
                loading.element.classList.remove('is-visible');
            }
            break;
    }

    activeLoadings.delete(id);
}

/**
 * Hide all active loading indicators
 */
function hideAllLoadings() {
    for (const id of activeLoadings.keys()) {
        hideLoadingById(id);
    }
}

// ============================================================================
// Main API - unified show/hide functions
// ============================================================================

/**
 * Show loading indicator
 *
 * Usage:
 * - showLoading() - Global SweetAlert2 overlay
 * - showLoading('Processing...') - With title
 * - showLoading({ title: 'Loading', message: 'Please wait' }) - With options
 * - showLoading(element) - Element-specific loading
 * - showLoading('#myElement') - Element by selector
 *
 * @param {string|HTMLElement|LoadingOptions} [arg1] - Title, element, selector, or options
 * @param {LoadingOptions} [arg2] - Additional options
 * @returns {string} - Loading ID for hiding later
 */
export function showLoading(arg1, arg2 = {}) {
    let options = {};

    // Parse arguments
    if (typeof arg1 === 'string') {
        if (arg1.startsWith('#') || arg1.startsWith('.') || arg1.startsWith('[')) {
            // Selector for element loading
            return showElementLoading(arg1, arg2);
        } else {
            // Title for global loading
            options = { title: arg1, ...arg2 };
        }
    } else if (arg1 instanceof HTMLElement) {
        // Element for element loading
        return showElementLoading(arg1, arg2);
    } else if (typeof arg1 === 'object' && arg1 !== null) {
        options = arg1;
    }

    // Determine type
    const type = options.type || 'swal';

    switch (type) {
        case 'modal':
            return showModalLoading(options);
        case 'element':
            return showElementLoading(options.target || options.selector, options);
        case 'overlay':
            return showOverlayLoading(options.selector, options);
        case 'swal':
        default:
            return showSwalLoading(options);
    }
}

/**
 * Hide loading indicator
 *
 * Usage:
 * - hideLoading() - Hide all loading indicators
 * - hideLoading(id) - Hide specific loading by ID
 * - hideLoading(element) - Hide element-specific loading
 *
 * @param {string|HTMLElement} [target] - Loading ID, element, or nothing to hide all
 */
export function hideLoading(target) {
    if (!target) {
        hideAllLoadings();
        return;
    }

    if (typeof target === 'string') {
        if (activeLoadings.has(target)) {
            hideLoadingById(target);
        } else {
            // Treat as selector
            const element = document.querySelector(target);
            if (element) {
                element.classList.remove('is-loading');
                element.dataset.loading = 'false';
                const spinner = element.querySelector('.loading-spinner-overlay');
                if (spinner) spinner.remove();
            }
        }
        return;
    }

    if (target instanceof HTMLElement) {
        target.classList.remove('is-loading');
        target.dataset.loading = 'false';
        const spinner = target.querySelector('.loading-spinner-overlay');
        if (spinner) spinner.remove();
        return;
    }
}

// ============================================================================
// Convenience aliases for backward compatibility
// ============================================================================

/**
 * Show loading modal (backward compatible)
 * @param {string} title - Modal title
 * @param {string} message - Modal message
 * @returns {string} - Loading ID
 */
export function showLoadingModal(title, message) {
    return showLoading({ type: 'modal', title, message });
}

/**
 * Hide loading modal (backward compatible)
 */
export function hideLoadingModal() {
    const modal = document.getElementById('loadingModal');
    if (modal) {
        if (modal._flowbiteModal) {
            modal._flowbiteModal.hide();
        }
        modal.remove();
    }
}

// Expose to window for backward compatibility
if (typeof window !== 'undefined') {
    window.LoadingService = {
        show: showLoading,
        hide: hideLoading,
        showModal: showLoadingModal,
        hideModal: hideLoadingModal,
        hideAll: hideAllLoadings
    };

    // Legacy function aliases
    window.showLoading = showLoading;
    window.hideLoading = hideLoading;
    window.showLoadingModal = showLoadingModal;
    window.hideLoadingModal = hideLoadingModal;
}

// Default export
export default {
    show: showLoading,
    hide: hideLoading,
    showModal: showLoadingModal,
    hideModal: hideLoadingModal,
    hideAll: hideAllLoadings
};
