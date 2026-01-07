'use strict';

/**
 * Match Management Task API
 * API calls for task loading and management
 * @module match-management/task-api
 */

import {
    isMatchManagementPage,
    isRequestPending,
    addPendingRequest,
    removePendingRequest,
    getCSRFToken
} from './state.js';
import { updateMatchTaskDetails, showTaskError, updateMatchRow } from './task-display.js';
import { getStatusColor, formatDuration } from './helpers.js';

/**
 * Refresh match statuses from server
 */
export function refreshStatuses() {
    const lastUpdatedEl = document.getElementById('lastUpdated');
    if (!lastUpdatedEl) {
        return;
    }

    fetch('/admin/match_management/statuses')
        .then(response => response.json())
        .then(data => {
            if (data.statuses) {
                data.statuses.forEach(match => {
                    updateMatchRow(match);
                });
            }
            lastUpdatedEl.textContent =
                `Last updated: ${new Date().toLocaleTimeString()}`;
        })
        .catch(error => console.error('Error refreshing statuses:', error));
}

/**
 * Load detailed task information for a specific match
 * @param {string|number} matchId
 */
export function loadMatchTaskDetails(matchId) {
    if (!isMatchManagementPage()) {
        return;
    }

    if (isRequestPending(matchId)) {
        return;
    }
    addPendingRequest(matchId);

    fetch(`/admin/match_management/match-tasks/${matchId}`)
        .then(response => {
            if (!response.ok) {
                throw new Error(`Server error: ${response.status}`);
            }
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                throw new Error('Server returned non-JSON response');
            }
            return response.json();
        })
        .then(data => {
            updateMatchTaskDetails(matchId, data);
        })
        .catch(error => {
            if (window.location.hostname === 'localhost' || window.location.hostname.includes('dev')) {
                console.warn(`Task details unavailable for match ${matchId}:`, error.message);
            }
            showTaskError(matchId, 'Task status unavailable');
        })
        .finally(() => {
            removePendingRequest(matchId);
        });
}

/**
 * Load task details for all matches on the page
 */
export function loadAllTaskDetails() {
    if (!isMatchManagementPage()) {
        return;
    }

    const matchRows = document.querySelectorAll('[data-match-id]:not([data-match-type="historical"])');
    matchRows.forEach(row => {
        const matchId = row.getAttribute('data-match-id');
        if (matchId) {
            loadMatchTaskDetails(matchId);
        }
    });

    const historicalSection = document.getElementById('historicalMatches');
    if (historicalSection && historicalSection.classList.contains('show')) {
        const historicalRows = document.querySelectorAll('[data-match-type="historical"][data-match-id]');
        historicalRows.forEach(row => {
            const matchId = row.getAttribute('data-match-id');
            if (matchId) {
                loadMatchTaskDetails(matchId);
            }
        });
    }
}

/**
 * Revoke a task
 * @param {string} taskId
 * @param {string|number} matchId
 * @param {string} taskType
 */
export function revokeTask(taskId, matchId, taskType) {
    window.Swal.fire({
        title: 'Revoke Task?',
        text: `Are you sure you want to revoke this ${taskType} task?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545',
        cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('secondary') : '#6c757d',
        confirmButtonText: 'Yes, revoke it!'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch('/admin/match_management/revoke-task', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCSRFToken()
                },
                body: JSON.stringify({
                    task_id: taskId,
                    match_id: matchId,
                    task_type: taskType
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Revoked!', data.message, 'success');
                    loadMatchTaskDetails(matchId);
                } else {
                    window.Swal.fire('Error!', data.error, 'error');
                }
            })
            .catch(error => {
                window.Swal.fire('Error!', 'Failed to revoke task', 'error');
            });
        }
    });
}

/**
 * Reschedule a task
 * @param {string|number} matchId
 * @param {string} taskType
 */
export function rescheduleTask(matchId, taskType) {
    window.Swal.fire({
        title: 'Reschedule Task?',
        text: `This will reschedule the ${taskType} task for match ${matchId}`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('success') : '#198754',
        cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('secondary') : '#6c757d',
        confirmButtonText: 'Yes, reschedule!'
    }).then((result) => {
        if (result.isConfirmed) {
            import('./match-actions.js').then(({ matchMgmtScheduleMatch }) => {
                matchMgmtScheduleMatch(matchId);
            });
        }
    });
}

/**
 * Show task info modal
 * @param {string} taskId
 * @param {string} taskType
 * @param {string|Object} taskData
 */
export function showTaskInfo(taskId, taskType, taskData) {
    let taskObj;
    try {
        taskObj = typeof taskData === 'string' ? JSON.parse(taskData) : taskData;
    } catch (e) {
        taskObj = { error: 'Failed to parse task data', raw: taskData };
    }

    const modalHtml = `
        <div class="task-info-details">
            <h6><i class="fas fa-info-circle"></i> ${taskType}</h6>
            <table class="table table-sm">
                <tr><td><strong>Task ID:</strong></td><td><code>${taskObj.task_id || 'N/A'}</code></td></tr>
                <tr><td><strong>Status:</strong></td><td><span class="badge bg-${getStatusColor(taskObj.status)}" data-status="${taskObj.status}">${taskObj.status}</span></td></tr>
                <tr><td><strong>ETA:</strong></td><td>${taskObj.eta ? new Date(taskObj.eta).toLocaleString() : 'N/A'}</td></tr>
                <tr><td><strong>TTL:</strong></td><td>${taskObj.ttl ? formatDuration(taskObj.ttl) : 'N/A'}</td></tr>
                <tr><td><strong>Redis Key:</strong></td><td><code>${taskObj.redis_key || 'N/A'}</code></td></tr>
                ${taskObj.result ? `<tr><td><strong>Result:</strong></td><td><pre class="small">${taskObj.result}</pre></td></tr>` : ''}
            </table>
        </div>
    `;

    window.Swal.fire({
        title: 'Task Information',
        html: modalHtml,
        width: '600px',
        showCloseButton: true,
        focusConfirm: false
    });
}

/**
 * Show task details
 * @param {string|number} matchId
 * @param {string} taskId
 */
export function showTaskDetails(matchId, taskId) {
    window.Swal.fire({
        title: 'Task Details',
        html: `
            <div class="text-start">
                <strong>Match ID:</strong> ${matchId}<br>
                <strong>Task ID:</strong> ${taskId}<br>
                <em>Detailed task information would be loaded here...</em>
            </div>
        `,
        confirmButtonText: 'Close'
    });
}
