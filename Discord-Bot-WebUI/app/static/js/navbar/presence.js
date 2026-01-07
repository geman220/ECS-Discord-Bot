/**
 * Navbar - Presence
 * Online/offline status tracking
 *
 * @module navbar/presence
 */

import { CONFIG, getCSRFToken } from './config.js';
import { getNavbar, getPresenceSocket, setPresenceSocket } from './state.js';

/**
 * Initialize presence tracking
 */
export function initPresence() {
  // Initialize WebSocket connection for presence if socket.io is available
  if (typeof window.io !== 'undefined') {
    initPresenceSocket();
  } else {
    // Fall back to API-only presence checking
    checkPresence();
  }

  // Refresh presence periodically
  setInterval(() => refreshPresence(), CONFIG.presenceRefreshInterval);

  // Also refresh presence when page becomes visible again
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      refreshPresence();
      // Reconnect socket if disconnected
      const presenceSocket = getPresenceSocket();
      if (presenceSocket && !presenceSocket.connected) {
        presenceSocket.connect();
      }
    }
  });
}

/**
 * Initialize WebSocket connection for presence tracking
 */
export function initPresenceSocket() {
  // Use SocketManager if available (preferred method)
  if (typeof window.SocketManager !== 'undefined') {
    console.log('[Navbar] Using SocketManager for presence');

    // Optimistic UI: Show "online" immediately if we were recently connected
    if (window.SocketManager.isOptimisticallyConnected()) {
      updateOnlineStatus(true);
      console.debug('[Navbar] Optimistic online status (recently connected)');
    }

    // Get socket reference
    setPresenceSocket(window.SocketManager.getSocket());

    // Register connect callback
    window.SocketManager.onConnect('Navbar', (socket) => {
      setPresenceSocket(window.socket);
      updateOnlineStatus(true);
      console.debug('Presence socket connected via SocketManager');
    });

    // Register disconnect callback
    window.SocketManager.onDisconnect('Navbar', (reason) => {
      updateOnlineStatus(false);
      console.debug('Presence socket disconnected:', reason);
    });

    // Register event listeners via SocketManager
    window.SocketManager.on('Navbar', 'authentication_success', (data) => {
      updateOnlineStatus(true);
      console.debug('Presence authenticated:', data.username);
    });

    window.SocketManager.on('Navbar', 'authentication_failed', () => {
      // Still connected but not authenticated - show as online anyway
      updateOnlineStatus(true);
    });

    return;
  }

  // Fallback: Use existing global socket if available
  if (window.socket) {
    console.log('[Navbar] Reusing existing socket (connected:', window.socket.connected, ')');
    setPresenceSocket(window.socket);
    if (window.socket.connected) {
      updateOnlineStatus(true);
    }
    attachSocketListenersDirect(window.socket);
    return;
  }

  // Fallback: Create new socket connection for presence
  try {
    console.log('[Navbar] Creating new socket connection (fallback)');
    const socket = window.io('/', {
      transports: ['polling', 'websocket'],
      upgrade: true,
      reconnection: true,
      reconnectionAttempts: 5,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 5000,
      timeout: 20000,
      autoConnect: true,
      withCredentials: true
    });

    setPresenceSocket(socket);

    // Store globally so other components can use it (only if not already set)
    if (!window.socket) window.socket = socket;

    attachSocketListenersDirect(socket);

  } catch (error) {
    console.warn('Failed to initialize presence socket:', error);
    checkPresence();
  }
}

/**
 * Attach event listeners directly to socket (fallback)
 * @param {Object} socket - Socket.IO socket
 */
function attachSocketListenersDirect(socket) {
  socket.on('connect', () => {
    updateOnlineStatus(true);
    console.debug('Presence socket connected');
  });

  socket.on('disconnect', () => {
    updateOnlineStatus(false);
    console.debug('Presence socket disconnected');
  });

  socket.on('authentication_success', (data) => {
    updateOnlineStatus(true);
    console.debug('Presence authenticated:', data.username);
  });

  socket.on('authentication_failed', () => {
    updateOnlineStatus(true);
  });

  socket.on('connect_error', (error) => {
    console.warn('Presence socket connection error:', error.message);
    updateOnlineStatus(false);
  });
}

/**
 * Check current presence status from server
 */
export async function checkPresence() {
  try {
    const response = await fetch('/api/notifications/presence');
    const data = await response.json();

    if (data.success) {
      updateOnlineStatus(data.online);
    }
  } catch (error) {
    // Don't log error - presence check is non-critical
  }
}

/**
 * Refresh presence TTL (keep showing as online)
 */
export async function refreshPresence() {
  try {
    await fetch('/api/notifications/presence/refresh', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      }
    });
  } catch (error) {
    // Silent fail - non-critical operation
  }
}

/**
 * Update the online status indicator in the navbar
 * @param {boolean} isOnline - Online status
 */
export function updateOnlineStatus(isOnline) {
  const navbar = getNavbar();
  if (!navbar) return;

  const statusIndicator = navbar.querySelector('.c-navbar-modern__avatar-status');
  if (!statusIndicator) return;

  if (isOnline) {
    statusIndicator.classList.add('is-online');
    statusIndicator.classList.remove('is-offline');
    statusIndicator.setAttribute('aria-label', 'Online');
    statusIndicator.setAttribute('title', 'You are online');
  } else {
    statusIndicator.classList.remove('is-online');
    statusIndicator.classList.add('is-offline');
    statusIndicator.setAttribute('aria-label', 'Offline');
    statusIndicator.setAttribute('title', 'You appear offline');
  }
}

export default {
  initPresence,
  initPresenceSocket,
  checkPresence,
  refreshPresence,
  updateOnlineStatus
};
