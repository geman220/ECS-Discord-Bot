/**
 * ==========================================================================
 * SOCKET MANAGER - Unified WebSocket Connection Management
 * ==========================================================================
 *
 * Centralizes Socket.IO connection management across the application.
 * Ensures a single socket instance is shared by all components (navbar,
 * chat widget, draft system, etc.) with proper reconnection handling.
 *
 * Features:
 * - Single shared socket instance
 * - Automatic reconnection with exponential backoff
 * - Late-binding: components can register after socket connects
 * - Event namespacing to prevent listener conflicts
 * - Connection state tracking and callbacks
 *
 * Usage:
 *   // Get the socket (creates if needed)
 *   const socket = SocketManager.getSocket();
 *
 *   // Register for connection events (called immediately if already connected)
 *   SocketManager.onConnect('myComponent', () => {
 *     socket.emit('join_room', { room: 'myroom' });
 *   });
 *
 *   // Register for specific events
 *   SocketManager.on('myComponent', 'new_message', (data) => {
 *     console.log('Got message:', data);
 *   });
 *
 *   // Cleanup when component unmounts
 *   SocketManager.removeListeners('myComponent');
 *
 * ==========================================================================
 */

(function() {
  'use strict';

  // ============================================================================
  // CONFIGURATION
  // ============================================================================

  const CONFIG = {
    // Socket.IO connection options
    connection: {
      // Start with polling to establish sticky session, then upgrade to websocket
      // This is critical for multi-worker setups with sticky sessions
      transports: ['polling', 'websocket'],
      upgrade: true,
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 1000,
      reconnectionDelayMax: 10000,
      randomizationFactor: 0.5,
      timeout: 20000,
      autoConnect: true,
      withCredentials: true
    },
    // Optimistic UI - delay showing "offline" to handle page navigation gracefully
    optimisticDisconnectDelay: 3000, // 3 seconds
    // Debug mode
    debug: false
  };

  // ============================================================================
  // STATE
  // ============================================================================

  let socket = null;
  let isConnected = false;
  let connectionAttempts = 0;
  let disconnectTimeout = null; // For optimistic UI delay

  // Optimistic UI state key
  const OPTIMISTIC_KEY = 'socket_last_connected';

  // Registered callbacks by component name
  const connectCallbacks = new Map();  // component -> callback
  const disconnectCallbacks = new Map();  // component -> callback
  const eventListeners = new Map();  // component -> Map(event -> callback)

  // ============================================================================
  // LOGGING
  // ============================================================================

  function log(...args) {
    if (CONFIG.debug) {
      console.log('[SocketManager]', ...args);
    }
  }

  function warn(...args) {
    console.warn('[SocketManager]', ...args);
  }

  function error(...args) {
    console.error('[SocketManager]', ...args);
  }

  // ============================================================================
  // SOCKET INITIALIZATION
  // ============================================================================

  /**
   * Get or create the socket instance
   * @returns {Socket|null} The socket instance or null if Socket.IO not available
   */
  function getSocket() {
    // Return existing socket if available
    if (socket) {
      return socket;
    }

    // Check if Socket.IO is available
    if (typeof window.io === 'undefined') {
      warn('Socket.IO library not loaded');
      return null;
    }

    // Check if there's already a global socket (created by another script)
    if (window.socket && window.socket.io) {
      log('Reusing existing global socket');
      socket = window.socket;
      isConnected = socket.connected;
      attachInternalListeners();

      // If already connected, fire callbacks
      if (isConnected) {
        fireConnectCallbacks();
      }

      return socket;
    }

    // Create new socket connection
    log('Creating new socket connection');
    try {
      socket = window.io('/', CONFIG.connection);

      // Store globally for other components
      window.socket = socket;

      attachInternalListeners();

      return socket;
    } catch (err) {
      error('Failed to create socket:', err);
      return null;
    }
  }

  /**
   * Attach internal event listeners for connection management
   */
  function attachInternalListeners() {
    if (!socket) return;

    // Remove existing listeners to prevent duplicates on reconnect
    socket.off('connect', handleConnect);
    socket.off('disconnect', handleDisconnect);
    socket.off('connect_error', handleConnectError);

    // Attach listeners
    socket.on('connect', handleConnect);
    socket.on('disconnect', handleDisconnect);
    socket.on('connect_error', handleConnectError);

    log('Internal listeners attached');
  }

  /**
   * Handle successful connection
   */
  function handleConnect() {
    log('Socket connected, id:', socket.id);
    isConnected = true;
    connectionAttempts = 0;

    // Save connection timestamp for optimistic UI across page loads
    try {
      sessionStorage.setItem(OPTIMISTIC_KEY, Date.now().toString());
    } catch (e) {
      // sessionStorage might be unavailable in private mode
    }

    // Clear any pending disconnect timeout (optimistic UI)
    if (disconnectTimeout) {
      clearTimeout(disconnectTimeout);
      disconnectTimeout = null;
      log('Cleared disconnect timeout - reconnected quickly');
    }

    // Fire all registered connect callbacks
    fireConnectCallbacks();
  }

  /**
   * Check if we were recently connected (for optimistic UI across page loads)
   * Returns true if connected within the optimistic delay period
   */
  function wasRecentlyConnected() {
    try {
      const lastConnected = sessionStorage.getItem(OPTIMISTIC_KEY);
      if (!lastConnected) return false;

      const elapsed = Date.now() - parseInt(lastConnected, 10);
      return elapsed < CONFIG.optimisticDisconnectDelay;
    } catch (e) {
      return false;
    }
  }

  /**
   * Handle disconnection
   * Uses optimistic UI - delays firing disconnect callbacks to handle page navigation gracefully
   */
  function handleDisconnect(reason) {
    log('Socket disconnected, reason:', reason);

    // Clear any existing timeout
    if (disconnectTimeout) {
      clearTimeout(disconnectTimeout);
    }

    // Optimistic UI: delay showing "disconnected" state
    // This handles page navigation where socket reconnects quickly on new page
    // If it's a real disconnect, callbacks fire after the delay
    disconnectTimeout = setTimeout(() => {
      log('Disconnect timeout elapsed, firing disconnect callbacks');
      isConnected = false;
      disconnectTimeout = null;
      fireDisconnectCallbacks(reason);
    }, CONFIG.optimisticDisconnectDelay);

    log(`Disconnect delayed by ${CONFIG.optimisticDisconnectDelay}ms (optimistic UI)`);
  }

  /**
   * Handle connection error
   */
  function handleConnectError(err) {
    connectionAttempts++;
    warn(`Connection error (attempt ${connectionAttempts}):`, err.message);

    // If too many failures, warn user
    if (connectionAttempts >= 5) {
      warn('Multiple connection failures. Real-time features may be unavailable.');
    }
  }

  /**
   * Fire all registered connect callbacks
   */
  function fireConnectCallbacks() {
    connectCallbacks.forEach((callback, component) => {
      try {
        log(`Firing connect callback for: ${component}`);
        callback(socket);
      } catch (err) {
        error(`Connect callback error for ${component}:`, err);
      }
    });
  }

  /**
   * Fire all registered disconnect callbacks
   */
  function fireDisconnectCallbacks(reason) {
    disconnectCallbacks.forEach((callback, component) => {
      try {
        callback(reason);
      } catch (err) {
        error(`Disconnect callback error for ${component}:`, err);
      }
    });
  }

  // ============================================================================
  // PUBLIC API
  // ============================================================================

  const SocketManager = {
    /**
     * Get the socket instance (creates if needed)
     * @returns {Socket|null}
     */
    getSocket: getSocket,

    /**
     * Check if socket is currently connected
     * @returns {boolean}
     */
    isConnected: function() {
      return isConnected && socket && socket.connected;
    },

    /**
     * Check if socket is connected OR was recently connected (optimistic UI)
     * Use this for UI status indicators to avoid flicker during page navigation
     * @returns {boolean}
     */
    isOptimisticallyConnected: function() {
      // Actually connected
      if (isConnected && socket && socket.connected) {
        return true;
      }
      // Recently connected (within last 3 seconds)
      return wasRecentlyConnected();
    },

    /**
     * Register a callback to be called when socket connects
     * If already connected, callback fires immediately
     *
     * @param {string} componentName - Unique name for the component
     * @param {Function} callback - Function to call on connect, receives socket
     */
    onConnect: function(componentName, callback) {
      if (typeof callback !== 'function') {
        warn('onConnect requires a function callback');
        return;
      }

      connectCallbacks.set(componentName, callback);
      log(`Registered connect callback: ${componentName}`);

      // If already connected, fire immediately
      if (isConnected && socket) {
        log(`Already connected, firing callback for: ${componentName}`);
        try {
          callback(socket);
        } catch (err) {
          error(`Connect callback error for ${componentName}:`, err);
        }
      }
    },

    /**
     * Register a callback to be called when socket disconnects
     *
     * @param {string} componentName - Unique name for the component
     * @param {Function} callback - Function to call on disconnect, receives reason
     */
    onDisconnect: function(componentName, callback) {
      if (typeof callback !== 'function') {
        warn('onDisconnect requires a function callback');
        return;
      }

      disconnectCallbacks.set(componentName, callback);
    },

    /**
     * Register an event listener with component namespacing
     * This ensures we can clean up all listeners for a component at once
     *
     * @param {string} componentName - Unique name for the component
     * @param {string} eventName - Socket event name
     * @param {Function} callback - Event handler
     */
    on: function(componentName, eventName, callback) {
      if (!socket) {
        getSocket(); // Ensure socket exists
      }

      if (!socket) {
        warn(`Cannot register event ${eventName}: no socket`);
        return;
      }

      // Store the listener reference for later cleanup
      if (!eventListeners.has(componentName)) {
        eventListeners.set(componentName, new Map());
      }

      const componentListeners = eventListeners.get(componentName);

      // If there's already a listener for this event from this component, remove it
      if (componentListeners.has(eventName)) {
        socket.off(eventName, componentListeners.get(eventName));
      }

      // Register the new listener
      componentListeners.set(eventName, callback);
      socket.on(eventName, callback);

      log(`Registered event listener: ${componentName}/${eventName}`);
    },

    /**
     * Emit an event on the socket
     *
     * @param {string} eventName - Event name
     * @param {*} data - Data to send
     */
    emit: function(eventName, data) {
      if (!socket || !isConnected) {
        warn(`Cannot emit ${eventName}: socket not connected`);
        return false;
      }

      socket.emit(eventName, data);
      return true;
    },

    /**
     * Remove all listeners for a component
     * Call this when a component unmounts or reinitializes
     *
     * @param {string} componentName - Component name to clean up
     */
    removeListeners: function(componentName) {
      // Remove connect callback
      connectCallbacks.delete(componentName);

      // Remove disconnect callback
      disconnectCallbacks.delete(componentName);

      // Remove event listeners
      if (eventListeners.has(componentName) && socket) {
        const componentListeners = eventListeners.get(componentName);
        componentListeners.forEach((callback, eventName) => {
          socket.off(eventName, callback);
        });
        eventListeners.delete(componentName);
      }

      log(`Removed all listeners for: ${componentName}`);
    },

    /**
     * Manually reconnect the socket
     */
    reconnect: function() {
      if (socket) {
        socket.connect();
      } else {
        getSocket();
      }
    },

    /**
     * Disconnect the socket
     */
    disconnect: function() {
      if (socket) {
        socket.disconnect();
      }
    },

    /**
     * Enable debug logging
     */
    enableDebug: function() {
      CONFIG.debug = true;
    },

    /**
     * Disable debug logging
     */
    disableDebug: function() {
      CONFIG.debug = false;
    }
  };

  // ============================================================================
  // INITIALIZATION
  // ============================================================================

  // Auto-initialize socket when DOM is ready
  function init() {
    // Only initialize if Socket.IO is available
    if (typeof window.io !== 'undefined') {
      getSocket();
      log('Socket manager initialized');
    } else {
      log('Socket.IO not available, skipping initialization');
    }
  }

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('socket-manager', init, {
      priority: 85,
      reinitializable: false,
      description: 'WebSocket connection manager'
    });
  }

  // Fallback: Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Handle page visibility changes
  document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'visible' && socket && !socket.connected) {
      log('Page visible, reconnecting socket');
      socket.connect();
    }
  });

  // Expose to global scope
  window.SocketManager = SocketManager;

})();
