'use strict';

/**
 * Sync Review Commit
 * Commit changes workflow
 * @module sync-review/commit
 */

import { getSyncData, getResolutions, getTaskId, getCSRFToken } from './state.js';

/**
 * Check if ready to commit changes
 */
export function checkCommitReadiness() {
    const syncData = getSyncData();
    const resolutions = getResolutions();

    const totalIssues = (syncData.flagged_multi_orders?.length || 0) +
                        (syncData.new_players?.length || 0) +
                        (syncData.email_mismatch_players?.length || 0);
    const resolvedIssues = Object.keys(resolutions.multiOrders).length +
                           Object.keys(resolutions.newPlayers).length +
                           Object.keys(resolutions.emailMismatches).length;

    const commitValidation = document.getElementById('commitValidation');
    const readyToCommit = document.getElementById('readyToCommit');

    if (resolvedIssues === totalIssues) {
        if (commitValidation) commitValidation.classList.add('hidden');
        if (readyToCommit) readyToCommit.classList.remove('hidden');
        populateCommitSummary();
    } else {
        if (commitValidation) commitValidation.classList.remove('hidden');
        if (readyToCommit) readyToCommit.classList.add('hidden');
    }
}

/**
 * Populate commit summary
 */
export function populateCommitSummary() {
    const syncData = getSyncData();
    const resolutions = getResolutions();
    const playerUpdates = document.getElementById('playerUpdatesSummary');
    const statusChanges = document.getElementById('statusChangesSummary');

    if (!playerUpdates || !statusChanges) return;

    playerUpdates.innerHTML = '';
    statusChanges.innerHTML = '';

    // Add summary items based on resolutions
    Object.keys(resolutions.newPlayers).forEach(id => {
        const li = document.createElement('li');
        li.innerHTML = `<i class="ti ti-plus me-1 text-success"></i>Create: ${syncData.new_players[id].info.name}`;
        playerUpdates.appendChild(li);
    });

    Object.keys(resolutions.multiOrders).forEach(id => {
        const li = document.createElement('li');
        li.innerHTML = `<i class="ti ti-users me-1 text-info"></i>Multi-order resolved for ${syncData.flagged_multi_orders[id].buyer_info.name}`;
        playerUpdates.appendChild(li);
    });

    Object.keys(resolutions.emailMismatches).forEach(id => {
        const li = document.createElement('li');
        li.innerHTML = `<i class="ti ti-mail me-1 text-warning"></i>Email mismatch resolved for ${syncData.email_mismatch_players[id].existing_player.name}`;
        playerUpdates.appendChild(li);
    });

    const statusLi = document.createElement('li');
    statusLi.innerHTML = `<i class="ti ti-toggle-right me-1 text-success"></i>Update player active/inactive status`;
    statusChanges.appendChild(statusLi);

    // Add inactive players count if there are any
    if (syncData.players_to_inactivate && syncData.players_to_inactivate.length > 0) {
        const inactiveLi = document.createElement('li');
        inactiveLi.innerHTML = `<i class="ti ti-user-off me-1 text-warning"></i>Mark ${syncData.players_to_inactivate.length} players as inactive`;
        statusChanges.appendChild(inactiveLi);
    }
}

/**
 * Commit all changes
 */
export function commitAllChanges() {
    window.Swal.fire({
        title: 'Commit All Changes?',
        text: 'This will apply all resolutions to your database. This action cannot be undone.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, commit changes',
        cancelButtonText: 'Cancel',
        confirmButtonClass: 'text-white bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-5 py-2.5',
        cancelButtonClass: 'text-gray-900 bg-gray-200 hover:bg-gray-300 focus:ring-4 focus:ring-gray-100 font-medium rounded-lg text-sm px-5 py-2.5 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600'
    }).then((result) => {
        if (result.isConfirmed) {
            executeCommit();
        }
    });
}

/**
 * Execute the commit
 */
export function executeCommit() {
    const resolutions = getResolutions();
    const processInactiveCheck = document.getElementById('processInactiveCheck');
    const confirmInactiveCheck = document.getElementById('confirmInactiveProcess');

    const commitData = {
        task_id: getTaskId(),
        resolutions: resolutions,
        process_inactive: processInactiveCheck?.checked && (!confirmInactiveCheck || confirmInactiveCheck.checked)
    };

    const commitBtn = document.getElementById('finalCommitBtn');
    if (commitBtn) {
        commitBtn.disabled = true;
        commitBtn.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></span>Committing Changes...';
    }

    fetch('/user_management/commit_sync_changes', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify(commitData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire({
                icon: 'success',
                title: 'Changes Committed!',
                text: 'All sync changes have been successfully applied.',
                confirmButtonClass: 'text-white bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-5 py-2.5'
            }).then(() => {
                window.location.href = '/user_management/manage_users';
            });
        } else {
            throw new Error(data.error || 'Unknown error occurred');
        }
    })
    .catch(error => {
        window.Swal.fire({
            icon: 'error',
            title: 'Commit Failed',
            text: 'Error committing changes: ' + error.message,
            confirmButtonClass: 'text-white bg-red-600 hover:bg-red-700 focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-sm px-5 py-2.5'
        });

        if (commitBtn) {
            commitBtn.disabled = false;
            commitBtn.innerHTML = '<i class="ti ti-database-import me-2"></i> Commit All Changes';
        }
    });
}

/**
 * Refresh sync data
 */
export function refreshSyncData() {
    window.location.reload();
}
