'use strict';

/**
 * Draft Enhanced Socket Handler
 * Socket connection and event handling
 * @module draft-enhanced/socket-handler
 */

import { updateTeamCount } from './team-management.js';
import { updateAvailablePlayerCount } from './search-filter.js';
import { getLeagueName } from './state.js';

/**
 * Join the draft room for real-time updates
 * @param {Object} socket - The socket instance
 */
function joinDraftRoom(socket) {
    const leagueName = getLeagueName();
    if (!leagueName) {
        console.warn('[DraftEnhanced] No league name found, cannot join draft room');
        return;
    }

    socket.emit('join_draft_room', { league_name: leagueName });
    console.log(`[DraftEnhanced] Joining draft room: draft_${leagueName}`);

    // Listen for join confirmation
    socket.on('joined_room', function(data) {
        console.log(`[DraftEnhanced] Successfully joined room: ${data.room}`);
    });
}

/**
 * Setup socket connection for draft enhanced page
 * Uses SocketManager instead of creating own socket
 */
export function setupDraftEnhancedSocket() {
    // Use SocketManager if available (preferred)
    if (typeof window.SocketManager !== 'undefined') {
        console.log('[DraftEnhanced] Using SocketManager');

        // Register event listeners through SocketManager
        window.SocketManager.on('draftEnhanced', 'player_drafted_enhanced', function(data) {
            console.log('[DraftEnhanced] Player drafted event received:', data);
            handlePlayerDraftedEvent(data);
        });

        window.SocketManager.on('draftEnhanced', 'player_removed_enhanced', function(data) {
            console.log('[DraftEnhanced] Player removed event received:', data);
            handlePlayerRemovedEvent(data);
        });

        window.SocketManager.on('draftEnhanced', 'draft_error', function(data) {
            console.log('[DraftEnhanced] Draft error:', data.message);
            handleDraftError(data);
        });

        // Store socket reference for other functions (backward compatibility)
        const socket = window.SocketManager.getSocket();
        window.draftEnhancedSocket = socket;

        // Join the draft room for real-time updates
        if (socket && socket.connected) {
            joinDraftRoom(socket);
        } else if (socket) {
            // Wait for connection then join
            socket.on('connect', function() {
                joinDraftRoom(socket);
            });
        }
        return;
    }

    // Fallback: Direct socket if SocketManager not available
    if (typeof window.io === 'undefined') return;

    console.log('[DraftEnhanced] SocketManager not available, using direct socket');
    const socket = window.socket || window.io('/', {
        transports: ['polling', 'websocket'],
        upgrade: true,
        withCredentials: true
    });
    if (!window.socket) window.socket = socket;
    window.draftEnhancedSocket = window.socket;

    window.socket.on('player_drafted_enhanced', handlePlayerDraftedEvent);
    window.socket.on('player_removed_enhanced', handlePlayerRemovedEvent);
    window.socket.on('draft_error', handleDraftError);

    // Join the draft room for real-time updates
    if (window.socket.connected) {
        joinDraftRoom(window.socket);
    } else {
        window.socket.on('connect', function() {
            joinDraftRoom(window.socket);
        });
    }
}

/**
 * Handle player drafted event
 * @param {Object} data
 */
export function handlePlayerDraftedEvent(data) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handlePlayerDrafted === 'function') {
        window.draftSystemInstance.handlePlayerDrafted(data);
    } else {
        if (data.player && data.player.id) {
            // Find and remove the player card directly (card itself has data-player-id)
            const playerCard = document.querySelector(`#available-players [data-player-id="${data.player.id}"]`);
            if (playerCard) {
                playerCard.remove();
                // Count visible players (respects current filters)
                const visibleCount = document.querySelectorAll('#available-players [data-player-id]:not(.hidden)').length;
                updateAvailablePlayerCount(visibleCount);
            }

            // Add player to team sidebar
            if (data.team_id) {
                addPlayerToTeamSidebar(data.player, data.team_id, data.team_name);
            }
        }
        if (data.team_id) {
            setTimeout(() => updateTeamCount(data.team_id), 100);
        }
        // Update header drafted count
        updateDraftedCount();
    }
}

/**
 * Add a player to the team sidebar
 * @param {Object} player - Player data
 * @param {number} teamId - Team ID
 * @param {string} teamName - Team name for remove button
 */
function addPlayerToTeamSidebar(player, teamId, teamName) {
    const teamContainer = document.getElementById(`teamPlayers${teamId}`);
    if (!teamContainer) return;

    // Check if player already exists in team
    if (teamContainer.querySelector(`[data-player-id="${player.id}"]`)) {
        return;
    }

    // Remove empty state message if present
    const emptyState = teamContainer.querySelector('.text-center.py-4');
    if (emptyState) {
        emptyState.remove();
    }

    const profilePic = player.profile_picture_url || '/static/img/default_player.png';
    const position = player.favorite_position || 'Any';

    const playerRow = document.createElement('div');
    playerRow.className = 'flex items-center gap-2 p-2 bg-gray-50 dark:bg-gray-700 rounded-lg js-draggable-player';
    playerRow.setAttribute('draggable', 'true');
    playerRow.setAttribute('data-player-id', player.id);

    playerRow.innerHTML = `
        <img src="${profilePic}" alt="${player.name}" class="w-8 h-8 rounded-full object-cover">
        <div class="flex-1 min-w-0">
            <div class="text-sm font-medium text-gray-900 dark:text-white truncate">${player.name}</div>
            <div class="text-xs text-gray-500 dark:text-gray-400">${position}</div>
        </div>
        <button class="p-1 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/30 rounded"
                data-action="remove-player"
                data-target-player-id="${player.id}"
                data-team-id="${teamId}"
                data-player-name="${player.name}"
                data-team-name="${teamName || ''}">
            <i class="ti ti-x"></i>
        </button>
    `;

    teamContainer.appendChild(playerRow);
    console.log(`[socket-handler] Added ${player.name} to team ${teamId} sidebar`);
}

/**
 * Update the drafted count in the header stats
 */
export function updateDraftedCount() {
    // Count all players in all team containers
    let totalDrafted = 0;
    document.querySelectorAll('[id^="teamPlayers"]').forEach(container => {
        totalDrafted += container.querySelectorAll('[data-player-id]').length;
    });

    // Update the drafted count in the header (green number showing "Drafted")
    // Find the element that shows drafted count - it's the one with text-green-500
    const headerStats = document.querySelectorAll('.text-2xl.font-bold.text-green-500');
    headerStats.forEach(el => {
        // Check if parent has "Drafted" text to confirm it's the right element
        const parent = el.closest('.text-center');
        if (parent && parent.textContent.includes('Drafted')) {
            el.textContent = totalDrafted;
        }
    });
}

/**
 * Handle player removed event
 * @param {Object} data
 */
export function handlePlayerRemovedEvent(data) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handlePlayerRemoved === 'function') {
        window.draftSystemInstance.handlePlayerRemoved(data);
    } else {
        // Remove player from team container in sidebar
        if (data.team_id && data.player) {
            const teamContainer = document.getElementById(`teamPlayers${data.team_id}`);
            if (teamContainer) {
                const playerInTeam = teamContainer.querySelector(`[data-player-id="${data.player.id}"]`);
                if (playerInTeam) {
                    playerInTeam.remove();
                }
            }
            setTimeout(() => updateTeamCount(data.team_id), 100);
        }

        // Add player back to available players pool
        if (data.player) {
            addPlayerBackToAvailable(data.player);
        }

        // Update header drafted count
        updateDraftedCount();
    }
}

/**
 * Add a player card back to the available players container
 * @param {Object} player - Player data from socket event
 */
function addPlayerBackToAvailable(player) {
    const container = document.getElementById('available-players');
    if (!container) return;

    // Check if player already exists in available pool
    if (container.querySelector(`[data-player-id="${player.id}"]`)) {
        return;
    }

    // Create player card HTML matching the template structure
    const card = document.createElement('div');
    card.id = `player-${player.id}`;
    card.className = 'bg-white dark:bg-gray-700 rounded-xl shadow-sm border border-gray-200 dark:border-gray-600 overflow-hidden js-draggable-player';
    card.setAttribute('data-player-id', player.id);
    card.setAttribute('data-player-name', (player.name || '').toLowerCase());
    card.setAttribute('data-position', (player.favorite_position || '').toLowerCase());
    card.setAttribute('data-experience', player.league_experience_seasons || 0);
    card.setAttribute('data-attendance', player.attendance_estimate || '');
    card.setAttribute('data-goals', player.career_goals || 0);
    card.setAttribute('data-prev-draft', player.prev_draft_position || 999);
    card.setAttribute('draggable', 'true');

    const profilePic = player.profile_picture_medium || player.profile_picture_webp || player.profile_picture_url || '/static/img/default_player.png';
    const position = player.favorite_position || 'Any';
    const goals = player.career_goals || 0;
    const assists = player.career_assists || 0;
    const yellowCards = player.career_yellow_cards || 0;
    const redCards = player.career_red_cards || 0;
    const attendance = player.attendance_estimate;

    // Build position badges HTML
    let positionBadges = '';
    if (position && position !== 'Any') {
        positionBadges = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700">
            <i class="ti ti-star-filled mr-1 text-green-500 text-[10px]"></i>${position}
        </span>`;
    } else {
        positionBadges = `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 dark:bg-gray-600 text-gray-600 dark:text-gray-300">Any Position</span>`;
    }

    // Add secondary positions (orange)
    if (player.other_positions) {
        const cleanPositions = player.other_positions.replace(/[{}]/g, '');
        cleanPositions.split(',').forEach(pos => {
            const cleanPos = pos.trim();
            if (cleanPos && cleanPos !== position) {
                positionBadges += `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400">${cleanPos}</span>`;
            }
        });
    }

    // Add positions not to play (red)
    if (player.positions_not_to_play) {
        const cleanNotPositions = player.positions_not_to_play.replace(/[{}]/g, '');
        cleanNotPositions.split(',').forEach(pos => {
            const cleanPos = pos.trim();
            if (cleanPos) {
                positionBadges += `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 border border-red-300 dark:border-red-700">
                    <i class="ti ti-x mr-1 text-red-500 text-[10px]"></i>${cleanPos}
                </span>`;
            }
        });
    }

    // Attendance display
    let attendanceHtml = '<div class="font-bold text-gray-400">N/A</div>';
    if (attendance !== null && attendance !== undefined && attendance !== '') {
        const attendanceNum = parseFloat(attendance);
        const attendanceClass = attendanceNum >= 80 ? 'text-green-500' : (attendanceNum >= 60 ? 'text-yellow-500' : 'text-red-500');
        attendanceHtml = `<div class="font-bold ${attendanceClass}">${Math.round(attendanceNum)}%</div>`;
    }

    card.innerHTML = `
        <div class="relative h-32 bg-gradient-to-b from-gray-100 to-gray-200 dark:from-gray-600 dark:to-gray-700">
            <img src="${profilePic}" alt="${player.name}" class="w-full h-full object-cover object-top" loading="lazy">
            <div class="absolute bottom-0 left-0 right-0 bg-gradient-to-t from-black/70 to-transparent p-2">
                <h3 class="text-white font-bold text-sm truncate">${player.name}</h3>
            </div>
        </div>
        <div class="p-3">
            <div class="text-center mb-2 flex flex-wrap justify-center gap-1">${positionBadges}</div>
            <div class="grid grid-cols-2 gap-2 text-center text-xs mb-2">
                <div><div class="font-bold text-green-500">${goals}</div><div class="text-gray-500 dark:text-gray-400">Goals</div></div>
                <div><div class="font-bold text-blue-500">${assists}</div><div class="text-gray-500 dark:text-gray-400">Assists</div></div>
            </div>
            <div class="grid grid-cols-2 gap-2 text-center text-xs mb-3">
                <div><div class="font-bold"><span class="text-yellow-500">${yellowCards}</span>/<span class="text-red-500">${redCards}</span></div><div class="text-gray-500 dark:text-gray-400">Cards</div></div>
                <div>${attendanceHtml}<div class="text-gray-500 dark:text-gray-400">Attend</div></div>
            </div>
            <div class="space-y-1">
                <button class="w-full px-3 py-1.5 rounded-lg bg-ecs-green text-white text-sm font-medium hover:bg-ecs-green/90 transition-colors"
                        data-action="draft-player" data-target-player-id="${player.id}" data-player-name="${player.name}">
                    <i class="ti ti-user-plus mr-1"></i>Draft
                </button>
                <button class="w-full px-3 py-1.5 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 text-sm hover:bg-gray-50 dark:hover:bg-gray-600 transition-colors"
                        data-action="view-player-profile" data-target-player-id="${player.id}">
                    <i class="ti ti-info-circle mr-1"></i>More Info
                </button>
            </div>
        </div>
    `;

    // Insert at beginning of container
    container.insertBefore(card, container.firstChild);

    // Update available count
    const visibleCount = container.querySelectorAll('[data-player-id]:not(.hidden)').length;
    updateAvailablePlayerCount(visibleCount);

    console.log(`[socket-handler] Added ${player.name} back to available pool`);
}

/**
 * Handle draft error
 * @param {Object} data
 */
export function handleDraftError(data) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.showToast === 'function') {
        window.draftSystemInstance.showToast(data.message, 'error');
    } else if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'error',
            title: 'Draft Error',
            text: data.message,
            timer: 3000,
            showConfirmButton: false
        });
    }
}

/**
 * Get the active socket connection
 * @returns {Object|null}
 */
export function getSocket() {
    // Try SocketManager first
    if (typeof window.SocketManager !== 'undefined' && window.SocketManager.isConnected()) {
        return window.SocketManager.getSocket();
    }

    // Fallback to DraftSystemV2 socket
    if (window.draftSystemInstance && window.draftSystemInstance.socket && window.draftSystemInstance.isConnected) {
        return window.draftSystemInstance.socket;
    }

    // Fallback to global socket
    const socket = window.draftEnhancedSocket || window.socket;
    if (socket && socket.connected) {
        return socket;
    }

    return null;
}

/**
 * Check if socket is connected
 * @returns {boolean}
 */
export function isSocketConnected() {
    return getSocket() !== null;
}
