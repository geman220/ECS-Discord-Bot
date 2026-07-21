import { EventDelegation } from '../core.js';
import { ModalManager } from '../../modal-manager.js';
import { escapeHtml } from '../../utils/sanitize.js';

/**
 * Store Management Action Handlers
 * Handles store items, orders, and analytics management
 */

// ============================================================================
// STORE ITEM MANAGEMENT
// ============================================================================

/**
 * Edit Store Item
 * Opens edit modal for a store item
 */
window.EventDelegation.register('edit-store-item', function(element, e) {
    e.preventDefault();

    const itemId = element.dataset.itemId;

    if (!itemId) {
        console.error('[edit-store-item] Missing item ID');
        return;
    }

    // Redirect to edit page or open modal
    if (typeof window.editStoreItem === 'function') {
        window.editStoreItem(itemId);
    } else {
        window.location.href = `/admin-panel/store/items/${itemId}/edit`;
    }
});

/**
 * Delete Store Item
 * Deletes a store item with confirmation
 */
window.EventDelegation.register('delete-store-item', function(element, e) {
    e.preventDefault();

    const itemId = element.dataset.itemId;
    const itemName = element.dataset.itemName || 'this item';

    if (!itemId) {
        console.error('[delete-store-item] Missing item ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Delete Item',
            text: `Are you sure you want to delete "${itemName}"? This cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Delete',
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                performDeleteStoreItem(itemId, element);
            }
        });
    }
});

function performDeleteStoreItem(itemId, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/store/items/${itemId}/delete`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Item deleted', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to delete item');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
}

// ============================================================================
// ORDER MANAGEMENT
// ============================================================================

/**
 * View Order Details
 * Opens modal showing order details
 */
window.EventDelegation.register('view-order-details', function(element, e) {
    e.preventDefault();

    const orderId = element.dataset.orderId;

    if (!orderId) {
        console.error('[view-order-details] Missing order ID');
        return;
    }

    if (typeof window.viewOrderDetails === 'function') {
        window.viewOrderDetails(orderId);
        return;
    }

    fetch(`/admin-panel/store/orders/${orderId}/details`, {
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            throw new Error(data.message || 'Failed to load order details');
        }
        const o = data.order;
        const row = (label, value) => value
            ? `<div class="flex justify-between gap-3 py-1 text-left">
                 <span class="text-gray-500 dark:text-gray-400">${label}</span>
                 <span class="font-semibold text-right">${escapeHtml(String(value))}</span>
               </div>`
            : '';
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: `Order #${escapeHtml(String(o.id))}`,
                html: [
                    row('Item', o.item_name),
                    row('Ordered by', o.orderer_name),
                    row('Quantity', o.quantity),
                    row('Color', o.selected_color),
                    row('Size', o.selected_size),
                    row('Status', o.status),
                    row('Ordered', o.order_date),
                    row('Processed', o.processed_date),
                    row('Delivered', o.delivered_date),
                    row('Processed by', o.processor_name),
                    row('Season', o.season_name),
                    row('Notes', o.notes)
                ].join(''),
                confirmButtonText: 'Close'
            });
        }
    })
    .catch(error => {
        console.error('[view-order-details] ', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message || 'Failed to load order details', 'error');
        }
    });
});

/**
 * Update Order Status
 * Changes the status of an order
 */
window.EventDelegation.register('update-order-status', function(element, e) {
    e.preventDefault();

    const orderId = element.dataset.orderId;
    const newStatus = element.dataset.newStatus;

    if (!orderId || !newStatus) {
        console.error('[update-order-status] Missing order ID or status');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/store/orders/${orderId}/update-status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken
        },
        body: new URLSearchParams({ status: newStatus })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast(data.message || 'Order updated', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.message || 'Failed to update order');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

/**
 * Store Order Status (legacy /store/admin page)
 * Change handler for the status <select> rows; posts to the store blueprint's
 * own update route (always returns JSON). Bind with data-on-change.
 */
window.EventDelegation.register('store-order-status', function(element) {
    const orderId = element.dataset.orderId;
    const newStatus = element.value;
    const previousStatus = element.dataset.currentStatus;

    if (!orderId || !newStatus) {
        return;
    }

    element.disabled = true;
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/store/admin/order/${orderId}/update`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken
        },
        body: new URLSearchParams({ status: newStatus })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            element.dataset.currentStatus = newStatus;
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast(data.message || 'Order updated', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.message || 'Failed to update order');
        }
    })
    .catch(error => {
        if (previousStatus) element.value = previousStatus;
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message || 'Failed to update order', 'error');
        }
    })
    .finally(() => {
        element.disabled = false;
    });
});

// ============================================================================
// STORE ANALYTICS
// ============================================================================

/**
 * Refresh Analytics
 * Refreshes analytics dashboard
 */
window.EventDelegation.register('refresh-store-analytics', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

/**
 * Change Date Range
 * Changes analytics date range filter
 */
window.EventDelegation.register('change-analytics-range', function(element, e) {
    const range = element.value || element.dataset.range;

    if (!range) {
        console.error('[change-analytics-range] Missing range');
        return;
    }

    const url = new URL(window.location);
    url.searchParams.set('range', range);
    window.location.href = url.toString();
});

// ============================================================================
// ITEM FORM
// ============================================================================

/**
 * Preview Item Image
 * Shows preview of uploaded item image
 */
window.EventDelegation.register('preview-item-image', function(element, e) {
    const file = element.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const preview = document.getElementById('item-image-preview');
        if (preview) {
            preview.src = e.target.result;
            preview.classList.remove('hidden');
        }
    };
    reader.readAsDataURL(file);
});

/**
 * Remove Item Image
 * Removes the current item image
 */
window.EventDelegation.register('remove-item-image', function(element, e) {
    e.preventDefault();

    const preview = document.getElementById('item-image-preview');
    const input = document.getElementById('item-image-input');
    const removeFlag = document.getElementById('remove-image-flag');

    if (preview) preview.classList.add('hidden');
    if (input) input.value = '';
    if (removeFlag) removeFlag.value = 'true';
});

/**
 * Add Item Variant
 * Adds a new variant option to the item
 */
window.EventDelegation.register('add-item-variant', function(element, e) {
    e.preventDefault();

    if (typeof window.addItemVariant === 'function') {
        window.addItemVariant();
    } else {
        console.error('[add-item-variant] addItemVariant function not available');
    }
});

/**
 * Remove Item Variant
 * Removes a variant option from the item
 */
window.EventDelegation.register('remove-item-variant', function(element, e) {
    e.preventDefault();

    const variantIndex = element.dataset.variantIndex;
    const variantRow = element.closest('.variant-row');

    if (variantRow) {
        variantRow.remove();
    }
});

// ============================================================================

// Handlers loaded
