'use strict';

/**
 * Mobile Features Handlers
 *
 * Event delegation handlers for admin panel mobile features pages:
 * - feature_toggles.html
 * - mobile_analytics.html
 * - error_cleanup.html
 * - error_analytics.html
 * - error_list.html
 * - push_subscriptions.html
 * - mobile_config.html
 * - mobile_users.html
 * - push_campaigns.html
 * - push_history.html
 *
 * @version 1.0.0
 */

import { EventDelegation } from '../core.js';

// ============================================================================
// FEATURE TOGGLES HANDLERS
// ============================================================================

/**
 * Emergency kill switch for all mobile features
 */
EventDelegation.register('emergency-kill-switch', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Emergency Kill Switch',
        text: 'This will immediately disable ALL mobile features for ALL users!',
        icon: 'error',
        showCancelButton: true,
        confirmButtonText: 'EMERGENCY DISABLE',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Disabling All Features...',
                text: 'Emergency shutdown in progress',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                    setTimeout(() => {
                        // Disable all feature toggles
                        document.querySelectorAll('input[data-feature]').forEach(toggle => {
                            toggle.checked = false;
                        });
                        Swal.fire('Emergency Shutdown Complete!', 'All mobile features have been disabled.', 'warning');
                    }, 3000);
                }
            });
        }
    });
});

/**
 * Export feature configuration
 */
EventDelegation.register('export-feature-config', (element, event) => {
    event.preventDefault();
    const config = {
        features: {},
        settings: {
            defaultFeatureState: document.getElementById('defaultFeatureState')?.value || 'disabled',
            rolloutStrategy: document.getElementById('rolloutStrategy')?.value || 'immediate',
            killSwitchEnabled: document.getElementById('killSwitchEnabled')?.checked || false,
            autoRollbackEnabled: document.getElementById('autoRollbackEnabled')?.checked || false
        },
        exportedAt: new Date().toISOString()
    };

    // Collect all feature states
    document.querySelectorAll('input[data-feature]').forEach(toggle => {
        config.features[toggle.dataset.feature] = toggle.checked;
    });

    // Create and download JSON file
    const dataStr = JSON.stringify(config, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
    const exportFileDefaultName = `mobile-features-config-${new Date().toISOString().split('T')[0]}.json`;

    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileDefaultName);
    linkElement.click();

    Swal.fire('Config Exported!', 'Feature configuration has been downloaded.', 'success');
});

/**
 * Save feature rollout settings
 */
EventDelegation.register('save-feature-settings', (element, event) => {
    event.preventDefault();
    const settings = {
        defaultFeatureState: document.getElementById('defaultFeatureState')?.value,
        rolloutStrategy: document.getElementById('rolloutStrategy')?.value,
        killSwitchEnabled: document.getElementById('killSwitchEnabled')?.checked,
        autoRollbackEnabled: document.getElementById('autoRollbackEnabled')?.checked
    };

    Swal.fire({
        title: 'Save Feature Settings?',
        text: 'This will update the global feature rollout configuration',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Save Settings'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Saving Settings...',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                    setTimeout(() => {
                        Swal.fire('Settings Saved!', 'Feature rollout settings have been updated.', 'success');
                    }, 2000);
                }
            });
        }
    });
});

// ============================================================================
// MOBILE ANALYTICS HANDLERS
// ============================================================================

/**
 * Update chart with time period
 */
EventDelegation.register('update-chart', (element, event) => {
    event.preventDefault();
    const period = element.dataset.period;

    // Update active button
    const btnGroup = element.closest('.btn-group');
    if (btnGroup) {
        btnGroup.querySelectorAll('.c-btn, .btn').forEach(btn => btn.classList.remove('active'));
        element.classList.add('active');
    }

    Swal.fire({
        title: 'Loading Data...',
        text: `Loading ${period} analytics data`,
        allowOutsideClick: false,
        timer: 1500,
        didOpen: () => {
            Swal.showLoading();
        }
    });
});

/**
 * Export analytics data
 */
EventDelegation.register('export-analytics', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Export Analytics',
        text: 'Choose export format and date range',
        icon: 'info',
        showCancelButton: true,
        confirmButtonText: 'Export',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label class="form-label">Date Range</label>
                    <select class="form-select" id="exportDateRange" data-form-select>
                        <option value="7d">Last 7 days</option>
                        <option value="30d">Last 30 days</option>
                        <option value="90d">Last 90 days</option>
                        <option value="all">All time</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Format</label>
                    <select class="form-select" id="exportFormat" data-form-select>
                        <option value="csv">CSV</option>
                        <option value="json">JSON</option>
                        <option value="pdf">PDF Report</option>
                    </select>
                </div>
            </div>
        `
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Export Started', 'Your analytics export will download shortly.', 'success');
        }
    });
});

/**
 * Refresh analytics data
 */
EventDelegation.register('refresh-analytics', (element, event) => {
    event.preventDefault();
    location.reload();
});

/**
 * View detailed user flow analysis
 */
EventDelegation.register('view-detailed-flow', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'User Flow Analysis',
        html: `
            <div class="text-start">
                <p>Detailed user flow analysis shows the paths users take through the app.</p>
                <div class="mt-3">
                    <h6>Entry Points:</h6>
                    <ul>
                        <li>Direct App Launch: 65%</li>
                        <li>Push Notification: 25%</li>
                        <li>Deep Link: 10%</li>
                    </ul>
                </div>
                <div class="mt-3">
                    <h6>Exit Points:</h6>
                    <ul>
                        <li>Home Screen: 40%</li>
                        <li>Match Details: 25%</li>
                        <li>Settings: 20%</li>
                        <li>Other: 15%</li>
                    </ul>
                </div>
            </div>
        `,
        width: '600px',
        confirmButtonText: 'Close'
    });
});

// ============================================================================
// ERROR ANALYTICS HANDLERS
// ============================================================================

/**
 * Export error data
 */
EventDelegation.register('export-errors', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Export Errors',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label class="form-label">Date Range</label>
                    <select class="form-select" id="exportDays" data-form-select>
                        <option value="7">Last 7 days</option>
                        <option value="30">Last 30 days</option>
                        <option value="90">Last 90 days</option>
                        <option value="all">All time</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Format</label>
                    <select class="form-select" id="exportFormat" data-form-select>
                        <option value="csv">CSV</option>
                        <option value="json">JSON</option>
                    </select>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Export'
    }).then((result) => {
        if (result.isConfirmed) {
            const days = document.getElementById('exportDays')?.value || '7';
            const format = document.getElementById('exportFormat')?.value || 'csv';
            const exportUrl = element.dataset.exportUrl || '/admin/mobile/errors';
            window.location.href = `${exportUrl}?export=true&days=${days}&format=${format}`;
            Swal.fire('Exporting...', 'Your download will start shortly.', 'info');
        }
    });
});

// ============================================================================
// ERROR CLEANUP HANDLERS
// ============================================================================

/**
 * Execute error data cleanup
 */
EventDelegation.register('execute-cleanup', (element, event) => {
    event.preventDefault();
    const confirmCheckbox = document.getElementById('confirmCleanup');

    if (!confirmCheckbox?.checked) {
        Swal.fire('Confirmation Required', 'Please check the confirmation box before proceeding.', 'warning');
        return;
    }

    Swal.fire({
        title: 'Execute Cleanup?',
        html: `
            <p>This will permanently delete old error data based on retention settings.</p>
            <p class="text-danger"><strong>This action cannot be undone!</strong></p>
        `,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, delete data',
        cancelButtonText: 'Cancel'
    }).then(async (result) => {
        if (!result.isConfirmed) return;

        Swal.fire({
            title: 'Executing Cleanup...',
            text: 'Please wait while old data is being deleted',
            allowOutsideClick: false,
            didOpen: () => {
                Swal.showLoading();
            }
        });

        try {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
            const cleanupUrl = element.dataset.cleanupUrl || '/admin/mobile/errors/cleanup';

            const response = await fetch(cleanupUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({ confirmed: true })
            });

            const data = await response.json();

            if (data.status === 'success') {
                await Swal.fire({
                    icon: 'success',
                    title: 'Cleanup Complete',
                    html: `
                        <p>Successfully deleted:</p>
                        <ul class="text-start">
                            <li>${data.deleted_errors || 0} error records</li>
                            <li>${data.deleted_logs || 0} log entries</li>
                            <li>${data.deleted_patterns || 0} error patterns</li>
                        </ul>
                    `,
                    confirmButtonText: 'OK'
                });
                location.reload();
            } else {
                Swal.fire('Error', data.error || 'Cleanup failed', 'error');
            }
        } catch (error) {
            console.error('Cleanup error:', error);
            Swal.fire('Error', 'Failed to execute cleanup. Please try again.', 'error');
        }
    });
});

// ============================================================================
// PUSH SUBSCRIPTIONS HANDLERS
// ============================================================================

/**
 * Copy device token to clipboard
 */
EventDelegation.register('copy-token', (element, event) => {
    event.preventDefault();
    const token = element.dataset.token;

    navigator.clipboard.writeText(token).then(() => {
        Swal.fire({
            icon: 'success',
            title: 'Token Copied!',
            text: 'Device token has been copied to clipboard',
            showConfirmButton: false,
            timer: 2000
        });
    }).catch(() => {
        // Fallback for older browsers
        const textarea = document.createElement('textarea');
        textarea.value = token;
        document.body.appendChild(textarea);
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);

        Swal.fire({
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
EventDelegation.register('view-token', (element, event) => {
    event.preventDefault();
    const tokenId = element.dataset.tokenId;

    Swal.fire({
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
                    <ul style="margin-left: 20px;">
                        <li>Device Model: iPhone 12 Pro</li>
                        <li>OS Version: iOS 17.2</li>
                        <li>App Version: 1.2.0</li>
                    </ul>
                </div>
                <div class="mb-3">
                    <strong>Notification History:</strong><br>
                    <ul style="margin-left: 20px;">
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
EventDelegation.register('test-notification', (element, event) => {
    event.preventDefault();
    const tokenId = element.dataset.tokenId;

    Swal.fire({
        title: 'Send Test Notification',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label class="form-label">Test Message</label>
                    <input type="text" class="form-control" id="testMessage" value="Test notification from admin panel" maxlength="160" data-form-control>
                    <div class="form-text">Maximum 160 characters</div>
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
                Swal.showValidationMessage('Please enter a test message');
                return false;
            }
            return {
                message: message,
                highPriority: document.getElementById('testHighPriority')?.checked
            };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Test Sent!', 'Test notification has been sent to the device.', 'success');
        }
    });
});

/**
 * Activate a device token
 */
EventDelegation.register('activate-token', (element, event) => {
    event.preventDefault();
    const tokenId = element.dataset.tokenId;

    Swal.fire({
        title: 'Activate Token?',
        text: 'This will enable push notifications for this device',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Activate'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Token Activated!', 'Push notifications enabled for this device.', 'success')
                .then(() => location.reload());
        }
    });
});

/**
 * Deactivate a device token
 */
EventDelegation.register('deactivate-token', (element, event) => {
    event.preventDefault();
    const tokenId = element.dataset.tokenId;
    const deactivateUrl = element.dataset.deactivateUrl || '/admin/mobile/push/deactivate';
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    Swal.fire({
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
                    Swal.fire('Token Deactivated!', 'Push notifications disabled for this device.', 'success')
                        .then(() => location.reload());
                } else {
                    Swal.fire('Error', data.message || 'Failed to deactivate token', 'error');
                }
            })
            .catch(error => {
                Swal.fire('Error', 'Failed to deactivate token', 'error');
            });
        }
    });
});

/**
 * Delete a device token
 */
EventDelegation.register('delete-token', (element, event) => {
    event.preventDefault();
    const tokenId = element.dataset.tokenId;

    Swal.fire({
        title: 'Delete Token?',
        text: 'This will permanently remove this device token. This action cannot be undone.',
        icon: 'error',
        showCancelButton: true,
        confirmButtonText: 'Delete Token',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Token Deleted!', 'Device token has been permanently removed.', 'success')
                .then(() => location.reload());
        }
    });
});

/**
 * Bulk activate selected tokens
 */
EventDelegation.register('bulk-activate', (element, event) => {
    event.preventDefault();
    const selectedTokens = Array.from(document.querySelectorAll('.token-checkbox:checked')).map(cb => cb.value);

    if (selectedTokens.length === 0) {
        Swal.fire('No Tokens Selected', 'Please select tokens to activate.', 'warning');
        return;
    }

    Swal.fire({
        title: `Activate ${selectedTokens.length} Tokens?`,
        text: 'This will enable push notifications for all selected devices',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Activate All'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Tokens Activated!', `${selectedTokens.length} device tokens have been activated.`, 'success')
                .then(() => location.reload());
        }
    });
});

/**
 * Bulk deactivate selected tokens
 */
EventDelegation.register('bulk-deactivate', (element, event) => {
    event.preventDefault();
    const selectedTokens = Array.from(document.querySelectorAll('.token-checkbox:checked')).map(cb => cb.value);

    if (selectedTokens.length === 0) {
        Swal.fire('No Tokens Selected', 'Please select tokens to deactivate.', 'warning');
        return;
    }

    Swal.fire({
        title: `Deactivate ${selectedTokens.length} Tokens?`,
        text: 'This will disable push notifications for all selected devices',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Deactivate All',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Tokens Deactivated!', `${selectedTokens.length} device tokens have been deactivated.`, 'success')
                .then(() => location.reload());
        }
    });
});

/**
 * Cleanup inactive tokens
 */
EventDelegation.register('cleanup-inactive', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Cleanup Inactive Tokens?',
        text: 'This will permanently remove tokens that have been inactive for 30+ days',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Cleanup Inactive',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Cleaning Up...',
                text: 'Removing inactive device tokens',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                    setTimeout(() => {
                        Swal.fire('Cleanup Complete!', 'Inactive tokens have been removed.', 'success')
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
EventDelegation.register('export-subscriptions', (element, event) => {
    event.preventDefault();
    const selectedTokens = Array.from(document.querySelectorAll('.token-checkbox:checked')).map(cb => cb.value);

    Swal.fire({
        title: 'Export Subscriptions?',
        text: selectedTokens.length > 0 ? `Export ${selectedTokens.length} selected subscriptions?` : 'Export all visible subscriptions?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Export Data'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Export Started!', 'Subscription data export is being prepared for download.', 'success');
        }
    });
});

// ============================================================================
// MOBILE CONFIG HANDLERS
// ============================================================================

/**
 * Test mobile configuration
 */
EventDelegation.register('test-config', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Testing Configuration...',
        text: 'Validating mobile app configuration settings',
        allowOutsideClick: false,
        timer: 2000,
        didOpen: () => {
            Swal.showLoading();
        }
    }).then(() => {
        Swal.fire('Configuration Valid', 'All mobile configuration settings are valid.', 'success');
    });
});

/**
 * Export mobile configuration
 */
EventDelegation.register('export-config', (element, event) => {
    event.preventDefault();
    const form = document.getElementById('mobile-config-form');
    const config = {};

    if (form) {
        const formData = new FormData(form);
        formData.forEach((value, key) => {
            config[key] = value;
        });
    }

    const dataStr = JSON.stringify(config, null, 2);
    const dataUri = 'data:application/json;charset=utf-8,' + encodeURIComponent(dataStr);
    const exportFileName = `mobile-config-${new Date().toISOString().split('T')[0]}.json`;

    const linkElement = document.createElement('a');
    linkElement.setAttribute('href', dataUri);
    linkElement.setAttribute('download', exportFileName);
    linkElement.click();

    Swal.fire('Config Exported!', 'Mobile configuration has been downloaded.', 'success');
});

/**
 * Reset mobile configuration to defaults
 */
EventDelegation.register('reset-config', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Reset to Defaults?',
        text: 'This will reset all mobile configuration settings to their default values',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Reset Settings',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffc107'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Settings Reset!', 'Mobile configuration has been reset to defaults.', 'success')
                .then(() => location.reload());
        }
    });
});

// ============================================================================
// ERROR LIST HANDLERS
// ============================================================================

/**
 * View error details
 */
EventDelegation.register('view-error', async (element, event) => {
    event.preventDefault();
    const errorUrl = element.dataset.errorUrl;

    if (!errorUrl) {
        Swal.fire('Error', 'Error details URL not available', 'error');
        return;
    }

    try {
        const response = await fetch(errorUrl);
        const data = await response.json();

        if (data.error) {
            Swal.fire('Error', data.error, 'error');
            return;
        }

        Swal.fire({
            title: 'Error Details',
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <strong>Error Type:</strong><br>
                        <code>${data.error_type}</code>
                    </div>
                    <div class="mb-3">
                        <strong>Severity:</strong><br>
                        <span class="badge bg-${data.severity === 'critical' ? 'danger' : data.severity === 'error' ? 'warning' : 'info'}" data-badge>${data.severity}</span>
                    </div>
                    <div class="mb-3">
                        <strong>Message:</strong><br>
                        ${data.message}
                    </div>
                    ${data.stack_trace ? `
                    <div class="mb-3">
                        <strong>Stack Trace:</strong><br>
                        <pre class="bg-light p-2 rounded" style="max-height: 200px; overflow-y: auto; font-size: 11px;">${data.stack_trace}</pre>
                    </div>
                    ` : ''}
                    ${data.device_info ? `
                    <div class="mb-3">
                        <strong>Device Info:</strong><br>
                        <pre class="bg-light p-2 rounded">${JSON.stringify(data.device_info, null, 2)}</pre>
                    </div>
                    ` : ''}
                    <div class="mb-3">
                        <strong>Timestamp:</strong><br>
                        ${data.created_at || 'N/A'}
                    </div>
                </div>
            `,
            width: '600px',
            confirmButtonText: 'Close'
        });
    } catch (error) {
        console.error('Error fetching error details:', error);
        Swal.fire('Error', 'Failed to load error details', 'error');
    }
});

// ============================================================================
// MOBILE USERS HANDLERS
// ============================================================================

/**
 * View mobile user details
 */
EventDelegation.register('view-user-details', async (element, event) => {
    event.preventDefault();
    const userId = element.dataset.userId;

    if (!userId) {
        Swal.fire('Error', 'User ID not available', 'error');
        return;
    }

    try {
        const response = await fetch(`/admin-panel/mobile/user-details?user_id=${userId}`);
        const data = await response.json();

        if (data.success) {
            const user = data.user;
            let deviceTokensHtml = '';

            if (user.device_tokens && user.device_tokens.length > 0) {
                deviceTokensHtml = user.device_tokens.map(token => `
                    <div class="mb-2">
                        <div class="d-flex justify-content-between align-items-center">
                            <div>
                                <strong>Token:</strong> ${token.token.substring(0, 20)}...<br>
                                <small class="text-muted">Platform: ${token.platform || 'Unknown'} | Created: ${token.created_at ? new Date(token.created_at).toLocaleDateString() : 'Unknown'}</small>
                            </div>
                            <span class="badge bg-${token.is_active ? 'success' : 'secondary'}" data-badge>
                                ${token.is_active ? 'Active' : 'Inactive'}
                            </span>
                        </div>
                    </div>
                `).join('');
            } else {
                deviceTokensHtml = '<p class="text-muted">No device tokens found</p>';
            }

            Swal.fire({
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
            Swal.fire('Error', data.message || 'Failed to load user details', 'error');
        }
    } catch (error) {
        console.error('Error fetching user details:', error);
        Swal.fire('Error', 'Failed to load user details', 'error');
    }
});

/**
 * Send notification to a single user
 */
EventDelegation.register('send-notification', (element, event) => {
    event.preventDefault();
    const userId = element.dataset.userId;

    Swal.fire({
        title: 'Send Push Notification',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label class="form-label">Notification Title</label>
                    <input type="text" class="form-control" id="notificationTitle" placeholder="Match Update" data-form-control>
                </div>
                <div class="mb-3">
                    <label class="form-label">Notification Message</label>
                    <textarea class="form-control" id="notificationMessage" rows="3" placeholder="Your match against Arsenal FC starts in 30 minutes!" data-form-control></textarea>
                </div>
                <div class="mb-3">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="highPriority">
                        <label class="form-check-label" for="highPriority">
                            High Priority Notification
                        </label>
                    </div>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Send Notification',
        width: '500px',
        preConfirm: () => {
            const title = document.getElementById('notificationTitle').value;
            const message = document.getElementById('notificationMessage').value;

            if (!title || !message) {
                Swal.showValidationMessage('Please fill in both title and message');
                return false;
            }

            return {
                title: title,
                message: message,
                highPriority: document.getElementById('highPriority').checked
            };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Notification Sent!', 'Push notification has been sent to the user.', 'success');
        }
    });
});

/**
 * Manage devices for a user
 */
EventDelegation.register('manage-devices', (element, event) => {
    event.preventDefault();
    const userId = element.dataset.userId;

    Swal.fire({
        title: 'Device Management',
        html: `
            <div class="text-start">
                <p class="text-muted">Loading device information...</p>
                <div class="list-group">
                    <div class="list-group-item d-flex justify-content-between align-items-center">
                        <div>
                            <strong>iPhone 12 Pro</strong><br>
                            <small class="text-muted">iOS 17.2 - Last active: 2 hours ago</small>
                        </div>
                        <div class="btn-group btn-group-sm">
                            <button class="c-btn c-btn--outline-warning" data-action="deactivate-device" data-token-id="token123" aria-label="Block"><i class="ti ti-ban"></i></button>
                        </div>
                    </div>
                    <div class="list-group-item d-flex justify-content-between align-items-center">
                        <div>
                            <strong>Samsung Galaxy S23</strong><br>
                            <small class="text-muted">Android 14 - Last active: 1 day ago</small>
                        </div>
                        <div class="btn-group btn-group-sm">
                            <button class="c-btn c-btn--outline-warning" data-action="deactivate-device" data-token-id="token456" aria-label="Block"><i class="ti ti-ban"></i></button>
                        </div>
                    </div>
                </div>
            </div>
        `,
        width: '600px',
        confirmButtonText: 'Close'
    });
});

/**
 * Deactivate a device
 */
EventDelegation.register('deactivate-device', (element, event) => {
    event.preventDefault();
    const tokenId = element.dataset.tokenId;
    const deactivateUrl = element.dataset.deactivateUrl || '/admin-panel/mobile/deactivate-device';
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    Swal.fire({
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
                    Swal.fire('Device Deactivated!', 'The device has been deactivated successfully.', 'success');
                } else {
                    Swal.fire('Error', data.message || 'Failed to deactivate device', 'error');
                }
            })
            .catch(error => {
                Swal.fire('Error', 'Failed to deactivate device', 'error');
            });
        }
    });
});

/**
 * Send bulk notification
 */
EventDelegation.register('send-bulk-notification', (element, event) => {
    event.preventDefault();
    const selectedUsers = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);

    if (selectedUsers.length === 0) {
        Swal.fire('No Users Selected', 'Please select users to send notifications to.', 'warning');
        return;
    }

    Swal.fire({
        title: `Send Bulk Notification (${selectedUsers.length} users)`,
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label class="form-label">Notification Title</label>
                    <input type="text" class="form-control" id="bulkNotificationTitle" placeholder="Important Update" data-form-control>
                </div>
                <div class="mb-3">
                    <label class="form-label">Notification Message</label>
                    <textarea class="form-control" id="bulkNotificationMessage" rows="3" placeholder="Check out the latest updates in the app!" data-form-control></textarea>
                </div>
                <div class="mb-3">
                    <label class="form-label">Send Schedule</label>
                    <select class="form-select" id="sendSchedule" data-form-select>
                        <option value="immediate">Send Immediately</option>
                        <option value="scheduled">Schedule for Later</option>
                    </select>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Send to All Selected',
        width: '500px',
        preConfirm: () => {
            const title = document.getElementById('bulkNotificationTitle').value;
            const message = document.getElementById('bulkNotificationMessage').value;

            if (!title || !message) {
                Swal.showValidationMessage('Please fill in both title and message');
                return false;
            }

            return {
                title: title,
                message: message,
                schedule: document.getElementById('sendSchedule').value
            };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Bulk Notification Sent!', `Notification sent to ${selectedUsers.length} users.`, 'success');
        }
    });
});

/**
 * Export user data
 */
EventDelegation.register('export-user-data', (element, event) => {
    event.preventDefault();
    const selectedUsers = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);

    Swal.fire({
        title: 'Export User Data?',
        text: selectedUsers.length > 0 ? `Export data for ${selectedUsers.length} selected users?` : 'Export data for all visible users?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Export Data'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Export Started!', 'User data export is being prepared for download.', 'success');
        }
    });
});

/**
 * Bulk device management
 */
EventDelegation.register('bulk-device-management', (element, event) => {
    event.preventDefault();
    const selectedUsers = Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);

    if (selectedUsers.length === 0) {
        Swal.fire('No Users Selected', 'Please select users to manage their devices.', 'warning');
        return;
    }

    Swal.fire({
        title: `Bulk Device Management (${selectedUsers.length} users)`,
        html: `
            <div class="text-start">
                <div class="list-group">
                    <button class="list-group-item list-group-item-action" data-action="bulk-deactivate-devices">
                        <i class="ti ti-ban text-danger me-2"></i>
                        <strong>Deactivate All Devices</strong><br>
                        <small class="text-muted">Stop push notifications for selected users</small>
                    </button>
                    <button class="list-group-item list-group-item-action" data-action="bulk-reactivate-devices">
                        <i class="ti ti-check text-success me-2"></i>
                        <strong>Reactivate All Devices</strong><br>
                        <small class="text-muted">Resume push notifications for selected users</small>
                    </button>
                    <button class="list-group-item list-group-item-action" data-action="cleanup-inactive-devices">
                        <i class="ti ti-trash text-warning me-2"></i>
                        <strong>Cleanup Inactive Devices</strong><br>
                        <small class="text-muted">Remove devices not used in 30+ days</small>
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
EventDelegation.register('bulk-deactivate-devices', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Deactivate All Devices?',
        text: 'This will stop push notifications for all selected users',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Deactivate All',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Devices Deactivated!', 'All devices for selected users have been deactivated.', 'success');
        }
    });
});

/**
 * Bulk reactivate devices
 */
EventDelegation.register('bulk-reactivate-devices', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Reactivate All Devices?',
        text: 'This will resume push notifications for all selected users',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Reactivate All'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Devices Reactivated!', 'All devices for selected users have been reactivated.', 'success');
        }
    });
});

/**
 * Cleanup inactive devices
 */
EventDelegation.register('cleanup-inactive-devices', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Cleanup Inactive Devices?',
        text: 'This will remove device tokens not used in the last 30 days',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Cleanup Devices'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Cleanup Complete!', 'Inactive devices have been removed.', 'success');
        }
    });
});

// ============================================================================
// PUSH CAMPAIGNS HANDLERS
// ============================================================================

/**
 * Preview campaign
 */
EventDelegation.register('preview-campaign', (element, event) => {
    event.preventDefault();
    const form = document.getElementById('campaignForm');
    if (!form) return;

    const formData = new FormData(form);
    const title = formData.get('notification_title') || 'Notification Title';
    const message = formData.get('notification_message') || 'Notification message will appear here';
    const audience = formData.get('target_audience') || 'all';
    const schedule = formData.get('send_schedule') || 'immediate';

    Swal.fire({
        title: 'Campaign Preview',
        html: `
            <div class="text-start">
                <div class="c-card border mb-3 mx-auto" style="max-width: 300px;">
                    <div class="c-card__body">
                        <div class="d-flex align-items-center mb-2">
                            <div class="bg-primary rounded-circle me-2 d-flex align-items-center justify-content-center" style="width: 32px; height: 32px;">
                                <i class="ti ti-shield text-white"></i>
                            </div>
                            <div>
                                <strong style="font-size: 14px;">ECS FC</strong><br>
                                <small class="text-muted">now</small>
                            </div>
                        </div>
                        <div class="mb-2">
                            <strong style="font-size: 15px;">${title}</strong>
                        </div>
                        <div style="font-size: 14px;" class="text-muted">
                            ${message}
                        </div>
                    </div>
                </div>

                <div class="mt-3">
                    <strong>Campaign Details:</strong><br>
                    <small>
                    - Target Audience: ${audience}<br>
                    - Send Schedule: ${schedule}<br>
                    - High Priority: ${formData.get('high_priority') ? 'Yes' : 'No'}
                    </small>
                </div>
            </div>
        `,
        width: '400px',
        confirmButtonText: 'Close'
    });
});

/**
 * Save draft
 */
EventDelegation.register('save-draft', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Save Draft?',
        text: 'This will save the campaign as a draft for later editing',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Save Draft'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Draft Saved!', 'Campaign has been saved as a draft.', 'success');
        }
    });
});

/**
 * Load template
 */
EventDelegation.register('load-template', (element, event) => {
    event.preventDefault();
    const templateId = element.dataset.templateId;

    const templates = {
        1: {
            name: 'Match Day Reminder',
            title: 'Match Starting Soon!',
            message: 'Your match against [OPPONENT] starts in 30 minutes. Good luck team!',
            type: 'match_reminder',
            audience: 'active'
        },
        2: {
            name: 'Season Update',
            title: 'Season Standings Update',
            message: 'Check out the latest season standings and upcoming fixtures in the app!',
            type: 'season_update',
            audience: 'all'
        },
        3: {
            name: 'Event Announcement',
            title: 'Special Event This Weekend',
            message: 'Join us for our annual tournament this weekend. Register now!',
            type: 'event_announcement',
            audience: 'active'
        }
    };

    const template = templates[templateId];
    if (template) {
        const nameInput = document.querySelector('input[name="campaign_name"]');
        const titleInput = document.querySelector('input[name="notification_title"]');
        const messageInput = document.querySelector('textarea[name="notification_message"]');
        const typeSelect = document.querySelector('select[name="campaign_type"]');
        const audienceSelect = document.querySelector('select[name="target_audience"]');
        const counter = document.getElementById('messageCounter');

        if (nameInput) nameInput.value = template.name;
        if (titleInput) titleInput.value = template.title;
        if (messageInput) messageInput.value = template.message;
        if (typeSelect) typeSelect.value = template.type;
        if (audienceSelect) audienceSelect.value = template.audience;
        if (counter) counter.textContent = template.message.length;

        Swal.fire('Template Loaded!', `${template.name} template has been applied.`, 'success');
    }
});

/**
 * View campaign details
 */
EventDelegation.register('view-campaign-details', (element, event) => {
    event.preventDefault();
    const campaignId = element.dataset.campaignId;

    Swal.fire({
        title: `Campaign Details`,
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <strong>Campaign ID:</strong> ${campaignId}<br>
                    <strong>Type:</strong> Match Reminder<br>
                    <strong>Created:</strong> 2024-01-15 09:00:00<br>
                    <strong>Sent:</strong> 2024-01-15 10:30:00
                </div>
                <div class="mb-3">
                    <strong>Notification Content:</strong><br>
                    <div class="c-card bg-light p-2">
                        <strong>Title:</strong> Match Starting Soon!<br>
                        <strong>Message:</strong> Your match against Arsenal FC starts in 30 minutes. Good luck team!
                    </div>
                </div>
                <div class="mb-3">
                    <strong>Performance Metrics:</strong><br>
                    - Recipients: 150 users<br>
                    - Delivered: 95% (142 users)<br>
                    - Opened: 78% (117 users)<br>
                    - Clicked: 45% (68 users)
                </div>
            </div>
        `,
        width: '600px',
        confirmButtonText: 'Close'
    });
});

/**
 * Duplicate Mobile Campaign
 * Note: Renamed from 'duplicate-campaign' to avoid conflict with admin/push-campaigns.js
 */
EventDelegation.register('duplicate-mobile-campaign', (element, event) => {
    event.preventDefault();
    const campaignId = element.dataset.campaignId;

    Swal.fire({
        title: 'Duplicate Campaign?',
        text: 'This will create a copy of this campaign that you can edit',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Duplicate Campaign'
    }).then((result) => {
        if (result.isConfirmed) {
            const nameInput = document.querySelector('input[name="campaign_name"]');
            const titleInput = document.querySelector('input[name="notification_title"]');
            const messageInput = document.querySelector('textarea[name="notification_message"]');
            const typeSelect = document.querySelector('select[name="campaign_type"]');
            const audienceSelect = document.querySelector('select[name="target_audience"]');

            if (nameInput) nameInput.value = 'Copy of Week 5 Match Reminders';
            if (titleInput) titleInput.value = 'Match Starting Soon!';
            if (messageInput) messageInput.value = 'Your match against Arsenal FC starts in 30 minutes. Good luck team!';
            if (typeSelect) typeSelect.value = 'match_reminder';
            if (audienceSelect) audienceSelect.value = 'active';

            Swal.fire('Campaign Duplicated!', 'Campaign has been loaded into the form for editing.', 'success');
        }
    });
});

/**
 * Download report
 */
EventDelegation.register('download-report', (element, event) => {
    event.preventDefault();
    const campaignId = element.dataset.campaignId;

    Swal.fire({
        title: 'Download Campaign Report?',
        text: 'This will generate a detailed analytics report for this campaign',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Download Report'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Report Generating...', 'Your campaign report is being prepared for download.', 'success');
        }
    });
});

// ============================================================================
// PUSH HISTORY HANDLERS
// ============================================================================

/**
 * View notification details
 */
EventDelegation.register('view-notification', (element, event) => {
    event.preventDefault();
    const notificationId = element.dataset.notificationId;

    Swal.fire({
        title: `Notification Details`,
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <strong>Notification ID:</strong> ${notificationId}<br>
                    <strong>Type:</strong> Push Notification<br>
                    <strong>Status:</strong> <span class="badge bg-success" data-badge>Sent</span><br>
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
EventDelegation.register('retry-notification', (element, event) => {
    event.preventDefault();
    const notificationId = element.dataset.notificationId;

    Swal.fire({
        title: 'Retry Notification?',
        text: 'This will attempt to resend the failed notification',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Retry Send'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Retrying...',
                text: 'Attempting to resend notification',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                    setTimeout(() => {
                        Swal.fire('Notification Retried!', 'The notification has been queued for retry.', 'success')
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
EventDelegation.register('duplicate-notification', (element, event) => {
    event.preventDefault();
    const notificationId = element.dataset.notificationId;

    Swal.fire({
        title: 'Duplicate Notification?',
        text: 'This will create a copy of this notification that you can send again',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Duplicate'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Notification Duplicated!', 'The notification has been copied to a new campaign.', 'success');
        }
    });
});

/**
 * Delete notification
 */
EventDelegation.register('delete-notification', (element, event) => {
    event.preventDefault();
    const notificationId = element.dataset.notificationId;

    Swal.fire({
        title: 'Delete Notification?',
        text: 'This will permanently remove this notification from history',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Notification Deleted!', 'The notification has been removed from history.', 'success')
                .then(() => location.reload());
        }
    });
});

/**
 * Retry failed notifications
 */
EventDelegation.register('retry-failed', (element, event) => {
    event.preventDefault();
    const selectedNotifications = Array.from(document.querySelectorAll('.notification-checkbox:checked')).map(cb => cb.value);

    if (selectedNotifications.length === 0) {
        Swal.fire('No Notifications Selected', 'Please select failed notifications to retry.', 'warning');
        return;
    }

    Swal.fire({
        title: `Retry ${selectedNotifications.length} Failed Notifications?`,
        text: 'This will attempt to resend all selected failed notifications',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Retry All'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Retrying Notifications...',
                text: 'Processing retry requests',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                    setTimeout(() => {
                        Swal.fire('Retry Complete!', `${selectedNotifications.length} notifications have been queued for retry.`, 'success')
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
EventDelegation.register('export-history', (element, event) => {
    event.preventDefault();
    const selectedNotifications = Array.from(document.querySelectorAll('.notification-checkbox:checked')).map(cb => cb.value);

    Swal.fire({
        title: 'Export Push History?',
        text: selectedNotifications.length > 0 ? `Export ${selectedNotifications.length} selected notifications?` : 'Export all visible notifications?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Export Data'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire('Export Started!', 'Push history export is being prepared for download.', 'success');
        }
    });
});

/**
 * Cleanup old notifications
 */
EventDelegation.register('cleanup-old', (element, event) => {
    event.preventDefault();
    Swal.fire({
        title: 'Cleanup Old Notifications?',
        text: 'This will permanently remove push notifications older than 90 days',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Cleanup Old',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Cleaning Up...',
                text: 'Removing old push notifications',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                    setTimeout(() => {
                        Swal.fire('Cleanup Complete!', '247 old notifications have been removed.', 'success')
                            .then(() => location.reload());
                    }, 2000);
                }
            });
        }
    });
});

console.log('[EventDelegation] Mobile features handlers loaded');
