'use strict';

/**
 * Draft Enhanced Drag & Drop
 * Drag and drop functionality for player cards
 * @module draft-enhanced/drag-drop
 */

import { getLeagueName } from './state.js';
import { getSocket } from './socket-handler.js';
import { updateTeamCount } from './team-management.js';

// Guard against redeclaration
if (typeof window._draftEnhancedDragDropSetup === 'undefined') {
    window._draftEnhancedDragDropSetup = false;
}

/**
 * Setup drag and drop functionality for player cards and drop zones
 */
export function setupDragAndDrop() {
    // Guard against duplicate setup
    if (window._draftEnhancedDragDropSetup) return;
    window._draftEnhancedDragDropSetup = true;

    // Drag start on draggable player cards
    document.addEventListener('dragstart', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const playerCard = e.target.closest('.js-draggable-player');
        if (playerCard) {
            const playerId = playerCard.dataset.playerId;
            e.dataTransfer.setData('text/plain', playerId);
            e.dataTransfer.effectAllowed = 'move';
            playerCard.classList.add('opacity-50', 'dragging');

            // Add body class for global drag state (triggers CSS animations)
            document.body.classList.add('is-dragging');

            // Store for fallback
            window._draggedPlayerId = playerId;
        }
    });

    // Drag end on draggable player cards
    document.addEventListener('dragend', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const playerCard = e.target.closest('.js-draggable-player');
        if (playerCard) {
            playerCard.classList.remove('opacity-50', 'dragging');
            window._draggedPlayerId = null;
        }
        // Remove body drag state class
        document.body.classList.remove('is-dragging');
    });

    // Drag over on drop zones
    document.addEventListener('dragover', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const dropZone = e.target.closest('.js-draft-drop-zone');
        if (dropZone) {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            dropZone.classList.add('drag-over');

            // Add specific styling based on drop target type
            const dropTarget = dropZone.dataset.dropTarget;
            if (dropTarget === 'available') {
                dropZone.classList.add('drag-over-available');
            } else if (dropTarget === 'team') {
                dropZone.classList.add('drag-over-team');
            }
        }
    });

    // Drag leave on drop zones
    document.addEventListener('dragleave', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const dropZone = e.target.closest('.js-draft-drop-zone');
        if (dropZone && !dropZone.contains(e.relatedTarget)) {
            dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team');
        }
    });

    // Drop on drop zones
    document.addEventListener('drop', function(e) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const dropZone = e.target.closest('.js-draft-drop-zone');
        if (dropZone) {
            e.preventDefault();
            dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team');

            const playerId = e.dataTransfer.getData('text/plain') || window._draggedPlayerId;
            if (!playerId) {
                console.error('No player ID found in drop event');
                return;
            }

            const dropTarget = dropZone.dataset.dropTarget;
            const teamId = dropZone.dataset.teamId;

            if (dropTarget === 'team' && teamId) {
                // Dropping on a team - draft the player
                handleDropOnTeam(playerId, teamId, dropZone);
            } else if (dropTarget === 'available') {
                // Dropping back to available pool - undraft the player
                handleDropToAvailable(playerId);
            }
        }
    });
}

/**
 * Handle dropping a player onto a team
 * @param {string} playerId
 * @param {string} teamId
 * @param {Element} dropZone
 */
export function handleDropOnTeam(playerId, teamId, dropZone) {
    // Check if player is already on this team
    const teamSection = document.getElementById(`teamPlayers${teamId}`);
    if (teamSection && teamSection.querySelector(`[data-player-id="${playerId}"]`)) {
        console.log('[DraftEnhanced] Player already on this team in UI');
        if (window.draftSystemInstance) {
            window.draftSystemInstance.showToast('Player is already on this team', 'warning');
        }
        return;
    }

    // Get player name for display (Tailwind uses font-bold, font-semibold, font-medium)
    const playerCard = document.querySelector(`[data-player-id="${playerId}"]`);
    const playerName = playerCard ?
        (playerCard.getAttribute('data-player-name') ||
         playerCard.querySelector('.font-bold')?.textContent?.trim() ||
         playerCard.querySelector('.font-semibold')?.textContent?.trim() ||
         playerCard.querySelector('.font-medium')?.textContent?.trim() ||
         'Player') : 'Player';

    // Get team name - look for details/summary structure or data attribute
    const teamDetails = dropZone.closest('details');
    const teamSummary = teamDetails?.querySelector('summary');
    const teamName = teamDetails?.dataset?.teamName ||
        teamSummary?.querySelector('.font-semibold')?.textContent?.trim() ||
        teamSummary?.querySelector('.font-bold')?.textContent?.trim() ||
        `Team ${teamId}`;

    const leagueName = getLeagueName();
    const socket = getSocket();

    if (socket) {
        socket.emit('draft_player_enhanced', {
            player_id: parseInt(playerId),
            team_id: parseInt(teamId),
            league_name: leagueName,
            player_name: playerName
        });
        console.log(`[DraftEnhanced] Drafting player ${playerId} to team ${teamId}`);
    } else {
        console.error('[DraftEnhanced] No connected socket available - cannot draft');
        showConnectionError();
    }
}

/**
 * Handle dropping a player back to the available pool (undraft)
 * @param {string} playerId
 */
export function handleDropToAvailable(playerId) {
    // Find which team the player is currently on
    const playerCard = document.querySelector(`[data-player-id="${playerId}"]`);
    if (!playerCard) {
        console.error('[DraftEnhanced] Player card not found');
        return;
    }

    // Check if player is in a team section (not already in available pool)
    const teamSection = playerCard.closest('[id^="teamPlayers"]');
    if (!teamSection) {
        console.log('[DraftEnhanced] Player is already in available pool');
        return;
    }

    // Extract team ID from the section ID (format: teamPlayers123)
    const teamId = teamSection.id.replace('teamPlayers', '');
    const leagueName = getLeagueName();
    const socket = getSocket();

    if (socket) {
        socket.emit('remove_player_enhanced', {
            player_id: parseInt(playerId),
            team_id: parseInt(teamId),
            league_name: leagueName
        });
        console.log(`[DraftEnhanced] Undrafting player ${playerId} from team ${teamId}`);
    } else {
        console.error('[DraftEnhanced] No connected socket available - cannot undraft');
        showConnectionError();
    }
}

/**
 * Show connection error message
 */
function showConnectionError() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'warning',
            title: 'Connection Issue',
            text: 'Not connected to server. Please wait a moment and try again.',
            timer: 3000,
            showConfirmButton: true,
            confirmButtonText: 'Refresh Page',
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.reload();
            }
        });
    }
}
