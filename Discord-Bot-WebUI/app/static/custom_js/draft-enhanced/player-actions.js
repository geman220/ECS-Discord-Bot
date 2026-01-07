'use strict';

/**
 * Draft Enhanced Player Actions
 * Player removal and management actions
 * @module draft-enhanced/player-actions
 */

import { getLeagueName } from './state.js';

/**
 * Confirm removal of player from team
 * @param {string} playerId
 * @param {string} teamId
 * @param {string} playerName
 * @param {string} teamName
 */
export function confirmRemovePlayer(playerId, teamId, playerName, teamName) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Remove Player',
            text: `Remove ${playerName} from ${teamName}?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, Remove',
            cancelButtonText: 'Cancel',
            confirmButtonColor: '#dc3545',
            cancelButtonColor: '#6c757d'
        }).then((result) => {
            if (result.isConfirmed) {
                // Execute removal via socket or API
                const socket = window.draftEnhancedSocket || window.socket;
                if (socket && socket.connected) {
                    const leagueName = getLeagueName();

                    socket.emit('remove_player_enhanced', {
                        player_id: parseInt(playerId),
                        team_id: parseInt(teamId),
                        league_name: leagueName
                    });
                }
                console.log(`Removing player ${playerId} from team ${teamId}`);
            }
        });
    }
}
