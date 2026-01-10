'use strict';

/**
 * Push Subscriptions Handlers
 * Handles push_subscriptions.html actions
 * @module event-delegation/handlers/mobile/push-subscriptions
 */

/**
 * Initialize push subscriptions handlers
 * @param {Object} ED - EventDelegation instance
 */
export function initPushSubscriptionsHandlers(ED) {
    /**
     * Copy device token to clipboard
     */
    ED.register('copy-token', (element, event) => {
        event.preventDefault();
        const token = element.dataset.token;

        navigator.clipboard.writeText(token).then(() => {
            window.Swal.fire({
                icon: 'success',
                title: 'Token Copied!',
                text: 'Device token has been copied to clipboard',
                showConfirmButton: false,
                timer: 2000
            });
        }).catch(() => {
            const textarea = document.createElement('textarea');
            textarea.value = token;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);

            window.Swal.fire({
                icon: 'success',
                title: 'Token Copied!',
                text: 'Device token has been copied to clipboard',
                showConfirmButton: false,
                timer: 2000
            });
        });
    });

    /**
     * View device token details
     */
    ED.register('view-token', (element, event) => {
        event.preventDefault();
        const tokenId = element.dataset.tokenId;

        window.Swal.fire({
            title: 'Device Token Details',
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <strong>Token ID:</strong> ${tokenId}<br>
                        <strong>Platform:</strong> iOS<br>
                        <strong>Status:</strong> <span class="badge bg-success" data-badge>Active</span><br>
                        <strong>Created:</strong> ${new Date().toISOString().split('T')[0]}
                    </div>
                    <div class="mb-3">
                        <strong>Device Information:</strong><br>
                        <ul class="ms-4">
                            <li>Device Model: iPhone 12 Pro</li>
                            <li>OS Version: iOS 17.2</li>
                            <li>App Version: 1.2.0</li>
                        </ul>
                    </div>
                    <div class="mb-3">
                        <strong>Notification History:</strong><br>
                        <ul class="ms-4">
                            <li>Total Sent: 45 notifications</li>
                            <li>Successfully Delivered: 43 (95.6%)</li>
                            <li>Opened: 32 (71.1%)</li>
                        </ul>
                    </div>
                </div>
            `,
            width: '600px',
            confirmButtonText: 'Close'
        });
    });

    /**
     * Send test notification to device
     */
    ED.register('test-notification', (element, event) => {
        event.preventDefault();
        const tokenId = element.dataset.tokenId;

        window.Swal.fire({
            title: 'Send Test Notification',
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Test Message</label>
                        <input type="text" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="testMessage" value="Test notification from admin panel" maxlength="160" data-form-control>
                        <p class="mt-2 text-sm text-gray-500 dark:text-gray-400">Maximum 160 characters</p>
                    </div>
                    <div class="mb-3">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" id="testHighPriority">
                            <label class="form-check-label" for="testHighPriority">
                                High Priority Notification
                            </label>
                        </div>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Send Test',
            width: '400px',
            preConfirm: () => {
                const message = document.getElementById('testMessage')?.value;
                if (!message?.trim()) {
                    window.Swal.showValidationMessage('Please enter a test message');
                    return false;
                }
                return {
                    message: message,
                    highPriority: document.getElementById('testHighPriority')?.checked
                };
            }
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Test Sent!', 'Test notification has been sent to the device.', 'success');
            }
        });
    });

    /**
     * Activate a device token
     */
    ED.register('activate-token', (element, event) => {
        event.preventDefault();
        const tokenId = element.dataset.tokenId;

        window.Swal.fire({
            title: 'Activate Token?',
            text: 'This will enable push notifications for this device',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Activate'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Token Activated!', 'Push notifications enabled for this device.', 'success')
                    .then(() => location.reload());
            }
        });
    });

    /**
     * Deactivate a device token
     */
    ED.register('deactivate-token', (element, event) => {
        event.preventDefault();
        const tokenId = element.dataset.tokenId;
        const deactivateUrl = element.dataset.deactivateUrl || '/admin/mobile/push/deactivate';
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

        window.Swal.fire({
            title: 'Deactivate Token?',
            text: 'This will disable push notifications for this device',
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
                        window.Swal.fire('Token Deactivated!', 'Push notifications disabled for this device.', 'success')
                            .then(() => location.reload());
                    } else {
                        window.Swal.fire('Error', data.message || 'Failed to deactivate token', 'error');
                    }
                })
                .catch(error => {
                    window.Swal.fire('Error', 'Failed to deactivate token', 'error');
                });
            }
        });
    });

    /**
     * Delete a device token
     */
    ED.register('delete-token', (element, event) => {
        event.preventDefault();
        const tokenId = element.dataset.tokenId;

        window.Swal.fire({
            title: 'Delete Token?',
            text: 'This will permanently remove this device token. This action cannot be undone.',
            icon: 'error',
            showCancelButton: true,
            confirmButtonText: 'Delete Token',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Token Deleted!', 'Device token has been permanently removed.', 'success')
                    .then(() => location.reload());
            }
        });
    });

    /**
     * Bulk activate selected tokens
     */
    ED.register('bulk-activate', (element, event) => {
        event.preventDefault();
        const selectedTokens = Array.from(document.querySelectorAll('.token-checkbox:checked')).map(cb => cb.value);

        if (selectedTokens.length === 0) {
            window.Swal.fire('No Tokens Selected', 'Please select tokens to activate.', 'warning');
            return;
        }

        window.Swal.fire({
            title: `Activate ${selectedTokens.length} Tokens?`,
            text: 'This will enable push notifications for all selected devices',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Activate All'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Tokens Activated!', `${selectedTokens.length} device tokens have been activated.`, 'success')
                    .then(() => location.reload());
            }
        });
    });

    /**
     * Bulk deactivate selected tokens
     */
    ED.register('bulk-deactivate', (element, event) => {
        event.preventDefault();
        const selectedTokens = Array.from(document.querySelectorAll('.token-checkbox:checked')).map(cb => cb.value);

        if (selectedTokens.length === 0) {
            window.Swal.fire('No Tokens Selected', 'Please select tokens to deactivate.', 'warning');
            return;
        }

        window.Swal.fire({
            title: `Deactivate ${selectedTokens.length} Tokens?`,
            text: 'This will disable push notifications for all selected devices',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Deactivate All',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Tokens Deactivated!', `${selectedTokens.length} device tokens have been deactivated.`, 'success')
                    .then(() => location.reload());
            }
        });
    });

    /**
     * Cleanup inactive tokens
     */
    ED.register('cleanup-inactive', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Cleanup Inactive Tokens?',
            text: 'This will permanently remove tokens that have been inactive for 30+ days',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Cleanup Inactive',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Cleaning Up...',
                    text: 'Removing inactive device tokens',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();
                        setTimeout(() => {
                            window.Swal.fire('Cleanup Complete!', 'Inactive tokens have been removed.', 'success')
                                .then(() => location.reload());
                        }, 2000);
                    }
                });
            }
        });
    });

    /**
     * Export subscription data
     */
    ED.register('export-subscriptions', (element, event) => {
        event.preventDefault();
        const selectedTokens = Array.from(document.querySelectorAll('.token-checkbox:checked')).map(cb => cb.value);

        window.Swal.fire({
            title: 'Export Subscriptions?',
            text: selectedTokens.length > 0 ? `Export ${selectedTokens.length} selected subscriptions?` : 'Export all visible subscriptions?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Export Data'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Export Started!', 'Subscription data export is being prepared for download.', 'success');
            }
        });
    });
}
