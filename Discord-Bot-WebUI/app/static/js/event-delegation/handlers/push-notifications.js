import { EventDelegation } from '../core.js';
import { InitSystem } from '../../init-system.js';
import { ModalManager } from '../../modal-manager.js';
import { escapeHtml } from '../../utils/sanitize.js';

/**
 * Push Notification Action Handlers
 * Handles push notification management actions
 */

// PUSH NOTIFICATION IMPLEMENTATION FUNCTIONS
// ============================================================================

/**
 * Refresh notification status from server
 */
function refreshNotificationStatus() {
    const statusIndicator = document.getElementById('firebase-status-indicator');
    const statusContent = document.getElementById('firebase-status-content');

    if (!statusIndicator || !statusContent) return;

    // Show loading state
    statusIndicator.className = 'badge bg-secondary';
    statusIndicator.innerHTML = '<i class="ti ti-loader-2 spin me-1"></i>Checking...';

    // API call to check Firebase status using Flask session auth
    fetch('/admin/notifications/status', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        updateFirebaseStatus(data);
        updateStatistics(data);
    })
    .catch(error => {
        console.error('Error checking notification status:', error);
        statusIndicator.className = 'badge bg-danger';
        statusIndicator.innerHTML = '<i class="ti ti-x me-1"></i>Error';
        statusContent.innerHTML = `
            <div class="alert alert-danger mb-0" data-alert>
                <i class="ti ti-alert-circle me-2"></i>
                Failed to check Firebase status. Please check your connection and try again.
            </div>
        `;
    });
}

/**
 * Update Firebase status display
 */
function updateFirebaseStatus(data) {
    const statusIndicator = document.getElementById('firebase-status-indicator');
    const statusContent = document.getElementById('firebase-status-content');

    if (!statusIndicator || !statusContent) return;

    if (data.firebase_configured) {
        statusIndicator.className = 'badge bg-success';
        statusIndicator.innerHTML = '<i class="ti ti-check me-1"></i>Online';
        statusContent.innerHTML = `
            <div class="alert alert-success mb-0" data-alert>
                <i class="ti ti-check-circle me-2"></i>
                Firebase Cloud Messaging is properly configured and ready to send notifications.
            </div>
        `;
    } else {
        statusIndicator.className = 'badge bg-danger';
        statusIndicator.innerHTML = '<i class="ti ti-x me-1"></i>Not Configured';
        statusContent.innerHTML = `
            <div class="alert alert-danger mb-3" data-alert>
                <i class="ti ti-alert-circle me-2"></i>
                Firebase is not properly configured. Please check your service account configuration.
            </div>
            <ul class="list-unstyled mb-0">
                <li class="text-danger mb-1">
                    <i class="ti ti-arrow-right me-1"></i>
                    Ensure firebase-service-account.json is in your instance folder
                </li>
                <li class="text-danger mb-1">
                    <i class="ti ti-arrow-right me-1"></i>
                    Verify Firebase project settings and permissions
                </li>
            </ul>
        `;
    }
}

/**
 * Update statistics display
 */
function updateStatistics(data) {
    const totalDevices = document.getElementById('total-devices');
    const iosDevices = document.getElementById('ios-devices');
    const androidDevices = document.getElementById('android-devices');
    const notificationsSent = document.getElementById('notifications-sent');

    if (totalDevices) totalDevices.textContent = data.stats?.total_devices || '0';
    if (iosDevices) iosDevices.textContent = data.stats?.ios_devices || '0';
    if (androidDevices) androidDevices.textContent = data.stats?.android_devices || '0';
    if (notificationsSent) notificationsSent.textContent = data.stats?.notifications_sent_24h || '0';
}

/**
 * Load recent notification activity
 */
function loadRecentActivity() {
    const tableBody = document.querySelector('#notification-activity-table tbody');
    if (!tableBody) return;

    // Load recent activity using Flask session auth
    fetch('/admin/notifications/recent-activity', {
        method: 'GET',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.activities && data.activities.length > 0) {
            tableBody.innerHTML = data.activities.map(activity => `
                <tr>
                    <td>${escapeHtml(new Date(activity.timestamp).toLocaleString())}</td>
                    <td><span class="badge bg-${activity.type === 'broadcast' ? 'primary' : 'info'}" data-badge>${escapeHtml(activity.type)}</span></td>
                    <td>${escapeHtml(activity.title)}</td>
                    <td>${escapeHtml(String(activity.recipients))}</td>
                    <td>
                        <div class="progress" class="u-progress-h-6">
                            <div class="progress-bar" role="progressbar" style="width: ${parseFloat(activity.success_rate) || 0}%"></div>
                        </div>
                        <small class="text-muted">${escapeHtml(String(activity.success_rate))}%</small>
                    </td>
                    <td>
                        <span class="badge bg-${activity.status === 'success' ? 'success' : 'danger'}" data-badge>
                            ${escapeHtml(activity.status)}
                        </span>
                    </td>
                </tr>
            `).join('');
        } else {
            tableBody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center py-4 text-muted">
                        <i class="ti ti-bell-off me-2"></i>
                        No recent notification activity
                    </td>
                </tr>
            `;
        }
    })
    .catch(error => {
        console.error('Error loading recent activity:', error);
        tableBody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center py-4 text-danger">
                    <i class="ti ti-alert-circle me-2"></i>
                    Failed to load recent activity
                </td>
            </tr>
        `;
    });
}

/**
 * Show test notification modal
 */
function sendTestNotification() {
    const modal = document.getElementById('testNotificationModal');
    if (modal) {
        window.ModalManager.showByElement(modal);
    }
}

/**
 * Confirm and send test notification
 */
function confirmSendTest() {
    const modal = document.getElementById('testNotificationModal');
    const flowbiteModal = modal ? modal._flowbiteModal : null;

    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value ||
                      document.querySelector('meta[name="csrf-token"]')?.content || '';

    fetch('/admin/notifications/test-notification', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (flowbiteModal) flowbiteModal.hide();
        if (data.result && data.result.success > 0) {
            if (window.Swal) {
                window.Swal.fire({
                    title: 'Success!',
                    text: 'Test notification sent successfully',
                    icon: 'success',
                    confirmButtonText: 'OK'
                });
            }
        } else {
            if (window.Swal) {
                window.Swal.fire({
                    title: 'Failed',
                    text: data.msg || 'Failed to send test notification',
                    icon: 'error',
                    confirmButtonText: 'OK'
                });
            }
        }
        loadRecentActivity(); // Refresh activity
    })
    .catch(error => {
        if (flowbiteModal) flowbiteModal.hide();
        console.error('Error sending test notification:', error);
        if (window.Swal) {
            window.Swal.fire({
                title: 'Error',
                text: 'Failed to send test notification',
                icon: 'error',
                confirmButtonText: 'OK'
            });
        }
    });
}

/**
 * Send broadcast notification
 */
function sendBroadcast() {
    const title = document.getElementById('broadcast-title')?.value;
    const message = document.getElementById('broadcast-message')?.value;
    const target = document.getElementById('broadcast-target')?.value;

    if (!title || !message || !target) {
        if (window.Swal) {
            window.Swal.fire({
                title: 'Validation Error',
                text: 'Please fill in all required fields',
                icon: 'warning',
                confirmButtonText: 'OK'
            });
        }
        return;
    }

    const modal = document.getElementById('broadcastModal');
    const flowbiteModal = modal ? modal._flowbiteModal : null;

    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value ||
                      document.querySelector('meta[name="csrf-token"]')?.content || '';

    fetch('/admin/notifications/broadcast', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            title: title,
            message: message,
            target: target
        })
    })
    .then(response => response.json())
    .then(data => {
        if (flowbiteModal) flowbiteModal.hide();
        const form = document.getElementById('broadcastForm');
        if (form) form.reset();

        if (data.result && data.result.success > 0) {
            if (window.Swal) {
                window.Swal.fire({
                    title: 'Broadcast Sent!',
                    text: `Notification sent to ${data.result.success} devices`,
                    icon: 'success',
                    confirmButtonText: 'OK'
                });
            }
        } else {
            if (window.Swal) {
                window.Swal.fire({
                    title: 'Failed',
                    text: data.msg || 'Failed to send broadcast notification',
                    icon: 'error',
                    confirmButtonText: 'OK'
                });
            }
        }
        loadRecentActivity(); // Refresh activity
    })
    .catch(error => {
        if (flowbiteModal) flowbiteModal.hide();
        console.error('Error sending broadcast:', error);
        if (window.Swal) {
            window.Swal.fire({
                title: 'Error',
                text: 'Failed to send broadcast notification',
                icon: 'error',
                confirmButtonText: 'OK'
            });
        }
    });
}

/**
 * Send match reminder
 */
function sendMatchReminder() {
    if (window.Swal) {
        window.Swal.fire({
            title: 'Match Reminders',
            html: `
                <div class="text-start">
                    <p>Match reminders are handled via Discord for real-time delivery to players.</p>
                    <p class="mb-2"><strong>How it works:</strong></p>
                    <ul class="small text-muted">
                        <li>Automated reminders sent 24h and 2h before matches</li>
                        <li>Direct messages to players via Discord bot</li>
                        <li>Channel announcements in team channels</li>
                    </ul>
                    <p class="small text-muted mt-2">Configure timing in Discord Bot Settings.</p>
                </div>
            `,
            icon: 'info',
            confirmButtonText: 'Go to Discord Settings',
            showCancelButton: true,
            cancelButtonText: 'Close'
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = '/admin-panel/discord-bot-management';
            }
        });
    }
}

/**
 * Send RSVP reminder
 */
function sendRSVPReminder() {
    if (window.Swal) {
        window.Swal.fire({
            title: 'RSVP Reminders',
            html: `
                <div class="text-start">
                    <p>RSVP reminders are sent automatically via Discord to ensure player responses.</p>
                    <p class="mb-2"><strong>How it works:</strong></p>
                    <ul class="small text-muted">
                        <li>Reminders sent to players who haven't responded</li>
                        <li>Escalation to team captains for missing RSVPs</li>
                        <li>Configurable reminder intervals</li>
                    </ul>
                    <p class="small text-muted mt-2">Manage RSVP settings in Match Operations.</p>
                </div>
            `,
            icon: 'info',
            confirmButtonText: 'Go to Match Operations',
            showCancelButton: true,
            cancelButtonText: 'Close'
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = '/admin-panel/match-operations';
            }
        });
    }
}

/**
 * View notification logs
 */
function viewNotificationLogs() {
    if (window.Swal) {
        window.Swal.fire({
            title: 'Notification Logs',
            text: 'Notification logs are available in the system monitoring dashboard.',
            icon: 'info',
            confirmButtonText: 'Go to Monitoring',
            showCancelButton: true
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = '/admin/system_monitoring';
            }
        });
    }
}

/**
 * Manage FCM tokens
 */
function manageTokens() {
    if (window.Swal) {
        window.Swal.fire({
            title: 'FCM Token Management',
            html: `
                <div class="text-start">
                    <p>Firebase Cloud Messaging tokens are managed automatically.</p>
                    <p class="mb-2"><strong>Automatic maintenance:</strong></p>
                    <ul class="small text-muted">
                        <li>Invalid tokens cleaned up on failed delivery</li>
                        <li>Stale tokens removed after 30 days of inactivity</li>
                        <li>Duplicate tokens deduplicated automatically</li>
                    </ul>
                    <p class="small text-muted mt-2">Use the cleanup button below for manual intervention.</p>
                </div>
            `,
            icon: 'info',
            confirmButtonText: 'Run Manual Cleanup',
            showCancelButton: true,
            cancelButtonText: 'Close'
        }).then((result) => {
            if (result.isConfirmed) {
                cleanupInvalidTokens();
            }
        });
    }
}

/**
 * Cleanup invalid tokens
 */
function cleanupInvalidTokens() {
    if (window.Swal) {
        window.Swal.fire({
            title: 'Cleanup Invalid Tokens?',
            html: '<p>This will remove invalid and inactive FCM tokens from the database.</p><p class="small text-muted">This helps improve notification delivery performance.</p>',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Run Cleanup'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Cleaning Up Tokens...',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();

                        fetch('/admin-panel/communication/push-notifications/cleanup-tokens', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-Requested-With': 'XMLHttpRequest'
                            }
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                window.Swal.fire({
                                    title: 'Cleanup Complete!',
                                    html: `<p>${data.message}</p><p class="text-muted small mt-2">${data.cleaned_count || 0} tokens removed</p>`,
                                    icon: 'success'
                                });
                            } else {
                                window.Swal.fire('Error', data.message || 'Failed to cleanup tokens', 'error');
                            }
                        })
                        .catch(error => {
                            console.error('[cleanupInvalidTokens] Error:', error);
                            window.Swal.fire('Error', 'Failed to cleanup tokens. Check server connectivity.', 'error');
                        });
                    }
                });
            }
        });
    }
}

// EVENT DELEGATION HANDLERS
// ============================================================================

/**
 * Refresh Notification Status
 */
window.EventDelegation.register('refresh-notification-status', function(element, e) {
    e.preventDefault();
    refreshNotificationStatus();
}, { preventDefault: true });

/**
 * Send Test Notification
 */
window.EventDelegation.register('send-test-notification', function(element, e) {
    e.preventDefault();
    sendTestNotification();
}, { preventDefault: true });

/**
 * Send Match Reminder
 */
window.EventDelegation.register('send-match-reminder', function(element, e) {
    e.preventDefault();
    sendMatchReminder();
}, { preventDefault: true });

/**
 * Send RSVP Reminder
 */
window.EventDelegation.register('send-rsvp-reminder-notification', function(element, e) {
    e.preventDefault();
    sendRSVPReminder();
}, { preventDefault: true });

/**
 * View Notification Logs
 */
window.EventDelegation.register('view-notification-logs', function(element, e) {
    e.preventDefault();
    viewNotificationLogs();
}, { preventDefault: true });

/**
 * Manage Tokens
 */
window.EventDelegation.register('manage-push-tokens', function(element, e) {
    e.preventDefault();
    manageTokens();
}, { preventDefault: true });

/**
 * Cleanup Invalid Tokens
 */
window.EventDelegation.register('cleanup-invalid-tokens', function(element, e) {
    e.preventDefault();
    cleanupInvalidTokens();
}, { preventDefault: true });

/**
 * Send Broadcast
 */
window.EventDelegation.register('send-broadcast', function(element, e) {
    e.preventDefault();
    sendBroadcast();
}, { preventDefault: true });

/**
 * Confirm Send Test
 */
window.EventDelegation.register('confirm-send-test', function(element, e) {
    e.preventDefault();
    confirmSendTest();
}, { preventDefault: true });

/**
 * Mark All Notifications as Read
 * Prompts user then navigates to mark-all endpoint
 * Usage: <button data-action="mark-all-notifications-read" data-url="/mark_all_as_read">
 */
window.EventDelegation.register('mark-all-notifications-read', function(element, e) {
    e.preventDefault();
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Mark All as Read?',
            text: 'Mark all notifications as read?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                const url = element.dataset.url;
                if (url) {
                    window.location.href = url;
                } else if (typeof window.markAllNotificationsAsRead === 'function') {
                    window.markAllNotificationsAsRead();
                } else {
                    console.error('[mark-all-notifications-read] No URL or handler available');
                }
            }
        });
    }
}, { preventDefault: true });

/**
 * Mark Push Notification as Read
 * Adds visual feedback (fade) when marking a push notification as read
 * Note: Renamed from 'mark-read' to avoid conflict with navbar-modern.js
 * Usage: <a data-action="mark-push-notification-read" href="/mark_notification_read/123">
 */
window.EventDelegation.register('mark-push-notification-read', function(element, e) {
    // Don't prevent default - let the link navigate naturally
    const card = element.closest('.c-notification-card');
    if (card) {
        card.classList.add('is-fading');
    }
}, { preventDefault: false });

// ============================================================================

// INITIALIZATION
// ============================================================================

window.InitSystem.register('pushNotifications', function() {
    // Check if we're on the push notifications page
    const statusIndicator = document.getElementById('firebase-status-indicator');
    if (!statusIndicator) return;

    // Initialize the page
    refreshNotificationStatus();
    loadRecentActivity();

    console.log('[pushNotifications] Initialized');
}, { priority: 50 });

// Export functions for global access
window.refreshNotificationStatus = refreshNotificationStatus;
window.updateFirebaseStatus = updateFirebaseStatus;
window.updateStatistics = updateStatistics;
window.loadRecentActivity = loadRecentActivity;
window.sendTestNotification = sendTestNotification;
window.confirmSendTest = confirmSendTest;
window.sendBroadcast = sendBroadcast;
window.sendMatchReminder = sendMatchReminder;
window.sendRSVPReminder = sendRSVPReminder;
window.viewNotificationLogs = viewNotificationLogs;
window.manageTokens = manageTokens;
window.cleanupInvalidTokens = cleanupInvalidTokens;

// Handlers loaded
