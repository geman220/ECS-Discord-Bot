/**
 * Draft System - Drag and Drop
 * Player card drag and drop functionality
 *
 * @module draft-system/drag-drop
 */

let draggedPlayerId = null;

/**
 * Handle drag start event
 * @param {DragEvent} event - Drag event
 * @param {string} playerId - Player ID being dragged
 */
export function handleDragStart(event, playerId) {
    event.dataTransfer.setData('text/plain', playerId);
    event.dataTransfer.effectAllowed = 'move';

    event.target.classList.add('opacity-50', 'dragging');
    draggedPlayerId = playerId;
}

/**
 * Handle drag end event
 * @param {DragEvent} event - Drag event
 */
export function handleDragEnd(event) {
    event.target.classList.remove('opacity-50', 'dragging');
    draggedPlayerId = null;
}

/**
 * Handle drag over event
 * @param {DragEvent} event - Drag event
 */
export function handleDragOver(event) {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';

    const dropZone = event.currentTarget;
    dropZone.classList.add('drag-over');

    if (dropZone.id === 'available-players') {
        dropZone.classList.add('drag-over-available');
    } else if (dropZone.id && dropZone.id.startsWith('teamSection')) {
        dropZone.classList.add('drag-over-team');
    } else if (dropZone.classList.contains('team-drop-zone')) {
        dropZone.classList.add('drag-over-team-zone');
    }
}

/**
 * Handle drag leave event
 * @param {DragEvent} event - Drag event
 */
export function handleDragLeave(event) {
    const dropZone = event.currentTarget;
    dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team', 'drag-over-team-zone');
}

/**
 * Handle drop event on team
 * @param {DragEvent} event - Drag event
 * @param {string} teamId - Target team ID
 * @param {Function} onDraft - Callback to execute draft
 * @returns {Object|null} Draft info or null if invalid
 */
export function handleDrop(event, teamId, onDraft) {
    event.preventDefault();

    const dropZone = event.currentTarget;
    dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team', 'drag-over-team-zone');

    const playerId = event.dataTransfer.getData('text/plain') || draggedPlayerId;

    if (!playerId) {
        return { error: 'No player data found' };
    }

    // Check if player is already on this team
    const existingPlayerInTeam = document.querySelector(`#teamPlayers${teamId} [data-player-id="${playerId}"]`);
    if (existingPlayerInTeam) {
        return { error: 'Player is already on this team', type: 'warning' };
    }

    // Get player info
    const playerCard = document.querySelector(`[data-player-id="${playerId}"]`);
    const playerName = playerCard ? (playerCard.querySelector('.fw-semibold')?.textContent || 'Unknown Player') : 'Unknown Player';

    // Get team name from the drop zone
    let teamName = `Team ${teamId}`;
    if (dropZone.classList.contains('team-drop-zone')) {
        const teamNameElement = dropZone.querySelector('[data-component="team-name"]');
        teamName = teamNameElement ? teamNameElement.textContent.trim() : `Team ${teamId}`;
    } else {
        const teamAccordion = document.querySelector(`#teamSection${teamId}`)?.closest('[data-component="team-item"]');
        const teamNameElement = teamAccordion ? teamAccordion.querySelector('[data-component="team-name"]') : null;
        teamName = teamNameElement ? teamNameElement.textContent.trim() : `Team ${teamId}`;
    }

    if (onDraft) {
        onDraft(playerId, teamId, teamName, playerName);
    }

    return { playerId, teamId, teamName, playerName };
}

/**
 * Handle drop to available players pool
 * @param {DragEvent} event - Drag event
 * @param {Function} onRemove - Callback to execute removal
 * @returns {Object|null} Removal info or null if invalid
 */
export function handleDropToAvailable(event, onRemove) {
    event.preventDefault();

    const dropZone = event.currentTarget;
    dropZone.classList.remove('drag-over', 'drag-over-available', 'drag-over-team', 'drag-over-team-zone');

    const playerId = event.dataTransfer.getData('text/plain') || draggedPlayerId;

    if (!playerId) {
        return { error: 'No player data found' };
    }

    // Check if player is already in available pool
    const existingPlayerInAvailable = document.querySelector(`#available-players [data-player-id="${playerId}"]`);
    if (existingPlayerInAvailable) {
        return { error: 'Player is already in available pool', type: 'warning' };
    }

    // Find which team the player is currently on
    const currentPlayerCard = document.querySelector(`[data-player-id="${playerId}"]`);
    const teamSection = currentPlayerCard ? currentPlayerCard.closest('[id^="teamPlayers"]') : null;
    const teamId = teamSection ? teamSection.id.replace('teamPlayers', '') : null;

    if (!teamId) {
        return { error: 'Could not determine current team' };
    }

    // Get player and team names
    const playerName = currentPlayerCard ? (currentPlayerCard.querySelector('[data-component="player-name"]')?.textContent || 'Unknown Player') : 'Unknown Player';
    const teamNameElement = document.querySelector(`#teamSection${teamId}`)?.closest('[data-component="team-item"]')?.querySelector('[data-component="team-name"]');
    const teamName = teamNameElement ? teamNameElement.textContent.trim() : `Team ${teamId}`;

    if (onRemove) {
        onRemove(playerId, teamId);
    }

    return { playerId, teamId, teamName, playerName };
}

/**
 * Get currently dragged player ID
 * @returns {string|null} Player ID
 */
export function getDraggedPlayerId() {
    return draggedPlayerId;
}

export default {
    handleDragStart,
    handleDragEnd,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handleDropToAvailable,
    getDraggedPlayerId
};
