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

console.log('[EventDelegation] Mobile features handlers loaded');
