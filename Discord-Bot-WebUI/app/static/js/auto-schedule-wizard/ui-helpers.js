/**
 * Auto Schedule Wizard - UI Helpers
 * Modal, toast, and CSS injection utilities
 *
 * @module auto-schedule-wizard/ui-helpers
 */

import { showToast } from '../services/toast-service.js';

/**
 * Apply theme color to element using CSS custom property
 * @param {HTMLElement} element - The element to apply theme color to
 * @param {string} color - The color value to apply
 */
export function applyThemeColor(element, color) {
    element.dataset.themeColor = color;
    element.style.setProperty('--drop-indicator-color', color);
}

/**
 * Apply multiple utility classes to an element
 * @param {HTMLElement} element - The element to apply classes to
 * @param {...string} classes - Class names to add
 */
export function applyUtilityClasses(element, ...classes) {
    element.classList.add(...classes);
}

/**
 * Remove multiple utility classes from an element
 * @param {HTMLElement} element - The element to remove classes from
 * @param {...string} classes - Class names to remove
 */
export function removeUtilityClasses(element, ...classes) {
    element.classList.remove(...classes);
}

/**
 * Show a modal dialog
 * @param {string} id - Modal ID
 * @param {string} title - Modal title
 * @param {string} message - Modal message
 * @param {string} type - Modal type (info, success, error, loading)
 * @param {Function|null} callback - Optional callback on close
 */
export function showModal(id, title, message, type = 'info', callback = null) {
    // Remove existing modal if present
    const existingModal = document.getElementById(id);
    if (existingModal) {
        existingModal.remove();
    }

    const iconMap = {
        info: 'ti-info-circle text-blue-500',
        success: 'ti-check text-green-500',
        error: 'ti-x text-red-500',
        loading: 'ti-loader-2 text-ecs-green'
    };

    const modalHTML = `
        <div class="modal fade" id="${id}" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="ti ${iconMap[type] || iconMap.info} me-2"></i>
                            ${title}
                        </h5>
                        ${type !== 'loading' ? '<button type="button" class="text-gray-400 hover:text-gray-500" onclick="var modal = this.closest(\'[id]\'); if(modal._flowbiteModal) modal._flowbiteModal.hide();"><i class="ti ti-x text-xl"></i></button>' : ''}
                    </div>
                    <div class="modal-body">
                        ${type === 'loading' ? '<div class="flex justify-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin mb-3"></div></div>' : ''}
                        <p class="mb-0">${message}</p>
                    </div>
                    ${type !== 'loading' ? `
                    <div class="modal-footer">
                        <button type="button" class="c-btn c-btn--primary" onclick="var modal = this.closest('[id]'); if(modal._flowbiteModal) modal._flowbiteModal.hide();">OK</button>
                    </div>
                    ` : ''}
                </div>
            </div>
        </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHTML);
    const modalEl = document.getElementById(id);
    const modal = modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
    modal.show();

    if (callback) {
        document.getElementById(id).addEventListener('hidden.bs.modal', callback, { once: true });
    }
}

/**
 * Show a loading modal
 * @param {string} title - Modal title
 * @param {string} message - Modal message
 */
export function showLoadingModal(title, message) {
    showModal('loadingModal', title, message, 'loading');
}

/**
 * Hide the loading modal
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

/**
 * Show a success modal
 * @param {string} title - Modal title
 * @param {string} message - Modal message
 * @param {Function|null} callback - Optional callback on close
 */
export function showSuccessModal(title, message, callback = null) {
    showModal('successModal', title, message, 'success', callback);
}

/**
 * Show an error modal
 * @param {string} title - Modal title
 * @param {string} message - Modal message
 */
export function showErrorModal(title, message) {
    showModal('errorModal', title, message, 'error');
}

// showToast imported from services/toast-service.js
export { showToast };

/**
 * Add spinner CSS dynamically (fallback if not in stylesheet)
 */
export function addSpinnerCSS() {
    if (document.getElementById('wizard-spinner-css')) return;

    const css = `
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
        .wizard-spinner {
            width: 40px;
            height: 40px;
            border: 4px solid #f3f3f3;
            border-top: 4px solid var(--color-ecs-green, #1a472a);
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
    `;

    const style = document.createElement('style');
    style.id = 'wizard-spinner-css';
    style.textContent = css;
    document.head.appendChild(style);
}

/**
 * Add calendar CSS dynamically (fallback if not in stylesheet)
 */
export function addCalendarCSS() {
    if (document.getElementById('wizard-calendar-css')) return;

    const css = `
        .wizard-week-item {
            transition: all 0.2s ease;
            cursor: grab;
        }
        .wizard-week-item:active {
            cursor: grabbing;
        }
        .wizard-week-item.drag-active {
            opacity: 0.5;
        }
        .wizard-week-item.drop-indicator-top {
            border-top: 3px solid var(--drop-indicator-color, var(--color-ecs-green, #1a472a)) !important;
        }
        .wizard-week-item.drop-indicator-bottom {
            border-bottom: 3px solid var(--drop-indicator-color, var(--color-ecs-green, #1a472a)) !important;
        }
    `;

    const style = document.createElement('style');
    style.id = 'wizard-calendar-css';
    style.textContent = css;
    document.head.appendChild(style);
}

export default {
    applyThemeColor,
    applyUtilityClasses,
    removeUtilityClasses,
    showModal,
    showLoadingModal,
    hideLoadingModal,
    showSuccessModal,
    showErrorModal,
    showToast,
    addSpinnerCSS,
    addCalendarCSS
};
