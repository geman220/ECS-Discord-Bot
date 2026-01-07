/**
 * Navbar - Notifications
 * Notification loading, rendering, and management
 *
 * @module navbar/notifications
 */

import { CONFIG, getCSRFToken, escapeHtml, showToast } from './config.js';

/**
 * Initialize notifications
 */
export function initNotifications() {
  // Load notifications on page load
  loadNotifications();

  // Refresh notification count periodically
  setInterval(() => refreshNotificationCount(), CONFIG.notificationRefreshInterval);
}

/**
 * Load notifications from API
 */
export async function loadNotifications() {
  const container = document.getElementById('notifications-list');
  if (!container) return;

  const loadingEl = container.querySelector('[data-state="loading"]');
  const emptyEl = container.querySelector('[data-state="empty"]');

  try {
    const response = await fetch('/api/notifications?include_read=true&limit=10');
    const data = await response.json();

    // Hide loading
    if (loadingEl) loadingEl.classList.add('u-hidden');

    if (data.success && data.notifications.length > 0) {
      // Hide empty state
      if (emptyEl) emptyEl.classList.add('u-hidden');

      // Remove existing notifications (but keep loading/empty elements)
      container.querySelectorAll('.c-navbar-modern__notification').forEach(el => el.remove());

      // Render notifications
      data.notifications.forEach(notification => {
        const notifEl = createNotificationElement(notification);
        container.appendChild(notifEl);
      });

      // Update badge count
      updateNotificationBadge(data.unread_count);
    } else {
      // Show empty state
      if (emptyEl) emptyEl.classList.remove('u-hidden');
      updateNotificationBadge(0);
    }
  } catch (error) {
    console.error('Error loading notifications:', error);
    if (loadingEl) loadingEl.classList.add('u-hidden');
    if (emptyEl) {
      emptyEl.classList.remove('u-hidden');
      const emptyText = emptyEl.querySelector('p');
      if (emptyText) emptyText.textContent = 'Failed to load notifications';
    }
  }
}

/**
 * Create a notification DOM element
 * @param {Object} notification - Notification data
 * @returns {HTMLElement}
 */
export function createNotificationElement(notification) {
  const div = document.createElement('div');
  div.className = `c-navbar-modern__notification${notification.is_read ? '' : ' is-unread'}`;
  div.setAttribute('data-notification-id', notification.id);
  div.setAttribute('role', 'menuitem');
  div.setAttribute('tabindex', '0');

  // Icon color class
  const colorClass = notification.icon_color ? `text-${notification.icon_color}` : '';

  // Truncate long messages
  const truncatedMessage = notification.message.length > 80
    ? notification.message.substring(0, 80) + '...'
    : notification.message;
  const hasMore = notification.message.length > 80;

  div.innerHTML = `
    <div class="c-navbar-modern__notification-main"
         data-action="expand-notification"
         data-notification-id="${notification.id}">
      <div class="c-navbar-modern__notification-icon ${colorClass}">
        <i class="${notification.icon}"></i>
      </div>
      <div class="c-navbar-modern__notification-content">
        <p class="c-navbar-modern__notification-title">${escapeHtml(notification.title)}</p>
        <p class="c-navbar-modern__notification-text">${escapeHtml(truncatedMessage)}</p>
        ${hasMore ? '<span class="c-navbar-modern__notification-expand-hint">Click to read more</span>' : ''}
      </div>
      <span class="c-navbar-modern__notification-time">${notification.time_ago}</span>
    </div>
    <div class="c-navbar-modern__notification-expanded u-hidden" data-expanded-content>
      <p class="c-navbar-modern__notification-full-text">${escapeHtml(notification.message)}</p>
      <span class="c-navbar-modern__notification-date">${notification.created_at || ''}</span>
    </div>
    <button class="c-navbar-modern__notification-dismiss"
            data-action="dismiss-notification"
            data-notification-id="${notification.id}"
            aria-label="Dismiss notification"
            title="Dismiss">
      <i class="ti ti-x" aria-hidden="true"></i>
    </button>
  `;

  return div;
}

/**
 * Toggle notification expansion
 * @param {string} notificationId - Notification ID
 */
export function toggleNotificationExpand(notificationId) {
  const notification = document.querySelector(`[data-notification-id="${notificationId}"]`);
  if (!notification) return;

  const expandedContent = notification.querySelector('[data-expanded-content]');
  if (!expandedContent) return;

  const isExpanded = notification.classList.contains('is-expanded');

  if (isExpanded) {
    notification.classList.remove('is-expanded');
    expandedContent.classList.add('u-hidden');
  } else {
    notification.classList.add('is-expanded');
    expandedContent.classList.remove('u-hidden');

    // Mark as read when expanded
    if (notification.classList.contains('is-unread')) {
      markNotificationRead(notificationId);
    }
  }
}

/**
 * Mark notification as read
 * @param {string} notificationId - Notification ID
 */
export async function markNotificationRead(notificationId) {
  const notification = document.querySelector(`[data-notification-id="${notificationId}"]`);
  if (!notification) return;

  // Optimistically update UI
  notification.classList.remove('is-unread');

  try {
    const response = await fetch(`/api/notifications/${notificationId}/read`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      }
    });

    const data = await response.json();
    if (data.success) {
      updateNotificationBadge(data.unread_count);
    }
  } catch (error) {
    console.error('Mark notification read error:', error);
    // Revert on error
    notification.classList.add('is-unread');
  }
}

/**
 * Mark all notifications as read
 */
export async function markAllNotificationsRead() {
  const notifications = document.querySelectorAll('.c-navbar-modern__notification.is-unread');

  // Optimistically update UI
  notifications.forEach(notification => {
    notification.classList.remove('is-unread');
  });

  try {
    const response = await fetch('/api/notifications/mark-all-read', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      }
    });

    const data = await response.json();
    if (data.success) {
      updateNotificationBadge(0);
      showToast('All notifications marked as read', 'success');
    }
  } catch (error) {
    console.error('Mark all read error:', error);
    // Revert - reload notifications
    loadNotifications();
  }
}

/**
 * Dismiss a notification
 * @param {string} notificationId - Notification ID
 */
export async function dismissNotification(notificationId) {
  const notification = document.querySelector(`[data-notification-id="${notificationId}"]`);
  if (!notification) return;

  // Optimistically remove with animation
  notification.classList.add('is-dismissing');

  try {
    const response = await fetch(`/api/notifications/${notificationId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      }
    });

    const data = await response.json();

    if (data.success) {
      // Remove from DOM after animation
      setTimeout(() => {
        notification.remove();
        updateNotificationBadge(data.unread_count);

        // Show empty state if no more notifications
        const container = document.getElementById('notifications-list');
        const remaining = container.querySelectorAll('.c-navbar-modern__notification');
        if (remaining.length === 0) {
          const emptyEl = container.querySelector('[data-state="empty"]');
          if (emptyEl) emptyEl.classList.remove('u-hidden');
        }
      }, 200);
    } else {
      // Revert animation on failure
      notification.classList.remove('is-dismissing');
      showToast('Failed to dismiss notification', 'error');
    }
  } catch (error) {
    console.error('Dismiss notification error:', error);
    notification.classList.remove('is-dismissing');
    showToast('Failed to dismiss notification', 'error');
  }
}

/**
 * Clear all notifications
 */
export async function clearAllNotifications() {
  const container = document.getElementById('notifications-list');
  const notifications = container.querySelectorAll('.c-navbar-modern__notification');

  if (notifications.length === 0) {
    showToast('No notifications to clear', 'info');
    return;
  }

  // Confirm with user using SweetAlert2
  if (typeof window.Swal !== 'undefined') {
    const result = await window.Swal.fire({
      title: 'Clear All Notifications',
      text: 'Are you sure you want to clear all notifications?',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Yes, clear all',
      cancelButtonText: 'Cancel'
    });
    if (!result.isConfirmed) {
      return;
    }
  }

  // Optimistically fade out all
  notifications.forEach(n => n.classList.add('is-dismissing'));

  try {
    const response = await fetch('/api/notifications/clear-all', {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      }
    });

    const data = await response.json();

    if (data.success) {
      // Remove all from DOM
      setTimeout(() => {
        notifications.forEach(n => n.remove());
        updateNotificationBadge(0);

        // Show empty state
        const emptyEl = container.querySelector('[data-state="empty"]');
        if (emptyEl) emptyEl.classList.remove('u-hidden');

        showToast(`Cleared ${data.deleted_count} notification${data.deleted_count !== 1 ? 's' : ''}`, 'success');
      }, 200);
    } else {
      // Revert on failure
      notifications.forEach(n => n.classList.remove('is-dismissing'));
      showToast('Failed to clear notifications', 'error');
    }
  } catch (error) {
    console.error('Clear all notifications error:', error);
    notifications.forEach(n => n.classList.remove('is-dismissing'));
    showToast('Failed to clear notifications', 'error');
  }
}

/**
 * Refresh notification count only (lightweight)
 */
export async function refreshNotificationCount() {
  try {
    const response = await fetch('/api/notifications/count');
    const data = await response.json();
    if (data.success) {
      updateNotificationBadge(data.count);
    }
  } catch (error) {
    console.error('Error refreshing notification count:', error);
  }
}

/**
 * Update notification badge display
 * @param {number} count - Unread count
 */
export function updateNotificationBadge(count) {
  const badges = document.querySelectorAll('[data-badge="notification-count"]');
  badges.forEach(badge => {
    if (count > 0) {
      badge.textContent = count > 99 ? '99+' : count;
      badge.classList.remove('u-hidden');
    } else {
      badge.classList.add('u-hidden');
    }
  });
}

export default {
  initNotifications,
  loadNotifications,
  createNotificationElement,
  toggleNotificationExpand,
  markNotificationRead,
  markAllNotificationsRead,
  dismissNotification,
  clearAllNotifications,
  refreshNotificationCount,
  updateNotificationBadge
};
