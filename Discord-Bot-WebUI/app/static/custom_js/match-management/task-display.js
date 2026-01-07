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
    const statusColor = getStatusColor(task.status);
    const statusIcon = getStatusIcon(task.status);
    const typeName = task.type || (taskType === 'thread' ? 'Thread Creation' : 'Live Reporting');
    const typeIcon = taskType === 'thread' ? 'fa-comments' : 'fa-broadcast-tower';

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

    const fallbackIndicator = isFallback ? '<i class="fas fa-info-circle text-muted" title="Status derived from match data"></i>' : '';
    const taskDataJson = JSON.stringify(task).replace(/"/g, '&quot;').replace(/'/g, '&#39;');

    return `
        <div data-component="task-card" data-task-type="${taskType}" data-match-id="${matchId}" class="mb-2 p-2 border rounded ${isFallback ? 'border-info' : ''}">
            <div class="d-flex justify-content-between align-items-center mb-1">
                <span class="badge bg-${statusColor}" data-status="${task.status}">
                    <i class="fas ${statusIcon}"></i> ${statusDisplay}
                </span>
                <small class="text-muted">${countdown} ${fallbackIndicator}</small>
            </div>
            <div class="d-flex align-items-center mb-2">
                <i class="fas ${typeIcon} me-2 text-primary"></i>
                <div class="flex-grow-1">
                    <small class="fw-bold">${typeName}</small><br>
                    <small class="text-muted">${displayMessage}</small>
                </div>
            </div>
            ${task.result ? `<div class="mb-2"><small class="text-muted"><strong>Details:</strong> ${task.result}</small></div>` : ''}
            <div class="task-actions">
                <button class="btn btn-xs btn-outline-info me-1"
                        data-action="show-task-info"
                        data-task-id="${task.task_id}"
                        data-task-type="${typeName}"
                        data-task-data='${taskDataJson}' aria-label="Button"><i class="fas fa-info-circle"></i></button>
                ${!isFallback && task.task_id !== 'unknown' && task.task_id !== 'scheduled' ? `
                <button class="btn btn-xs btn-outline-danger me-1"
                        data-action="revoke-task"
                        data-task-id="${task.task_id}"
                        data-match-id="${matchId}"
                        data-task-type="${taskType}" aria-label="Close"><i class="fas fa-times"></i></button>` : ''}
                <button class="btn btn-xs btn-outline-warning"
                        data-action="reschedule-task"
                        data-match-id="${matchId}"
                        data-task-type="${taskType}" aria-label="Button"><i class="fas fa-redo"></i></button>
            </div>
        </div>
    `;
}

/**
 * Create a "no task" card
 * @param {string} taskName
 * @param {string} message
 * @returns {string} HTML string
 */
export function createNoTaskCard(taskName, message) {
    const typeIcon = taskName.includes('Thread') ? 'fa-comments' : 'fa-broadcast-tower';
    return `
        <div data-component="no-task-card" data-task-name="${taskName}" class="mb-1 p-2 border rounded bg-light">
            <div class="d-flex align-items-center">
                <i class="fas ${typeIcon} me-2 text-muted"></i>
                <div class="flex-grow-1">
                    <small class="fw-bold text-muted">${taskName}</small><br>
                    <small class="text-muted">${message}</small>
                </div>
                <span class="badge bg-secondary" data-status="not-scheduled">Not Scheduled</span>
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
            <div class="text-center">
                <small class="text-muted"><i class="fas fa-database"></i> Task system unavailable</small><br>
                <small class="text-muted">Redis connection needed</small>
            </div>
        `;
    } else {
        container.innerHTML = `
            <div class="alert alert-danger alert-sm mb-0">
                <small><i class="fas fa-exclamation-triangle"></i> ${error}</small>
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
