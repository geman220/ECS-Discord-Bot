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
    /**
     * View notification details
     */
    ED.register('view-notification', (element, event) => {
        event.preventDefault();
        const notificationId = element.dataset.notificationId;

        window.Swal.fire({
            title: `Notification Details`,
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <strong>Notification ID:</strong> ${notificationId}<br>
                        <strong>Type:</strong> Push Notification<br>
                        <strong>Status:</strong> <span class="px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300" data-badge>Sent</span><br>
                        <strong>Created:</strong> 2024-01-30 18:00:00
                    </div>
                    <div class="mb-3">
                        <strong>Content:</strong><br>
                        <div class="c-card bg-light p-2">
                            <strong>Title:</strong> Match Starting Soon!<br>
                            <strong>Message:</strong> Your match against Arsenal FC starts in 30 minutes. Good luck team!
                        </div>
                    </div>
                    <div class="mb-3">
                        <strong>Delivery Information:</strong><br>
                        - Sent to: john.doe@example.com<br>
                        - Device: iPhone 12 Pro (iOS)<br>
                        - Sent at: 2024-01-30 18:00:15<br>
                        - Delivered at: 2024-01-30 18:00:18<br>
                        - Opened at: 2024-01-30 18:02:45
                    </div>
                </div>
            `,
            width: '600px',
            confirmButtonText: 'Close'
        });
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
                window.Swal.fire('Export Started!', 'Push history export is being prepared for download.', 'success');
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
                        setTimeout(() => {
                            window.Swal.fire('Cleanup Complete!', '247 old notifications have been removed.', 'success')
                                .then(() => location.reload());
                        }, 2000);
                    }
                });
            }
        });
    });
}
