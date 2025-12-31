import { EventDelegation } from '../core.js';

/**
 * Push Notification Action Handlers
 * Handles push notification management actions
 */

// PUSH NOTIFICATION ACTIONS
// ============================================================================

/**
 * Refresh Notification Status
 */
EventDelegation.register('refresh-notification-status', function(element, e) {
    e.preventDefault();
    if (typeof window.refreshNotificationStatus === 'function') {
        window.refreshNotificationStatus();
    } else {
        console.error('[refresh-notification-status] refreshNotificationStatus function not found');
    }
}, { preventDefault: true });

/**
 * Send Test Notification
 */
EventDelegation.register('send-test-notification', function(element, e) {
    e.preventDefault();
    if (typeof window.sendTestNotification === 'function') {
        window.sendTestNotification();
    } else {
        console.error('[send-test-notification] sendTestNotification function not found');
    }
}, { preventDefault: true });

/**
 * Send Match Reminder
 */
EventDelegation.register('send-match-reminder', function(element, e) {
    e.preventDefault();
    if (typeof window.sendMatchReminder === 'function') {
        window.sendMatchReminder();
    } else {
        console.error('[send-match-reminder] sendMatchReminder function not found');
    }
}, { preventDefault: true });

/**
 * Send RSVP Reminder
 */
EventDelegation.register('send-rsvp-reminder-notification', function(element, e) {
    e.preventDefault();
    if (typeof window.sendRSVPReminder === 'function') {
        window.sendRSVPReminder();
    } else {
        console.error('[send-rsvp-reminder-notification] sendRSVPReminder function not found');
    }
}, { preventDefault: true });

/**
 * View Notification Logs
 */
EventDelegation.register('view-notification-logs', function(element, e) {
    e.preventDefault();
    if (typeof window.viewNotificationLogs === 'function') {
        window.viewNotificationLogs();
    } else {
        console.error('[view-notification-logs] viewNotificationLogs function not found');
    }
}, { preventDefault: true });

/**
 * Manage Tokens
 */
EventDelegation.register('manage-push-tokens', function(element, e) {
    e.preventDefault();
    if (typeof window.manageTokens === 'function') {
        window.manageTokens();
    } else {
        console.error('[manage-push-tokens] manageTokens function not found');
    }
}, { preventDefault: true });

/**
 * Cleanup Invalid Tokens
 */
EventDelegation.register('cleanup-invalid-tokens', function(element, e) {
    e.preventDefault();
    if (typeof window.cleanupInvalidTokens === 'function') {
        window.cleanupInvalidTokens();
    } else {
        console.error('[cleanup-invalid-tokens] cleanupInvalidTokens function not found');
    }
}, { preventDefault: true });

/**
 * Send Broadcast
 */
EventDelegation.register('send-broadcast', function(element, e) {
    e.preventDefault();
    if (typeof window.sendBroadcast === 'function') {
        window.sendBroadcast();
    } else {
        console.error('[send-broadcast] sendBroadcast function not found');
    }
}, { preventDefault: true });

/**
 * Confirm Send Test
 */
EventDelegation.register('confirm-send-test', function(element, e) {
    e.preventDefault();
    if (typeof window.confirmSendTest === 'function') {
        window.confirmSendTest();
    } else {
        console.error('[confirm-send-test] confirmSendTest function not found');
    }
}, { preventDefault: true });

/**
 * Mark All Notifications as Read
 * Prompts user then navigates to mark-all endpoint
 * Usage: <button data-action="mark-all-notifications-read" data-url="/mark_all_as_read">
 */
EventDelegation.register('mark-all-notifications-read', function(element, e) {
    e.preventDefault();
    if (confirm('Mark all notifications as read?')) {
        const url = element.dataset.url;
        if (url) {
            window.location.href = url;
        } else if (typeof window.markAllNotificationsAsRead === 'function') {
            window.markAllNotificationsAsRead();
        } else {
            console.error('[mark-all-notifications-read] No URL or handler available');
        }
    }
}, { preventDefault: true });

/**
 * Mark Single Notification as Read
 * Adds visual feedback (fade) when marking a notification as read
 * Usage: <a data-action="mark-read" href="/mark_notification_read/123">
 */
EventDelegation.register('mark-read', function(element, e) {
    // Don't prevent default - let the link navigate naturally
    const card = element.closest('.c-notification-card');
    if (card) {
        card.classList.add('is-fading');
    }
}, { preventDefault: false });

// ============================================================================

console.log('[EventDelegation] Push notification handlers loaded');
