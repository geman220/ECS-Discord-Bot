'use strict';

/**
 * Store Admin Page Module
 * Handles store item management, order management, and bulk operations
 *
 * @module store-admin
 * @requires window.InitSystem
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Store Admin functionality
 */
const StoreAdmin = {
    /**
     * Initialize store admin functionality
     */
    init() {
        this.setupCreateItemForm();
        this.setupItemDeletion();
        this.setupOrderStatusUpdates();
        this.setupBulkOrderManagement();
        this.setupSeasonReset();
        this.setupOrderDeletion();

        console.log('[StoreAdmin] Initialized');
    },

    /**
     * Get CSRF token from meta tag or form
     * @returns {string} CSRF token
     */
    getCsrfToken() {
        const metaToken = document.querySelector('meta[name="csrf-token"]');
        if (metaToken) {
            return metaToken.getAttribute('content');
        }
        const inputToken = document.querySelector('input[name="csrf_token"]');
        return inputToken ? inputToken.value : '';
    },

    /**
     * Setup create item form functionality using event delegation
     */
    setupCreateItemForm() {
        const self = this;

        // Delegated click handler for add/remove color/size
        document.addEventListener('click', (e) => {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            // Add color
            if (e.target.closest('#add-color')) {
                const container = document.getElementById('colors-container');
                if (container) {
                    const div = document.createElement('div');
                    div.className = 'flex gap-2 mb-2';
                    div.innerHTML = `
                        <input type="text" class="flex-1 bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" name="colors[]" placeholder="e.g. Navy, Black, White" data-form-control aria-label="e.g. Navy, Black, White">
                        <button type="button" class="text-red-600 hover:text-red-800 dark:text-red-500 dark:hover:text-red-400 p-2.5 remove-color" aria-label="Remove color"><i class="ti ti-x"></i></button>
                    `;
                    container.appendChild(div);
                    self.updateRemoveButtons('color');
                }
                return;
            }

            // Add size
            if (e.target.closest('#add-size')) {
                const container = document.getElementById('sizes-container');
                if (container) {
                    const div = document.createElement('div');
                    div.className = 'flex gap-2 mb-2';
                    div.innerHTML = `
                        <input type="text" class="flex-1 bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" name="sizes[]" placeholder="e.g. YXS, YS, YM, YL" data-form-control aria-label="e.g. YXS, YS, YM, YL">
                        <button type="button" class="text-red-600 hover:text-red-800 dark:text-red-500 dark:hover:text-red-400 p-2.5 remove-size" aria-label="Remove size"><i class="ti ti-x"></i></button>
                    `;
                    container.appendChild(div);
                    self.updateRemoveButtons('size');
                }
                return;
            }

            // Remove color
            if (e.target.closest('.remove-color')) {
                e.target.closest('.flex.gap-2').remove();
                self.updateRemoveButtons('color');
                return;
            }

            // Remove size
            if (e.target.closest('.remove-size')) {
                e.target.closest('.flex.gap-2').remove();
                self.updateRemoveButtons('size');
                return;
            }
        });

        // Delegated submit handler for create item form
        document.addEventListener('submit', (e) => {
            if (e.target.id === 'createItemForm') {
                e.preventDefault();
                self.handleCreateItem(e.target);
            }
        });

        // Initial update for remove buttons
        this.updateRemoveButtons('color');
        this.updateRemoveButtons('size');
    },

    /**
     * Update remove button visibility
     * @param {string} type - 'color' or 'size'
     */
    updateRemoveButtons(type) {
        const container = document.getElementById(`${type}s-container`);
        if (!container) return;

        const groups = container.querySelectorAll('.flex.gap-2');
        groups.forEach((group) => {
            const removeBtn = group.querySelector(`.remove-${type}`);
            if (removeBtn) {
                if (groups.length > 1) {
                    removeBtn.classList.remove('hidden');
                } else {
                    removeBtn.classList.add('hidden');
                }
            }
        });
    },

    /**
     * Handle create item form submission
     * @param {HTMLFormElement} form - The form element
     */
    handleCreateItem(form) {
        const formData = new FormData(form);
        const submitBtn = form.querySelector('button[type="submit"]');
        const originalText = submitBtn.innerHTML;

        // Show loading
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin me-1" role="status" data-spinner></div>Creating...';

        const createItemUrl = form.getAttribute('action') || '/store/create-item';

        fetch(createItemUrl, {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Item Created!',
                        text: data.message
                    }).then(() => {
                        window.location.reload();
                    });
                } else {
                    window.location.reload();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: data.message
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'An error occurred while creating the item.'
                });
            }
        })
        .finally(() => {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
        });
    },

    /**
     * Setup item deletion handlers
     */
    setupItemDeletion() {
        document.addEventListener('click', (e) => {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const deleteBtn = e.target.closest('[data-action="delete-item"]');
            if (!deleteBtn) return;

            e.preventDefault();
            const itemId = deleteBtn.getAttribute('data-item-id');
            const itemName = deleteBtn.getAttribute('data-item-name');

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Delete Item',
                    text: `Are you sure you want to delete "${itemName}"? This will also delete all associated orders.`,
                    icon: 'warning',
                    showCancelButton: true,
                    confirmButtonText: 'Yes, delete it!',
                    cancelButtonText: 'Cancel',
                    confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
                }).then((result) => {
                    if (result.isConfirmed) {
                        this.performDeleteItem(itemId);
                    }
                });
            }
        });
    },

    /**
     * Perform item deletion
     * @param {string} itemId - Item ID to delete
     */
    performDeleteItem(itemId) {
        const deleteUrl = `/store/admin/item/${itemId}/delete`;

        fetch(deleteUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Deleted!',
                        text: data.message
                    }).then(() => {
                        window.location.reload();
                    });
                } else {
                    window.location.reload();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: data.message
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'An error occurred while deleting the item.'
                });
            }
        });
    },

    /**
     * Setup order status update handlers
     */
    setupOrderStatusUpdates() {
        document.addEventListener('change', (e) => {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const statusSelect = e.target.closest('[data-action="update-order-status"]');
            if (!statusSelect) return;

            const orderId = statusSelect.getAttribute('data-order-id');
            const currentStatus = statusSelect.getAttribute('data-current-status');
            const newStatus = statusSelect.value;

            if (newStatus === currentStatus) return;

            const formData = new FormData();
            formData.append('status', newStatus);
            formData.append('csrf_token', this.getCsrfToken());

            const updateUrl = `/store/admin/order/${orderId}/update`;

            fetch(updateUrl, {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    statusSelect.setAttribute('data-current-status', newStatus);
                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire({
                            icon: 'success',
                            title: 'Updated!',
                            text: data.message,
                            timer: 2000,
                            showConfirmButton: false
                        });
                    }
                } else {
                    // Revert the select back to the previous status
                    statusSelect.value = currentStatus;
                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire({
                            icon: 'error',
                            title: 'Error',
                            text: data.message
                        });
                    }
                }
            })
            .catch(error => {
                console.error('Error:', error);
                // Revert the select back to the previous status
                statusSelect.value = currentStatus;
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: 'An error occurred while updating the order status.'
                    });
                }
            });
        });
    },

    /**
     * Setup bulk order management using event delegation
     */
    setupBulkOrderManagement() {
        const self = this;

        // Delegated change handler for checkboxes and select
        document.addEventListener('change', (e) => {
            // Select all checkbox
            if (e.target.matches('#select-all-orders')) {
                const orderCheckboxes = document.querySelectorAll('.order-checkbox');
                orderCheckboxes.forEach(checkbox => {
                    checkbox.checked = e.target.checked;
                });
                self.updateBulkUpdateButton();
                return;
            }

            // Individual order checkboxes
            if (e.target.matches('.order-checkbox')) {
                self.updateSelectAllState();
                self.updateBulkUpdateButton();
                return;
            }

            // Bulk status select
            if (e.target.matches('#bulk-status-select')) {
                self.updateBulkUpdateButton();
                return;
            }
        });

        // Delegated click handler for bulk buttons
        document.addEventListener('click', (e) => {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            // Bulk update button
            if (e.target.closest('#bulk-update-btn')) {
                self.handleBulkUpdate();
                return;
            }

            // Bulk delete button
            if (e.target.closest('#bulk-delete-btn')) {
                self.handleBulkDelete();
                return;
            }
        });
    },

    /**
     * Update select all checkbox state
     */
    updateSelectAllState() {
        const selectAllCheckbox = document.getElementById('select-all-orders');
        const orderCheckboxes = document.querySelectorAll('.order-checkbox');
        const checkedBoxes = document.querySelectorAll('.order-checkbox:checked').length;
        const totalBoxes = orderCheckboxes.length;

        if (checkedBoxes === 0) {
            selectAllCheckbox.indeterminate = false;
            selectAllCheckbox.checked = false;
        } else if (checkedBoxes === totalBoxes) {
            selectAllCheckbox.indeterminate = false;
            selectAllCheckbox.checked = true;
        } else {
            selectAllCheckbox.indeterminate = true;
        }
    },

    /**
     * Update bulk update button state
     */
    updateBulkUpdateButton() {
        const bulkStatusSelect = document.getElementById('bulk-status-select');
        const bulkUpdateBtn = document.getElementById('bulk-update-btn');
        const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
        const checkedBoxes = document.querySelectorAll('.order-checkbox:checked').length;
        const hasStatus = bulkStatusSelect && bulkStatusSelect.value !== '';

        if (bulkUpdateBtn) {
            bulkUpdateBtn.disabled = checkedBoxes === 0 || !hasStatus;
            bulkUpdateBtn.innerHTML = checkedBoxes > 0
                ? `<i class="ti ti-check me-1"></i>Update ${checkedBoxes} Selected`
                : '<i class="ti ti-check me-1"></i>Update Selected';
        }

        if (bulkDeleteBtn) {
            bulkDeleteBtn.disabled = checkedBoxes === 0;
            bulkDeleteBtn.innerHTML = checkedBoxes > 0
                ? `<i class="ti ti-trash me-1"></i>Delete ${checkedBoxes} Selected`
                : '<i class="ti ti-trash me-1"></i>Delete Selected';
        }
    },

    /**
     * Handle bulk update
     */
    handleBulkUpdate() {
        const checkedBoxes = document.querySelectorAll('.order-checkbox:checked');
        const bulkStatusSelect = document.getElementById('bulk-status-select');
        const newStatus = bulkStatusSelect ? bulkStatusSelect.value : '';

        if (checkedBoxes.length === 0 || !newStatus) return;

        const orderIds = Array.from(checkedBoxes).map(cb => cb.value);

        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Bulk Update Orders',
                text: `Are you sure you want to update ${orderIds.length} orders to "${newStatus}"?`,
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Yes, update them!',
                cancelButtonText: 'Cancel',
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#696cff'
            }).then((result) => {
                if (result.isConfirmed) {
                    this.performBulkUpdate(orderIds, newStatus);
                }
            });
        }
    },

    /**
     * Perform bulk update
     * @param {Array} orderIds - Array of order IDs
     * @param {string} newStatus - New status
     */
    performBulkUpdate(orderIds, newStatus) {
        const bulkUpdateBtn = document.getElementById('bulk-update-btn');
        const originalText = bulkUpdateBtn.innerHTML;
        bulkUpdateBtn.disabled = true;
        bulkUpdateBtn.innerHTML = '<div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin me-1" role="status" data-spinner></div>Updating...';

        fetch('/store/admin/orders/bulk-update', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify({
                order_ids: orderIds,
                status: newStatus
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Orders Updated!',
                        text: data.message
                    }).then(() => {
                        window.location.reload();
                    });
                } else {
                    window.location.reload();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Update Failed',
                        text: data.message
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'An error occurred while updating the orders.'
                });
            }
        })
        .finally(() => {
            bulkUpdateBtn.disabled = false;
            bulkUpdateBtn.innerHTML = originalText;
        });
    },

    /**
     * Handle bulk delete
     */
    handleBulkDelete() {
        const checkedBoxes = document.querySelectorAll('.order-checkbox:checked');

        if (checkedBoxes.length === 0) return;

        const orderIds = Array.from(checkedBoxes).map(cb => cb.value);

        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Delete Orders',
                text: `Are you sure you want to permanently delete ${orderIds.length} orders? This action cannot be undone.`,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, delete them!',
                cancelButtonText: 'Cancel',
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
            }).then((result) => {
                if (result.isConfirmed) {
                    this.performBulkDelete(orderIds);
                }
            });
        }
    },

    /**
     * Perform bulk delete
     * @param {Array} orderIds - Array of order IDs
     */
    performBulkDelete(orderIds) {
        const bulkDeleteBtn = document.getElementById('bulk-delete-btn');
        const originalText = bulkDeleteBtn.innerHTML;
        bulkDeleteBtn.disabled = true;
        bulkDeleteBtn.innerHTML = '<div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin me-1" role="status" data-spinner></div>Deleting...';

        fetch('/store/admin/orders/bulk-delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify({
                order_ids: orderIds
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Orders Deleted!',
                        text: data.message
                    }).then(() => {
                        window.location.reload();
                    });
                } else {
                    window.location.reload();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Delete Failed',
                        text: data.message
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'An error occurred while deleting the orders.'
                });
            }
        })
        .finally(() => {
            bulkDeleteBtn.disabled = false;
            bulkDeleteBtn.innerHTML = originalText;
        });
    },

    /**
     * Setup season reset functionality using event delegation
     */
    setupSeasonReset() {
        const self = this;

        // Delegated click handler for confirm reset button
        document.addEventListener('click', (e) => {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            if (!e.target.closest('#confirmResetBtn')) return;

            const resetTypeInput = document.querySelector('input[name="resetType"]:checked');
            const resetType = resetTypeInput ? resetTypeInput.value : 'all';
            const modalEl = document.getElementById('resetOrderingModal');
            const modal = modalEl?._flowbiteModal || null;

            const actionText = resetType === 'all'
                ? 'delete all orders for the current season'
                : 'reset ordering eligibility for the current season';

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Confirm Reset',
                    text: `Are you sure you want to ${actionText}? This action cannot be undone.`,
                    icon: 'warning',
                    showCancelButton: true,
                    confirmButtonText: 'Yes, reset it!',
                    cancelButtonText: 'Cancel',
                    confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffc107'
                }).then((result) => {
                    if (result.isConfirmed) {
                        self.performSeasonReset(resetType, modal);
                    }
                });
            }
        });
    },

    /**
     * Perform season reset
     * @param {string} resetType - Reset type ('all' or 'eligibility')
     * @param {Object} modal - Bootstrap modal instance
     */
    performSeasonReset(resetType, modal) {
        const confirmResetBtn = document.getElementById('confirmResetBtn');
        const originalText = confirmResetBtn.innerHTML;
        confirmResetBtn.disabled = true;
        confirmResetBtn.innerHTML = '<div class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin me-1" role="status" data-spinner></div>Resetting...';

        fetch('/store/admin/reset-season-ordering', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify({
                reset_type: resetType
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Season Reset Complete!',
                        text: data.message
                    }).then(() => {
                        if (modal) modal.hide();
                        window.location.reload();
                    });
                } else {
                    if (modal) modal.hide();
                    window.location.reload();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Reset Failed',
                        text: data.message
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'An error occurred while resetting season ordering.'
                });
            }
        })
        .finally(() => {
            confirmResetBtn.disabled = false;
            confirmResetBtn.innerHTML = originalText;
        });
    },

    /**
     * Setup order deletion handlers
     */
    setupOrderDeletion() {
        document.addEventListener('click', (e) => {
            // Guard: ensure e.target is an Element with closest method
            if (!e.target || typeof e.target.closest !== 'function') return;
            const deleteBtn = e.target.closest('[data-action="delete-order"]');
            if (!deleteBtn) return;

            e.preventDefault();
            const orderId = deleteBtn.getAttribute('data-order-id');
            const orderInfo = deleteBtn.getAttribute('data-order-info');
            const customerName = deleteBtn.getAttribute('data-customer-name');

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Delete Order',
                    text: `Are you sure you want to delete ${orderInfo} from ${customerName}? This action cannot be undone.`,
                    icon: 'warning',
                    showCancelButton: true,
                    confirmButtonText: 'Yes, delete it!',
                    cancelButtonText: 'Cancel',
                    confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
                }).then((result) => {
                    if (result.isConfirmed) {
                        this.performSingleDelete(orderId);
                    }
                });
            }
        });
    },

    /**
     * Perform single order delete
     * @param {string} orderId - Order ID to delete
     */
    performSingleDelete(orderId) {
        fetch(`/store/admin/order/${orderId}/delete`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Order Deleted!',
                        text: data.message
                    }).then(() => {
                        window.location.reload();
                    });
                } else {
                    window.location.reload();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Delete Failed',
                        text: data.message
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'An error occurred while deleting the order.'
                });
            }
        });
    }
};

// Register with window.InitSystem
window.InitSystem.register('store-admin', () => {
    // Only initialize on store admin page
    if (document.querySelector('[data-component="store-items-table"]') ||
        document.querySelector('[data-component="orders-table"]')) {
        StoreAdmin.init();
    }
}, {
    priority: 40,
    description: 'Store admin page functionality',
    reinitializable: false
});

// Export for direct use
export { StoreAdmin };
