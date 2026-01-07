'use strict';

/**
 * Admin Panel Base - Utilities
 * Public API utilities for admin panel
 * @module admin-panel-base/utilities
 */

import { CONFIG, isMobile } from './config.js';

/**
 * Show mobile-friendly toast notification
 * Uses data-component="toast-container" selector
 */
export function showMobileToast(message, type) {
    type = type || 'info';

    const toast = document.createElement('div');
    toast.className = `toast align-items-center text-white bg-${type} border-0`;
    toast.setAttribute('role', 'alert');
    toast.setAttribute('aria-live', 'assertive');
    toast.setAttribute('aria-atomic', 'true');
    toast.dataset.toast = type;
    toast.innerHTML = `
        <div class="d-flex">
            <div class="toast-body">${message}</div>
            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" data-action="close-toast" aria-label="Close"></button>
        </div>
    `;

    const container = document.querySelector('[data-component="toast-container"]');
    if (container) {
        container.appendChild(toast);

        const toastInstance = new window.bootstrap.Toast(toast, {
            autohide: true,
            delay: isMobile() ? CONFIG.TOAST_DURATION_MOBILE : CONFIG.TOAST_DURATION_DESKTOP
        });

        toastInstance.show();

        toast.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
    }
}

/**
 * Confirm action with mobile-optimized UX
 * @param {string} message - The confirmation message
 * @param {function} callback - Function to call if confirmed
 * @param {object} options - Optional configuration
 */
export function confirmAction(message, callback, options) {
    options = options || {};

    // Smart defaults based on message content
    const messageLower = message.toLowerCase();
    let defaultConfirm = 'Confirm';
    let defaultCancel = 'Cancel';
    let defaultIcon = 'question';
    let defaultTitle = 'Confirm Action';
    let defaultColor = '#3085d6';

    // Contextual button text based on action type
    if (messageLower.includes('delete') || messageLower.includes('remove')) {
        defaultConfirm = 'Delete';
        defaultIcon = 'warning';
        defaultTitle = 'Confirm Delete';
        defaultColor = '#dc3545';
    } else if (messageLower.includes('sync')) {
        defaultConfirm = 'Sync';
        defaultIcon = 'question';
        defaultTitle = 'Confirm Sync';
    } else if (messageLower.includes('reset')) {
        defaultConfirm = 'Reset';
        defaultIcon = 'warning';
        defaultTitle = 'Confirm Reset';
        defaultColor = '#dc3545';
    } else if (messageLower.includes('clear')) {
        defaultConfirm = 'Clear';
        defaultIcon = 'warning';
        defaultTitle = 'Confirm Clear';
        defaultColor = '#dc3545';
    } else if (messageLower.includes('approve')) {
        defaultConfirm = 'Approve';
        defaultIcon = 'question';
        defaultTitle = 'Confirm Approval';
        defaultColor = '#28a745';
    } else if (messageLower.includes('reject') || messageLower.includes('deny')) {
        defaultConfirm = 'Reject';
        defaultIcon = 'warning';
        defaultTitle = 'Confirm Rejection';
        defaultColor = '#dc3545';
    } else if (messageLower.includes('send')) {
        defaultConfirm = 'Send';
        defaultIcon = 'question';
        defaultTitle = 'Confirm Send';
    } else if (messageLower.includes('save')) {
        defaultConfirm = 'Save';
        defaultIcon = 'question';
        defaultTitle = 'Confirm Save';
        defaultColor = '#28a745';
    } else if (messageLower.includes('cancel')) {
        defaultConfirm = 'Yes, Cancel';
        defaultIcon = 'warning';
        defaultTitle = 'Confirm Cancellation';
    } else if (messageLower.includes('disable')) {
        defaultConfirm = 'Disable';
        defaultIcon = 'warning';
        defaultTitle = 'Confirm Disable';
        defaultColor = '#dc3545';
    } else if (messageLower.includes('enable')) {
        defaultConfirm = 'Enable';
        defaultIcon = 'question';
        defaultTitle = 'Confirm Enable';
        defaultColor = '#28a745';
    } else if (messageLower.includes('continue')) {
        defaultConfirm = 'Continue';
    }

    const confirmText = options.confirmText || defaultConfirm;
    const cancelText = options.cancelText || defaultCancel;
    const title = options.title || defaultTitle;
    const icon = options.icon || defaultIcon;
    const confirmColor = options.confirmColor || defaultColor;

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: title,
            text: message,
            icon: icon,
            showCancelButton: true,
            confirmButtonText: confirmText,
            cancelButtonText: cancelText,
            confirmButtonColor: confirmColor,
            cancelButtonColor: '#6c757d',
            reverseButtons: true
        }).then((result) => {
            if (result.isConfirmed) {
                callback();
            }
        });
    }
}

/**
 * Show loading state on element
 */
export function showLoading(element) {
    if (element) {
        element.classList.add('is-loading');
        element.dataset.loading = 'true';
    }
}

/**
 * Hide loading state on element
 */
export function hideLoading(element) {
    if (element) {
        element.classList.remove('is-loading');
        element.dataset.loading = 'false';
    }
}

/**
 * Optimized fetch for mobile with timeout and error handling
 */
export async function optimizedFetch(url, options) {
    options = options || {};
    const controller = new AbortController();
    const timeoutId = setTimeout(
        () => controller.abort(),
        isMobile() ? CONFIG.FETCH_TIMEOUT_MOBILE : CONFIG.FETCH_TIMEOUT_DESKTOP
    );

    try {
        const response = await fetch(url, {
            ...options,
            signal: controller.signal
        });

        clearTimeout(timeoutId);
        return response;
    } catch (error) {
        clearTimeout(timeoutId);

        if (error.name === 'AbortError') {
            showMobileToast('Request timed out. Please try again.', 'warning');
        } else if (!navigator.onLine) {
            showMobileToast('No internet connection. Please check your network.', 'danger');
        }

        throw error;
    }
}
