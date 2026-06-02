'use strict';

/**
 * Mobile Users Handlers
 * Handles mobile_users.html actions
 * @module event-delegation/handlers/mobile/users
 */

/**
 * Initialize mobile users handlers
 * @param {Object} ED - EventDelegation instance
 */
export function initMobileUsersHandlers(ED) {
    const BASE = '/admin-panel/mobile-features';

    function csrf() {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    }

    function postForm(url, params) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrf()
            },
            body: new URLSearchParams(params).toString()
        }).then(r => r.json());
    }

    /**
     * View mobile user details
     */
    ED.register('view-user-details', async (element, event) => {
        event.preventDefault();
        const userId = element.dataset.userId;

        if (!userId) {
            window.Swal.fire('Error', 'User ID not available', 'error');
            return;
        }

        try {
            const response = await fetch(`${BASE}/user/details?user_id=${userId}`);
            const data = await response.json();

            if (data.success) {
                const user = data.user;
                let deviceTokensHtml = '';

                if (user.device_tokens && user.device_tokens.length > 0) {
                    deviceTokensHtml = user.device_tokens.map(token => {
                        const badgeClass = token.is_active
                            ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300'
                            : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
                        return `
                        <div class="mb-2">
                            <div class="flex justify-between items-center">
                                <div>
                                    <strong class="text-gray-900 dark:text-white">Token:</strong> <span class="text-gray-700 dark:text-gray-300">${token.token.substring(0, 20)}...</span><br>
                                    <small class="text-gray-500 dark:text-gray-400">Platform: ${token.platform || 'Unknown'} | Created: ${token.created_at ? new Date(token.created_at).toLocaleDateString() : 'Unknown'}</small>
                                </div>
                                <span class="px-2 py-0.5 text-xs font-medium rounded ${badgeClass}" data-badge>
                                    ${token.is_active ? 'Active' : 'Inactive'}
                                </span>
                            </div>
                        </div>
                    `;
                    }).join('');
                } else {
                    deviceTokensHtml = '<p class="text-gray-500 dark:text-gray-400">No device tokens found</p>';
                }

                window.Swal.fire({
                    title: `User Details: ${user.username || 'Unknown'}`,
                    html: `
                        <div class="text-start">
                            <div class="mb-3">
                                <strong>User ID:</strong> ${user.id}<br>
                                <strong>Username:</strong> ${user.username || 'Unknown'}<br>
                                <strong>Email:</strong> ${user.email || 'No email'}<br>
                                <strong>Joined:</strong> ${user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unknown'}
                            </div>
                            <div class="mb-3">
                                <strong>Device Tokens:</strong><br>
                                ${deviceTokensHtml}
                            </div>
                        </div>
                    `,
                    width: '600px',
                    confirmButtonText: 'Close'
                });
            } else {
                window.Swal.fire('Error', data.message || 'Failed to load user details', 'error');
            }
        } catch (error) {
            console.error('Error fetching user details:', error);
            window.Swal.fire('Error', 'Failed to load user details', 'error');
        }
    });

    /**
     * Send notification to a single user
     */
    ED.register('send-notification', (element, event) => {
        event.preventDefault();
        const userId = element.dataset.userId;

        window.Swal.fire({
            title: 'Send Push Notification',
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Notification Title</label>
                        <input type="text" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="notificationTitle" placeholder="Match Update" data-form-control>
                    </div>
                    <div class="mb-3">
                        <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Notification Message</label>
                        <textarea class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="notificationMessage" rows="3" placeholder="Your match against Arsenal FC starts in 30 minutes!" data-form-control></textarea>
                    </div>
                    <div class="mb-3">
                        <div class="flex items-center">
                            <input type="checkbox" id="highPriority" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                            <label for="highPriority" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">
                                High Priority Notification
                            </label>
                        </div>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Send Notification',
            width: '500px',
            showLoaderOnConfirm: true,
            allowOutsideClick: () => !window.Swal.isLoading(),
            preConfirm: () => {
                const title = document.getElementById('notificationTitle').value;
                const message = document.getElementById('notificationMessage').value;

                if (!title || !message) {
                    window.Swal.showValidationMessage('Please fill in both title and message');
                    return false;
                }

                return postForm(`${BASE}/user/send-notification`, {
                    user_id: userId, title, message
                })
                    .then(data => {
                        if (!data.success) {
                            window.Swal.showValidationMessage(data.message || 'Failed to send notification');
                        }
                        return data;
                    })
                    .catch(() => window.Swal.showValidationMessage('Failed to send notification'));
            }
        }).then((result) => {
            if (result.isConfirmed && result.value && result.value.success) {
                window.Swal.fire('Notification Sent!', result.value.message || 'Push notification has been sent to the user.', 'success');
            }
        });
    });

    /**
     * Escape HTML to prevent XSS when injecting API data into the DOM.
     */
    function escapeHtml(str) {
        return String(str ?? '').replace(/[&<>"']/g, (c) => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    /**
     * Render the real device-token list for the device-management modal.
     */
    function renderDeviceTokens(tokens) {
        if (!tokens || tokens.length === 0) {
            return '<p class="text-gray-500 dark:text-gray-400 p-3">No registered devices found for this user.</p>';
        }
        return `
            <div class="divide-y divide-gray-200 dark:divide-gray-700 border border-gray-200 dark:border-gray-700 rounded-lg">
                ${tokens.map(token => {
                    const platform = escapeHtml(token.platform || 'Unknown');
                    const created = token.created_at ? new Date(token.created_at).toLocaleDateString() : 'Unknown';
                    const updated = token.updated_at ? new Date(token.updated_at).toLocaleDateString() : 'Unknown';
                    const tokenPreview = escapeHtml(token.token || '');
                    const statusBadge = token.is_active
                        ? '<span class="px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300">Active</span>'
                        : '<span class="px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300">Inactive</span>';
                    const actionBtn = token.is_active
                        ? `<button class="text-yellow-600 bg-transparent border border-yellow-600 hover:bg-yellow-600 hover:text-white focus:ring-4 focus:ring-yellow-300 font-medium rounded-lg text-xs p-1.5" data-action="deactivate-device" data-token-id="${escapeHtml(token.id)}" aria-label="Deactivate device"><i class="ti ti-ban"></i></button>`
                        : '';
                    return `
                        <div class="flex justify-between items-center p-3">
                            <div>
                                <strong class="text-gray-900 dark:text-white">${platform}</strong> ${statusBadge}<br>
                                <small class="text-gray-500 dark:text-gray-400">Token: ${tokenPreview} - Registered: ${escapeHtml(created)} - Updated: ${escapeHtml(updated)}</small>
                            </div>
                            <div>${actionBtn}</div>
                        </div>
                    `;
                }).join('')}
            </div>
        `;
    }

    /**
     * Manage devices for a user (real device tokens from the API).
     */
    ED.register('manage-devices', async (element, event) => {
        event.preventDefault();
        const userId = element.dataset.userId;

        if (!userId) {
            window.Swal.fire('Error', 'User ID not available', 'error');
            return;
        }

        window.Swal.fire({
            title: 'Device Management',
            html: '<p class="text-gray-500 dark:text-gray-400 p-3">Loading device information...</p>',
            width: '600px',
            confirmButtonText: 'Close',
            didOpen: () => window.Swal.showLoading()
        });

        try {
            const response = await fetch(`${BASE}/user/details?user_id=${encodeURIComponent(userId)}`);
            const data = await response.json();

            if (!data.success) {
                window.Swal.fire('Error', data.message || 'Failed to load device information', 'error');
                return;
            }

            const tokens = (data.user && data.user.device_tokens) || [];
            window.Swal.fire({
                title: 'Device Management',
                html: `<div class="text-start">${renderDeviceTokens(tokens)}</div>`,
                width: '600px',
                confirmButtonText: 'Close'
            });
        } catch (error) {
            console.error('Error fetching device information:', error);
            window.Swal.fire('Error', 'Failed to load device information', 'error');
        }
    });

    /**
     * Deactivate a device
     */
    ED.register('deactivate-device', (element, event) => {
        event.preventDefault();
        const tokenId = element.dataset.tokenId;
        const deactivateUrl = element.dataset.deactivateUrl || `${BASE}/device-token/deactivate`;
        const csrfToken = csrf();

        window.Swal.fire({
            title: 'Deactivate Device?',
            text: 'This will stop push notifications to this device',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Deactivate',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                fetch(deactivateUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                        'X-CSRFToken': csrfToken
                    },
                    body: `token_id=${tokenId}`
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.Swal.fire('Device Deactivated!', 'The device has been deactivated successfully.', 'success');
                    } else {
                        window.Swal.fire('Error', data.message || 'Failed to deactivate device', 'error');
                    }
                })
                .catch(error => {
                    window.Swal.fire('Error', 'Failed to deactivate device', 'error');
                });
            }
        });
    });

    /**
     * Send bulk notification
     */
    ED.register('send-bulk-notification', (element, event) => {
        event.preventDefault();
        const selectedUsers = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);

        if (selectedUsers.length === 0) {
            window.Swal.fire('No Users Selected', 'Please select users to send notifications to.', 'warning');
            return;
        }

        window.Swal.fire({
            title: `Send Bulk Notification (${selectedUsers.length} users)`,
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Notification Title</label>
                        <input type="text" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="bulkNotificationTitle" placeholder="Important Update" data-form-control>
                    </div>
                    <div class="mb-3">
                        <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Notification Message</label>
                        <textarea class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="bulkNotificationMessage" rows="3" placeholder="Check out the latest updates in the app!" data-form-control></textarea>
                    </div>
                    <div class="mb-3">
                        <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Send Schedule</label>
                        <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="sendSchedule" data-form-select>
                            <option value="immediate">Send Immediately</option>
                            <option value="scheduled">Schedule for Later</option>
                        </select>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Send to All Selected',
            width: '500px',
            showLoaderOnConfirm: true,
            allowOutsideClick: () => !window.Swal.isLoading(),
            preConfirm: () => {
                const title = document.getElementById('bulkNotificationTitle').value;
                const message = document.getElementById('bulkNotificationMessage').value;

                if (!title || !message) {
                    window.Swal.showValidationMessage('Please fill in both title and message');
                    return false;
                }

                return postForm(`${BASE}/user/send-bulk-notification`, {
                    user_ids: selectedUsers.join(','), title, message
                })
                    .then(data => {
                        if (!data.success) {
                            window.Swal.showValidationMessage(data.message || 'Failed to send notification');
                        }
                        return data;
                    })
                    .catch(() => window.Swal.showValidationMessage('Failed to send notification'));
            }
        }).then((result) => {
            if (result.isConfirmed && result.value && result.value.success) {
                window.Swal.fire('Bulk Notification Sent!', result.value.message || `Notification sent to ${selectedUsers.length} users.`, 'success');
            }
        });
    });

    /**
     * Export user data
     */
    ED.register('export-user-data', (element, event) => {
        event.preventDefault();
        const selectedUsers = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);

        window.Swal.fire({
            title: 'Export User Data?',
            text: selectedUsers.length > 0 ? `Export data for ${selectedUsers.length} selected users?` : 'Export data for all visible users?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Export Data'
        }).then((result) => {
            if (result.isConfirmed) {
                let url = `${BASE}/user/export`;
                if (selectedUsers.length > 0) {
                    url += `?user_ids=${encodeURIComponent(selectedUsers.join(','))}`;
                }
                window.location.href = url;
            }
        });
    });

    /**
     * Bulk device management
     */
    ED.register('bulk-device-management', (element, event) => {
        event.preventDefault();
        const selectedUsers = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);

        if (selectedUsers.length === 0) {
            window.Swal.fire('No Users Selected', 'Please select users to manage their devices.', 'warning');
            return;
        }

        window.Swal.fire({
            title: `Bulk Device Management (${selectedUsers.length} users)`,
            html: `
                <div class="text-start">
                    <div class="divide-y divide-gray-200 dark:divide-gray-700 border border-gray-200 dark:border-gray-700 rounded-lg">
                        <button class="w-full text-left p-3 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" data-action="bulk-deactivate-devices">
                            <i class="ti ti-ban text-red-600 me-2"></i>
                            <strong class="text-gray-900 dark:text-white">Deactivate All Devices</strong><br>
                            <small class="text-gray-500 dark:text-gray-400">Stop push notifications for selected users</small>
                        </button>
                        <button class="w-full text-left p-3 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" data-action="bulk-reactivate-devices">
                            <i class="ti ti-check text-green-600 me-2"></i>
                            <strong class="text-gray-900 dark:text-white">Reactivate All Devices</strong><br>
                            <small class="text-gray-500 dark:text-gray-400">Resume push notifications for selected users</small>
                        </button>
                        <button class="w-full text-left p-3 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors" data-action="cleanup-inactive-devices">
                            <i class="ti ti-trash text-yellow-600 me-2"></i>
                            <strong class="text-gray-900 dark:text-white">Cleanup Inactive Devices</strong><br>
                            <small class="text-gray-500 dark:text-gray-400">Remove devices not used in 30+ days</small>
                        </button>
                    </div>
                </div>
            `,
            width: '500px',
            showCancelButton: true,
            showConfirmButton: false,
            cancelButtonText: 'Close'
        });
    });

    /**
     * Bulk deactivate devices
     */
    /**
     * Shared runner for bulk device actions on selected users.
     */
    function runBulkDeviceAction(action, successTitle) {
        const selectedUsers = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);
        if (selectedUsers.length === 0) {
            window.Swal.fire('No Users Selected', 'Please select users first.', 'warning');
            return;
        }
        postForm(`${BASE}/user/bulk-device-action`, {
            user_ids: selectedUsers.join(','), device_action: action
        })
            .then(data => {
                if (data.success) {
                    window.Swal.fire(successTitle, data.message || 'Done.', 'success');
                } else {
                    window.Swal.fire('Error', data.message || 'Action failed', 'error');
                }
            })
            .catch(() => window.Swal.fire('Error', 'Action failed', 'error'));
    }

    ED.register('bulk-deactivate-devices', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Deactivate All Devices?',
            text: 'This will stop push notifications for all selected users',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Deactivate All',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                runBulkDeviceAction('deactivate', 'Devices Deactivated!');
            }
        });
    });

    /**
     * Bulk reactivate devices
     */
    ED.register('bulk-reactivate-devices', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Reactivate All Devices?',
            text: 'This will resume push notifications for all selected users',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Reactivate All'
        }).then((result) => {
            if (result.isConfirmed) {
                runBulkDeviceAction('reactivate', 'Devices Reactivated!');
            }
        });
    });

    /**
     * Cleanup inactive devices
     */
    ED.register('cleanup-inactive-devices', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Cleanup Inactive Devices?',
            text: 'This will remove device tokens not used in the last 30 days',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Cleanup Devices'
        }).then((result) => {
            if (result.isConfirmed) {
                runBulkDeviceAction('cleanup', 'Cleanup Complete!');
            }
        });
    });
}
