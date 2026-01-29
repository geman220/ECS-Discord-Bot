'use strict';

/**
 * Quick Actions - Content Management
 *
 * Event delegation handlers for content management quick actions:
 * - Sync templates
 * - Test notifications
 * - Emergency alerts
 * - Data export
 *
 * @module quick-actions/content
 */

/**
 * Sync Templates
 * Synchronizes message templates
 */
window.EventDelegation.register('sync-templates', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[sync-templates] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Sync Message Templates?',
        html: '<p>This will synchronize all message templates with the latest versions from the database.</p>',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Sync Templates'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Syncing Templates...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/sync-templates', {
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
                                title: 'Templates Synced!',
                                html: `<p>${data.message}</p><p class="text-gray-500 dark:text-gray-400 small mt-2">${data.synced_count || 0} templates synchronized</p>`,
                                icon: 'success'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to sync templates', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[sync-templates] Error:', error);
                        window.Swal.fire('Error', 'Failed to sync templates. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Quick Test Notifications
 * Sends a test push notification (quick actions menu)
 * Note: Renamed from 'test-notifications' to avoid conflict with monitoring-handlers.js
 */
window.EventDelegation.register('quick-test-notifications', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[quick-test-notifications] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Send Test Notification?',
        text: 'This will send a test push notification to your devices.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Send Test'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Sending Test...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin/notifications/test-notification', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.msg && !data.msg.includes('error') && !data.msg.includes('Error')) {
                            window.Swal.fire('Test Sent!', data.msg, 'success');
                        } else {
                            window.Swal.fire('Notice', data.msg || 'Test notification processed.', 'info');
                        }
                    })
                    .catch(error => {
                        console.error('[quick-test-notifications] Error:', error);
                        window.Swal.fire('Error', 'Failed to send test notification.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Send Emergency Alert
 * Sends an emergency alert to all users
 */
window.EventDelegation.register('send-emergency-alert', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[send-emergency-alert] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Send Emergency Alert',
        html: `
            <div class="p-4 mb-3 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>
                <strong>Warning:</strong> This will send an emergency push notification to all users.
            </div>
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Alert Title</label>
                <input type="text" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="emergencyTitle" placeholder="Emergency alert title" value="Emergency Alert" data-form-control>
            </div>
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Alert Message</label>
                <textarea class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="emergencyMessage" rows="3" placeholder="Enter emergency alert message" data-form-control></textarea>
            </div>
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Alert Level</label>
                <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="alertLevel" data-form-select>
                    <option value="info">Info</option>
                    <option value="warning">Warning</option>
                    <option value="critical" selected>Critical</option>
                </select>
            </div>
        `,
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: 'Send Emergency Alert',
        preConfirm: () => {
            const title = document.getElementById('emergencyTitle').value;
            const message = document.getElementById('emergencyMessage').value;
            const level = document.getElementById('alertLevel').value;

            if (!message) {
                window.Swal.showValidationMessage('Alert message is required');
                return false;
            }

            return { title, message, level };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Sending Alert...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/send-emergency-alert', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(result.value)
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire({
                                title: 'Alert Sent!',
                                html: `<p>${data.message}</p><p class="text-gray-500 dark:text-gray-400 small mt-2">${data.sent_count || 0} notifications sent</p>`,
                                icon: 'warning'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to send alert', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[send-emergency-alert] Error:', error);
                        window.Swal.fire('Error', 'Failed to send emergency alert. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Export System Data
 * Exports system data in various formats
 */
window.EventDelegation.register('export-system-data', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[export-system-data] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Export System Data',
        html: `
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Data to Export</label>
                <div class="flex items-center mb-2">
                    <input class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600" type="checkbox" id="exportUsers" checked>
                    <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="exportUsers">User Data</label>
                </div>
                <div class="flex items-center mb-2">
                    <input class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600" type="checkbox" id="exportSettings" checked>
                    <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="exportSettings">System Settings</label>
                </div>
                <div class="flex items-center mb-2">
                    <input class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600" type="checkbox" id="exportLogs">
                    <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="exportLogs">Audit Logs</label>
                </div>
                <div class="flex items-center mb-2">
                    <input class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600" type="checkbox" id="exportTemplates">
                    <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="exportTemplates">Message Templates</label>
                </div>
            </div>
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Export Format</label>
                <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="exportFormat" data-form-select>
                    <option value="json" selected>JSON</option>
                </select>
                <small class="text-gray-500 dark:text-gray-400">JSON format exports all selected data types</small>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Export Data',
        preConfirm: () => {
            return {
                include_users: document.getElementById('exportUsers').checked,
                include_settings: document.getElementById('exportSettings').checked,
                include_logs: document.getElementById('exportLogs').checked,
                include_templates: document.getElementById('exportTemplates').checked,
                format: document.getElementById('exportFormat').value
            };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Exporting Data...',
                html: '<p>Generating system data export...</p><p class="text-gray-500 dark:text-gray-400 small">This may take a moment for large datasets</p>',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/export-system-data', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(result.value)
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            // Create download link
                            const blob = new Blob([JSON.stringify(data.export_data, null, 2)], { type: 'application/json' });
                            const url = window.URL.createObjectURL(blob);
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = data.filename || 'system-export.json';
                            document.body.appendChild(a);
                            a.click();
                            window.URL.revokeObjectURL(url);
                            document.body.removeChild(a);

                            window.Swal.fire({
                                title: 'Export Complete!',
                                html: `<p>${data.message}</p><p class="text-gray-500 dark:text-gray-400 small mt-2">File: ${data.filename}</p>`,
                                icon: 'success'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to export data', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[export-system-data] Error:', error);
                        window.Swal.fire('Error', 'Failed to export data. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});
