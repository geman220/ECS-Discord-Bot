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
        // Count ONLY the player card elements, not buttons inside them
        const playerCount = teamSection.querySelectorAll('.draft-team-player-card').length;
        teamCountBadge.textContent = `${playerCount} players`;

        console.log(`Updated team ${teamId} count to ${playerCount} players`);
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
