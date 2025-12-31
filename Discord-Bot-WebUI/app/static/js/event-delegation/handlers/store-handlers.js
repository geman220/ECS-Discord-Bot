import { EventDelegation } from '../core.js';
import { ModalManager } from '../../modal-manager.js';

/**
 * Store Management Action Handlers
 * Handles store items, orders, and analytics management
 */

// ============================================================================
// STORE ITEM MANAGEMENT
// ============================================================================

/**
 * Toggle Item Availability
 * Toggles whether a store item is available for purchase
 */
EventDelegation.register('toggle-item-availability', function(element, e) {
    e.preventDefault();

    const itemId = element.dataset.itemId;
    const currentState = element.dataset.available === 'true';

    if (!itemId) {
        console.error('[toggle-item-availability] Missing item ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/store/items/${itemId}/toggle`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ available: !currentState })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update button state
            element.dataset.available = (!currentState).toString();
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Item updated', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to update item');
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
 * Edit Store Item
 * Opens edit modal for a store item
 */
EventDelegation.register('edit-store-item', function(element, e) {
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
EventDelegation.register('delete-store-item', function(element, e) {
    e.preventDefault();

    const itemId = element.dataset.itemId;
    const itemName = element.dataset.itemName || 'this item';

    if (!itemId) {
        console.error('[delete-store-item] Missing item ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        if (!confirm(`Delete "${itemName}"?`)) return;
        performDeleteStoreItem(itemId, element);
        return;
    }

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

/**
 * Duplicate Store Item
 * Creates a copy of an existing store item
 */
EventDelegation.register('duplicate-store-item', function(element, e) {
    e.preventDefault();

    const itemId = element.dataset.itemId;

    if (!itemId) {
        console.error('[duplicate-store-item] Missing item ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/store/items/${itemId}/duplicate`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Item Duplicated',
                    text: 'A copy of the item has been created',
                    timer: 2000,
                    showConfirmButton: false
                }).then(() => location.reload());
            } else {
                location.reload();
            }
        } else {
            throw new Error(data.error || 'Failed to duplicate item');
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

// ============================================================================
// ORDER MANAGEMENT
// ============================================================================

/**
 * View Order Details
 * Opens modal showing order details
 */
EventDelegation.register('view-order-details', function(element, e) {
    e.preventDefault();

    const orderId = element.dataset.orderId;

    if (!orderId) {
        console.error('[view-order-details] Missing order ID');
        return;
    }

    if (typeof window.viewOrderDetails === 'function') {
        window.viewOrderDetails(orderId);
    } else {
        // Fallback: open in new window
        window.open(`/admin-panel/store/orders/${orderId}`, '_blank');
    }
});

/**
 * Update Order Status
 * Changes the status of an order
 */
EventDelegation.register('update-order-status', function(element, e) {
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

    fetch(`/admin-panel/store/orders/${orderId}/status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ status: newStatus })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Order updated', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to update order');
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
 * Mark Order Fulfilled
 * Marks an order as fulfilled
 */
EventDelegation.register('fulfill-order', function(element, e) {
    e.preventDefault();

    const orderId = element.dataset.orderId;

    if (!orderId) {
        console.error('[fulfill-order] Missing order ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        if (!confirm('Mark this order as fulfilled?')) return;
        performFulfillOrder(orderId, element);
        return;
    }

    window.Swal.fire({
        title: 'Fulfill Order',
        text: 'Mark this order as fulfilled?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Fulfill',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('success') : '#28a745'
    }).then((result) => {
        if (result.isConfirmed) {
            performFulfillOrder(orderId, element);
        }
    });
});

function performFulfillOrder(orderId, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/store/orders/${orderId}/fulfill`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Order Fulfilled',
                    timer: 1500,
                    showConfirmButton: false
                }).then(() => location.reload());
            } else {
                location.reload();
            }
        } else {
            throw new Error(data.error || 'Failed to fulfill order');
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

/**
 * Cancel Order
 * Cancels an order with confirmation
 */
EventDelegation.register('cancel-order', function(element, e) {
    e.preventDefault();

    const orderId = element.dataset.orderId;

    if (!orderId) {
        console.error('[cancel-order] Missing order ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        if (!confirm('Cancel this order?')) return;
        performCancelOrder(orderId, element);
        return;
    }

    window.Swal.fire({
        title: 'Cancel Order',
        text: 'Are you sure you want to cancel this order?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Cancel Order',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            performCancelOrder(orderId, element);
        }
    });
});

function performCancelOrder(orderId, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/store/orders/${orderId}/cancel`, {
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
                window.AdminPanel.showMobileToast('Order cancelled', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to cancel order');
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

/**
 * Resend Order Confirmation
 * Resends order confirmation email
 */
EventDelegation.register('resend-order-confirmation', function(element, e) {
    e.preventDefault();

    const orderId = element.dataset.orderId;

    if (!orderId) {
        console.error('[resend-order-confirmation] Missing order ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/store/orders/${orderId}/resend-confirmation`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Email Sent',
                    text: 'Order confirmation has been resent',
                    timer: 2000,
                    showConfirmButton: false
                });
            }
        } else {
            throw new Error(data.error || 'Failed to send confirmation');
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

// ============================================================================
// STORE ANALYTICS
// ============================================================================

/**
 * Export Analytics
 * Exports store analytics data
 */
EventDelegation.register('export-store-analytics', function(element, e) {
    e.preventDefault();

    const format = element.dataset.format || 'csv';
    const dateRange = element.dataset.dateRange || 'all';

    window.location.href = `/admin-panel/store/analytics/export?format=${format}&range=${dateRange}`;
});

/**
 * Refresh Analytics
 * Refreshes analytics dashboard
 */
EventDelegation.register('refresh-store-analytics', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

/**
 * Change Date Range
 * Changes analytics date range filter
 */
EventDelegation.register('change-analytics-range', function(element, e) {
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
EventDelegation.register('preview-item-image', function(element, e) {
    const file = element.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = function(e) {
        const preview = document.getElementById('item-image-preview');
        if (preview) {
            preview.src = e.target.result;
            preview.classList.remove('d-none');
        }
    };
    reader.readAsDataURL(file);
});

/**
 * Remove Item Image
 * Removes the current item image
 */
EventDelegation.register('remove-item-image', function(element, e) {
    e.preventDefault();

    const preview = document.getElementById('item-image-preview');
    const input = document.getElementById('item-image-input');
    const removeFlag = document.getElementById('remove-image-flag');

    if (preview) preview.classList.add('d-none');
    if (input) input.value = '';
    if (removeFlag) removeFlag.value = 'true';
});

/**
 * Add Item Variant
 * Adds a new variant option to the item
 */
EventDelegation.register('add-item-variant', function(element, e) {
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
EventDelegation.register('remove-item-variant', function(element, e) {
    e.preventDefault();

    const variantIndex = element.dataset.variantIndex;
    const variantRow = element.closest('.variant-row');

    if (variantRow) {
        variantRow.remove();
    }
});

// ============================================================================

console.log('[EventDelegation] Store handlers loaded');
