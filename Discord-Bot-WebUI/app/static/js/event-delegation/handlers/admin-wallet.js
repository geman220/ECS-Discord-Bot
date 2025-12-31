/**
 * Admin Wallet Pass Management Handlers
 *
 * Event delegation handlers for wallet pass administration:
 * - Void/reactivate passes
 * - Bulk operations
 * - Copy download links
 * - Filter operations
 */

import { EventDelegation } from '../core.js';

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Get CSRF token from meta tag
 */
function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

/**
 * Show notification using Swal if available
 */
function showNotification(title, message, type = 'info') {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: title,
            text: message,
            icon: type,
            timer: type === 'success' ? 2000 : undefined,
            showConfirmButton: type !== 'success'
        });
    } else {
        alert(`${title}: ${message}`);
    }
}

/**
 * Show toast notification
 */
function showToast(title, type = 'success') {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            toast: true,
            position: 'top-end',
            icon: type,
            title: title,
            showConfirmButton: false,
            timer: 2000
        });
    }
}

// ============================================================================
// SINGLE PASS ACTIONS
// ============================================================================

/**
 * Void a single pass (from detail page)
 */
EventDelegation.register('void-pass', (element, event) => {
    event.preventDefault();
    const passId = element.dataset.passId;

    if (typeof Swal === 'undefined') {
        console.error('SweetAlert2 not loaded');
        return;
    }

    Swal.fire({
        title: 'Void This Pass?',
        html: '<p class="mb-3">The member will no longer be able to use this pass for check-ins.</p><input id="void-reason" class="form-control" placeholder="Reason for voiding (optional)" data-form-control>',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: '<i class="ti ti-ban me-1"></i>Void Pass',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            const reason = document.getElementById('void-reason')?.value || 'Voided by admin';
            const url = passId ? `/admin/wallet/api/passes/${passId}/void` : window.location.pathname.replace('/detail', '/api/passes') + '/void';

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reason: reason })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    Swal.fire('Pass Voided', 'The pass has been marked as invalid.', 'success')
                        .then(() => location.reload());
                } else {
                    Swal.fire('Error', data.error || 'Failed to void pass', 'error');
                }
            })
            .catch(err => Swal.fire('Error', 'Failed to void pass. Please try again.', 'error'));
        }
    });
});

/**
 * Reactivate a single pass (from detail page)
 */
EventDelegation.register('reactivate-pass', (element, event) => {
    event.preventDefault();
    const passId = element.dataset.passId;

    if (typeof Swal === 'undefined') {
        console.error('SweetAlert2 not loaded');
        return;
    }

    Swal.fire({
        title: 'Reactivate This Pass?',
        text: 'The pass will become valid again and can be used for check-ins.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28a745',
        confirmButtonText: '<i class="ti ti-refresh me-1"></i>Reactivate',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            const url = passId ? `/admin/wallet/api/passes/${passId}/reactivate` : window.location.pathname.replace('/detail', '/api/passes') + '/reactivate';

            fetch(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    Swal.fire('Pass Reactivated', 'The pass is now active and valid.', 'success')
                        .then(() => location.reload());
                } else {
                    Swal.fire('Error', data.error || 'Failed to reactivate pass', 'error');
                }
            })
            .catch(err => Swal.fire('Error', 'Failed to reactivate pass. Please try again.', 'error'));
        }
    });
});

/**
 * Copy download link to clipboard
 */
EventDelegation.register('copy-link', (element, event) => {
    event.preventDefault();
    const linkInput = document.getElementById('download-link');
    if (linkInput) {
        linkInput.select();
        document.execCommand('copy');
        showToast('Link copied to clipboard!');
    }
});

// ============================================================================
// FILTER OPERATIONS
// ============================================================================

/**
 * Filter by status (dropdown change)
 */
EventDelegation.register('filter-by-value', (element, event) => {
    const param = element.dataset.param || 'status';
    const value = element.value;
    const url = new URL(window.location);
    url.searchParams.set(param, value);
    window.location = url;
});

// ============================================================================
// BULK SELECTION OPERATIONS
// ============================================================================

/**
 * Toggle select all checkboxes
 */
EventDelegation.register('toggle-select-all', (element, event) => {
    const target = element.dataset.target || '.pass-checkbox';
    const checkboxes = document.querySelectorAll(target);
    checkboxes.forEach(cb => cb.checked = element.checked);
    updateBulkActionsBar();
});

/**
 * Update selection count when individual checkbox changes
 */
EventDelegation.register('update-selection', (element, event) => {
    updateBulkActionsBar();
});

/**
 * Clear all selections
 */
EventDelegation.register('clear-pass-selection', (element, event) => {
    event.preventDefault();
    const checkboxes = document.querySelectorAll('.pass-checkbox');
    checkboxes.forEach(cb => cb.checked = false);
    const selectAll = document.getElementById('selectAll');
    if (selectAll) selectAll.checked = false;
    updateBulkActionsBar();
});

/**
 * Helper to update bulk actions bar visibility
 */
function updateBulkActionsBar() {
    const checkboxes = document.querySelectorAll('.pass-checkbox:checked');
    const count = checkboxes.length;
    const bar = document.getElementById('bulkActionsBar');
    const countSpan = document.getElementById('selectedCount');

    if (bar) {
        if (count > 0) {
            bar.classList.remove('d-none');
            if (countSpan) countSpan.textContent = count;
        } else {
            bar.classList.add('d-none');
        }
    }
}

/**
 * Get IDs of selected passes
 */
function getSelectedIds() {
    const checkboxes = document.querySelectorAll('.pass-checkbox:checked');
    return Array.from(checkboxes).map(cb => parseInt(cb.value));
}

// ============================================================================
// BULK VOID/REACTIVATE OPERATIONS
// ============================================================================

/**
 * Open bulk void modal
 */
EventDelegation.register('bulk-void-passes', (element, event) => {
    event.preventDefault();
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    const voidCountEl = document.getElementById('voidCount');
    if (voidCountEl) voidCountEl.textContent = ids.length;

    if (typeof ModalManager !== 'undefined') {
        ModalManager.show('bulkVoidModal');
    } else if (typeof bootstrap !== 'undefined') {
        const modal = new bootstrap.Modal(document.getElementById('bulkVoidModal'));
        modal.show();
    }
});

/**
 * Confirm bulk void
 */
EventDelegation.register('confirm-bulk-void', (element, event) => {
    event.preventDefault();
    const ids = getSelectedIds();
    const reason = document.getElementById('voidReason')?.value || 'Bulk voided by admin';

    fetch('/admin/wallet/api/passes/bulk-void', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pass_ids: ids, reason: reason })
    })
    .then(response => response.json())
    .then(data => {
        const modal = document.getElementById('bulkVoidModal');
        if (modal && typeof bootstrap !== 'undefined') {
            bootstrap.Modal.getInstance(modal)?.hide();
        }
        showNotification('Bulk Void Complete', `Voided ${data.success?.length || 0} passes. ${data.failed?.length || 0} failed.`, 'success');
        location.reload();
    })
    .catch(err => showNotification('Error', 'Error voiding passes. Please try again.', 'error'));
});

/**
 * Bulk reactivate passes
 */
EventDelegation.register('bulk-reactivate-passes', (element, event) => {
    event.preventDefault();
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    if (!confirm(`Are you sure you want to reactivate ${ids.length} passes?`)) return;

    fetch('/admin/wallet/api/passes/bulk-reactivate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pass_ids: ids })
    })
    .then(response => response.json())
    .then(data => {
        showNotification('Bulk Reactivate Complete', `Reactivated ${data.success?.length || 0} passes. ${data.failed?.length || 0} failed.`, 'success');
        location.reload();
    })
    .catch(err => showNotification('Error', 'Error reactivating passes. Please try again.', 'error'));
});

// ============================================================================
// BULK GENERATE OPERATIONS
// ============================================================================

/**
 * Handle pass type change in bulk generate modal
 */
EventDelegation.register('bulk-pass-type-change', (element, event) => {
    const yearField = document.getElementById('yearField');
    const seasonField = document.getElementById('seasonField');

    if (element.value === 'pub_league') {
        if (yearField) yearField.classList.add('d-none');
        if (seasonField) seasonField.classList.remove('d-none');
    } else {
        if (yearField) yearField.classList.remove('d-none');
        if (seasonField) seasonField.classList.add('d-none');
    }
});

/**
 * Bulk generate passes
 */
EventDelegation.register('bulk-generate-passes', (element, event) => {
    event.preventDefault();
    const passType = document.getElementById('bulkPassType')?.value;
    const year = document.getElementById('bulkYear')?.value;
    const seasonName = document.getElementById('bulkSeasonName')?.value;
    const btn = element;
    const resultsDiv = document.getElementById('bulkGenerateResults');
    const resultsContent = document.getElementById('bulkResultsContent');

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Generating...';

    fetch('/admin/wallet/api/passes/bulk-generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            pass_type: passType,
            year: parseInt(year),
            season_name: seasonName
        })
    })
    .then(response => response.json())
    .then(data => {
        btn.disabled = false;
        btn.innerHTML = '<i class="ti ti-bolt me-1"></i>Generate Passes';

        if (resultsDiv) resultsDiv.classList.remove('d-none');

        if (data.error) {
            if (resultsContent) resultsContent.innerHTML = `<div class="alert alert-danger" data-alert>${data.error}</div>`;
            return;
        }

        let html = `
            <div class="mb-2"><strong>Total eligible:</strong> ${data.total_eligible}</div>
            <div class="mb-2 text-success"><i class="ti ti-check me-1"></i><strong>Created:</strong> ${data.success?.length || 0}</div>
            <div class="mb-2 text-info"><i class="ti ti-minus me-1"></i><strong>Skipped (already have pass):</strong> ${data.skipped?.length || 0}</div>
            <div class="mb-2 text-danger"><i class="ti ti-x me-1"></i><strong>Failed:</strong> ${data.failed?.length || 0}</div>
        `;

        if (data.failed?.length > 0) {
            html += '<details class="mt-2"><summary class="text-danger">View failures</summary><ul class="small mt-2">';
            data.failed.forEach(f => {
                html += `<li>${f.player_name || f.player_id}: ${f.error}</li>`;
            });
            html += '</ul></details>';
        }

        if (resultsContent) resultsContent.innerHTML = html;
    })
    .catch(err => {
        btn.disabled = false;
        btn.innerHTML = '<i class="ti ti-bolt me-1"></i>Generate Passes';
        if (resultsContent) resultsContent.innerHTML = `<div class="alert alert-danger" data-alert>Error generating passes. Please try again.</div>`;
        if (resultsDiv) resultsDiv.classList.remove('d-none');
    });
});

console.log('[EventDelegation] Admin wallet handlers loaded');
