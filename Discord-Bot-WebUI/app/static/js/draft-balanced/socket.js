'use strict';

/**
 * Balanced-draft socket wiring. Reuses the exact room/persistence path of the
 * legacy draft: emits the existing draft_player_enhanced /
 * remove_player_enhanced events with league_name 'classic' and consumes
 * player_drafted_enhanced / player_removed_enhanced. Client state updates
 * optimistically from events; a debounced state.json refetch reconciles.
 */

import { state, loadInitial, applyDrafted, applyRemoved } from './state.js';
import { renderAll } from './render.js';

const LEAGUE = 'classic';
const RESYNC_DEBOUNCE_MS = 1500;

let resyncTimer = null;
let socketRef = null;
let onChangeCallback = null;

function setConnection(connected) {
    const pill = document.getElementById('db-connection');
    if (!pill) return;
    pill.className = `inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs ${
        connected ? 'bg-ecs-green/10 text-ecs-green' : 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400'}`;
    pill.innerHTML = `<span class="w-1.5 h-1.5 rounded-full ${connected ? 'bg-ecs-green' : 'bg-red-500'}"></span>${connected ? 'Live' : 'Reconnecting…'}`;
}

export function scheduleResync() {
    clearTimeout(resyncTimer);
    resyncTimer = setTimeout(async () => {
        try {
            const url = document.getElementById('draft-balanced-root')?.dataset.stateUrl;
            if (!url) return;
            const resp = await fetch(url);
            const data = await resp.json();
            if (resp.ok && data.success) {
                loadInitial(data);
                renderAll();
                onChangeCallback?.();
            }
        } catch (err) {
            console.warn('[draft-balanced] resync failed', err);
        }
    }, RESYNC_DEBOUNCE_MS);
}

function handleDrafted(data) {
    const playerId = data?.player?.id ?? data?.player_id;
    if (playerId === undefined) return;
    applyDrafted(playerId, data.team_id);
    renderAll();
    onChangeCallback?.();
    scheduleResync();   // authoritative reconciliation (joins mid-draft, drift)
}

function handleRemoved(data) {
    const playerId = data?.player?.id ?? data?.player_id;
    if (playerId === undefined) return;
    applyRemoved(playerId);
    renderAll();
    onChangeCallback?.();
    scheduleResync();
}

function handleError(data) {
    const message = data?.message || 'Draft action failed';
    if (window.Swal) {
        window.Swal.fire({ icon: 'error', title: 'Draft error', text: message,
                           toast: true, position: 'top-end', timer: 3500, showConfirmButton: false });
    }
    scheduleResync();
}

function joinRoom(socket) {
    socket.emit('join_draft_room', { league_name: LEAGUE });
}

export function setupSocket(onChange) {
    onChangeCallback = onChange;

    if (typeof window.SocketManager !== 'undefined') {
        window.SocketManager.on('draftBalanced', 'player_drafted_enhanced', handleDrafted);
        window.SocketManager.on('draftBalanced', 'player_removed_enhanced', handleRemoved);
        window.SocketManager.on('draftBalanced', 'draft_error', handleError);
        window.SocketManager.on('draftBalanced', 'remove_error', handleError);
        socketRef = window.SocketManager.getSocket();
    } else if (typeof window.io !== 'undefined') {
        socketRef = window.socket || window.io('/', {
            transports: ['polling', 'websocket'], upgrade: true, withCredentials: true,
        });
        if (!window.socket) window.socket = socketRef;
        socketRef.on('player_drafted_enhanced', handleDrafted);
        socketRef.on('player_removed_enhanced', handleRemoved);
        socketRef.on('draft_error', handleError);
        socketRef.on('remove_error', handleError);
    }

    if (socketRef) {
        // Re-join on EVERY connect — server room membership does not survive a
        // reconnect (same guard as draft-enhanced/socket-handler.js).
        socketRef.on('connect', () => { setConnection(true); joinRoom(socketRef); });
        socketRef.on('disconnect', () => setConnection(false));
        if (socketRef.connected) { setConnection(true); joinRoom(socketRef); }
    } else {
        setConnection(false);
    }
    return socketRef;
}

export function emitDraft(playerId, teamId) {
    if (!socketRef || !socketRef.connected) {
        handleError({ message: 'Not connected — wait for the live indicator and retry' });
        return false;
    }
    socketRef.emit('draft_player_enhanced', {
        player_id: Number(playerId),
        team_id: Number(teamId),
        league_name: LEAGUE,
    });
    return true;
}

export function emitRemove(playerId, teamId) {
    if (!socketRef || !socketRef.connected) {
        handleError({ message: 'Not connected — wait for the live indicator and retry' });
        return false;
    }
    socketRef.emit('remove_player_enhanced', {
        player_id: Number(playerId),
        team_id: Number(teamId),
        league_name: LEAGUE,
    });
    return true;
}
