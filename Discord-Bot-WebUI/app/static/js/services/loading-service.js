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
 * Show loading using SweetAlert2 (global overlay)
 * @param {LoadingOptions} options - Loading options
 * @returns {string} - Loading ID for tracking
 */
function showSwalLoading(options = {}) {
    const id = `swal-${++loadingCounter}`;

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: options.title || 'Loading...',
            html: options.message
                ? `<div class="text-center"><div class="spinner-border text-primary mb-3" role="status"></div><p class="mb-0">${options.message}</p></div>`
                : '<div class="text-center"><div class="spinner-border text-primary" role="status"></div></div>',
            allowOutsideClick: false,
            allowEscapeKey: false,
            showConfirmButton: false,
            didOpen: () => {
                // Store reference to close later
                activeLoadings.set(id, { type: 'swal' });
            }
        });
    } else {
        // Fallback to modal if Swal not available
        return showModalLoading(options);
    }

    return id;
}

/**
 * Show loading using Bootstrap modal
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
        <div class="modal fade" id="loadingModal" tabindex="-1" data-bs-backdrop="static" data-bs-keyboard="false">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-body text-center py-5">
                        <div class="spinner-border text-primary mb-3" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                        <h5 class="mb-2">${title}</h5>
                        <p class="text-muted mb-0">${message}</p>
                    </div>
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);

    const modal = document.getElementById('loadingModal');
    if (modal && typeof window.bootstrap !== 'undefined') {
        const bsModal = new window.bootstrap.Modal(modal);
        bsModal.show();
        activeLoadings.set(id, { type: 'modal', element: modal, instance: bsModal });
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
            spinner.className = 'loading-spinner-overlay';
            spinner.innerHTML = '<div class="spinner-border text-primary" role="status"></div>';
            spinner.style.cssText = 'position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; background: rgba(255,255,255,0.8); z-index: 10;';

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
        if (typeof window.bootstrap !== 'undefined') {
            const bsModal = window.bootstrap.Modal.getInstance(modal);
            if (bsModal) bsModal.hide();
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
