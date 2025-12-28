/**
 * Substitute Pool Action Handlers
 * Handles substitute pool management and player assignments
 */
import { EventDelegation } from '../core.js';

// SUBSTITUTE POOL MANAGEMENT ACTIONS
// ============================================================================

/**
 * Approve Pool Player Action
 * Adds a pending player to the active substitute pool
 */
EventDelegation.register('approve-pool-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[approve-pool-player] Missing required data attributes');
        return;
    }

    if (typeof approvePlayer === 'function') {
        approvePlayer(playerId, league);
    } else {
        console.error('[approve-pool-player] approvePlayer function not found');
    }
});

/**
 * Remove Pool Player Action
 * Removes a player from the active substitute pool
 * Supports both pool management (with league) and pool detail (with playerName) contexts
 */
EventDelegation.register('remove-pool-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;
    const playerName = element.dataset.playerName;

    if (!playerId) {
        console.error('[remove-pool-player] Missing player ID');
        return;
    }

    // Pool management context (uses league parameter)
    if (league && typeof removePlayer === 'function') {
        removePlayer(playerId, league);
    }
    // Pool detail context (uses playerName parameter)
    else if (typeof removeFromPool === 'function') {
        removeFromPool(playerId, playerName);
    }
    else {
        console.error('[remove-pool-player] No removal function available (removePlayer or removeFromPool)');
    }
});

/**
 * Edit Pool Preferences Action
 * Opens modal to edit player's substitute pool preferences
 */
EventDelegation.register('edit-pool-preferences', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[edit-pool-preferences] Missing required data attributes');
        return;
    }

    if (typeof openEditPreferencesModal === 'function') {
        openEditPreferencesModal(playerId, league);
    } else {
        console.error('[edit-pool-preferences] openEditPreferencesModal function not found');
    }
});

/**
 * View Pool Player Details Action
 * Opens modal with detailed player information
 */
EventDelegation.register('view-pool-player-details', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[view-pool-player-details] Missing player ID');
        return;
    }

    if (typeof openPlayerDetailsModal === 'function') {
        openPlayerDetailsModal(playerId);
    } else {
        console.error('[view-pool-player-details] openPlayerDetailsModal function not found');
    }
});

/**
 * Add Player to League Action
 * Adds a player to a specific league's substitute pool (from search results)
 */
EventDelegation.register('add-player-to-league', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[add-player-to-league] Missing required data attributes');
        return;
    }

    if (typeof approvePlayer === 'function') {
        approvePlayer(playerId, league);
    } else {
        console.error('[add-player-to-league] approvePlayer function not found');
    }
});

/**
 * Toggle Pool View Action
 * Switches between grid and list view for substitute pool
 */
EventDelegation.register('toggle-pool-view', function(element, e) {
    e.preventDefault();

    const view = element.dataset.view;
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!view || !league || !section) {
        console.error('[toggle-pool-view] Missing required data attributes');
        return;
    }

    // Update button states
    const siblings = element.parentElement.querySelectorAll('.view-toggle');
    siblings.forEach(btn => btn.classList.remove('active'));
    element.classList.add('active');

    // Show/hide views
    const listView = document.getElementById(`${section}-list-${league}`);
    const gridView = document.getElementById(`${section}-grid-${league}`);

    if (view === 'list') {
        if (listView) listView.classList.remove('u-hidden');
        if (gridView) gridView.classList.add('u-hidden');
    } else {
        if (listView) listView.classList.add('u-hidden');
        if (gridView) gridView.classList.remove('u-hidden');
    }
});

/**
 * Filter Pool Action (triggered by input event)
 * Filters player cards by search text
 */
EventDelegation.register('filter-pool', function(element, e) {
    const filterText = element.value.toLowerCase().trim();
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!league || !section) {
        console.error('[filter-pool] Missing required data attributes');
        return;
    }

    if (typeof filterPlayerCards === 'function') {
        filterPlayerCards(league, section, filterText);
    } else {
        // Fallback implementation
        const cards = document.querySelectorAll(
            `.player-card[data-league="${league}"][data-status="${section}"], ` +
            `.player-list-item[data-league="${league}"][data-status="${section}"]`
        );

        cards.forEach(card => {
            const searchText = (card.dataset.searchText || '').toLowerCase();
            const shouldShow = !filterText || searchText.includes(filterText);
            card.classList.toggle('u-hidden', !shouldShow);
        });
    }
});

/**
 * Manage League Pool Action
 * Opens modal for league-specific pool management
 */
EventDelegation.register('manage-league-pool', function(element, e) {
    e.preventDefault();

    const league = element.dataset.league;

    if (!league) {
        console.error('[manage-league-pool] Missing league identifier');
        return;
    }

    if (typeof openLeagueManagementModal === 'function') {
        openLeagueManagementModal(league);
    } else {
        console.error('[manage-league-pool] openLeagueManagementModal function not found');
    }
});

/**
 * Save Pool Preferences Action
 * Saves edited preferences for a substitute pool player
 */
EventDelegation.register('save-pool-preferences', function(element, e) {
    e.preventDefault();

    if (typeof savePreferences === 'function') {
        savePreferences();
    } else {
        console.error('[save-pool-preferences] savePreferences function not found');
    }
});

/**
 * Pagination Click Handler for Pool Pages
 * Handles page navigation for substitute pool pagination
 */
EventDelegation.register('pool-pagination', function(element, e) {
    e.preventDefault();

    const page = parseInt(element.dataset.page);
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!page || !league || !section) {
        console.error('[pool-pagination] Missing required data attributes');
        return;
    }

    const key = `${league}-${section}`;

    if (typeof paginationState !== 'undefined' && paginationState[key]) {
        if (page !== paginationState[key].currentPage) {
            paginationState[key].currentPage = page;
            if (typeof updatePagination === 'function') {
                updatePagination(league, section);
            }
        }
    }
});

/**
 * Add to Pool Action (Admin Panel variant)
 * Adds a player to substitute pool (admin panel version)
 */
EventDelegation.register('add-to-pool', async function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[add-to-pool] Missing player ID');
        return;
    }

    // Check if addToPool function exists (from substitute_pool_detail.html)
    if (typeof addToPool === 'function') {
        addToPool(playerId);
    } else {
        console.error('[add-to-pool] addToPool function not found');
    }
});

/**
 * Reject Player Action (Admin Panel)
 * Rejects a player from being added to substitute pool
 */
EventDelegation.register('reject-player', async function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;

    if (!playerId) {
        console.error('[reject-player] Missing player ID');
        return;
    }

    // Check if rejectPlayer function exists (from substitute_pool_detail.html)
    if (typeof rejectPlayer === 'function') {
        rejectPlayer(playerId, playerName);
    } else {
        console.error('[reject-player] rejectPlayer function not found');
    }
});

// NOTE: remove-pool-player action is defined earlier in this file
// with unified support for both pool management (league param) and pool detail (playerName param) contexts

/**
 * Load Stats Action (Admin Panel)
 * Opens statistics modal for substitute pool
 */
EventDelegation.register('load-stats', async function(element, e) {
    e.preventDefault();

    if (typeof loadStatistics === 'function') {
        loadStatistics();
    } else {
        console.error('[load-stats] loadStatistics function not found');
    }
});

/**
 * Add Player Action (Admin Panel)
 * Opens modal to add player to substitute pool
 */
EventDelegation.register('add-player', function(element, e) {
    e.preventDefault();

    if (typeof showAddPlayerModal === 'function') {
        showAddPlayerModal();
    } else {
        console.error('[add-player] showAddPlayerModal function not found');
    }
});

// ============================================================================

console.log('[EventDelegation] Substitute pool handlers loaded');
