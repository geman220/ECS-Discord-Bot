'use strict';

/**
 * Online Users Widget Module
 * Extracted from components/_online_users_widget.html
 * Handles real-time display of online users
 * @module online-users-widget
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Initialize Online Users Widget
 */
export function init() {
    const widget = document.querySelector('[data-component="online-users-widget"]');
    if (!widget) return;

    const countEl = widget.querySelector('[data-online-count]');
    const listEl = widget.querySelector('[data-online-users-list]');
    const loadingEl = widget.querySelector('[data-state="loading"]');
    const emptyEl = widget.querySelector('[data-state="empty"]');

    let updateInterval = null;

    /**
     * Fetch and render online users
     */
    async function fetchOnlineUsers() {
        try {
            const response = await fetch('/api/notifications/presence/online-users?details=true&limit=10');
            const data = await response.json();

            if (data.success) {
                renderUsers(data.online_users || [], data.count || 0);
            }
        } catch (error) {
            console.warn('[OnlineUsersWidget] Failed to fetch online users:', error);
        }
    }

    /**
     * Render user list
     * @param {Array} users - List of online users
     * @param {number} totalCount - Total count of online users
     */
    function renderUsers(users, totalCount) {
        // Update count
        if (countEl) {
            const oldCount = parseInt(countEl.textContent, 10);
            countEl.textContent = totalCount;

            if (oldCount !== totalCount) {
                countEl.classList.add('is-updating');
                setTimeout(() => countEl.classList.remove('is-updating'), 500);
            }
        }

        // Hide loading
        if (loadingEl) {
            loadingEl.classList.add('u-hidden');
        }

        // Remove existing user items (but keep loading/empty states)
        const existingUsers = listEl.querySelectorAll('.c-online-widget__user');
        existingUsers.forEach(el => el.remove());

        // Show empty state if no users
        if (users.length === 0) {
            if (emptyEl) emptyEl.classList.remove('u-hidden');
            return;
        }

        // Hide empty state
        if (emptyEl) emptyEl.classList.add('u-hidden');

        // Create user items
        users.forEach(user => {
            const li = document.createElement('li');
            const profileUrl = user.profile_url || '#';
            const avatarUrl = user.avatar_url || '/static/img/default_player.png';
            const name = user.name || user.username || 'User';

            li.innerHTML = `
                <a href="${profileUrl}"
                   class="c-online-widget__user"
                   data-user-id="${user.id}"
                   title="View ${name}'s profile">
                    <div class="c-online-widget__user-avatar">
                        <img src="${avatarUrl}"
                             alt="${name}"
                             class="c-online-widget__user-avatar-img"
                             onerror="this.src='/static/img/default_player.png'">
                        <span class="c-online-status c-online-status--sm is-online"
                              data-online-status="${user.id}"></span>
                    </div>
                    <span class="c-online-widget__user-name">${name}</span>
                </a>
            `;

            listEl.appendChild(li);
        });
    }

    // Initial fetch
    fetchOnlineUsers();

    // Set up periodic refresh
    const refreshInterval = parseInt(widget.getAttribute('data-refresh-interval'), 10) || 30000;
    updateInterval = setInterval(fetchOnlineUsers, refreshInterval);

    // Listen for WebSocket presence updates if available
    if (window.socket) {
        window.socket.on('user_online', fetchOnlineUsers);
        window.socket.on('user_offline', fetchOnlineUsers);
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', function() {
        if (updateInterval) {
            clearInterval(updateInterval);
        }
    });

    console.log('[OnlineUsersWidget] Initialized');
}

// Register with InitSystem
if (typeof InitSystem !== 'undefined' && InitSystem.register) {
    InitSystem.register('online-users-widget', init, {
        priority: 40,
        description: 'Online users widget module'
    });
} else if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('online-users-widget', init, {
        priority: 40,
        description: 'Online users widget module'
    });
}

// Window exports for backward compatibility
window.OnlineUsersWidget = {
    init: init
};
