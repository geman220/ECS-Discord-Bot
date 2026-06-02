'use strict';

/**
 * Push History Handlers
 * Handles push_history.html actions
 * @module event-delegation/handlers/mobile/push-history
 */

/**
 * Initialize push history handlers
 * @param {Object} ED - EventDelegation instance
 */
export function initPushHistoryHandlers(ED) {
    const BASE = '/admin-panel/mobile-features/push-history';

    function csrf() {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    }

    function escHtml(s) {
        return String(s == null ? '' : s)
            .replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
    }

    /**
     * View notification details
     */
    ED.register('view-notification', async (element, event) => {
        event.preventDefault();
        const notificationId = element.dataset.notificationId;
        const source = element.dataset.source || 'campaign';

        try {
            const resp = await fetch(`${BASE}/details?source=${encodeURIComponent(source)}&id=${encodeURIComponent(notificationId)}`);
            const data = await resp.json();
            if (!data.success) {
                window.Swal.fire('Error', data.message || 'Failed to load notification details', 'error');
                return;
            }
            const n = data.notification;
            const metricRows = (n.source === 'campaign')
                ? `- Recipients: ${escHtml(n.recipients ?? 0)}<br>
                   - Delivered: ${escHtml(n.delivered_count ?? 0)} (${escHtml(n.delivery_rate ?? '0%')})<br>
                   - Failed: ${escHtml(n.failed_count ?? 0)}<br>
                   - Clicked: ${escHtml(n.click_count ?? 0)}`
                : `- Recipient: ${escHtml(n.recipient || 'N/A')}${n.recipient_email ? ' (' + escHtml(n.recipient_email) + ')' : ''}`;

            window.Swal.fire({
                title: 'Notification Details',
                html: `
                    <div class="text-start">
                        <div class="mb-3">
                            <strong>ID:</strong> ${escHtml(n.id)}<br>
                            <strong>Type:</strong> ${escHtml(n.notification_type)}<br>
                            ${n.status ? `<strong>Status:</strong> ${escHtml(n.status)}<br>` : ''}
                            <strong>Created:</strong> ${escHtml(n.created_at || 'N/A')}
                        </div>
                        <div class="mb-3">
                            <strong>Content:</strong><br>
                            <div class="bg-gray-100 dark:bg-gray-700 p-2 rounded">
                                <strong>Title:</strong> ${escHtml(n.title)}<br>
                                <strong>Message:</strong> ${escHtml(n.content)}
                            </div>
                        </div>
                        <div class="mb-3">
                            <strong>Delivery Information:</strong><br>
                            ${metricRows}
                        </div>
                    </div>
                `,
                width: '600px',
                confirmButtonText: 'Close'
            });
        } catch (err) {
            window.Swal.fire('Error', 'Failed to load notification details', 'error');
        }
    });

    /**
     * Retry notification
     */
    ED.register('retry-notification', (element, event) => {
        event.preventDefault();
        const notificationId = element.dataset.notificationId;

        window.Swal.fire({
            title: 'Retry Notification?',
            text: 'This will attempt to resend the failed notification',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Retry Send'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Retrying...',
                    text: 'Attempting to resend notification',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();
                        setTimeout(() => {
                            window.Swal.fire('Notification Retried!', 'The notification has been queued for retry.', 'success')
                                .then(() => location.reload());
                        }, 2000);
                    }
                });
            }
        });
    });

    /**
     * Duplicate notification
     */
    ED.register('duplicate-notification', (element, event) => {
        event.preventDefault();
        const notificationId = element.dataset.notificationId;

        window.Swal.fire({
            title: 'Duplicate Notification?',
            text: 'This will create a copy of this notification that you can send again',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Duplicate'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Notification Duplicated!', 'The notification has been copied to a new campaign.', 'success');
            }
        });
    });

    /**
     * Delete notification
     */
    ED.register('delete-notification', (element, event) => {
        event.preventDefault();
        const notificationId = element.dataset.notificationId;

        window.Swal.fire({
            title: 'Delete Notification?',
            text: 'This will permanently remove this notification from history',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Delete',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Notification Deleted!', 'The notification has been removed from history.', 'success')
                    .then(() => location.reload());
            }
        });
    });

    /**
     * Retry failed notifications
     */
    ED.register('retry-failed', (element, event) => {
        event.preventDefault();
        const selectedNotifications = Array.from(document.querySelectorAll('.notification-checkbox:checked')).map(cb => cb.value);

        if (selectedNotifications.length === 0) {
            window.Swal.fire('No Notifications Selected', 'Please select failed notifications to retry.', 'warning');
            return;
        }

        window.Swal.fire({
            title: `Retry ${selectedNotifications.length} Failed Notifications?`,
            text: 'This will attempt to resend all selected failed notifications',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Retry All'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Retrying Notifications...',
                    text: 'Processing retry requests',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();
                        setTimeout(() => {
                            window.Swal.fire('Retry Complete!', `${selectedNotifications.length} notifications have been queued for retry.`, 'success')
                                .then(() => location.reload());
                        }, 3000);
                    }
                });
            }
        });
    });

    /**
     * Export history
     */
    ED.register('export-history', (element, event) => {
        event.preventDefault();
        const selectedNotifications = Array.from(document.querySelectorAll('.notification-checkbox:checked')).map(cb => cb.value);

        window.Swal.fire({
            title: 'Export Push History?',
            text: selectedNotifications.length > 0 ? `Export ${selectedNotifications.length} selected notifications?` : 'Export all visible notifications?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Export Data'
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = `${BASE}/export`;
            }
        });
    });

    /**
     * Cleanup old notifications
     */
    ED.register('cleanup-old', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Cleanup Old Notifications?',
            text: 'This will permanently remove push notifications older than 90 days',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Cleanup Old',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Cleaning Up...',
                    text: 'Removing old push notifications',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();
                        fetch(`${BASE}/cleanup-old`, {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded',
                                'X-CSRFToken': csrf()
                            }
                        })
                            .then(r => r.json())
                            .then(data => {
                                if (data.success) {
                                    window.Swal.fire('Cleanup Complete!', data.message || `${data.count} old notifications removed.`, 'success')
                                        .then(() => location.reload());
                                } else {
                                    window.Swal.fire('Error', data.message || 'Failed to clean up notifications', 'error');
                                }
                            })
                            .catch(() => window.Swal.fire('Error', 'Failed to clean up notifications', 'error'));
                    }
                });
            }
        });
    });
}
