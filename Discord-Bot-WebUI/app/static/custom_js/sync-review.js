'use strict';

/**
 * Sync Review Module
 *
 * Handles WooCommerce sync review functionality including:
 * - Multi-order resolution
 * - Player search and assignment
 * - Email mismatch handling
 * - New player creation
 * - Commit changes workflow
 *
 * @version 1.0.0
 */

import { InitSystem } from '../js/init-system.js';

// Module state
let syncData = {};
let resolutions = {
    multiOrders: {},
    newPlayers: {},
    emailMismatches: {}
};
let taskId = '';
let playersWithOrders = new Set();
let searchTimeout;

/**
 * Initialize the sync review module
 * @param {Object} data - Sync data from server
 * @param {string} id - Task ID
 * @param {string} csrfToken - CSRF token for requests
 */
function initSyncReview(data, id, csrfToken) {
    syncData = data;
    taskId = id;
    window._syncReviewCsrfToken = csrfToken;

    updateProgressBar();
    checkCommitReadiness();
    initializeAssignmentSelects();

    console.log('[SyncReview] Module initialized');
}

/**
 * Initialize assignment select handlers
 */
function initializeAssignmentSelects() {
    document.querySelectorAll('.assignment-select').forEach(select => {
        select.addEventListener('change', function() {
            const issueId = this.dataset.issueId;
            const orderIndex = this.dataset.orderIndex;
            const searchDiv = document.getElementById(`search-${issueId}-${orderIndex}`);
            const createDiv = document.getElementById(`create-new-${issueId}-${orderIndex}`);

            // Hide all forms first
            if (searchDiv) searchDiv.classList.add('d-none');
            if (createDiv) createDiv.classList.add('d-none');

            // Show appropriate form based on selection
            if (this.value === 'search' && searchDiv) {
                searchDiv.classList.remove('d-none');
            } else if (this.value === 'new' && createDiv) {
                createDiv.classList.remove('d-none');
            }
        });
    });
}

/**
 * Update progress bar based on resolutions
 */
function updateProgressBar() {
    const totalIssues = syncData.flagged_multi_orders.length + syncData.new_players.length + syncData.email_mismatch_players.length;
    const resolvedIssues = Object.keys(resolutions.multiOrders).length + Object.keys(resolutions.newPlayers).length + Object.keys(resolutions.emailMismatches).length;

    const percentage = totalIssues === 0 ? 100 : Math.round((resolvedIssues / totalIssues) * 100);

    const progressBar = document.getElementById('resolutionProgress');
    const progressText = document.getElementById('progressText');

    if (progressBar) {
        progressBar.setAttribute('style', `width: ${percentage}%`);
        progressBar.setAttribute('aria-valuenow', percentage);
    }

    if (progressText) {
        progressText.textContent = `${percentage}% Complete (${resolvedIssues}/${totalIssues} resolved)`;
    }

    const issuesResolvedCount = document.getElementById('issuesResolvedCount');
    if (issuesResolvedCount) {
        issuesResolvedCount.textContent = resolvedIssues + '/' + totalIssues;
    }

    // Update badges
    const multiOrdersBadge = document.getElementById('multiOrdersBadge');
    const newPlayersBadge = document.getElementById('newPlayersBadge');
    const emailMismatchBadge = document.getElementById('emailMismatchBadge');

    if (multiOrdersBadge) {
        multiOrdersBadge.textContent = syncData.flagged_multi_orders.length - Object.keys(resolutions.multiOrders).length;
    }
    if (newPlayersBadge) {
        newPlayersBadge.textContent = syncData.new_players.length - Object.keys(resolutions.newPlayers).length;
    }
    if (emailMismatchBadge) {
        emailMismatchBadge.textContent = syncData.email_mismatch_players.length - Object.keys(resolutions.emailMismatches).length;
    }

    // Update inactive player count
    updateInactivePlayerCount();

    if (percentage === 100 && progressBar) {
        progressBar.classList.remove('progress-bar-striped', 'progress-bar-animated');
        progressBar.classList.add('bg-success');
    }
}

/**
 * Update inactive player count based on assignments
 */
function updateInactivePlayerCount() {
    // Get all players assigned to existing orders
    let assignedPlayerIds = new Set();

    // Add players from multi-order assignments
    Object.values(resolutions.multiOrders).forEach(assignments => {
        assignments.forEach(assignment => {
            if (assignment.playerId) {
                assignedPlayerIds.add(assignment.playerId);
            }
        });
    });

    // Filter out assigned players from the inactive list
    const remainingInactive = syncData.players_to_inactivate ?
        syncData.players_to_inactivate.filter(player => !assignedPlayerIds.has(player.player_id)) : [];

    // Update the badge count
    const inactiveBadge = document.getElementById('inactivePlayersBadge');
    if (inactiveBadge) {
        inactiveBadge.textContent = remainingInactive.length;
    }

    // Update the count in the stats card
    const inactiveCount = document.getElementById('potentialInactiveCount');
    if (inactiveCount) {
        inactiveCount.textContent = remainingInactive.length;
    }

    // Update the display in the inactive players tab
    updateInactivePlayersDisplay(remainingInactive, assignedPlayerIds);
}

/**
 * Update inactive players display
 */
function updateInactivePlayersDisplay(remainingInactive, assignedPlayerIds) {
    const inactiveTab = document.getElementById('inactive-players');
    if (!inactiveTab) return;

    const cardBody = inactiveTab.querySelector('.card-body');
    if (!cardBody) return;

    if (remainingInactive.length === 0) {
        cardBody.innerHTML = `
            <div class="text-center py-5">
                <i class="ti ti-circle-check text-success empty-state-icon"></i>
                <h4 class="text-success mt-3">No Players to Mark Inactive!</h4>
                <p class="text-muted">All currently active players have current WooCommerce memberships.</p>
            </div>
        `;
        return;
    }

    let html = `
        <div class="alert alert-warning border-start border-warning border-3 py-3 px-4 mb-4" data-alert>
            <div class="d-flex align-items-center">
                <i class="ti ti-user-off me-2 fs-4"></i>
                <div>
                    <h6 class="alert-heading mb-1">Players to Mark Inactive</h6>
                    <p class="mb-0">These players are currently active but have no current WooCommerce membership orders. They will be marked as inactive.</p>
                </div>
            </div>
        </div>

        <div class="row mb-3">
            <div class="col-12">
                <div class="d-flex justify-content-between align-items-center">
                    <span class="text-muted">
                        <strong>${remainingInactive.length}</strong> players will be marked inactive
                    </span>
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="confirmInactiveProcess" checked>
                        <label class="form-check-label fw-semibold" for="confirmInactiveProcess">
                            Proceed with marking these players inactive
                        </label>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Show excluded players if any
    const excludedPlayers = syncData.players_to_inactivate ?
        syncData.players_to_inactivate.filter(player => assignedPlayerIds.has(player.player_id)) : [];

    if (excludedPlayers.length > 0) {
        html += `
            <div class="alert alert-info border-start border-info border-3 py-3 px-4 mb-4" data-alert>
                <div class="d-flex align-items-center">
                    <i class="ti ti-info-circle me-2 fs-4"></i>
                    <div>
                        <h6 class="alert-heading mb-1">Players Excluded from Inactive List</h6>
                        <p class="mb-0">${excludedPlayers.length} players were excluded because they were assigned to orders during resolution.</p>
                        <small class="text-muted">These players will remain active: ${excludedPlayers.map(p => p.player_name).join(', ')}</small>
                    </div>
                </div>
            </div>
        `;
    }

    // Add remaining inactive players
    remainingInactive.forEach(player => {
        html += `
            <div class="issue-card inactive-player-card border rounded p-3 mb-3">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h6 class="mb-1">
                            <i class="ti ti-user-off text-warning me-2"></i>
                            ${player.player_name}
                        </h6>
                        <small class="text-muted">
                            <i class="ti ti-user me-1"></i>Username: ${player.username}<br>
                            <i class="ti ti-shield me-1"></i>League: ${player.league_name}
                        </small>
                    </div>
                    <div class="col-md-4">
                        <div class="text-center">
                            <span class="badge bg-success" data-badge>Currently Active</span>
                            <div class="mt-2">
                                <i class="ti ti-arrow-down text-warning"></i>
                            </div>
                            <span class="badge bg-warning" data-badge>Will be Inactive</span>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="text-end">
                            <small class="text-muted">
                                <i class="ti ti-info-circle me-1"></i>${player.reason}
                            </small>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    cardBody.innerHTML = html;
}

/**
 * Check if ready to commit changes
 */
function checkCommitReadiness() {
    const totalIssues = syncData.flagged_multi_orders.length + syncData.new_players.length + syncData.email_mismatch_players.length;
    const resolvedIssues = Object.keys(resolutions.multiOrders).length + Object.keys(resolutions.newPlayers).length + Object.keys(resolutions.emailMismatches).length;

    const commitValidation = document.getElementById('commitValidation');
    const readyToCommit = document.getElementById('readyToCommit');

    if (resolvedIssues === totalIssues) {
        if (commitValidation) commitValidation.classList.add('d-none');
        if (readyToCommit) readyToCommit.classList.remove('d-none');
        populateCommitSummary();
    } else {
        if (commitValidation) commitValidation.classList.remove('d-none');
        if (readyToCommit) readyToCommit.classList.add('d-none');
    }
}

/**
 * Resolve a multi-order issue
 */
function resolveMultiOrder(issueId) {
    const storedAssignments = resolutions.multiOrders[issueId];

    if (!storedAssignments || storedAssignments.length === 0) {
        Swal.fire({
            icon: 'warning',
            title: 'No Assignments Made',
            text: 'Please assign all orders to players before resolving.',
            confirmButtonClass: 'btn btn-primary'
        });
        return;
    }

    const orderData = syncData.flagged_multi_orders[issueId];
    const totalOrders = orderData.orders.length;

    if (storedAssignments.length < totalOrders) {
        Swal.fire({
            icon: 'warning',
            title: 'Incomplete Assignments',
            text: `Please assign all ${totalOrders} orders to players before resolving.`,
            confirmButtonClass: 'btn btn-primary'
        });
        return;
    }

    markIssueResolved('multi-order', issueId, 'Resolved');

    let summaryText = 'Assignments made:\n';
    storedAssignments.forEach((assignment) => {
        const orderInfo = orderData.orders[assignment.orderIndex];
        summaryText += `Order #${orderInfo.order.order_id}: ${assignment.playerName}\n`;
    });

    Swal.fire({
        icon: 'success',
        title: 'Multi-Order Resolved!',
        text: summaryText,
        confirmButtonClass: 'btn btn-success'
    });
}

/**
 * Create a new player from issue
 */
function createNewPlayer(issueId) {
    resolutions.newPlayers[issueId] = { action: 'create' };
    markIssueResolved('new-player', issueId, 'Will Create');
}

/**
 * Search for existing players
 */
function searchExistingPlayers(issueId) {
    const searchDiv = document.getElementById(`player-search-${issueId}`);
    if (searchDiv) {
        searchDiv.classList.remove('d-none');
    }
}

/**
 * Flag order as invalid
 */
function flagAsInvalid(issueId) {
    Swal.fire({
        title: 'Mark as Invalid?',
        text: 'This will exclude the order from processing. Are you sure?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, mark as invalid',
        cancelButtonText: 'Cancel',
        confirmButtonClass: 'btn btn-danger',
        cancelButtonClass: 'btn btn-secondary'
    }).then((result) => {
        if (result.isConfirmed) {
            resolutions.newPlayers[issueId] = { action: 'invalid' };
            markIssueResolved('new-player', issueId, 'Invalid');
        }
    });
}

/**
 * Confirm player match (email mismatch)
 */
function confirmPlayerMatch(issueId) {
    resolutions.emailMismatches[issueId] = { action: 'keep_existing' };
    markIssueResolved('email-mismatch', issueId, 'Match Confirmed');
}

/**
 * Create separate player (email mismatch)
 */
function createSeparatePlayer(issueId) {
    resolutions.emailMismatches[issueId] = { action: 'create_separate' };
    markIssueResolved('email-mismatch', issueId, 'Separate Player');
}

/**
 * Mark an issue as resolved
 */
function markIssueResolved(issueType, issueId, status) {
    const issueCard = document.querySelector(`[data-issue-type="${issueType}"][data-issue-id="${issueId}"]`);
    if (issueCard) {
        issueCard.classList.remove('issue-pending');
        issueCard.classList.add('issue-resolved');

        const statusBadge = issueCard.querySelector('.status-badge');
        if (statusBadge) {
            statusBadge.textContent = status;
            statusBadge.className = 'status-badge badge bg-success';
        }
    }

    updateProgressBar();
    checkCommitReadiness();
}

/**
 * Populate commit summary
 */
function populateCommitSummary() {
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
function commitAllChanges() {
    Swal.fire({
        title: 'Commit All Changes?',
        text: 'This will apply all resolutions to your database. This action cannot be undone.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, commit changes',
        cancelButtonText: 'Cancel',
        confirmButtonClass: 'btn btn-success',
        cancelButtonClass: 'btn btn-secondary'
    }).then((result) => {
        if (result.isConfirmed) {
            executeCommit();
        }
    });
}

/**
 * Execute the commit
 */
function executeCommit() {
    const processInactiveCheck = document.getElementById('processInactiveCheck');
    const confirmInactiveCheck = document.getElementById('confirmInactiveProcess');

    const commitData = {
        task_id: taskId,
        resolutions: resolutions,
        process_inactive: processInactiveCheck?.checked && (!confirmInactiveCheck || confirmInactiveCheck.checked)
    };

    const commitBtn = document.getElementById('finalCommitBtn');
    if (commitBtn) {
        commitBtn.disabled = true;
        commitBtn.innerHTML = '<i class="spinner-border spinner-border-sm me-2"></i>Committing Changes...';
    }

    fetch('/user_management/commit_sync_changes', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': window._syncReviewCsrfToken
        },
        body: JSON.stringify(commitData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            Swal.fire({
                icon: 'success',
                title: 'Changes Committed!',
                text: 'All sync changes have been successfully applied.',
                confirmButtonClass: 'btn btn-success'
            }).then(() => {
                window.location.href = '/user_management/manage_users';
            });
        } else {
            throw new Error(data.error || 'Unknown error occurred');
        }
    })
    .catch(error => {
        Swal.fire({
            icon: 'error',
            title: 'Commit Failed',
            text: 'Error committing changes: ' + error.message,
            confirmButtonClass: 'btn btn-danger'
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
function refreshSyncData() {
    window.location.reload();
}

/**
 * Search players with delay
 */
function searchPlayersDelayed(input, issueId, orderIndex) {
    clearTimeout(searchTimeout);
    const query = input.value.trim();
    const resultsDiv = document.getElementById(`search-results-${issueId}-${orderIndex}`);

    if (query.length < 2) {
        if (resultsDiv) {
            resultsDiv.innerHTML = '<div class="text-muted small">Type at least 2 characters to search</div>';
        }
        return;
    }

    // Show loading
    if (resultsDiv) {
        resultsDiv.innerHTML = '<div class="text-muted small" data-spinner><i class="spinner-border spinner-border-sm me-1"></i>Searching...</div>';
    }

    searchTimeout = setTimeout(() => {
        searchPlayers(query, issueId, orderIndex);
    }, 300);
}

/**
 * Search players
 */
function searchPlayers(query, issueId, orderIndex) {
    fetch('/user_management/search_players', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': window._syncReviewCsrfToken
        },
        body: JSON.stringify({
            search_term: query
        })
    })
    .then(response => response.json())
    .then(data => {
        const resultsDiv = document.getElementById(`search-results-${issueId}-${orderIndex}`);
        if (!resultsDiv) return;

        if (data.success && data.players.length > 0) {
            let html = '<div class="mb-2"><small class="text-muted">Found ' + data.total_found + ' player(s):</small></div>';

            data.players.forEach(player => {
                const statusBadge = player.is_current ?
                    '<span class="badge bg-success" data-badge>Active</span>' :
                    '<span class="badge bg-warning" data-badge>Inactive</span>';

                let playerDetails = `Email: ${player.email}<br>Phone: ${player.phone}<br>League: ${player.league}`;
                if (player.jersey_size && player.jersey_size !== 'N/A') {
                    playerDetails += `<br>Jersey: ${player.jersey_size}`;
                }

                html += `
                    <div class="border rounded p-2 mb-2 player-result js-assign-player" data-action="assign-player" data-issue-id="${issueId}" data-order-index="${orderIndex}" data-player-id="${player.id}" data-player-name="${player.name}">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <strong>${player.name}</strong> ${statusBadge}
                                <br><small class="text-muted">
                                    ${playerDetails}
                                </small>
                            </div>
                            <i class="ti ti-arrow-right"></i>
                        </div>
                    </div>
                `;
            });

            resultsDiv.innerHTML = html;
        } else if (data.success && data.players.length === 0) {
            resultsDiv.innerHTML = '<div class="text-warning small"><i class="ti ti-search me-1"></i>No players found matching "' + query + '"</div>';
        } else {
            resultsDiv.innerHTML = '<div class="text-danger small" data-alert><i class="ti ti-alert-circle me-1"></i>Error searching: ' + (data.error || 'Unknown error') + '</div>';
        }
    })
    .catch(error => {
        console.error('Search error:', error);
        const resultsDiv = document.getElementById(`search-results-${issueId}-${orderIndex}`);
        if (resultsDiv) {
            resultsDiv.innerHTML = '<div class="text-danger small" data-alert><i class="ti ti-alert-circle me-1"></i>Search failed</div>';
        }
    });
}

/**
 * Assign order to player
 */
function assignToPlayer(issueId, orderIndex, playerId, playerName) {
    // Store the assignment
    if (!resolutions.multiOrders[issueId]) {
        resolutions.multiOrders[issueId] = [];
    }

    const assignment = {
        orderIndex: orderIndex,
        assignment: 'existing',
        playerId: playerId,
        playerName: playerName
    };

    // Update or add the assignment for this order
    const existingIndex = resolutions.multiOrders[issueId].findIndex(a => a.orderIndex === orderIndex);
    if (existingIndex >= 0) {
        resolutions.multiOrders[issueId][existingIndex] = assignment;
    } else {
        resolutions.multiOrders[issueId].push(assignment);
    }

    // Update UI to show assignment
    let assignmentText = `Assigned to: ${playerName}`;
    showAssignment(issueId, orderIndex, assignmentText);

    // Update inactive player counts since we assigned someone
    updateProgressBar();

    Swal.fire({
        icon: 'success',
        title: 'Player Assigned!',
        text: `Order assigned to ${playerName}`,
        timer: 2000,
        showConfirmButton: false
    });
}

/**
 * Create new player from form
 */
function createNewPlayerFromForm(issueId, orderIndex) {
    const nameInput = document.querySelector(`#create-new-${issueId}-${orderIndex} .new-player-name`);
    const name = nameInput?.value.trim();

    if (!name) {
        Swal.fire({
            icon: 'warning',
            title: 'Name Required',
            text: 'Please enter a player name',
            confirmButtonClass: 'btn btn-primary'
        });
        if (nameInput) nameInput.focus();
        return;
    }

    // Get full order data to pass to the backend
    const orderData = syncData.flagged_multi_orders[issueId];
    const orderInfo = orderData.orders[orderIndex];

    // If name was changed from original, don't use original email/phone
    const originalName = orderInfo.player_info.name;
    const nameChanged = name.toLowerCase().trim() !== originalName.toLowerCase().trim();

    // Prepare order info with all WooCommerce data
    const orderInfoForBackend = {
        player_info: {
            name: name,
            email: nameChanged ? '' : orderInfo.player_info.email,
            phone: nameChanged ? '' : orderInfo.player_info.phone,
            jersey_size: orderInfo.jersey_size
        },
        product_name: orderInfo.order.product_name,
        league_id: orderInfo.league_id,
        league_name: orderInfo.league_name
    };

    // Show loading
    const createBtn = document.querySelector(`#create-new-${issueId}-${orderIndex} .btn-success`);
    const originalText = createBtn?.innerHTML;
    if (createBtn) {
        createBtn.disabled = true;
        createBtn.innerHTML = '<i class="spinner-border spinner-border-sm me-1"></i>Creating...';
    }

    fetch('/user_management/create_quick_player', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': window._syncReviewCsrfToken
        },
        body: JSON.stringify({
            order_info: orderInfoForBackend
        })
    })
    .then(response => response.json())
    .then(data => {
        if (createBtn) {
            createBtn.disabled = false;
            createBtn.innerHTML = originalText;
        }

        if (data.success) {
            // Store the assignment
            if (!resolutions.multiOrders[issueId]) {
                resolutions.multiOrders[issueId] = [];
            }

            const assignment = {
                orderIndex: orderIndex,
                assignment: 'new',
                playerId: data.player.id,
                playerName: data.player.name,
                tempData: true
            };

            // Update or add the assignment for this order
            const existingIndex = resolutions.multiOrders[issueId].findIndex(a => a.orderIndex === orderIndex);
            if (existingIndex >= 0) {
                resolutions.multiOrders[issueId][existingIndex] = assignment;
            } else {
                resolutions.multiOrders[issueId].push(assignment);
            }

            // Update UI to show assignment
            let assignmentText = `Assigned to: ${data.player.name} (New Player)`;
            showAssignment(issueId, orderIndex, assignmentText);

            // Update inactive player counts since we created someone
            updateProgressBar();

            Swal.fire({
                icon: 'success',
                title: 'Player Created!',
                html: `<strong>${data.player.name}</strong><br>
                       League: ${data.player.league}<br>
                       ${data.player.jersey_size ? 'Jersey Size: ' + data.player.jersey_size + '<br>' : ''}
                       ${data.player.temp_data ? '<small class="text-warning">Some contact info is temporary</small>' : ''}`,
                timer: 3000,
                showConfirmButton: false
            });
        } else {
            Swal.fire({
                icon: 'error',
                title: 'Creation Failed',
                text: 'Error creating player: ' + (data.error || 'Unknown error'),
                confirmButtonClass: 'btn btn-danger'
            });
        }
    })
    .catch(error => {
        if (createBtn) {
            createBtn.disabled = false;
            createBtn.innerHTML = originalText;
        }
        console.error('Create player error:', error);
        Swal.fire({
            icon: 'error',
            title: 'Creation Failed',
            text: 'Failed to create player',
            confirmButtonClass: 'btn btn-danger'
        });
    });
}

/**
 * Cancel player creation
 */
function cancelPlayerCreation(issueId, orderIndex) {
    const select = document.querySelector(`[data-issue-id="${issueId}"][data-order-index="${orderIndex}"]`);
    if (select) select.value = '';

    const createDiv = document.getElementById(`create-new-${issueId}-${orderIndex}`);
    if (createDiv) createDiv.classList.add('d-none');
}

/**
 * Cancel player search
 */
function cancelPlayerSearch(issueId, orderIndex) {
    const select = document.querySelector(`[data-issue-id="${issueId}"][data-order-index="${orderIndex}"]`);
    if (select) select.value = '';

    const searchDiv = document.getElementById(`search-${issueId}-${orderIndex}`);
    if (searchDiv) searchDiv.classList.add('d-none');
}

/**
 * Remove assignment
 */
function removeAssignment(issueId, orderIndex) {
    // Remove from resolutions
    if (resolutions.multiOrders[issueId]) {
        resolutions.multiOrders[issueId] = resolutions.multiOrders[issueId].filter(a => a.orderIndex !== orderIndex);

        // If no assignments left for this issue, remove the entire entry
        if (resolutions.multiOrders[issueId].length === 0) {
            delete resolutions.multiOrders[issueId];
        }
    }

    // Hide current assignment display
    const currentAssignment = document.getElementById(`current-assignment-${issueId}-${orderIndex}`);
    if (currentAssignment) {
        currentAssignment.classList.add('sr-hidden');
        currentAssignment.classList.remove('sr-visible');
    }

    // Show assignment selection dropdown
    const assignmentSelection = document.getElementById(`assignment-selection-${issueId}-${orderIndex}`);
    if (assignmentSelection) {
        assignmentSelection.classList.remove('sr-hidden');
        assignmentSelection.classList.add('sr-visible');
    }

    // Reset dropdown
    const select = document.querySelector(`[data-issue-id="${issueId}"][data-order-index="${orderIndex}"]`);
    if (select) select.value = '';

    // Hide any open forms
    const searchDiv = document.getElementById(`search-${issueId}-${orderIndex}`);
    const createDiv = document.getElementById(`create-new-${issueId}-${orderIndex}`);
    if (searchDiv) searchDiv.classList.add('d-none');
    if (createDiv) createDiv.classList.add('d-none');

    // Update progress and inactive counts since we removed an assignment
    updateProgressBar();
    checkCommitReadiness();

    if (typeof showSuccessToast === 'function') {
        showSuccessToast('Assignment removed successfully');
    }
}

/**
 * Show assignment in UI
 */
function showAssignment(issueId, orderIndex, assignmentText) {
    // Hide assignment selection dropdown
    const assignmentSelection = document.getElementById(`assignment-selection-${issueId}-${orderIndex}`);
    if (assignmentSelection) {
        assignmentSelection.classList.add('sr-hidden');
        assignmentSelection.classList.remove('sr-visible');
    }

    // Show current assignment display
    const currentAssignmentDiv = document.getElementById(`current-assignment-${issueId}-${orderIndex}`);
    if (currentAssignmentDiv) {
        currentAssignmentDiv.classList.remove('sr-hidden');
        currentAssignmentDiv.classList.add('sr-visible');
        const textEl = currentAssignmentDiv.querySelector('.assignment-text');
        if (textEl) textEl.textContent = assignmentText;
    }

    // Hide any open forms
    const searchDiv = document.getElementById(`search-${issueId}-${orderIndex}`);
    const createDiv = document.getElementById(`create-new-${issueId}-${orderIndex}`);
    if (searchDiv) searchDiv.classList.add('d-none');
    if (createDiv) createDiv.classList.add('d-none');
}

// Register with EventDelegation system
if (typeof EventDelegation !== 'undefined') {
    // Refresh sync data
    EventDelegation.register('refresh-sync', function(element, event) {
        refreshSyncData();
    });

    // Remove assignment
    EventDelegation.register('remove-assignment', function(element, event) {
        const issueId = element.dataset.issueId;
        const orderIndex = element.dataset.orderIndex;
        removeAssignment(issueId, orderIndex);
    });

    // Create player from form
    EventDelegation.register('create-player-form', function(element, event) {
        const issueId = element.dataset.issueId;
        const orderIndex = element.dataset.orderIndex;
        createNewPlayerFromForm(issueId, orderIndex);
    });

    // Cancel creation
    EventDelegation.register('cancel-creation', function(element, event) {
        const issueId = element.dataset.issueId;
        const orderIndex = element.dataset.orderIndex;
        cancelPlayerCreation(issueId, orderIndex);
    });

    // Cancel search
    EventDelegation.register('cancel-search', function(element, event) {
        const issueId = element.dataset.issueId;
        const orderIndex = element.dataset.orderIndex;
        cancelPlayerSearch(issueId, orderIndex);
    });

    // Resolve multi-order
    EventDelegation.register('resolve-multi-order', function(element, event) {
        const issueId = element.dataset.issueId;
        resolveMultiOrder(issueId);
    });

    // Create new player
    EventDelegation.register('create-new-player', function(element, event) {
        const issueId = element.dataset.issueId;
        createNewPlayer(issueId);
    });

    // Search existing players
    EventDelegation.register('search-existing', function(element, event) {
        const issueId = element.dataset.issueId;
        searchExistingPlayers(issueId);
    });

    // Flag as invalid
    EventDelegation.register('flag-invalid', function(element, event) {
        const issueId = element.dataset.issueId;
        flagAsInvalid(issueId);
    });

    // Confirm match
    EventDelegation.register('confirm-match', function(element, event) {
        const issueId = element.dataset.issueId;
        confirmPlayerMatch(issueId);
    });

    // Create separate player
    EventDelegation.register('create-separate', function(element, event) {
        const issueId = element.dataset.issueId;
        createSeparatePlayer(issueId);
    });

    // Commit changes
    EventDelegation.register('commit-changes', function(element, event) {
        commitAllChanges();
    });

    // Assign player (dynamically added search results)
    EventDelegation.register('assign-player', function(element, event) {
        const issueId = element.dataset.issueId;
        const orderIndex = element.dataset.orderIndex;
        const playerId = element.dataset.playerId;
        const playerName = element.dataset.playerName;
        assignToPlayer(issueId, orderIndex, playerId, playerName);
    });
}

/**
 * Initialize player search input handlers
 */
function initPlayerSearchHandlers() {
    document.querySelectorAll('.js-player-search').forEach(input => {
        input.addEventListener('keyup', function() {
            const issueId = this.dataset.issueId;
            const orderIndex = this.dataset.orderIndex;
            searchPlayersDelayed(this, issueId, orderIndex);
        });
    });
}

// Register with InitSystem
InitSystem.register('sync-review', initPlayerSearchHandlers, {
    priority: 30,
    description: 'Sync review player search handlers'
});

// Fallback for non-module usage
document.addEventListener('DOMContentLoaded', initPlayerSearchHandlers);

// Export for use in templates
window.initSyncReview = initSyncReview;
window.SyncReview = {
    init: initSyncReview,
    refreshSyncData,
    resolveMultiOrder,
    createNewPlayer,
    searchExistingPlayers,
    flagAsInvalid,
    confirmPlayerMatch,
    createSeparatePlayer,
    commitAllChanges,
    assignToPlayer,
    createNewPlayerFromForm,
    cancelPlayerCreation,
    cancelPlayerSearch,
    removeAssignment
};
