/**
 * Admin Panel - Match List Management
 * Handles all interactions for /admin-panel/matches/list page
 * Migrated from inline scripts in admin_panel/matches/list.html
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function initAdminPanelMatchList() {
    if (_initialized) return;

    // Page guard - only run on match list page
    if (!document.querySelector('[data-page="admin-match-list"]') &&
        !window.location.pathname.includes('/admin-panel/matches')) {
        return;
    }

    _initialized = true;

    // Event delegation for all match list actions
    document.addEventListener('click', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;
        const matchId = target.dataset.matchId;
        const matchName = target.dataset.matchName;

        switch(action) {
            case 'view-match-details':
                viewMatchDetails(matchId);
                break;
            case 'delete-match':
                adminPanelDeleteMatch(matchId, matchName);
                break;
            case 'duplicate-match':
                duplicateMatch(matchId);
                break;
            case 'schedule-match':
                adminPanelScheduleMatch(matchId);
                break;
            case 'postpone-match':
                postponeMatch(matchId);
                break;
            case 'cancel-match':
                cancelMatch(matchId);
                break;
            case 'bulk-actions':
                bulkActions();
                break;
            case 'export-matches':
                exportMatches();
                break;
            case 'bulk-schedule-matches':
                bulkScheduleMatches();
                break;
        }
    });

    // Handle select all checkbox
    const selectAllCheckbox = document.getElementById('selectAll');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', toggleSelectAll);
    }
}

function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.match-checkbox');

    checkboxes.forEach(checkbox => {
        checkbox.checked = selectAll.checked;
    });
}

function getSelectedMatches() {
    const checkboxes = document.querySelectorAll('.match-checkbox:checked');
    return Array.from(checkboxes).map(cb => parseInt(cb.value));
}

function viewMatchDetails(matchId) {
    fetch(`/admin-panel/matches/${matchId}/details`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const match = data.match;
                let detailsHtml = `
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-6 text-left">
                        <div>
                            <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Match Information</h6>
                            <div class="space-y-2 text-sm">
                                <p><span class="font-medium text-gray-700 dark:text-gray-300">Teams:</span> <span class="text-gray-900 dark:text-white">${match.home_team} vs ${match.away_team}</span></p>
                                <p><span class="font-medium text-gray-700 dark:text-gray-300">Date:</span> <span class="text-gray-900 dark:text-white">${match.date || 'TBD'}</span></p>
                                <p><span class="font-medium text-gray-700 dark:text-gray-300">Time:</span> <span class="text-gray-900 dark:text-white">${match.time || 'TBD'}</span></p>
                                <p><span class="font-medium text-gray-700 dark:text-gray-300">Location:</span> <span class="text-gray-900 dark:text-white">${match.location}</span></p>
                                <p><span class="font-medium text-gray-700 dark:text-gray-300">Status:</span> <span class="px-2 py-0.5 text-xs font-medium bg-ecs-green text-white rounded ml-1">${match.status}</span></p>
                            </div>
                        </div>
                        <div>
                            <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">League & Season</h6>
                            <div class="space-y-2 text-sm">
                                <p><span class="font-medium text-gray-700 dark:text-gray-300">League:</span> <span class="text-gray-900 dark:text-white">${match.league}</span></p>
                                <p><span class="font-medium text-gray-700 dark:text-gray-300">Season:</span> <span class="text-gray-900 dark:text-white">${match.season}</span></p>
                            </div>
                        </div>
                    </div>
                `;

                if (match.rsvp_data && match.rsvp_data.total > 0) {
                    detailsHtml += `
                        <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 text-left">
                            <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">RSVP Information</h6>
                            <p class="text-sm mb-2"><span class="font-medium text-gray-700 dark:text-gray-300">Total RSVPs:</span> <span class="text-gray-900 dark:text-white">${match.rsvp_data.total}</span></p>
                            <div class="flex flex-wrap gap-1">
                                ${match.rsvp_data.status_breakdown ? Object.entries(match.rsvp_data.status_breakdown).map(([status, count]) =>
                                    `<span class="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300 rounded">${status}: ${count}</span>`
                                ).join('') : ''}
                            </div>
                        </div>
                    `;
                }

                if (match.team_history && match.team_history.length > 0) {
                    detailsHtml += `
                        <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700 text-left">
                            <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Recent Head-to-Head</h6>
                            <div class="overflow-x-auto">
                                <table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">
                                    <thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                                        <tr>
                                            <th class="px-3 py-2">Date</th>
                                            <th class="px-3 py-2">Match</th>
                                            <th class="px-3 py-2">Status</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        ${match.team_history.map(h =>
                                            `<tr class="border-b border-gray-200 dark:border-gray-700"><td class="px-3 py-2">${h.date}</td><td class="px-3 py-2">${h.home_team} vs ${h.away_team}</td><td class="px-3 py-2">${h.status}</td></tr>`
                                        ).join('')}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                    `;
                }

                window.Swal.fire({
                    title: 'Match Details',
                    html: detailsHtml,
                    width: '700px',
                    confirmButtonText: 'Close'
                });
            } else {
                window.Swal.fire('Error', 'Could not load match details', 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            window.Swal.fire('Error', 'Could not load match details', 'error');
        });
}

function adminPanelDeleteMatch(matchId, matchName) {
    window.Swal.fire({
        title: 'Delete Match?',
        text: `Are you sure you want to delete "${matchName}"? This action cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, delete it!'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/admin-panel/matches/${matchId}/delete`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Deleted!', 'Match has been deleted.', 'success').then(() => {
                        location.reload();
                    });
                } else {
                    window.Swal.fire('Error', data.error || 'Could not delete match', 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error', 'Could not delete match', 'error');
            });
        }
    });
}

function bulkActions() {
    const selectedMatches = getSelectedMatches();

    if (selectedMatches.length === 0) {
        window.Swal.fire('No Selection', 'Please select matches to perform bulk actions.', 'warning');
        return;
    }

    window.Swal.fire({
        title: 'Bulk Actions',
        text: `Perform action on ${selectedMatches.length} selected matches:`,
        input: 'select',
        inputOptions: {
            'update_status': 'Update Status',
            'delete': 'Delete Matches',
            'export': 'Export Selected'
        },
        showCancelButton: true,
        confirmButtonText: 'Execute'
    }).then((result) => {
        if (result.isConfirmed) {
            if (result.value === 'delete') {
                confirmBulkDelete(selectedMatches);
            } else if (result.value === 'update_status') {
                bulkUpdateStatus(selectedMatches);
            } else if (result.value === 'export') {
                exportSelectedMatches(selectedMatches);
            }
        }
    });
}

function confirmBulkDelete(matchIds) {
    window.Swal.fire({
        title: 'Confirm Bulk Delete',
        text: `Are you sure you want to delete ${matchIds.length} matches? This cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, delete them!'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch('/admin-panel/matches/bulk-actions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    action: 'delete',
                    match_ids: matchIds
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success').then(() => {
                        location.reload();
                    });
                } else {
                    window.Swal.fire('Error', data.error, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error', 'Could not perform bulk delete', 'error');
            });
        }
    });
}

function bulkUpdateStatus(matchIds) {
    window.Swal.fire({
        title: 'Update Status',
        text: 'Select new status for selected matches:',
        input: 'select',
        inputOptions: {
            'scheduled': 'Scheduled',
            'live': 'Live',
            'completed': 'Completed',
            'cancelled': 'Cancelled',
            'postponed': 'Postponed'
        },
        showCancelButton: true,
        confirmButtonText: 'Update'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch('/admin-panel/matches/bulk-actions', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    action: 'update_status',
                    match_ids: matchIds,
                    status: result.value
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success').then(() => {
                        location.reload();
                    });
                } else {
                    window.Swal.fire('Error', data.error, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error', 'Could not update status', 'error');
            });
        }
    });
}

function duplicateMatch(matchId) {
    window.Swal.fire({
        title: 'Duplicate Match',
        text: 'This will create a copy of the match. You can edit the details after creation.',
        showCancelButton: true,
        confirmButtonText: 'Duplicate'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Duplicated!', 'Match has been duplicated. Redirecting to edit...', 'success');
        }
    });
}

function adminPanelScheduleMatch(matchId) {
    window.Swal.fire('Schedule Match', 'Match scheduling functionality would be implemented here.', 'info');
}

function postponeMatch(matchId) {
    window.Swal.fire('Postpone Match', 'Match postponement functionality would be implemented here.', 'info');
}

function cancelMatch(matchId) {
    window.Swal.fire({
        title: 'Cancel Match',
        text: 'Are you sure you want to cancel this match?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, cancel it!'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Cancelled!', 'Match has been cancelled.', 'success');
        }
    });
}

function exportMatches() {
    window.Swal.fire({
        title: 'Export Matches',
        text: 'Choose export format:',
        input: 'select',
        inputOptions: {
            'csv': 'CSV',
            'xlsx': 'Excel',
            'json': 'JSON'
        },
        showCancelButton: true,
        confirmButtonText: 'Export'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Export Started', `Export in ${result.value.toUpperCase()} format has been queued.`, 'info');
        }
    });
}

function exportSelectedMatches(matchIds) {
    window.Swal.fire('Export Started', `Export of ${matchIds.length} selected matches has been queued.`, 'info');
}

function bulkScheduleMatches() {
    window.Swal.fire('Bulk Schedule', 'Bulk scheduling functionality would be implemented here.', 'info');
}

// ========================================================================
// EXPORTS
// ========================================================================

export {
    initAdminPanelMatchList,
    toggleSelectAll,
    getSelectedMatches,
    viewMatchDetails,
    adminPanelDeleteMatch,
    bulkActions,
    confirmBulkDelete,
    bulkUpdateStatus,
    duplicateMatch,
    adminPanelScheduleMatch,
    postponeMatch,
    cancelMatch,
    exportMatches,
    exportSelectedMatches,
    bulkScheduleMatches
};

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-panel-match-list', initAdminPanelMatchList, {
        priority: 30,
        reinitializable: true,
        description: 'Admin panel match list management'
    });
}

// Fallback
// window.InitSystem handles initialization

// No window exports needed - InitSystem handles initialization
// All functions use event delegation internally
