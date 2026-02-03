'use strict';

/**
 * Draft Enhanced Team Management
 * Team count updates and management
 * @module draft-enhanced/team-management
 */

/**
 * Update team player count
 * @param {string|number} teamId
 */
export function updateTeamCount(teamId) {
    const teamSection = document.getElementById(`teamPlayers${teamId}`);
    const teamCountBadge = document.getElementById(`teamCount${teamId}`);

    if (teamSection && teamCountBadge) {
        // Count direct children with data-player-id (the player cards, not buttons inside)
        const playerCount = teamSection.querySelectorAll(':scope > [data-player-id]').length;
        teamCountBadge.textContent = playerCount;

        console.log(`[team-management] Updated team ${teamId} count to ${playerCount}`);
    }
}

/**
 * Update all team counts
 */
export function updateAllTeamCounts() {
    document.querySelectorAll('[id^="teamPlayers"]').forEach(teamSection => {
        const teamId = teamSection.id.replace('teamPlayers', '');
        updateTeamCount(teamId);
    });
}
