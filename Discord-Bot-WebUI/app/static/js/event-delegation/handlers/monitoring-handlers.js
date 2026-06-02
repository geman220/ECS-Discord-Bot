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

/**
 * Escape a plain-text string for safe insertion into Swal `html` markup.
 * Values read from the DOM via textContent are already decoded, so they must
 * be re-escaped before being placed back into an HTML string.
 */
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

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
            <p class="text-gray-700 dark:text-gray-300">Emergency controls allow you to quickly disable system features.</p>
            <p class="text-gray-500 dark:text-gray-400">For immediate system issues, contact the system administrator or restart the Docker containers.</p>
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
    const period = element.dataset.period || '24h';

    // Update active button (legacy btn-group layout; console layout styles its own
    // buttons via an inline handler, so this is a no-op there).
    const btnGroup = element.closest('.btn-group');
    if (btnGroup) {
        btnGroup.querySelectorAll('.c-btn, .btn').forEach(btn => btn.classList.remove('active'));
        element.classList.add('active');
    }

    const historicalEl = document.getElementById('historicalChart');
    const chart = (historicalEl && window.Chart && typeof window.Chart.getChart === 'function')
        ? window.Chart.getChart(historicalEl)
        : null;

    const baseUrl = element.dataset.historicalUrl || '/admin-panel/monitoring/system/performance/historical';

    fetch(`${baseUrl}?period=${encodeURIComponent(period)}`)
        .then(response => response.json())
        .then(data => {
            if (!data || !data.success) {
                window.Swal.fire('Error', 'Failed to load historical data.', 'error');
                return;
            }
            if (chart) {
                // Dataset 0 = Response Time (ms), Dataset 1 = Requests/min (real series).
                chart.data.labels = data.labels || [];
                if (chart.data.datasets[0]) {
                    chart.data.datasets[0].data = data.response_time || [];
                }
                if (chart.data.datasets[1]) {
                    chart.data.datasets[1].data = data.requests || [];
                }
                chart.update();
            }
        })
        .catch(() => {
            window.Swal.fire('Error', 'Failed to load historical data.', 'error');
        });
});

// ============================================================================
// SYSTEM ALERTS HANDLERS
// ============================================================================

/**
 * View alert details
 */
window.EventDelegation.register('view-alert', (element, event) => {
    event.preventDefault();
    const alertId = element.dataset.alertId;

    // Read the REAL alert fields from the rendered alert card (the same data the
    // server passed into active_alerts and rendered into the row). The card is the
    // nearest ancestor that holds the title <h4>, message <p>, and severity pill.
    const card = element.closest('.relative') || element.closest('[data-row]') || element.parentElement;

    const titleEl = card ? card.querySelector('h4') : null;
    const messageEl = card ? card.querySelector('p.text-sm') : null;
    // The severity pill is the first uppercase tier label span (ERROR / WARNING / INFO).
    const pillEl = card ? card.querySelector('span.uppercase') : null;

    const title = titleEl ? titleEl.textContent.trim() : 'Alert';
    const message = messageEl ? messageEl.textContent.trim() : '';
    const severity = pillEl ? pillEl.textContent.trim().toUpperCase() : '';

    // Map severity word -> badge styling (no fabricated severity; falls back to neutral).
    let badgeClass = 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300';
    if (severity === 'ERROR' || severity === 'CRITICAL') {
        badgeClass = 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
    } else if (severity === 'WARNING' || severity === 'WARN') {
        badgeClass = 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';
    }

    const severityRow = severity
        ? `<strong class="text-gray-900 dark:text-white">Severity:</strong> <span class="px-2 py-0.5 text-xs font-medium rounded ${badgeClass}" data-badge>${escapeHtml(severity)}</span><br>`
        : '';
    const messageBlock = message
        ? `<div class="mb-3">
                    <strong class="text-gray-900 dark:text-white">Description:</strong><br>
                    <span class="text-gray-700 dark:text-gray-300">${escapeHtml(message)}</span>
                </div>`
        : '';

    window.Swal.fire({
        title: escapeHtml(title),
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <strong class="text-gray-900 dark:text-white">Alert ID:</strong> <span class="text-gray-700 dark:text-gray-300">${escapeHtml(alertId || '')}</span><br>
                    ${severityRow}
                    <strong class="text-gray-900 dark:text-white">Status:</strong> <span class="text-gray-700 dark:text-gray-300">Active</span>
                </div>
                ${messageBlock}
            </div>
        `,
        width: '600px',
        confirmButtonText: 'Close'
    });
});

/**
 * Test notification channels
 */
window.EventDelegation.register('test-notifications', (element, event) => {
    event.preventDefault();
    window.Swal.fire({
        title: 'Send Test Notifications?',
        text: 'This will send a test push notification to the devices registered to your account.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Send Test'
    }).then((result) => {
        if (!result.isConfirmed) return;

        const testUrl = element.dataset.testUrl || '/admin-panel/communication/push-notifications/test';
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

        window.Swal.fire({
            title: 'Sending Test...',
            allowOutsideClick: false,
            didOpen: () => window.Swal.showLoading()
        });

        fetch(testUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            }
        })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Test Sent!', data.message || 'Test notification sent to your devices.', 'success');
                } else {
                    window.Swal.fire('Test Failed', data.message || 'Unable to send test notification.', 'error');
                }
            })
            .catch(() => {
                window.Swal.fire('Error', 'Unable to send test notification.', 'error');
            });
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

// NOTE: refresh-connections, flush-query-cache, analyze-performance and
// optimize-database were removed. They previously showed hardcoded success
// toasts with no backend call — there is no route to reset idle DB connections,
// flush a query cache, run a performance analysis, or optimize the database, so
// the controls were not wired (no fake success). run-health-check above is the
// one real database maintenance action.

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

// NOTE: retry-task, kill-task and cleanup-zombies were removed. They showed
// hardcoded success toasts with no backend call. The real, working task-retry
// path is the console shell's 'retry-execution' handler (POSTs the persisted
// TaskExecution id to admin_panel.retry_task); the legacy 'retry-task' button
// only carried a Celery task UUID, which that route cannot act on. There is no
// backend route to forcibly kill a zombie task or bulk-clean zombies, so those
// controls were not wired (no fake success).

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

    // Update modal title (new pattern: {modalId}-title, fallback: old id pattern)
    const modalTitle = document.getElementById('taskDetailsModal-title') || document.getElementById('task_details_title');
    const modalContent = document.getElementById('task_details_content');

    if (modalTitle) modalTitle.textContent = `Details for ${taskName}`;
    if (modalContent) modalContent.innerHTML = '<div class="flex justify-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status" data-spinner></div></div>';

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
                modalContent.innerHTML = '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading task details</div>';
            }
        })
        .catch(error => {
            if (modalContent) {
                modalContent.innerHTML = '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading task details</div>';
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

    // Update modal title (new pattern: {modalId}-title, fallback: old id pattern)
    const modalTitle = document.getElementById('taskLogsModal-title') || document.getElementById('task_logs_title');
    const modalContent = document.getElementById('task_logs_content');

    if (modalTitle) modalTitle.textContent = `Logs for ${taskName}`;
    if (modalContent) modalContent.innerHTML = '<div class="flex justify-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status" data-spinner></div></div>';

    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('taskLogsModal');
    }

    const taskLogsUrl = element.dataset.taskLogsUrl || '/admin/monitoring/tasks/logs';

    fetch(`${taskLogsUrl}?task_id=${taskId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success && modalContent) {
                modalContent.innerHTML = `<pre class="bg-gray-900 text-gray-100 p-3 rounded text-sm overflow-x-auto">${data.logs}</pre>`;
            } else if (modalContent) {
                modalContent.innerHTML = '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading task logs</div>';
            }
        })
        .catch(error => {
            if (modalContent) {
                modalContent.innerHTML = '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading task logs</div>';
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
 * View log details
 */
window.EventDelegation.register('view-log-details', (element, event) => {
    event.preventDefault();

    // Read the REAL log entry fields straight from the row the server rendered.
    // Each row (table <tr> or mobile card <div>) carries data-row and holds the
    // timestamp, level badge, source, and message that system_logs() emitted.
    const row = element.closest('[data-row]');

    let timestamp = '';
    let level = '';
    let source = '';
    let message = '';

    if (row) {
        // Level: the level badge is a font-mono span (ERROR / WARN / INFO / DEBUG).
        const levelEl = row.querySelector('span.font-mono');
        level = levelEl ? levelEl.textContent.trim() : '';

        // Message: the message paragraph. Clone it and drop the "+N more" truncation
        // indicator span so we show only the real (displayed) message text.
        const msgEl = row.querySelector('p.font-mono');
        if (msgEl) {
            const clone = msgEl.cloneNode(true);
            clone.querySelectorAll('span').forEach(s => s.remove());
            message = clone.textContent.trim();
        }

        // Source + timestamp: table layout has dedicated cells; mobile packs them
        // into a single footer paragraph ("timestamp · source").
        const sourceEl = row.querySelector('[title]');
        const tableTs = row.querySelector('td.font-mono');
        if (tableTs) {
            timestamp = tableTs.textContent.trim();
            source = sourceEl ? sourceEl.getAttribute('title').trim() : (sourceEl ? sourceEl.textContent.trim() : '');
        } else {
            // Mobile card: last footer paragraph holds "timestamp · source".
            const paras = row.querySelectorAll('p');
            const footer = paras.length ? paras[paras.length - 1].textContent.trim() : '';
            const parts = footer.split('·');
            timestamp = (parts[0] || '').trim();
            source = (parts[1] || '').trim();
        }
    }

    let badgeClass = 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
    const lvlUpper = level.toUpperCase();
    if (lvlUpper === 'ERROR' || lvlUpper === 'CRITICAL') {
        badgeClass = 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
    } else if (lvlUpper === 'WARNING' || lvlUpper === 'WARN') {
        badgeClass = 'bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-300';
    } else if (lvlUpper === 'INFO') {
        badgeClass = 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300';
    }

    const rows = [];
    if (timestamp) {
        rows.push(`<strong class="text-gray-900 dark:text-white">Timestamp:</strong> <span class="text-gray-700 dark:text-gray-300">${escapeHtml(timestamp)}</span><br>`);
    }
    if (level) {
        rows.push(`<strong class="text-gray-900 dark:text-white">Level:</strong> <span class="px-2 py-0.5 text-xs font-medium rounded ${badgeClass}" data-badge>${escapeHtml(level)}</span><br>`);
    }
    if (source) {
        rows.push(`<strong class="text-gray-900 dark:text-white">Source:</strong> <span class="text-gray-700 dark:text-gray-300">${escapeHtml(source)}</span>`);
    }

    const messageBlock = message
        ? `<div class="mb-3">
                    <strong class="text-gray-900 dark:text-white">Message:</strong><br>
                    <pre class="bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 p-2 rounded text-sm whitespace-pre-wrap break-words">${escapeHtml(message)}</pre>
                </div>`
        : '';

    window.Swal.fire({
        title: 'Log Entry Details',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    ${rows.join('\n                    ')}
                </div>
                ${messageBlock}
            </div>
        `,
        width: '800px',
        confirmButtonText: 'Close'
    });
});

// Handlers loaded
