/**
 * Draft System - Socket Handler
 * Socket.io connection and event handling
 *
 * @module draft-system/socket-handler
 */

import { getState, setSocket, setConnected, getLeagueName } from './state.js';

/**
 * Initialize socket connection
 * @param {Object} callbacks - Event callbacks for the draft system
 */
export function initializeSocket(callbacks) {
    const state = getState();

    try {
        // Use SocketManager if available (preferred method)
        if (typeof window.SocketManager !== 'undefined') {
            console.log('🔌 [Draft] Using SocketManager');

            // Get socket reference
            const socket = window.SocketManager.getSocket();
            setSocket(socket);

            // Register connect callback - fires immediately if already connected
            window.SocketManager.onConnect('DraftSystem', (sock) => {
                console.log('🔌 [Draft] Socket connected via SocketManager');
                setSocket(window.socket);
                setConnected(true);
                callbacks.onConnectionChange(true);
                window.socket.emit('join_draft_room', { league_name: getLeagueName() });
            });

            // Register disconnect callback
            window.SocketManager.onDisconnect('DraftSystem', (reason) => {
                console.log('🔌 [Draft] Socket disconnected:', reason);
                setConnected(false);
                callbacks.onConnectionChange(false);
            });

            // Register event listeners via SocketManager
            setupSocketListenersViaManager(callbacks);
            return;
        }

        // Fallback: Reuse existing global socket if available
        if (window.socket) {
            console.log('🔌 [Draft] Reusing existing socket (connected:', window.socket.connected, ')');
            setSocket(window.socket);

            // If already connected, join room immediately
            if (window.socket.connected) {
                setConnected(true);
                callbacks.onConnectionChange(true);
                window.socket.emit('join_draft_room', { league_name: getLeagueName() });
            }
            // Set up listeners regardless - they'll fire when connected
            setupSocketListeners(callbacks);
            return;
        }

        console.log('🔌 [Draft] Creating new socket connection (fallback)');
        const socket = window.io('/', {
            transports: ['polling', 'websocket'],
            upgrade: true,
            timeout: 10000,
            reconnection: true,
            reconnectionDelay: 1000,
            reconnectionAttempts: 3,
            withCredentials: true
        });

        setSocket(socket);

        // Store globally so other components can reuse
        if (!window.socket) window.socket = socket;

        socket.on('connect', () => {
            setConnected(true);
            callbacks.onConnectionChange(true);
            socket.emit('join_draft_room', { league_name: getLeagueName() });
        });

        socket.on('disconnect', () => {
            setConnected(false);
            callbacks.onConnectionChange(false);
        });

        socket.on('connect_error', (error) => {
            callbacks.onConnectionChange(false, 'Connection Error');
            setTimeout(() => {
                if (!getState().isConnected) {
                    tryFallbackConnection(callbacks);
                }
            }, 3000);
        });

        setupSocketListeners(callbacks);

    } catch (error) {
        callbacks.onConnectionChange(false, 'Failed to Connect');
    }
}

/**
 * Set up socket listeners (used when reusing existing socket)
 * @param {Object} callbacks - Event callbacks
 */
export function setupSocketListeners(callbacks) {
    const socket = getState().socket;
    if (!socket) return;

    socket.on('connect', () => {
        console.log('🔌 [Draft] Socket connected, joining draft room');
        setConnected(true);
        callbacks.onConnectionChange(true);
        socket.emit('join_draft_room', { league_name: getLeagueName() });
    });

    socket.on('disconnect', () => {
        setConnected(false);
        callbacks.onConnectionChange(false);
    });

    socket.on('joined_room', (data) => {
        console.log('🏠 [Draft] Joined room:', data.room);
        callbacks.onJoinedRoom?.();
    });

    socket.on('player_drafted_enhanced', (data) => {
        callbacks.onPlayerDrafted(data);
    });

    socket.on('player_removed_enhanced', (data) => {
        callbacks.onPlayerRemoved(data);
    });

    socket.on('user_drafting', (data) => {
        if (data.username && data.player_name) {
            callbacks.onUserDrafting(data.username, data.player_name, data.team_name);
        }
    });

    socket.on('error', (data) => {
        callbacks.onError('Error: ' + data.message);
    });

    socket.on('draft_error', (data) => {
        callbacks.onError('Draft Error: ' + data.message);
    });

    socket.on('player_details', (data) => {
        callbacks.onPlayerDetails(data);
    });
}

/**
 * Set up socket listeners via SocketManager
 * @param {Object} callbacks - Event callbacks
 */
export function setupSocketListenersViaManager(callbacks) {
    const SM = window.SocketManager;

    SM.on('DraftSystem', 'joined_room', (data) => {
        console.log('🏠 [Draft] Joined room:', data.room);
        callbacks.onJoinedRoom?.();
    });

    SM.on('DraftSystem', 'player_drafted_enhanced', (data) => {
        callbacks.onPlayerDrafted(data);
    });

    SM.on('DraftSystem', 'player_removed_enhanced', (data) => {
        callbacks.onPlayerRemoved(data);
    });

    SM.on('DraftSystem', 'user_drafting', (data) => {
        if (data.username && data.player_name) {
            callbacks.onUserDrafting(data.username, data.player_name, data.team_name);
        }
    });

    SM.on('DraftSystem', 'error', (data) => {
        callbacks.onError('Error: ' + data.message);
    });

    SM.on('DraftSystem', 'draft_error', (data) => {
        callbacks.onError('Draft Error: ' + data.message);
    });

    SM.on('DraftSystem', 'player_details', (data) => {
        callbacks.onPlayerDetails(data);
    });

    console.log('🔌 [Draft] Socket listeners attached via SocketManager');
}

/**
 * Try fallback connection method
 * @param {Object} callbacks - Event callbacks
 */
export function tryFallbackConnection(callbacks) {
    try {
        const state = getState();
        if (state.socket) {
            state.socket.disconnect();
        }

        // Try with minimal configuration on default namespace
        const socket = window.io('/', {
            transports: ['polling'],
            upgrade: false,
            timeout: 10000,
            reconnection: false,
            forceNew: true
        });

        setSocket(socket);

        socket.on('connect', () => {
            setConnected(true);
            callbacks.onConnectionChange(true);
            socket.emit('join_draft_room', { league_name: getLeagueName() });
        });

        socket.on('connect_error', (error) => {
            callbacks.onConnectionChange(false, 'Using HTTP Fallback');
            callbacks.onToast?.('WebSocket connection failed. Using HTTP mode.', 'info');
        });

        // Set up other event listeners
        setupFallbackSocketListeners(callbacks);

    } catch (error) {
        callbacks.onConnectionChange(false, 'HTTP Fallback Only');
    }
}

/**
 * Set up fallback socket event listeners
 * @param {Object} callbacks - Event callbacks
 */
function setupFallbackSocketListeners(callbacks) {
    const socket = getState().socket;
    if (!socket) return;

    socket.on('player_drafted_enhanced', (data) => {
        callbacks.onPlayerDrafted(data);
    });

    socket.on('player_removed_enhanced', (data) => {
        callbacks.onPlayerRemoved(data);
    });

    socket.on('user_drafting', (data) => {
        if (data.username && data.player_name) {
            callbacks.onUserDrafting(data.username, data.player_name, data.team_name);
        }
    });

    socket.on('remove_error', (data) => {
        callbacks.onError('Remove Error: ' + data.message);
    });

    socket.on('error', (data) => {
        callbacks.onError('Error: ' + data.message);
    });
}

/**
 * Emit draft player event
 * @param {string} playerId - Player ID
 * @param {string} teamId - Team ID
 * @param {string} playerName - Player name
 */
export function emitDraftPlayer(playerId, teamId, playerName) {
    const state = getState();
    if (!state.socket || !state.isConnected) {
        return false;
    }

    state.socket.emit('draft_player_enhanced', {
        player_id: playerId,
        team_id: teamId,
        league_name: getLeagueName(),
        player_name: playerName
    });

    return true;
}

/**
 * Emit remove player event
 * @param {string} playerId - Player ID
 * @param {string} teamId - Team ID
 */
export function emitRemovePlayer(playerId, teamId) {
    const state = getState();
    if (!state.socket || !state.isConnected) {
        return false;
    }

    state.socket.emit('remove_player_enhanced', {
        player_id: playerId,
        team_id: teamId,
        league_name: getLeagueName()
    });

    return true;
}

/**
 * Emit get player details event
 * @param {string} playerId - Player ID
 */
export function emitGetPlayerDetails(playerId) {
    const state = getState();
    if (!state.socket || !state.isConnected) {
        return false;
    }

    state.socket.emit('get_player_details', { player_id: playerId });
    return true;
}

export default {
    initializeSocket,
    setupSocketListeners,
    setupSocketListenersViaManager,
    tryFallbackConnection,
    emitDraftPlayer,
    emitRemovePlayer,
    emitGetPlayerDetails
};
