import { EventDelegation } from '../../event-delegation/core.js';

/**
 * Draft System Action Handlers
 * Handles player drafting, team assignment, and draft UI
 */
// Uses global EventDelegation from core.js

// DRAFT SYSTEM ACTIONS
// ============================================================================

/**
 * Draft Player Action
 * Shows modal to select team and draft player
 */
EventDelegation.register('draft-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;

    if (!playerId || !playerName) {
        console.error('[draft-player] Missing required data attributes');
        return;
    }

    // Call global function
    if (typeof confirmDraftPlayer === 'function') {
        window.confirmDraftPlayer(playerId, playerName);
    } else if (window.draftSystemInstance && typeof window.draftSystemInstance.showDraftModal === 'function') {
        window.draftSystemInstance.showDraftModal(playerId, playerName);
    } else {
        console.error('[draft-player] No draft function available');
    }
});

/**
 * Remove Player Action
 * Removes player from team and returns to available pool
 */
EventDelegation.register('remove-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const teamId = element.dataset.teamId;
    const playerName = element.dataset.playerName;
    const teamName = element.dataset.teamName;

    if (!playerId || !teamId) {
        console.error('[remove-player] Missing required data attributes');
        return;
    }

    // Call global function
    if (typeof confirmRemovePlayer === 'function') {
        window.confirmRemovePlayer(playerId, teamId, playerName, teamName);
    } else {
        console.error('[remove-player] Function not found');
    }
});

/**
 * View Player Profile Action
 * Opens modal with player details
 */
EventDelegation.register('view-player-profile', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[view-player-profile] Missing player ID');
        return;
    }

    // Check for instance method first, then global
    if (window.draftSystemInstance && typeof window.draftSystemInstance.openPlayerModal === 'function') {
        window.draftSystemInstance.openPlayerModal(playerId);
    } else if (typeof openPlayerModal === 'function') {
        window.openPlayerModal(playerId);
    } else {
        console.error('[view-player-profile] No modal function available');
    }
});

/**
 * Search Players Action (triggered by input event)
 * Filters available players by name
 */
EventDelegation.register('search-players', function(element, e) {
    const searchTerm = element.value.toLowerCase().trim();

    if (window.draftSystemInstance && typeof window.draftSystemInstance.handleSearch === 'function') {
        window.draftSystemInstance.handleSearch(e);
    } else {
        // Fallback: basic search implementation
        const playerCards = document.querySelectorAll('[data-component="player-card"]');
        playerCards.forEach(card => {
            const playerName = (card.dataset.playerName || '').toLowerCase();
            const shouldShow = !searchTerm || playerName.includes(searchTerm);
            card.closest('[data-component="player-column"]')?.classList.toggle('d-none', !shouldShow);
        });
    }
});

/**
 * Filter Players by Position (triggered by change event)
 */
EventDelegation.register('filter-position', function(element, e) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handleFilter === 'function') {
        window.draftSystemInstance.handleFilter(e);
    } else {
        const position = element.value.toLowerCase();
        const playerCards = document.querySelectorAll('[data-component="player-card"]');
        playerCards.forEach(card => {
            const playerPosition = (card.dataset.position || '').toLowerCase();
            const shouldShow = !position || playerPosition === position;
            card.closest('[data-component="player-column"]')?.classList.toggle('d-none', !shouldShow);
        });
    }
});

/**
 * Sort Players (triggered by change event)
 */
EventDelegation.register('sort-players', function(element, e) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handleSort === 'function') {
        window.draftSystemInstance.handleSort(e);
    } else {
        console.warn('[sort-players] Sort function not available');
    }
});

// ============================================================================

console.log('[EventDelegation] Draft system handlers loaded');
