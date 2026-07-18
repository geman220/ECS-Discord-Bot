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

    // Escape/format helpers (mirror the server template's Jinja output)
    const esc = (s) => String(s == null ? '' : s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const fmtPos = (p) => !p ? p : String(p).replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());

    // Create the dense player row — MUST match the server-rendered markup in
    // draft_enhanced_flowbite.html so undrafted players look identical to the rest.
    const card = document.createElement('div');
    card.id = `player-${player.id}`;
    card.className = 'group relative js-draggable-player cursor-grab active:cursor-grabbing ' +
        'flex items-center gap-3 px-3 lg:px-5 py-3 rounded-xl lg:rounded-none ' +
        'border border-gray-200 dark:border-gray-600 lg:border-x-0 lg:border-t-0 lg:border-b-0 ' +
        'bg-white dark:bg-gray-700 lg:bg-transparent lg:dark:bg-transparent ' +
        'hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors';
    card.setAttribute('data-player-id', player.id);
    card.setAttribute('data-player-name', (player.name || '').toLowerCase());
    card.setAttribute('data-position', (player.favorite_position || '').toLowerCase());
    card.setAttribute('data-experience', player.league_experience_seasons || 0);
    card.setAttribute('data-attendance', (player.attendance_estimate === null || player.attendance_estimate === undefined) ? '' : player.attendance_estimate);
    card.setAttribute('data-goals', player.career_goals || 0);
    card.setAttribute('data-prev-draft', player.prev_draft_position || 999);
    card.setAttribute('data-is-new', player.is_new ? '1' : '0');
    card.setAttribute('data-is-admin', player.is_admin ? '1' : '0');
    card.setAttribute('draggable', 'true');

    const profilePic = player.profile_picture_url || player.profile_picture_medium || '/static/img/default_player.png';
    const position = player.favorite_position || 'Any';
    const goals = player.career_goals || 0;
    const assists = player.career_assists || 0;
    const yellowCards = player.career_yellow_cards || 0;
    const redCards = player.career_red_cards || 0;
    const attendance = player.attendance_estimate;

    // Experience ring + corner badge
    const exp = player.experience_level || '';
    const seasons = player.league_experience_seasons || 0;
    const ringClass = exp === 'Veteran' ? 'ring-green-500' : exp === 'Experienced' ? 'ring-yellow-500' : 'ring-gray-300 dark:ring-gray-500';
    const badgeBg = exp === 'Veteran' ? 'bg-green-500' : exp === 'Experienced' ? 'bg-yellow-500' : 'bg-gray-400';
    const expInitial = exp ? exp[0] : 'N';

    // Name-row badges (prev draft pick / ref / new / admin)
    let nameBadges = '';
    if (player.prev_draft_position) {
        nameBadges += `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold mono bg-blue-600 text-white shrink-0" title="Last season draft pick #${player.prev_draft_position}">#${player.prev_draft_position}</span>`;
    }
    if (player.is_ref) {
        nameBadges += `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-500 text-white shrink-0">REF</span>`;
    }
    if (player.is_new) {
        nameBadges += `<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-violet-100 text-violet-700 dark:bg-violet-500/20 dark:text-violet-300 shrink-0" title="Brand new — no prior team history"><i class="ti ti-sparkles text-[9px]"></i>NEW</span>`;
    }
    if (player.is_admin) {
        nameBadges += `<span class="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold bg-sky-100 text-sky-700 dark:bg-sky-500/20 dark:text-sky-300 shrink-0" title="Admin"><i class="ti ti-shield-check text-[9px]"></i>ADMIN</span>`;
    }

    // Position pills (primary green / alt orange / avoid red)
    let positionBadges = '';
    if (position && position !== 'Any') {
        positionBadges = `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400 border border-green-300 dark:border-green-700"><i class="ti ti-star-filled mr-0.5 text-[9px]"></i>${esc(fmtPos(position))}</span>`;
    } else {
        positionBadges = `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide bg-gray-100 dark:bg-gray-600 text-gray-600 dark:text-gray-300">Any</span>`;
    }
    if (player.other_positions) {
        player.other_positions.replace(/[{}]/g, '').split(',').forEach((pos) => {
            const cleanPos = pos.trim();
            if (cleanPos && cleanPos !== position) {
                positionBadges += `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide bg-orange-100 dark:bg-orange-900/30 text-orange-700 dark:text-orange-400">${esc(fmtPos(cleanPos))}</span>`;
            }
        });
    }
    if (player.positions_not_to_play) {
        player.positions_not_to_play.replace(/[{}]/g, '').split(',').forEach((pos) => {
            const cleanPos = pos.trim();
            if (cleanPos) {
                positionBadges += `<span class="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-400 border border-red-300 dark:border-red-700"><i class="ti ti-x mr-0.5 text-[9px]"></i>${esc(fmtPos(cleanPos))}</span>`;
            }
        });
    }

    // Attendance (lg column + mobile strip)
    const hasAttendance = attendance !== null && attendance !== undefined && attendance !== '';
    const attNum = hasAttendance ? parseFloat(attendance) : null;
    const attClass = !hasAttendance ? '' : attNum >= 80 ? 'text-green-600 dark:text-green-400' : attNum >= 60 ? 'text-yellow-500' : 'text-red-500';
    const attLg = hasAttendance
        ? `<span class="font-mono font-bold text-sm ${attClass}">${Math.round(attNum)}%</span>`
        : `<span class="font-mono text-sm text-gray-400">—</span>`;
    const attMobile = hasAttendance
        ? `<span class="${attClass}" title="Attendance"><i class="ti ti-calendar-check text-[11px]"></i> ${Math.round(attNum)}%</span>`
        : '';

    card.innerHTML = `
        <div class="relative shrink-0">
            <img src="${esc(profilePic)}" onerror="this.onerror=null;this.src='/static/img/default_player.png'"
                 alt="${esc(player.name)}" loading="lazy"
                 class="w-9 h-9 rounded-lg object-cover object-top ring-2 ${ringClass}">
            <span class="absolute -bottom-1 -right-1 inline-flex items-center justify-center w-4 h-4 rounded-full text-[9px] font-bold mono text-white ring-2 ring-white dark:ring-gray-800 ${badgeBg}"
                  title="${esc(exp || 'New Player')} · ${seasons} seasons">${esc(expInitial)}</span>
        </div>

        <div class="flex-1 min-w-0">
            <div class="flex items-center gap-2 flex-wrap">
                <span class="text-sm font-semibold text-gray-900 dark:text-white truncate">${esc(player.name)}</span>
                ${nameBadges}
            </div>
            <div class="flex flex-wrap items-center gap-1 mt-1">${positionBadges}</div>
        </div>

        <div class="hidden lg:flex items-center shrink-0">
            <div class="w-12 text-center"><div class="font-mono font-bold text-sm text-green-600 dark:text-green-400">${goals}</div></div>
            <div class="w-12 text-center"><div class="font-mono font-bold text-sm text-blue-600 dark:text-blue-400">${assists}</div></div>
            <div class="w-16 text-center font-mono font-bold text-sm"><span class="text-yellow-500">${yellowCards}</span><span class="text-gray-300 dark:text-gray-600">/</span><span class="text-red-500">${redCards}</span></div>
            <div class="w-14 text-center">${attLg}</div>
        </div>

        <div class="flex lg:hidden items-center gap-2.5 shrink-0 text-[11px] font-mono">
            <span class="text-green-600 dark:text-green-400" title="Goals"><i class="ti ti-ball-football text-[11px]"></i> ${goals}</span>
            <span class="text-blue-600 dark:text-blue-400" title="Assists"><i class="ti ti-arrow-forward-up text-[11px]"></i> ${assists}</span>
            ${attMobile}
        </div>

        <div class="flex items-center gap-1.5 shrink-0 lg:w-[150px] lg:justify-end">
            <button class="inline-flex items-center justify-center gap-1 min-h-[44px] sm:min-h-0 sm:h-9 px-3 rounded-lg bg-ecs-green text-white text-xs font-semibold hover:bg-ecs-green-700 transition-colors focus:outline-none focus:ring-2 focus:ring-ecs-green focus:ring-offset-2 dark:focus:ring-offset-gray-800"
                    data-action="draft-player" data-target-player-id="${player.id}" data-player-name="${esc(player.name)}">
                <i class="ti ti-user-plus"></i><span class="hidden sm:inline">Draft</span>
            </button>
            <button class="inline-flex items-center justify-center min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 sm:h-9 sm:w-9 rounded-lg border border-gray-300 dark:border-gray-600 text-gray-500 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-600 hover:text-gray-900 dark:hover:text-white transition-colors focus:outline-none focus:ring-2 focus:ring-ecs-green"
                    data-action="view-player-profile" data-target-player-id="${player.id}" aria-label="More info on ${esc(player.name)}">
                <i class="ti ti-info-circle"></i>
            </button>
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
