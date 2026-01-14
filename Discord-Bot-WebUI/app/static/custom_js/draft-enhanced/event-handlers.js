'use strict';

/**
 * Draft Enhanced Event Handlers
 * Event delegation setup for button clicks
 * @module draft-enhanced/event-handlers
 */

import { setupDragAndDrop } from './drag-drop.js';
import { confirmDraftPlayer } from './draft-confirmation.js';
import { openPlayerModal } from './player-modal.js';
import { confirmRemovePlayer } from './player-actions.js';

// Guard against redeclaration
if (typeof window._draftEnhancedEventDelegationSetup === 'undefined') {
    window._draftEnhancedEventDelegationSetup = false;
}

/**
 * Setup event delegation for all button clicks
 */
export function setupEventDelegation() {
    // Guard against duplicate setup
    if (window._draftEnhancedEventDelegationSetup) return;
    window._draftEnhancedEventDelegationSetup = true;

    // Event delegation for draft player buttons
    document.addEventListener('click', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        // Draft player button
        if (e.target.closest('.js-draft-player')) {
            const btn = e.target.closest('.js-draft-player');
            const playerId = btn.dataset.playerId;
            const playerName = btn.dataset.playerName;
            const isMultiTeam = btn.dataset.isMultiTeam === 'true';
            // Get existing teams from the player card
            const playerCard = btn.closest('.player-card');
            const existingTeams = playerCard?.dataset.existingTeams || '';
            confirmDraftPlayer(playerId, playerName, isMultiTeam, existingTeams);
        }

        // View player profile button
        if (e.target.closest('.js-view-player-profile')) {
            const btn = e.target.closest('.js-view-player-profile');
            const playerId = btn.dataset.playerId;
            openPlayerModal(playerId);
        }

        // Remove player button
        if (e.target.closest('.js-remove-player')) {
            const btn = e.target.closest('.js-remove-player');
            const playerId = btn.dataset.playerId;
            const teamId = btn.dataset.teamId;
            const playerName = btn.dataset.playerName;
            const teamName = btn.dataset.teamName;
            confirmRemovePlayer(playerId, teamId, playerName, teamName);
        }
    });

    // Setup drag and drop event delegation
    setupDragAndDrop();
}
