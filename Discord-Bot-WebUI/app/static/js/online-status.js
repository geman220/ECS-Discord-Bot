/**
 * ============================================================================
 * ONLINE STATUS MANAGER
 * ============================================================================
 *
 * Handles real-time online status updates across the application.
 * Automatically finds and updates online status indicators.
 *
 * Usage:
 *   - Add data-online-status="<user_id>" to any element to make it update
 *   - Elements should have c-online-status class with is-online/is-offline modifiers
 *
 * ============================================================================
 */

(function () {
  'use strict';

  class OnlineStatusManager {
    constructor() {
      this.updateInterval = 30000; // 30 seconds
      this.intervalId = null;
      this.onlineUserIds = new Set();
      this.initialized = false;
    }

    /**
     * Initialize the online status manager
     */
    init() {
      if (this.initialized) return;
      this.initialized = true;

      // Initial fetch
      this.fetchOnlineUsers();

      // Set up periodic updates
      this.intervalId = setInterval(() => {
        this.fetchOnlineUsers();
      }, this.updateInterval);

      // Listen for WebSocket presence events if available
      this.setupWebSocketListeners();
    }

    /**
     * Get CSRF token for API requests
     */
    getCSRFToken() {
      const csrfMeta = document.querySelector('meta[name="csrf-token"]');
      if (csrfMeta) return csrfMeta.getAttribute('content');

      const csrfInput = document.querySelector('input[name="csrf_token"]');
      if (csrfInput) return csrfInput.value;

      return '';
    }

    /**
     * Fetch list of online users from the API
     */
    async fetchOnlineUsers() {
      try {
        const response = await fetch('/api/notifications/presence/online-users');
        const data = await response.json();

        if (data.success && data.online_user_ids) {
          this.onlineUserIds = new Set(data.online_user_ids.map(String));
          this.updateAllIndicators();
        }
      } catch (error) {
        console.warn('Failed to fetch online users:', error);
      }
    }

    /**
     * Check if a specific user is online
     * @param {number|string} userId
     * @returns {boolean}
     */
    isUserOnline(userId) {
      return this.onlineUserIds.has(String(userId));
    }

    /**
     * Update all online status indicators on the page
     */
    updateAllIndicators() {
      const indicators = document.querySelectorAll('[data-online-status]');

      indicators.forEach((indicator) => {
        const userId = indicator.getAttribute('data-online-status');
        if (!userId) return;

        const isOnline = this.isUserOnline(userId);
        this.updateIndicator(indicator, isOnline);
      });
    }

    /**
     * Update a single indicator element
     * @param {HTMLElement} element
     * @param {boolean} isOnline
     */
    updateIndicator(element, isOnline) {
      // Update classes
      element.classList.toggle('is-online', isOnline);
      element.classList.toggle('is-offline', !isOnline);

      // Update tooltip if present
      const tooltip = element.getAttribute('data-bs-original-title') || element.getAttribute('title');
      if (tooltip) {
        element.setAttribute('title', isOnline ? 'Online' : 'Offline');
        element.setAttribute('data-bs-original-title', isOnline ? 'Online' : 'Offline');
      }

      // Dispatch custom event for other components to react
      element.dispatchEvent(
        new CustomEvent('onlineStatusChanged', {
          detail: { isOnline },
          bubbles: true,
        })
      );
    }

    /**
     * Manually mark a user as online/offline (for WebSocket updates)
     * @param {number|string} userId
     * @param {boolean} isOnline
     */
    setUserStatus(userId, isOnline) {
      const userIdStr = String(userId);

      if (isOnline) {
        this.onlineUserIds.add(userIdStr);
      } else {
        this.onlineUserIds.delete(userIdStr);
      }

      // Update indicators for this specific user
      const indicators = document.querySelectorAll(`[data-online-status="${userId}"]`);
      indicators.forEach((indicator) => {
        this.updateIndicator(indicator, isOnline);
      });
    }

    /**
     * Set up WebSocket listeners for real-time presence updates
     */
    setupWebSocketListeners() {
      // Check if Socket.IO is available
      if (typeof io === 'undefined') return;

      // Try to get existing socket or wait for it
      const checkSocket = () => {
        if (window.socket && window.socket.connected) {
          this.attachSocketListeners(window.socket);
        } else {
          // Retry in 1 second
          setTimeout(checkSocket, 1000);
        }
      };

      checkSocket();
    }

    /**
     * Attach presence event listeners to socket
     * @param {Socket} socket
     */
    attachSocketListeners(socket) {
      socket.on('user_online', (data) => {
        if (data.user_id) {
          this.setUserStatus(data.user_id, true);
        }
      });

      socket.on('user_offline', (data) => {
        if (data.user_id) {
          this.setUserStatus(data.user_id, false);
        }
      });

      socket.on('presence_update', (data) => {
        if (data.user_id !== undefined && data.online !== undefined) {
          this.setUserStatus(data.user_id, data.online);
        }
      });
    }

    /**
     * Stop the manager and clear intervals
     */
    destroy() {
      if (this.intervalId) {
        clearInterval(this.intervalId);
        this.intervalId = null;
      }
      this.initialized = false;
    }

    /**
     * Get count of online users
     * @returns {number}
     */
    getOnlineCount() {
      return this.onlineUserIds.size;
    }

    /**
     * Get all online user IDs
     * @returns {Array<string>}
     */
    getOnlineUserIds() {
      return Array.from(this.onlineUserIds);
    }
  }

  // Create global instance
  window.OnlineStatusManager = new OnlineStatusManager();

  // Auto-initialize when DOM is ready - ONLY if there are status indicators on the page
  function initIfNeeded() {
    // Page guard - only initialize if there are online status elements to update
    const hasStatusIndicators = document.querySelector('[data-online-status], .c-online-status, [data-component="online-status"]');
    if (!hasStatusIndicators) {
      return; // No status indicators on this page, skip initialization
    }
    window.OnlineStatusManager.init();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initIfNeeded);
  } else {
    initIfNeeded();
  }
})();
