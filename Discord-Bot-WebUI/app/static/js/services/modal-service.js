/**
 * Modal Service
 * Centralized modal management for the application
 *
 * This service wraps the ModalManager class to provide a consistent
 * service-oriented API matching other services (toast-service, loading-service).
 *
 * The underlying implementation is in modal-manager.js which provides:
 * - Instance caching (prevents duplicate modal initializations)
 * - Safe initialization (handles timing issues)
 * - Auto-discovery of all modals on page
 * - Event delegation support via data-action attributes
 * - Memory cleanup
 *
 * @module services/modal-service
 */

import { ModalManager } from '../modal-manager.js';

/**
 * Show a modal by ID
 * @param {string} modalId - The modal element ID (with or without #)
 * @param {Object} options - Bootstrap modal options
 * @returns {bootstrap.Modal|null} Modal instance or null
 */
export function showModal(modalId, options = {}) {
    return ModalManager.show(modalId, options);
}

/**
 * Hide a modal by ID
 * @param {string} modalId - The modal element ID (with or without #)
 */
export function hideModal(modalId) {
    ModalManager.hide(modalId);
}

/**
 * Toggle a modal by ID
 * @param {string} modalId - The modal element ID (with or without #)
 */
export function toggleModal(modalId) {
    ModalManager.toggle(modalId);
}

/**
 * Get or create a modal instance
 * @param {string} modalId - The modal element ID
 * @param {Object} options - Bootstrap modal options
 * @returns {bootstrap.Modal|null} Modal instance or null
 */
export function getModalInstance(modalId, options = {}) {
    return ModalManager.getInstance(modalId, options);
}

/**
 * Destroy a modal instance and clean up
 * @param {string} modalId - The modal element ID
 */
export function destroyModal(modalId) {
    ModalManager.destroy(modalId);
}

/**
 * Show a confirmation modal with SweetAlert2
 * @param {Object} options - SweetAlert2 options
 * @returns {Promise} SweetAlert2 result promise
 */
export function showConfirmModal(options = {}) {
    if (typeof window.Swal === 'undefined') {
        console.warn('[ModalService] SweetAlert2 not loaded, falling back to confirm()');
        return Promise.resolve({ isConfirmed: confirm(options.text || options.title || 'Are you sure?') });
    }

    const defaults = {
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#d33',
        confirmButtonText: 'Yes',
        cancelButtonText: 'Cancel'
    };

    return window.Swal.fire({ ...defaults, ...options });
}

/**
 * Show an error modal with SweetAlert2
 * @param {string} title - Error title
 * @param {string} message - Error message
 * @returns {Promise} SweetAlert2 result promise
 */
export function showErrorModal(title, message) {
    if (typeof window.Swal === 'undefined') {
        alert(`${title}\n\n${message}`);
        return Promise.resolve();
    }

    return window.Swal.fire({
        icon: 'error',
        title: title,
        text: message
    });
}

/**
 * Show a success modal with SweetAlert2
 * @param {string} title - Success title
 * @param {string} message - Success message
 * @returns {Promise} SweetAlert2 result promise
 */
export function showSuccessModal(title, message) {
    if (typeof window.Swal === 'undefined') {
        alert(`${title}\n\n${message}`);
        return Promise.resolve();
    }

    return window.Swal.fire({
        icon: 'success',
        title: title,
        text: message,
        timer: 2000,
        showConfirmButton: false
    });
}

// Expose to window for backward compatibility
if (typeof window !== 'undefined') {
    window.ModalService = {
        show: showModal,
        hide: hideModal,
        toggle: toggleModal,
        getInstance: getModalInstance,
        destroy: destroyModal,
        confirm: showConfirmModal,
        error: showErrorModal,
        success: showSuccessModal
    };
}

// Default export
export default {
    show: showModal,
    hide: hideModal,
    toggle: toggleModal,
    getInstance: getModalInstance,
    destroy: destroyModal,
    confirm: showConfirmModal,
    error: showErrorModal,
    success: showSuccessModal
};
