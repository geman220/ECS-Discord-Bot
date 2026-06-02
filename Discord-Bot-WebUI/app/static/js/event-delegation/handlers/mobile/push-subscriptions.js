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
    const BASE = '/admin-panel/mobile-features/device-token';

    function csrf() {
        return document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
    }

    function postForm(url, params) {
        const body = new URLSearchParams(params).toString();
        return fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-CSRFToken': csrf()
            },
            body
        }).then(r => r.json());
    }

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
        const d = element.dataset;

        // Real values are rendered on the button via data-* in the template.
        const esc = (s) => String(s == null ? '' : s)
            .replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));

        const rows = [
            ['Token ID', tokenId],
            ['User', d.user],
            ['Platform', d.platform],
            ['Status', d.status],
            ['App Version', d.appVersion],
            ['Created', d.created],
            ['Last Used', d.lastUsed],
        ].filter(([, v]) => v !== undefined && v !== null && v !== '')
         .map(([k, v]) => `<strong>${k}:</strong> ${esc(v)}<br>`).join('');

        window.Swal.fire({
            title: 'Device Token Details',
            html: `
                <div class="text-start">
                    <div class="mb-3">${rows}</div>
                    ${d.token ? `<div class="mb-3"><strong>FCM Token:</strong><br><code class="text-xs break-all">${esc(d.token)}</code></div>` : ''}
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
                        <div class="flex items-center">
                            <input class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600" type="checkbox" id="testHighPriority">
                            <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="testHighPriority">
                                High Priority Notification
                            </label>
                        </div>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Send Test',
            width: '400px',
            showLoaderOnConfirm: true,
            allowOutsideClick: () => !window.Swal.isLoading(),
            preConfirm: () => {
                const message = document.getElementById('testMessage')?.value;
                if (!message?.trim()) {
                    window.Swal.showValidationMessage('Please enter a test message');
                    return false;
                }
                return postForm(`${BASE}/test`, { token_id: tokenId })
                    .then(data => {
                        if (!data.success) {
                            window.Swal.showValidationMessage(data.message || 'Failed to send test notification');
                        }
                        return data;
                    })
                    .catch(() => {
                        window.Swal.showValidationMessage('Failed to send test notification');
                    });
            }
        }).then((result) => {
            if (result.isConfirmed && result.value && result.value.success) {
                window.Swal.fire('Test Sent!', result.value.message || 'Test notification has been sent to the device.', 'success');
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
                postForm(`${BASE}/activate`, { token_id: tokenId })
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire('Token Activated!', 'Push notifications enabled for this device.', 'success')
                                .then(() => location.reload());
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to activate token', 'error');
                        }
                    })
                    .catch(() => window.Swal.fire('Error', 'Failed to activate token', 'error'));
            }
        });
    });

    /**
     * Deactivate a device token
     */
    ED.register('deactivate-token', (element, event) => {
        event.preventDefault();
        const tokenId = element.dataset.tokenId;
        const deactivateUrl = element.dataset.deactivateUrl || `${BASE}/deactivate`;
        const csrfToken = csrf();

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
                postForm(`${BASE}/delete`, { token_id: tokenId })
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire('Token Deleted!', 'Device token has been permanently removed.', 'success')
                                .then(() => location.reload());
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to delete token', 'error');
                        }
                    })
                    .catch(() => window.Swal.fire('Error', 'Failed to delete token', 'error'));
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
                postForm(`${BASE}/bulk-activate`, { token_ids: selectedTokens.join(',') })
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire('Tokens Activated!', data.message || `${data.count} device tokens have been activated.`, 'success')
                                .then(() => location.reload());
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to activate tokens', 'error');
                        }
                    })
                    .catch(() => window.Swal.fire('Error', 'Failed to activate tokens', 'error'));
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
                postForm(`${BASE}/bulk-deactivate`, { token_ids: selectedTokens.join(',') })
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire('Tokens Deactivated!', data.message || `${data.count} device tokens have been deactivated.`, 'success')
                                .then(() => location.reload());
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to deactivate tokens', 'error');
                        }
                    })
                    .catch(() => window.Swal.fire('Error', 'Failed to deactivate tokens', 'error'));
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
                        postForm(`${BASE}/cleanup-inactive`, {})
                            .then(data => {
                                if (data.success) {
                                    window.Swal.fire('Cleanup Complete!', data.message || `${data.count} inactive tokens removed.`, 'success')
                                        .then(() => location.reload());
                                } else {
                                    window.Swal.fire('Error', data.message || 'Failed to clean up tokens', 'error');
                                }
                            })
                            .catch(() => window.Swal.fire('Error', 'Failed to clean up tokens', 'error'));
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
                let url = `${BASE}/export`;
                if (selectedTokens.length > 0) {
                    url += `?token_ids=${encodeURIComponent(selectedTokens.join(','))}`;
                }
                window.location.href = url;
            }
        });
    });
}
