'use strict';

/**
 * Match Management Queue
 * Queue status display and management
 * @module match-management/queue-management
 */

import { formatTaskETA, formatScheduledTime, getTaskStatusColor } from './helpers.js';

/**
 * Show queue status modal
 */
export function matchMgmtShowQueueStatus() {
    if (window.ModalManager) {
        window.ModalManager.show('queueStatusModal');
    } else if (window.Modal) {
        const modalEl = document.getElementById('queueStatusModal');
        if (modalEl) {
            modalEl._flowbiteModal = modalEl._flowbiteModal || new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
            modalEl._flowbiteModal.show();
        }
    }
    refreshQueueStatus();
}

/**
 * Refresh queue status
 */
export function refreshQueueStatus() {
    fetch('/admin/match_management/queue-status')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                displayQueueStatus(data);
            } else {
                document.getElementById('queueStatusContent').innerHTML =
                    '<div class="alert alert-danger">Failed to load queue status</div>';
            }
        })
        .catch(error => {
            console.error('Error loading queue status:', error);
            document.getElementById('queueStatusContent').innerHTML =
                '<div class="alert alert-danger">Error loading queue status</div>';
        });
}

/**
 * Display queue status
 * @param {Object} data
 */
export function displayQueueStatus(data) {
    let html = '';

    // Active tasks
    if (data.active_tasks && data.active_tasks.length > 0) {
        html += '<h6>Active Tasks</h6>';
        html += '<div class="table-responsive"><table class="table table-sm">';
        html += '<thead><tr><th>Task ID</th><th>Name</th><th>State</th><th>Worker</th><th>ETA</th></tr></thead><tbody>';

        data.active_tasks.forEach(task => {
            html += `
                <tr>
                    <td><code>${task.task_id.substring(0, 8)}...</code></td>
                    <td>${task.name || 'Unknown'}</td>
                    <td><span class="badge bg-${getTaskStatusColor(task.state)}" data-task-state="${task.state}">${task.state}</span></td>
                    <td>${task.worker || 'Unknown'}</td>
                    <td>${task.eta ? formatTaskETA(task.eta) : 'N/A'}</td>
                </tr>
            `;
        });

        html += '</tbody></table></div>';
    }

    // Scheduled tasks
    if (data.scheduled_tasks && data.scheduled_tasks.length > 0) {
        html += '<h6 class="mt-3">Scheduled Tasks</h6>';
        html += '<div class="table-responsive"><table class="table table-sm">';
        html += '<thead><tr><th>Task ID</th><th>Name</th><th>ETA</th></tr></thead><tbody>';

        data.scheduled_tasks.forEach(task => {
            html += `
                <tr>
                    <td><code>${task.task_id.substring(0, 8)}...</code></td>
                    <td>${task.name || 'Unknown'}</td>
                    <td>${task.eta ? formatScheduledTime(task.eta) : 'N/A'}</td>
                </tr>
            `;
        });

        html += '</tbody></table></div>';
    }

    // Worker stats
    if (data.worker_stats) {
        html += '<h6 class="mt-3">Worker Statistics</h6>';
        html += '<div class="row">';

        Object.entries(data.worker_stats).forEach(([worker, stats]) => {
            html += `
                <div class="col-md-6 mb-2">
                    <div data-component="worker-stats-card" data-worker="${worker}" class="card">
                        <div class="card-body p-2">
                            <h6 class="card-title mb-1">${worker}</h6>
                            <small class="text-muted">
                                Active: ${stats.active || 0} |
                                Processed: ${stats.processed || 0}
                            </small>
                        </div>
                    </div>
                </div>
            `;
        });

        html += '</div>';
    }

    if (!html) {
        html = '<div class="alert alert-info">No active or scheduled tasks</div>';
    }

    document.getElementById('queueStatusContent').innerHTML = html;
}

/**
 * Debug match tasks
 * @param {string|number} matchId
 */
export function debugMatchTasks(matchId) {
    fetch(`/admin/match_management/debug-tasks/${matchId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showDebugModal(data.debug_info);
            } else {
                window.Swal.fire('Error!', data.message, 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            window.Swal.fire('Error!', 'An error occurred while fetching debug information.', 'error');
        });
}

/**
 * Show debug modal
 * @param {Object} debugInfo
 */
export function showDebugModal(debugInfo) {
    let html = '<div class="text-start">';

    if (debugInfo.match_info) {
        html += '<h6>Match Information</h6>';
        html += '<pre class="bg-light p-2 rounded">' + JSON.stringify(debugInfo.match_info, null, 2) + '</pre>';
    }

    if (debugInfo.scheduled_tasks) {
        html += '<h6>Scheduled Tasks</h6>';
        html += '<pre class="bg-light p-2 rounded">' + JSON.stringify(debugInfo.scheduled_tasks, null, 2) + '</pre>';
    }

    if (debugInfo.active_tasks) {
        html += '<h6>Active Tasks</h6>';
        html += '<pre class="bg-light p-2 rounded">' + JSON.stringify(debugInfo.active_tasks, null, 2) + '</pre>';
    }

    if (debugInfo.celery_status) {
        html += '<h6>Celery Status</h6>';
        html += '<pre class="bg-light p-2 rounded">' + JSON.stringify(debugInfo.celery_status, null, 2) + '</pre>';
    }

    html += '</div>';

    window.Swal.fire({
        title: 'Debug Information',
        html: html,
        width: '80%',
        confirmButtonText: 'Close'
    });
}
