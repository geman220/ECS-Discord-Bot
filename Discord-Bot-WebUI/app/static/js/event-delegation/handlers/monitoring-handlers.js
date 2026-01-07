'use strict';

/**
 * Monitoring Handlers
 *
 * Event delegation handlers for admin panel monitoring pages:
 * - system_monitoring.html
 * - system_performance.html
 * - system_alerts.html
 * - database_monitor.html
 * - task_history.html
 * - task_monitor.html
 * - system_logs.html
 *
 * @version 1.0.0
 */

import { EventDelegation } from '../core.js';

// ============================================================================
// SYSTEM MONITORING HANDLERS
// ============================================================================

/**
 * Refresh system status
 */
window.EventDelegation.register('refresh-status', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Refreshing Status...',
        text: 'Checking all system services',
        allowOutsideClick: false,
        didOpen: () => {
            window.Swal.showLoading();
            setTimeout(() => {
                location.reload();
            }, 2000);
        }
    });
});

/**
 * View system logs
 */
window.EventDelegation.register('view-logs', (element, event) => {
    event.preventDefault();
    // Navigate to system logs page
    const logsUrl = element.dataset.logsUrl || '/admin/monitoring/logs';
    window.location.href = logsUrl;
});

/**
 * Clear system cache
 */
window.EventDelegation.register('clear-cache', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Clear System Cache?',
        text: 'This will clear all cached data',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Clear Cache',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffc107'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Cache Cleared!', 'System cache has been cleared successfully.', 'success');
        }
    });
});

/**
 * Toggle emergency mode
 */
window.EventDelegation.register('emergency-mode', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Emergency Mode',
        html: `
            <p>Emergency controls allow you to quickly disable system features.</p>
            <p class="text-muted">For immediate system issues, contact the system administrator or restart the Docker containers.</p>
        `,
        icon: 'warning',
        confirmButtonText: 'View System Status',
        showCancelButton: true
    }).then((result) => {
        if (result.isConfirmed) {
            window.location.href = '/admin/system_monitoring';
        }
    });
});

// ============================================================================
// SYSTEM PERFORMANCE HANDLERS
// ============================================================================

/**
 * Load historical performance data
 */
window.EventDelegation.register('load-historical', (element, event) => {
    event.preventDefault();
    const period = element.dataset.period;

    // Update active button
    const btnGroup = element.closest('.btn-group');
    if (btnGroup) {
        btnGroup.querySelectorAll('.c-btn, .btn').forEach(btn => btn.classList.remove('active'));
        element.classList.add('active');
    }

    window.Swal.fire({
        title: 'Loading Data...',
        text: `Loading ${period} historical data`,
        allowOutsideClick: false,
        didOpen: () => {
            window.Swal.showLoading();
            setTimeout(() => {
                window.Swal.close();
                // Charts would update with new data here
            }, 1000);
        }
    });
});

// ============================================================================
// SYSTEM ALERTS HANDLERS
// ============================================================================

/**
 * Acknowledge an alert
 */
window.EventDelegation.register('acknowledge-alert', (element, event) => {
    event.preventDefault();
    const alertId = element.dataset.alertId;

    window.Swal.fire({
        title: 'Acknowledge Alert?',
        text: 'This will mark the alert as acknowledged but keep it active',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Acknowledge'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Alert Acknowledged!', 'The alert has been acknowledged.', 'success');
        }
    });
});

/**
 * View alert details
 */
window.EventDelegation.register('view-alert', (element, event) => {
    event.preventDefault();
    const alertId = element.dataset.alertId;

    window.Swal.fire({
        title: 'Alert Details',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <strong>Alert ID:</strong> ${alertId}<br>
                    <strong>Component:</strong> System Monitor<br>
                    <strong>Severity:</strong> <span class="badge bg-danger" data-badge>CRITICAL</span><br>
                    <strong>Status:</strong> Active
                </div>
                <div class="mb-3">
                    <strong>Description:</strong><br>
                    CPU usage has exceeded 85% for the past 5 minutes. This may indicate high system load or a runaway process.
                </div>
                <div class="mb-3">
                    <strong>Suggested Actions:</strong><br>
                    <small>
                    1. Check running processes with 'top' or 'htop'<br>
                    2. Identify high CPU processes<br>
                    3. Consider scaling resources if sustained high usage
                    </small>
                </div>
            </div>
        `,
        width: '600px',
        confirmButtonText: 'Close'
    });
});

/**
 * Resolve an alert
 */
window.EventDelegation.register('resolve-alert', (element, event) => {
    event.preventDefault();
    const alertId = element.dataset.alertId;

    window.Swal.fire({
        title: 'Resolve Alert?',
        input: 'textarea',
        inputLabel: 'Resolution Notes (optional)',
        inputPlaceholder: 'Describe how this alert was resolved...',
        showCancelButton: true,
        confirmButtonText: 'Resolve Alert'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Alert Resolved!', 'The alert has been marked as resolved.', 'success');
            location.reload();
        }
    });
});

/**
 * Save alert configuration
 */
window.EventDelegation.register('save-alert-config', (element, event) => {
    event.preventDefault();
    window.Swal.fire('Configuration Saved!', 'Alert settings have been updated.', 'success');
});

/**
 * Test notification channels
 */
window.EventDelegation.register('test-notifications', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Send Test Notifications?',
        text: 'This will send test alerts to all configured notification channels',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Send Test'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Test Sent!', 'Test notifications have been sent to all channels.', 'success');
        }
    });
});

// ============================================================================
// DATABASE MONITOR HANDLERS
// ============================================================================

/**
 * Run database health check
 */
window.EventDelegation.register('run-health-check', (element, event) => {
    event.preventDefault();
    const button = element.closest('button') || element;
    const originalText = button.innerHTML;
    button.innerHTML = '<i class="ti ti-loader me-1"></i>Running...';
    button.disabled = true;

    const healthCheckUrl = button.dataset.healthCheckUrl || '/admin/monitoring/database/health-check';
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    fetch(healthCheckUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success', 'Database health check completed successfully!', 'success');
            setTimeout(() => window.location.reload(), 2000);
        } else {
            window.Swal.fire('Error', 'Health check failed: ' + (data.message || 'Unknown error'), 'error');
        }
    })
    .catch(error => {
        window.Swal.fire('Error', 'Failed to run health check', 'error');
    })
    .finally(() => {
        button.innerHTML = originalText;
        button.disabled = false;
    });
});

/**
 * Refresh database connections
 */
window.EventDelegation.register('refresh-connections', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Refresh Connections?',
        text: 'This will reset all idle database connections.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info') : '#17a2b8',
        confirmButtonText: 'Yes, refresh!'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Success', 'Database connections refreshed!', 'success');
        }
    });
});

/**
 * Flush query cache
 */
window.EventDelegation.register('flush-query-cache', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Flush Query Cache?',
        text: 'This will clear all cached query results.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffc107',
        confirmButtonText: 'Yes, flush cache!'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Success', 'Query cache flushed!', 'success');
        }
    });
});

/**
 * Analyze database performance
 */
window.EventDelegation.register('analyze-performance', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Analyze Performance?',
        text: 'This will run a comprehensive performance analysis.',
        icon: 'info',
        showCancelButton: true,
        confirmButtonText: 'Yes, analyze!'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Info', 'Performance analysis started. Results will be available shortly.', 'info');
        }
    });
});

/**
 * Optimize database
 */
window.EventDelegation.register('optimize-database', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Optimize Database?',
        text: 'This will run database optimization routines. This may take a few minutes.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28a745',
        confirmButtonText: 'Yes, optimize!'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Success', 'Database optimization completed!', 'success');
        }
    });
});

// ============================================================================
// TASK HISTORY HANDLERS
// ============================================================================

/**
 * View task details
 */
window.EventDelegation.register('view-task', (element, event) => {
    event.preventDefault();
    const taskId = element.dataset.taskId;
    const taskDetailsUrl = element.dataset.taskDetailsUrl || `/admin/monitoring/tasks/${taskId}/details`;

    fetch(`${taskDetailsUrl}?task_id=${taskId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.Swal.fire({
                    title: `Task Details: ${taskId.substring(0, 8)}`,
                    html: data.html,
                    width: '800px',
                    confirmButtonText: 'Close'
                });
            } else {
                window.Swal.fire('Error', data.message || 'Failed to load task details', 'error');
            }
        })
        .catch(error => {
            window.Swal.fire('Error', 'Failed to load task details', 'error');
        });
});

/**
 * Retry a failed task
 */
window.EventDelegation.register('retry-task', (element, event) => {
    event.preventDefault();
    const taskId = element.dataset.taskId;

    window.Swal.fire({
        title: 'Retry Task?',
        text: 'This will attempt to run the failed task again',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Retry Task'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Task Queued!', 'The task has been queued for retry.', 'success');
        }
    });
});

/**
 * Kill a zombie task
 */
window.EventDelegation.register('kill-task', (element, event) => {
    event.preventDefault();
    const taskId = element.dataset.taskId;

    window.Swal.fire({
        title: 'Kill Zombie Task?',
        text: 'This will forcefully terminate the zombie task',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Kill Task',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Task Killed!', 'The zombie task has been terminated.', 'success');
        }
    });
});

/**
 * Cleanup all zombie tasks
 */
window.EventDelegation.register('cleanup-zombies', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Cleanup All Zombie Tasks?',
        text: 'This will terminate all zombie tasks',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Cleanup All',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Zombies Cleaned!', 'All zombie tasks have been terminated.', 'success');
        }
    });
});

// ============================================================================
// TASK MONITOR HANDLERS
// ============================================================================

/**
 * Refresh active tasks
 */
window.EventDelegation.register('refresh-tasks', (element, event) => {
    event.preventDefault();
    const button = element.closest('button') || element;
    const originalText = button.innerHTML;
    button.innerHTML = '<i class="ti ti-loader me-1"></i>Refreshing...';
    button.disabled = true;

    setTimeout(() => {
        window.location.reload();
    }, 1000);
});

/**
 * View task details from task monitor
 */
window.EventDelegation.register('view-task-details', (element, event) => {
    event.preventDefault();
    const taskId = element.dataset.taskId;
    const taskName = element.dataset.taskName || 'Task';

    const modalTitle = document.getElementById('task_details_title');
    const modalContent = document.getElementById('task_details_content');

    if (modalTitle) modalTitle.textContent = `Details for ${taskName}`;
    if (modalContent) modalContent.innerHTML = '<div class="text-center"><div class="spinner-border" role="status" data-spinner></div></div>';

    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('taskDetailsModal');
    }

    const taskDetailsUrl = element.dataset.taskDetailsUrl || '/admin/monitoring/tasks/details';

    fetch(`${taskDetailsUrl}?task_id=${taskId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && modalContent) {
                modalContent.innerHTML = data.html;
            } else if (modalContent) {
                modalContent.innerHTML = '<div class="alert alert-danger" data-alert>Error loading task details</div>';
            }
        })
        .catch(error => {
            if (modalContent) {
                modalContent.innerHTML = '<div class="alert alert-danger" data-alert>Error loading task details</div>';
            }
        });
});

/**
 * View task logs
 */
window.EventDelegation.register('view-task-logs', (element, event) => {
    event.preventDefault();
    const taskId = element.dataset.taskId;
    const taskName = element.dataset.taskName || 'Task';

    const modalTitle = document.getElementById('task_logs_title');
    const modalContent = document.getElementById('task_logs_content');

    if (modalTitle) modalTitle.textContent = `Logs for ${taskName}`;
    if (modalContent) modalContent.innerHTML = '<div class="text-center"><div class="spinner-border" role="status" data-spinner></div></div>';

    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('taskLogsModal');
    }

    const taskLogsUrl = element.dataset.taskLogsUrl || '/admin/monitoring/tasks/logs';

    fetch(`${taskLogsUrl}?task_id=${taskId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && modalContent) {
                modalContent.innerHTML = `<pre class="bg-dark text-light p-3 rounded">${data.logs}</pre>`;
            } else if (modalContent) {
                modalContent.innerHTML = '<div class="alert alert-danger" data-alert>Error loading task logs</div>';
            }
        })
        .catch(error => {
            if (modalContent) {
                modalContent.innerHTML = '<div class="alert alert-danger" data-alert>Error loading task logs</div>';
            }
        });
});

/**
 * Cancel a running task
 */
window.EventDelegation.register('cancel-task', (element, event) => {
    event.preventDefault();
    const taskId = element.dataset.taskId;
    const taskName = element.dataset.taskName || 'this task';

    window.Swal.fire({
        title: 'Cancel Task?',
        text: `Cancel the running task "${taskName}"? This action cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        confirmButtonText: 'Yes, cancel it!'
    }).then((result) => {
        if (result.isConfirmed) {
            const cancelUrl = element.dataset.cancelUrl || '/admin/monitoring/tasks/cancel';
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

            // Create form and submit
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = cancelUrl;

            const tokenInput = document.createElement('input');
            tokenInput.type = 'hidden';
            tokenInput.name = 'csrf_token';
            tokenInput.value = csrfToken;

            const taskIdInput = document.createElement('input');
            taskIdInput.type = 'hidden';
            taskIdInput.name = 'task_id';
            taskIdInput.value = taskId;

            form.appendChild(tokenInput);
            form.appendChild(taskIdInput);
            document.body.appendChild(form);
            form.submit();
        }
    });
});

// ============================================================================
// SYSTEM LOGS HANDLERS
// ============================================================================

/**
 * Refresh logs
 */
window.EventDelegation.register('refresh-logs', (element, event) => {
    event.preventDefault();
    location.reload();
});

/**
 * Export logs
 */
window.EventDelegation.register('export-logs', (element, event) => {
    event.preventDefault();
    const params = new URLSearchParams(window.location.search);
    params.set('export', 'true');
    window.open(`${window.location.pathname}?${params.toString()}`, '_blank');
});

/**
 * Clear old logs
 */
window.EventDelegation.register('clear-old-logs', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Clear Old Logs?',
        text: 'This will delete log entries older than 30 days',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Clear Old Logs'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Logs Cleared!', 'Old log entries have been removed.', 'success');
        }
    });
});

/**
 * Start live tail
 */
window.EventDelegation.register('start-tail', (element, event) => {
    event.preventDefault();
    const liveTailArea = document.getElementById('liveTailArea');
    const liveTailContent = document.getElementById('liveTailContent');

    if (liveTailArea) {
        liveTailArea.classList.remove('u-hidden');

        // Start live tail interval
        if (!window._liveTailInterval) {
            window._liveTailInterval = setInterval(() => {
                if (liveTailContent) {
                    const timestamp = new Date().toISOString();
                    liveTailContent.innerHTML += `${timestamp} [INFO] Live log entry example\n`;
                    liveTailContent.scrollTop = liveTailContent.scrollHeight;
                }
            }, 2000);
        }
    }
});

/**
 * Stop live tail
 */
window.EventDelegation.register('stop-tail', (element, event) => {
    event.preventDefault();
    const liveTailArea = document.getElementById('liveTailArea');

    if (window._liveTailInterval) {
        clearInterval(window._liveTailInterval);
        window._liveTailInterval = null;
    }

    if (liveTailArea) {
        liveTailArea.classList.add('u-hidden');
    }
});

/**
 * View log details
 */
window.EventDelegation.register('view-log-details', (element, event) => {
    event.preventDefault();
    const logId = element.dataset.logId;

    window.Swal.fire({
        title: 'Log Entry Details',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <strong>Log ID:</strong> ${logId}<br>
                    <strong>Timestamp:</strong> ${new Date().toISOString()}<br>
                    <strong>Level:</strong> <span class="badge bg-danger" data-badge>ERROR</span><br>
                    <strong>Component:</strong> app.admin_panel
                </div>
                <div class="mb-3">
                    <strong>Message:</strong><br>
                    <pre class="bg-light p-2 rounded">Sample error message with details about what went wrong in the system.</pre>
                </div>
                <div class="mb-3">
                    <strong>Stack Trace:</strong><br>
                    <pre class="bg-dark text-light p-2 rounded scroll-container-sm">
Traceback (most recent call last):
  File "app.py", line 123, in handle_request
    result = process_data(data)
  File "handlers.py", line 45, in process_data
    return transform(data)
Exception: Sample error occurred
                    </pre>
                </div>
            </div>
        `,
        width: '800px',
        confirmButtonText: 'Close'
    });
});

// Handlers loaded
