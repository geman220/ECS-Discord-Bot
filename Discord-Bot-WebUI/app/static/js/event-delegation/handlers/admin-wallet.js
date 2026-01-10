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
import { escapeHtml } from '../../utils/sanitize.js';
import { showToast as toastServiceShowToast } from '../../services/toast-service.js';

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
 * Show notification using window.Swal if available
 */
function showNotification(title, message, type = 'info') {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: title,
            text: message,
            icon: type,
            timer: type === 'success' ? 2000 : undefined,
            showConfirmButton: type !== 'success'
        });
    }
}

// showToast imported from services/toast-service.js
function showToast(message, type = 'success') {
    toastServiceShowToast(message, type);
}

// ============================================================================
// SINGLE PASS ACTIONS
// ============================================================================

/**
 * Void a single pass (from detail page)
 */
window.EventDelegation.register('void-pass', (element, event) => {
    event.preventDefault();
    const passId = element.dataset.passId;

    if (typeof window.Swal === 'undefined') {
        console.error('SweetAlert2 not loaded');
        return;
    }

    window.Swal.fire({
        title: 'Void This Pass?',
        html: '<p class="mb-3">The member will no longer be able to use this pass for check-ins.</p><input id="void-reason" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="Reason for voiding (optional)" data-form-control>',
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
                    window.Swal.fire('Pass Voided', 'The pass has been marked as invalid.', 'success')
                        .then(() => location.reload());
                } else {
                    window.Swal.fire('Error', data.error || 'Failed to void pass', 'error');
                }
            })
            .catch(err => window.Swal.fire('Error', 'Failed to void pass. Please try again.', 'error'));
        }
    });
});

/**
 * Reactivate a single pass (from detail page)
 */
window.EventDelegation.register('reactivate-pass', (element, event) => {
    event.preventDefault();
    const passId = element.dataset.passId;

    if (typeof window.Swal === 'undefined') {
        console.error('SweetAlert2 not loaded');
        return;
    }

    window.Swal.fire({
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
                    window.Swal.fire('Pass Reactivated', 'The pass is now active and valid.', 'success')
                        .then(() => location.reload());
                } else {
                    window.Swal.fire('Error', data.error || 'Failed to reactivate pass', 'error');
                }
            })
            .catch(err => window.Swal.fire('Error', 'Failed to reactivate pass. Please try again.', 'error'));
        }
    });
});

/**
 * Copy download link to clipboard
 */
window.EventDelegation.register('copy-link', (element, event) => {
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
 * Note: filter-by-value is handled by form-actions.js (generic implementation)
 * Use data-param="status" in the HTML to specify the query parameter name
 */
// Removed duplicate registration - form-actions.js handles filter-by-value

// ============================================================================
// BULK SELECTION OPERATIONS
// ============================================================================

/**
 * Toggle select all checkboxes
 * Note: toggle-select-all is handled by form-actions.js (generic implementation)
 * Use data-target=".pass-checkbox" in the HTML to specify checkbox selector
 * Wallet-specific: also update bulk actions bar on change
 */
// Removed duplicate registration - form-actions.js handles toggle-select-all

/**
 * Update selection count when individual checkbox changes
 * Note: update-selection is handled by form-actions.js
 * For wallet-specific bulk actions bar, use data-bar="#bulkActionsBar"
 */
// Removed duplicate registration - form-actions.js handles update-selection

/**
 * Clear all selections
 */
window.EventDelegation.register('clear-pass-selection', (element, event) => {
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
            bar.classList.remove('hidden');
            if (countSpan) countSpan.textContent = count;
        } else {
            bar.classList.add('hidden');
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
window.EventDelegation.register('bulk-void-passes', (element, event) => {
    event.preventDefault();
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    const voidCountEl = document.getElementById('voidCount');
    if (voidCountEl) voidCountEl.textContent = ids.length;

    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('bulkVoidModal');
    } else if (typeof window.Modal !== 'undefined') {
        const modalEl = document.getElementById('bulkVoidModal');
        const modal = modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
        modal.show();
    }
});

/**
 * Confirm bulk void
 */
window.EventDelegation.register('confirm-bulk-void', (element, event) => {
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
        if (modal && modal._flowbiteModal) {
            modal._flowbiteModal.hide();
        }
        showNotification('Bulk Void Complete', `Voided ${data.success?.length || 0} passes. ${data.failed?.length || 0} failed.`, 'success');
        location.reload();
    })
    .catch(err => showNotification('Error', 'Error voiding passes. Please try again.', 'error'));
});

/**
 * Bulk reactivate passes
 */
window.EventDelegation.register('bulk-reactivate-passes', (element, event) => {
    event.preventDefault();
    const ids = getSelectedIds();
    if (ids.length === 0) return;

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Reactivate Passes?',
            text: `Are you sure you want to reactivate ${ids.length} passes?`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, reactivate',
            confirmButtonColor: '#28a745'
        }).then((result) => {
            if (result.isConfirmed) {
                performBulkReactivate(ids);
            }
        });
    }
});

function performBulkReactivate(ids) {
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
}

// ============================================================================
// BULK GENERATE OPERATIONS
// ============================================================================

/**
 * Handle pass type change in bulk generate modal
 */
window.EventDelegation.register('bulk-pass-type-change', (element, event) => {
    const yearField = document.getElementById('yearField');
    const seasonField = document.getElementById('seasonField');

    if (element.value === 'pub_league') {
        if (yearField) yearField.classList.add('hidden');
        if (seasonField) seasonField.classList.remove('hidden');
    } else {
        if (yearField) yearField.classList.remove('hidden');
        if (seasonField) seasonField.classList.add('hidden');
    }
});

/**
 * Bulk generate passes
 */
window.EventDelegation.register('bulk-generate-passes', (element, event) => {
    event.preventDefault();
    const passType = document.getElementById('bulkPassType')?.value;
    const year = document.getElementById('bulkYear')?.value;
    const seasonName = document.getElementById('bulkSeasonName')?.value;
    const btn = element;
    const resultsDiv = document.getElementById('bulkGenerateResults');
    const resultsContent = document.getElementById('bulkResultsContent');

    btn.disabled = true;
    btn.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-1"></span>Generating...';

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

        if (resultsDiv) resultsDiv.classList.remove('hidden');

        if (data.error) {
            if (resultsContent) resultsContent.innerHTML = `<div class="alert alert-danger" data-alert>${escapeHtml(data.error)}</div>`;
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
                html += `<li>${escapeHtml(f.player_name || String(f.player_id))}: ${escapeHtml(f.error)}</li>`;
            });
            html += '</ul></details>';
        }

        if (resultsContent) resultsContent.innerHTML = html;
    })
    .catch(err => {
        btn.disabled = false;
        btn.innerHTML = '<i class="ti ti-bolt me-1"></i>Generate Passes';
        if (resultsContent) resultsContent.innerHTML = `<div class="alert alert-danger" data-alert>Error generating passes. Please try again.</div>`;
        if (resultsDiv) resultsDiv.classList.remove('hidden');
    });
});

// ============================================================================
// PLAYER ELIGIBILITY
// ============================================================================

/**
 * Check player eligibility and show modal
 */
window.EventDelegation.register('check-player-eligibility', (element, event) => {
    event.preventDefault();
    const playerId = element.dataset.playerId;

    if (!playerId) return;

    const modalBody = document.getElementById('eligibilityModalBody');

    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('eligibilityModal');
    } else if (typeof window.Modal !== 'undefined') {
        const modalEl = document.getElementById('eligibilityModal');
        const modal = modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
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
                    html += `<li class="text-danger mb-2"><i class="ti ti-x me-2"></i>${escapeHtml(issue)}</li>`;
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
                            <span>${data.info.primary_team ? escapeHtml(data.info.primary_team) : '<em class="text-muted">None</em>'}</span>
                        </div>
                        <div class="col-6">
                            <small class="text-muted d-block">League</small>
                            <span>${data.info.league ? escapeHtml(data.info.league) : '<em class="text-muted">None</em>'}</span>
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
window.EventDelegation.register('bulk-generate-wallet-passes', (element, event) => {
    event.preventDefault();

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Generate Passes?',
            text: 'Generate passes for all eligible players? This will create passes that can be downloaded by each player.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, generate',
            confirmButtonColor: '#3085d6'
        }).then((result) => {
            if (result.isConfirmed) {
                performBulkGenerateWalletPasses(element);
            }
        });
    }
});

function performBulkGenerateWalletPasses(element) {
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
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('No Players', 'No eligible players found.', 'warning');
        }
        return;
    }

    // Show loading state
    const originalText = element.innerHTML;
    element.disabled = true;
    element.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-1"></span>Generating...';

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

        let htmlMessage = `<p><strong>Success:</strong> ${data.success?.length || 0} passes</p>`;
        htmlMessage += `<p><strong>Failed:</strong> ${data.failed?.length || 0} passes</p>`;

        if (data.failed && data.failed.length > 0) {
            htmlMessage += '<hr><p><strong>Failed:</strong></p><ul class="text-start">';
            data.failed.slice(0, 5).forEach(failure => {
                htmlMessage += `<li>${failure.player_name || 'Player ' + failure.player_id}: ${failure.error}</li>`;
            });
            if (data.failed.length > 5) {
                htmlMessage += `<li>...and ${data.failed.length - 5} more</li>`;
            }
            htmlMessage += '</ul>';
        }

        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Bulk Generation Complete',
                html: htmlMessage,
                icon: data.failed?.length > 0 ? 'warning' : 'success',
                confirmButtonText: 'OK'
            }).then(() => {
                if (data.success && data.success.length > 0) {
                    location.reload();
                }
            });
        }
    })
    .catch(error => {
        element.disabled = false;
        element.innerHTML = originalText;
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Error during bulk generation. Please try again.', 'error');
        }
    });
}

/**
 * Reload page action
 */
window.EventDelegation.register('reload-page', (element, event) => {
    event.preventDefault();
    location.reload();
});

// Handlers loaded
