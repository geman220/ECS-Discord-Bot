'use strict';

/**
 * Sync Review Module
 * Aggregates all sync review submodules
 * @module sync-review
 */

// State management
import {
    setSyncData,
    setTaskId,
    setCSRFToken,
    getResolutions
} from './state.js';

// Progress tracking
import { updateProgressBar, markIssueResolved } from './progress.js';

// Inactive players
import { updateInactivePlayerCount, updateInactivePlayersDisplay } from './inactive-players.js';

// Resolution actions
import {
    resolveMultiOrder,
    createNewPlayer,
    searchExistingPlayers,
    flagAsInvalid,
    confirmPlayerMatch,
    createSeparatePlayer
} from './resolution-actions.js';

// Search
import { searchPlayersDelayed, searchPlayers, cancelPlayerSearch } from './search.js';

// Assignment
import {
    assignToPlayer,
    createNewPlayerFromForm,
    cancelPlayerCreation,
    removeAssignment,
    showAssignment
} from './assignment.js';

// Commit
import {
    checkCommitReadiness,
    populateCommitSummary,
    commitAllChanges,
    executeCommit,
    refreshSyncData
} from './commit.js';

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

/**
 * Initialize the sync review module
 * @param {Object} data - Sync data from server
 * @param {string} id - Task ID
 * @param {string} csrfToken - CSRF token for requests
 */
function initSyncReview(data, id, csrfToken) {
    setSyncData(data);
    setTaskId(id);
    setCSRFToken(csrfToken);

    updateProgressBar();
    checkCommitReadiness();
    initializeAssignmentSelects();
    initPlayerSearchHandlers();

    console.log('[SyncReview] Module initialized');
}

// Register with EventDelegation system
function registerEventDelegation() {
    if (typeof window.EventDelegation === 'undefined') return;

    window.EventDelegation.register('refresh-sync', () => refreshSyncData());
    window.EventDelegation.register('remove-assignment', (element) => {
        removeAssignment(element.dataset.issueId, element.dataset.orderIndex);
    });
    window.EventDelegation.register('create-player-form', (element) => {
        createNewPlayerFromForm(element.dataset.issueId, element.dataset.orderIndex);
    });
    window.EventDelegation.register('cancel-creation', (element) => {
        cancelPlayerCreation(element.dataset.issueId, element.dataset.orderIndex);
    });
    window.EventDelegation.register('cancel-search', (element) => {
        cancelPlayerSearch(element.dataset.issueId, element.dataset.orderIndex);
    });
    window.EventDelegation.register('resolve-multi-order', (element) => {
        resolveMultiOrder(element.dataset.issueId);
    });
    window.EventDelegation.register('create-new-player', (element) => {
        createNewPlayer(element.dataset.issueId);
    });
    window.EventDelegation.register('search-existing', (element) => {
        searchExistingPlayers(element.dataset.issueId);
    });
    window.EventDelegation.register('flag-invalid', (element) => {
        flagAsInvalid(element.dataset.issueId);
    });
    window.EventDelegation.register('confirm-match', (element) => {
        confirmPlayerMatch(element.dataset.issueId);
    });
    window.EventDelegation.register('create-separate', (element) => {
        createSeparatePlayer(element.dataset.issueId);
    });
    window.EventDelegation.register('commit-changes', () => {
        commitAllChanges();
    });
    window.EventDelegation.register('assign-player', (element) => {
        assignToPlayer(
            element.dataset.issueId,
            element.dataset.orderIndex,
            element.dataset.playerId,
            element.dataset.playerName
        );
    });
}

// Register event delegation
registerEventDelegation();

// Register with InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('sync-review', initPlayerSearchHandlers, {
        priority: 30,
        description: 'Sync review player search handlers'
    });
}

// Fallback for non-module usage
document.addEventListener('DOMContentLoaded', initPlayerSearchHandlers);

// Re-export all functions
export {
    initSyncReview,
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
    removeAssignment,
    updateProgressBar,
    checkCommitReadiness
};

// Window exports for template compatibility
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
