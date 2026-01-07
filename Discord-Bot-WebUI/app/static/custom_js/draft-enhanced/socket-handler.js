'use strict';

/**
 * Draft Enhanced Socket Handler
 * Socket connection and event handling
 * @module draft-enhanced/socket-handler
 */

import { updateTeamCount } from './team-management.js';
import { updateAvailablePlayerCount } from './search-filter.js';

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
        window.draftEnhancedSocket = window.SocketManager.getSocket();
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
            const playerCard = document.querySelector(`#available-players [data-player-id="${data.player.id}"]`);
            if (playerCard) {
                const column = playerCard.closest('[data-component="player-column"]');
                if (column) {
                    column.remove();
                    updateAvailablePlayerCount(document.querySelectorAll('#available-players .player-card').length);
                }
            }
        }
        if (data.team_id) {
            setTimeout(() => updateTeamCount(data.team_id), 100);
        }
    }
}

/**
 * Handle player removed event
 * @param {Object} data
 */
export function handlePlayerRemovedEvent(data) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handlePlayerRemoved === 'function') {
        window.draftSystemInstance.handlePlayerRemoved(data);
    } else {
        if (data.team_id) {
            setTimeout(() => updateTeamCount(data.team_id), 100);
        }
    }
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
