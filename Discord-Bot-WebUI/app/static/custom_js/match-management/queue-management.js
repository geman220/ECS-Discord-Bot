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
                    '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert">Failed to load queue status</div>';
            }
        })
        .catch(error => {
            console.error('Error loading queue status:', error);
            document.getElementById('queueStatusContent').innerHTML =
                '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert">Error loading queue status</div>';
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
        html += '<h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">Active Tasks</h6>';
        html += '<div class="overflow-x-auto"><table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">';
        html += '<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr><th class="px-3 py-2">Task ID</th><th class="px-3 py-2">Name</th><th class="px-3 py-2">State</th><th class="px-3 py-2">Worker</th><th class="px-3 py-2">ETA</th></tr></thead><tbody>';

        data.active_tasks.forEach(task => {
            const stateColor = getTaskStatusColorTailwind(task.state);
            html += `
                <tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700">
                    <td class="px-3 py-2"><code class="text-xs bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">${task.task_id.substring(0, 8)}...</code></td>
                    <td class="px-3 py-2 text-gray-900 dark:text-white">${task.name || 'Unknown'}</td>
                    <td class="px-3 py-2"><span class="px-2 py-0.5 text-xs font-medium rounded ${stateColor}" data-task-state="${task.state}">${task.state}</span></td>
                    <td class="px-3 py-2">${task.worker || 'Unknown'}</td>
                    <td class="px-3 py-2">${task.eta ? formatTaskETA(task.eta) : 'N/A'}</td>
                </tr>
            `;
        });

        html += '</tbody></table></div>';
    }

    // Scheduled tasks
    if (data.scheduled_tasks && data.scheduled_tasks.length > 0) {
        html += '<h6 class="text-sm font-semibold text-gray-900 dark:text-white mt-4 mb-2">Scheduled Tasks</h6>';
        html += '<div class="overflow-x-auto"><table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">';
        html += '<thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400"><tr><th class="px-3 py-2">Task ID</th><th class="px-3 py-2">Name</th><th class="px-3 py-2">ETA</th></tr></thead><tbody>';

        data.scheduled_tasks.forEach(task => {
            html += `
                <tr class="bg-white border-b dark:bg-gray-800 dark:border-gray-700">
                    <td class="px-3 py-2"><code class="text-xs bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">${task.task_id.substring(0, 8)}...</code></td>
                    <td class="px-3 py-2 text-gray-900 dark:text-white">${task.name || 'Unknown'}</td>
                    <td class="px-3 py-2">${task.eta ? formatScheduledTime(task.eta) : 'N/A'}</td>
                </tr>
            `;
        });

        html += '</tbody></table></div>';
    }

    // Worker stats
    if (data.worker_stats) {
        html += '<h6 class="text-sm font-semibold text-gray-900 dark:text-white mt-4 mb-2">Worker Statistics</h6>';
        html += '<div class="grid grid-cols-1 md:grid-cols-2 gap-2">';

        Object.entries(data.worker_stats).forEach(([worker, stats]) => {
            html += `
                <div data-component="worker-stats-card" data-worker="${worker}" class="p-3 bg-white border border-gray-200 rounded-lg dark:bg-gray-800 dark:border-gray-700">
                    <h6 class="text-sm font-medium text-gray-900 dark:text-white mb-1">${worker}</h6>
                    <p class="text-xs text-gray-500 dark:text-gray-400">
                        Active: ${stats.active || 0} |
                        Processed: ${stats.processed || 0}
                    </p>
                </div>
            `;
        });

        html += '</div>';
    }

    if (!html) {
        html = '<div class="p-4 text-sm text-blue-800 rounded-lg bg-blue-50 dark:bg-gray-800 dark:text-blue-400" role="alert">No active or scheduled tasks</div>';
    }

    document.getElementById('queueStatusContent').innerHTML = html;
}

/**
 * Get Tailwind color classes for task status
 * @param {string} state
 * @returns {string}
 */
function getTaskStatusColorTailwind(state) {
    const colors = {
        'PENDING': 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
        'STARTED': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
        'SUCCESS': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
        'FAILURE': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
        'RETRY': 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
        'REVOKED': 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
    };
    return colors[state] || 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
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
    let html = '<div class="text-left">';

    if (debugInfo.match_info) {
        html += '<h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">Match Information</h6>';
        html += '<pre class="bg-gray-100 dark:bg-gray-700 p-3 rounded-lg text-xs text-gray-800 dark:text-gray-200 overflow-x-auto mb-4">' + JSON.stringify(debugInfo.match_info, null, 2) + '</pre>';
    }

    if (debugInfo.scheduled_tasks) {
        html += '<h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">Scheduled Tasks</h6>';
        html += '<pre class="bg-gray-100 dark:bg-gray-700 p-3 rounded-lg text-xs text-gray-800 dark:text-gray-200 overflow-x-auto mb-4">' + JSON.stringify(debugInfo.scheduled_tasks, null, 2) + '</pre>';
    }

    if (debugInfo.active_tasks) {
        html += '<h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">Active Tasks</h6>';
        html += '<pre class="bg-gray-100 dark:bg-gray-700 p-3 rounded-lg text-xs text-gray-800 dark:text-gray-200 overflow-x-auto mb-4">' + JSON.stringify(debugInfo.active_tasks, null, 2) + '</pre>';
    }

    if (debugInfo.celery_status) {
        html += '<h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">Celery Status</h6>';
        html += '<pre class="bg-gray-100 dark:bg-gray-700 p-3 rounded-lg text-xs text-gray-800 dark:text-gray-200 overflow-x-auto">' + JSON.stringify(debugInfo.celery_status, null, 2) + '</pre>';
    }

    html += '</div>';

    window.Swal.fire({
        title: 'Debug Information',
        html: html,
        width: '80%',
        confirmButtonText: 'Close'
    });
}
