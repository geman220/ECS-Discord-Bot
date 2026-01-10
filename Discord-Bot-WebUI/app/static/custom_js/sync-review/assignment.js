'use strict';

/**
 * Sync Review Assignment
 * Order-to-player assignment functionality
 * @module sync-review/assignment
 */

import { getSyncData, getResolutions, getCSRFToken } from './state.js';
import { updateProgressBar } from './progress.js';
import { checkCommitReadiness } from './commit.js';

/**
 * Assign order to player
 * @param {string} issueId
 * @param {string} orderIndex
 * @param {string} playerId
 * @param {string} playerName
 */
export function assignToPlayer(issueId, orderIndex, playerId, playerName) {
    const resolutions = getResolutions();

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

    window.Swal.fire({
        icon: 'success',
        title: 'Player Assigned!',
        text: `Order assigned to ${playerName}`,
        timer: 2000,
        showConfirmButton: false
    });
}

/**
 * Create new player from form
 * @param {string} issueId
 * @param {string} orderIndex
 */
export function createNewPlayerFromForm(issueId, orderIndex) {
    const syncData = getSyncData();
    const resolutions = getResolutions();
    const nameInput = document.querySelector(`#create-new-${issueId}-${orderIndex} .new-player-name`);
    const name = nameInput?.value.trim();

    if (!name) {
        window.Swal.fire({
            icon: 'warning',
            title: 'Name Required',
            text: 'Please enter a player name',
            confirmButtonClass: 'text-white bg-ecs-green hover:bg-ecs-green-dark focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-5 py-2.5'
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
        createBtn.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-1"></span>Creating...';
    }

    fetch('/user_management/create_quick_player', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
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

            window.Swal.fire({
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
            window.Swal.fire({
                icon: 'error',
                title: 'Creation Failed',
                text: 'Error creating player: ' + (data.error || 'Unknown error'),
                confirmButtonClass: 'text-white bg-red-600 hover:bg-red-700 focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-sm px-5 py-2.5'
            });
        }
    })
    .catch(error => {
        if (createBtn) {
            createBtn.disabled = false;
            createBtn.innerHTML = originalText;
        }
        console.error('Create player error:', error);
        window.Swal.fire({
            icon: 'error',
            title: 'Creation Failed',
            text: 'Failed to create player',
            confirmButtonClass: 'text-white bg-red-600 hover:bg-red-700 focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-sm px-5 py-2.5'
        });
    });
}

/**
 * Cancel player creation
 * @param {string} issueId
 * @param {string} orderIndex
 */
export function cancelPlayerCreation(issueId, orderIndex) {
    const select = document.querySelector(`[data-issue-id="${issueId}"][data-order-index="${orderIndex}"]`);
    if (select) select.value = '';

    const createDiv = document.getElementById(`create-new-${issueId}-${orderIndex}`);
    if (createDiv) createDiv.classList.add('hidden');
}

/**
 * Remove assignment
 * @param {string} issueId
 * @param {string} orderIndex
 */
export function removeAssignment(issueId, orderIndex) {
    const resolutions = getResolutions();

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
    if (searchDiv) searchDiv.classList.add('hidden');
    if (createDiv) createDiv.classList.add('hidden');

    // Update progress and inactive counts since we removed an assignment
    updateProgressBar();
    checkCommitReadiness();

    if (typeof showSuccessToast === 'function') {
        showSuccessToast('Assignment removed successfully');
    }
}

/**
 * Show assignment in UI
 * @param {string} issueId
 * @param {string} orderIndex
 * @param {string} assignmentText
 */
export function showAssignment(issueId, orderIndex, assignmentText) {
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
    if (searchDiv) searchDiv.classList.add('hidden');
    if (createDiv) createDiv.classList.add('hidden');
}
