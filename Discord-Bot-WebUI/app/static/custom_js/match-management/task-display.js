'use strict';

/**
 * Match Management Task Display
 * Task card rendering and display functions
 * @module match-management/task-display
 */

import { getStatusColor, getStatusIcon, formatDuration } from './helpers.js';

/**
 * Create a task card for display
 * @param {string} taskType
 * @param {Object} task
 * @param {string|number} matchId
 * @returns {string} HTML string
 */
export function createTaskCard(taskType, task, matchId) {
    const statusColor = getStatusColorTailwind(task.status);
    const statusIcon = getStatusIcon(task.status);
    const typeName = task.type || (taskType === 'thread' ? 'Thread Creation' : 'Live Reporting');
    const typeIcon = taskType === 'thread' ? 'ti-message-circle' : 'ti-broadcast';

    const displayMessage = task.message || typeName;
    const isFallback = task.fallback === true;

    // Format countdown
    let countdown = 'N/A';
    if (task.ttl && task.ttl > 0) {
        countdown = formatDuration(task.ttl);
    } else if (task.eta && task.eta !== 'completed') {
        const etaTime = new Date(task.eta);
        const now = new Date();
        const diff = Math.max(0, Math.floor((etaTime - now) / 1000));
        countdown = diff > 0 ? formatDuration(diff) : 'Due now';
    }

    // Special handling for different status types
    let statusDisplay = task.status;
    if (isFallback) {
        if (task.status === 'SUCCESS') statusDisplay = 'Completed';
        if (task.status === 'PENDING') statusDisplay = 'Scheduled';
        if (task.status === 'RUNNING') statusDisplay = 'Active';
        if (task.status === 'FINISHED') statusDisplay = 'Completed';
        if (task.status === 'MISSING') statusDisplay = 'Issue';
    }

    const fallbackIndicator = isFallback ? '<i class="ti ti-info-circle text-gray-400 dark:text-gray-500" title="Status derived from match data"></i>' : '';
    const taskDataJson = JSON.stringify(task).replace(/"/g, '&quot;').replace(/'/g, '&#39;');

    return `
        <div data-component="task-card" data-task-type="${taskType}" data-match-id="${matchId}" class="mb-2 p-2 border rounded-lg ${isFallback ? 'border-blue-300 dark:border-blue-700' : 'border-gray-200 dark:border-gray-700'}">
            <div class="flex justify-between items-center mb-1">
                <span class="px-2 py-0.5 text-xs font-medium rounded ${statusColor}" data-status="${task.status}">
                    <i class="ti ${statusIcon}"></i> ${statusDisplay}
                </span>
                <span class="text-xs text-gray-500 dark:text-gray-400">${countdown} ${fallbackIndicator}</span>
            </div>
            <div class="flex items-center mb-2">
                <i class="ti ${typeIcon} mr-2 text-blue-600 dark:text-blue-400"></i>
                <div class="flex-1">
                    <span class="text-xs font-semibold text-gray-900 dark:text-white block">${typeName}</span>
                    <span class="text-xs text-gray-500 dark:text-gray-400">${displayMessage}</span>
                </div>
            </div>
            ${task.result ? `<div class="mb-2"><span class="text-xs text-gray-500 dark:text-gray-400"><strong>Details:</strong> ${task.result}</span></div>` : ''}
            <div class="flex gap-1">
                <button class="p-1.5 text-xs text-blue-600 border border-blue-600 rounded hover:bg-blue-600 hover:text-white dark:text-blue-400 dark:border-blue-400"
                        data-action="show-task-info"
                        data-task-id="${task.task_id}"
                        data-task-type="${typeName}"
                        data-task-data='${taskDataJson}' aria-label="Info"><i class="ti ti-info-circle"></i></button>
                ${!isFallback && task.task_id !== 'unknown' && task.task_id !== 'scheduled' ? `
                <button class="p-1.5 text-xs text-red-600 border border-red-600 rounded hover:bg-red-600 hover:text-white dark:text-red-400 dark:border-red-400"
                        data-action="revoke-task"
                        data-task-id="${task.task_id}"
                        data-match-id="${matchId}"
                        data-task-type="${taskType}" aria-label="Revoke"><i class="ti ti-x"></i></button>` : ''}
                <button class="p-1.5 text-xs text-yellow-600 border border-yellow-600 rounded hover:bg-yellow-600 hover:text-white dark:text-yellow-400 dark:border-yellow-400"
                        data-action="reschedule-task"
                        data-match-id="${matchId}"
                        data-task-type="${taskType}" aria-label="Reschedule"><i class="ti ti-refresh"></i></button>
            </div>
        </div>
    `;
}

/**
 * Get Tailwind color classes for task status
 * @param {string} status
 * @returns {string}
 */
function getStatusColorTailwind(status) {
    const colors = {
        'PENDING': 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
        'STARTED': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
        'SUCCESS': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
        'FAILURE': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
        'RETRY': 'bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300',
        'REVOKED': 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
        'RUNNING': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
        'FINISHED': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
        'MISSING': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300'
    };
    return colors[status] || 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
}

/**
 * Create a "no task" card
 * @param {string} taskName
 * @param {string} message
 * @returns {string} HTML string
 */
export function createNoTaskCard(taskName, message) {
    const typeIcon = taskName.includes('Thread') ? 'ti-message-circle' : 'ti-broadcast';
    return `
        <div data-component="no-task-card" data-task-name="${taskName}" class="mb-1 p-2 border border-gray-200 dark:border-gray-700 rounded-lg bg-gray-50 dark:bg-gray-800">
            <div class="flex items-center">
                <i class="ti ${typeIcon} mr-2 text-gray-400 dark:text-gray-500"></i>
                <div class="flex-1">
                    <span class="text-xs font-semibold text-gray-500 dark:text-gray-400 block">${taskName}</span>
                    <span class="text-xs text-gray-500 dark:text-gray-400">${message}</span>
                </div>
                <span class="px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300" data-status="not-scheduled">Not Scheduled</span>
            </div>
        </div>
    `;
}

/**
 * Show task error in container
 * @param {string|number} matchId
 * @param {string} error
 */
export function showTaskError(matchId, error) {
    const container = document.getElementById(`task-details-${matchId}`);
    if (!container) return;

    if (error === 'Redis not available') {
        container.innerHTML = `
            <div class="text-center py-2">
                <p class="text-xs text-gray-500 dark:text-gray-400"><i class="ti ti-database mr-1"></i> Task system unavailable</p>
                <p class="text-xs text-gray-500 dark:text-gray-400">Redis connection needed</p>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="p-2 text-xs text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert">
                <i class="ti ti-alert-triangle mr-1"></i> ${error}
            </div>
        `;
    }
}

/**
 * Update the task details display for a match
 * @param {string|number} matchId
 * @param {Object} data
 */
export function updateMatchTaskDetails(matchId, data) {
    const container = document.getElementById(`task-details-${matchId}`);

    if (!container) {
        return;
    }

    if (!data.success) {
        showTaskError(matchId, data.error || 'Failed to load task details');
        return;
    }

    const tasks = data.tasks || {};
    let html = '';

    // Thread Creation Task
    if (tasks.thread) {
        html += createTaskCard('thread', tasks.thread, matchId);
    } else {
        html += createNoTaskCard('Thread Creation', 'No thread task scheduled');
    }

    // Live Reporting Task
    if (tasks.reporting) {
        html += createTaskCard('reporting', tasks.reporting, matchId);
    } else {
        html += createNoTaskCard('Live Reporting', 'No reporting task scheduled');
    }

    if (!html) {
        html = '<small class="text-muted">No tasks scheduled</small>';
    }

    container.innerHTML = html;
}

/**
 * Update a match row with status
 * @param {Object} match
 */
export function updateMatchRow(match) {
    const statusBadge = document.getElementById(`status-${match.id}`);
    if (statusBadge) {
        statusBadge.className = 'badge';
        statusBadge.classList.add(`bg-${match.status_color}`);
        statusBadge.setAttribute('data-status', match.status);
        statusBadge.innerHTML = `<i class="fas ${match.status_icon}"></i> ${match.status_display}`;
    }

    const taskContainer = document.getElementById(`task-details-${match.id}`);
    if (taskContainer) {
        // Import dynamically to avoid circular dependency
        import('./task-api.js').then(({ loadMatchTaskDetails }) => {
            loadMatchTaskDetails(match.id);
        });
    }
}
