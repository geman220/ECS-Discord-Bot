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

// ============================================================================
// PLAYER ELIGIBILITY
// ============================================================================

/**
 * Check player eligibility and show modal
 */
EventDelegation.register('check-player-eligibility', (element, event) => {
    event.preventDefault();
    const playerId = element.dataset.playerId;

    if (!playerId) return;

    const modalBody = document.getElementById('eligibilityModalBody');

    if (typeof ModalManager !== 'undefined') {
        ModalManager.show('eligibilityModal');
    } else if (typeof bootstrap !== 'undefined') {
        const modal = new bootstrap.Modal(document.getElementById('eligibilityModal'));
        modal.show();
    }

    // Construct the URL by replacing 0 with the actual player ID
    const baseUrl = window.location.origin;
    const url = `${baseUrl}/admin/wallet/check-eligibility/${playerId}`;

    fetch(url)
        .then(response => response.json())
        .then(data => {
            let html = `
                <div class="mb-3">
                    <h6 class="mb-0">${data.player_name}</h6>
                    <small class="text-muted">Player ID: ${data.player_id}</small>
                </div>

                <div class="alert alert-${data.eligible ? 'success' : 'warning'} d-flex align-items-center" data-alert>
                    <i class="ti ti-${data.eligible ? 'circle-check' : 'alert-triangle'} me-2 fs-4"></i>
                    <div>
                        <strong>${data.eligible ? 'Eligible for Wallet Pass' : 'Not Currently Eligible'}</strong>
                        <p class="mb-0 small">${data.eligible ? 'This player meets all requirements.' : 'See issues below.'}</p>
                    </div>
                </div>
            `;

            if (data.issues && data.issues.length > 0) {
                html += '<h6 class="mt-3 mb-2">Issues to Resolve:</h6><ul class="list-unstyled mb-0">';
                data.issues.forEach(issue => {
                    html += `<li class="text-danger mb-2"><i class="ti ti-x me-2"></i>${issue}</li>`;
                });
                html += '</ul>';
            }

            if (data.info) {
                html += `
                    <hr class="my-3">
                    <h6 class="mb-2">Player Details</h6>
                    <div class="row g-2">
                        <div class="col-6">
                            <small class="text-muted d-block">Status</small>
                            <span class="badge ${data.info.is_current_player ? 'bg-success' : 'bg-secondary'}" data-badge>${data.info.is_current_player ? 'Active' : 'Inactive'}</span>
                        </div>
                        <div class="col-6">
                            <small class="text-muted d-block">User Account</small>
                            <span class="badge ${data.info.has_user_account ? 'bg-success' : 'bg-secondary'}" data-badge>${data.info.has_user_account ? 'Yes' : 'No'}</span>
                        </div>
                        <div class="col-6">
                            <small class="text-muted d-block">Primary Team</small>
                            <span>${data.info.primary_team || '<em class="text-muted">None</em>'}</span>
                        </div>
                        <div class="col-6">
                            <small class="text-muted d-block">League</small>
                            <span>${data.info.league || '<em class="text-muted">None</em>'}</span>
                        </div>
                    </div>
                `;
            }

            if (modalBody) modalBody.innerHTML = html;
        })
        .catch(error => {
            if (modalBody) {
                modalBody.innerHTML = '<div class="alert alert-danger" data-alert><i class="ti ti-alert-circle me-2"></i>Error checking eligibility. Please try again.</div>';
            }
        });
});

/**
 * Bulk generate wallet passes
 */
EventDelegation.register('bulk-generate-wallet-passes', (element, event) => {
    event.preventDefault();

    if (!confirm('Generate passes for all eligible players?\n\nThis will create passes that can be downloaded by each player. Continue?')) {
        return;
    }

    // Get eligible player IDs from the data attribute or collect from table
    let eligiblePlayerIds = [];

    // Try to get from data attribute first
    const idsAttr = element.dataset.playerIds;
    if (idsAttr) {
        try {
            eligiblePlayerIds = JSON.parse(idsAttr);
        } catch (e) {
            console.error('Failed to parse player IDs:', e);
        }
    }

    // If no IDs found, try to collect from table checkboxes or rows
    if (eligiblePlayerIds.length === 0) {
        const table = document.querySelector('.c-table tbody');
        if (table) {
            table.querySelectorAll('tr').forEach(row => {
                // Look for player ID in various places
                const idCell = row.querySelector('td small');
                if (idCell && idCell.textContent.includes('ID:')) {
                    const idMatch = idCell.textContent.match(/ID:\s*(\d+)/);
                    if (idMatch) {
                        eligiblePlayerIds.push(parseInt(idMatch[1]));
                    }
                }
            });
        }
    }

    if (eligiblePlayerIds.length === 0) {
        alert('No eligible players found.');
        return;
    }

    // Show loading state
    const originalText = element.innerHTML;
    element.disabled = true;
    element.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Generating...';

    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

    fetch('/admin/wallet/generate-bulk-passes', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ player_ids: eligiblePlayerIds })
    })
    .then(response => response.json())
    .then(data => {
        element.disabled = false;
        element.innerHTML = originalText;

        let message = `Bulk Generation Complete\n\n`;
        message += `Success: ${data.success?.length || 0} passes\n`;
        message += `Failed: ${data.failed?.length || 0} passes`;

        if (data.failed && data.failed.length > 0) {
            message += '\n\nFailed:\n';
            data.failed.slice(0, 5).forEach(failure => {
                message += `- ${failure.player_name || 'Player ' + failure.player_id}: ${failure.error}\n`;
            });
            if (data.failed.length > 5) {
                message += `...and ${data.failed.length - 5} more`;
            }
        }

        alert(message);
        if (data.success && data.success.length > 0) {
            location.reload();
        }
    })
    .catch(error => {
        element.disabled = false;
        element.innerHTML = originalText;
        alert('Error during bulk generation. Please try again.');
    });
});

/**
 * Reload page action
 */
EventDelegation.register('reload-page', (element, event) => {
    event.preventDefault();
    location.reload();
});

console.log('[EventDelegation] Admin wallet handlers loaded');
