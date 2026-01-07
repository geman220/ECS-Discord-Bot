'use strict';

/**
 * Sync Review Resolution Actions
 * Multi-order resolution, new player creation, email mismatch handling
 * @module sync-review/resolution-actions
 */

import { getSyncData, getResolutions, setNewPlayerResolution, setEmailMismatchResolution } from './state.js';
import { updateProgressBar, markIssueResolved } from './progress.js';
import { checkCommitReadiness } from './commit.js';

/**
 * Resolve a multi-order issue
 * @param {string} issueId
 */
export function resolveMultiOrder(issueId) {
    const resolutions = getResolutions();
    const syncData = getSyncData();
    const storedAssignments = resolutions.multiOrders[issueId];

    if (!storedAssignments || storedAssignments.length === 0) {
        window.Swal.fire({
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
        window.Swal.fire({
            icon: 'warning',
            title: 'Incomplete Assignments',
            text: `Please assign all ${totalOrders} orders to players before resolving.`,
            confirmButtonClass: 'btn btn-primary'
        });
        return;
    }

    markIssueResolved('multi-order', issueId, 'Resolved');
    checkCommitReadiness();

    let summaryText = 'Assignments made:\n';
    storedAssignments.forEach((assignment) => {
        const orderInfo = orderData.orders[assignment.orderIndex];
        summaryText += `Order #${orderInfo.order.order_id}: ${assignment.playerName}\n`;
    });

    window.Swal.fire({
        icon: 'success',
        title: 'Multi-Order Resolved!',
        text: summaryText,
        confirmButtonClass: 'btn btn-success'
    });
}

/**
 * Create a new player from issue
 * @param {string} issueId
 */
export function createNewPlayer(issueId) {
    setNewPlayerResolution(issueId, { action: 'create' });
    markIssueResolved('new-player', issueId, 'Will Create');
    checkCommitReadiness();
}

/**
 * Search for existing players
 * @param {string} issueId
 */
export function searchExistingPlayers(issueId) {
    const searchDiv = document.getElementById(`player-search-${issueId}`);
    if (searchDiv) {
        searchDiv.classList.remove('d-none');
    }
}

/**
 * Flag order as invalid
 * @param {string} issueId
 */
export function flagAsInvalid(issueId) {
    window.Swal.fire({
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
            setNewPlayerResolution(issueId, { action: 'invalid' });
            markIssueResolved('new-player', issueId, 'Invalid');
            checkCommitReadiness();
        }
    });
}

/**
 * Confirm player match (email mismatch)
 * @param {string} issueId
 */
export function confirmPlayerMatch(issueId) {
    setEmailMismatchResolution(issueId, { action: 'keep_existing' });
    markIssueResolved('email-mismatch', issueId, 'Match Confirmed');
    checkCommitReadiness();
}

/**
 * Create separate player (email mismatch)
 * @param {string} issueId
 */
export function createSeparatePlayer(issueId) {
    setEmailMismatchResolution(issueId, { action: 'create_separate' });
    markIssueResolved('email-mismatch', issueId, 'Separate Player');
    checkCommitReadiness();
}
