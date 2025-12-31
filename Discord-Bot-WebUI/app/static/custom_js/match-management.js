/**
 * Match Management JavaScript
 * Handles match scheduling, status updates, task management, and administrative functions
 *
 * Dependencies: jQuery, Bootstrap 5, SweetAlert2
 */

(function() {
    'use strict';

    let _initialized = false;
    let csrfToken = '';

// Initialize CSRF token
function initializeCSRFToken() {
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
        csrfToken = csrfMeta.getAttribute('content');
    } else {
        // Fallback: try to get from a hidden input if meta tag doesn't exist
        const csrfInput = document.querySelector('input[name="csrf_token"]');
        if (csrfInput) {
            csrfToken = csrfInput.value;
        }
    }
}

// Auto-refresh functionality
function refreshStatuses() {
    // Page guard - only run on match management page
    const lastUpdatedEl = document.getElementById('lastUpdated');
    if (!lastUpdatedEl) {
        return; // Not on match management page
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

function updateMatchRow(match) {
    const statusBadge = document.getElementById(`status-${match.id}`);
    if (statusBadge) {
        // Set stable structure first
        statusBadge.className = 'badge'; // Keep styling class for CSS
        statusBadge.classList.add(`bg-${match.status_color}`); // Keep visual styling
        statusBadge.setAttribute('data-status', match.status); // For JS behavior
        statusBadge.innerHTML = `<i class="fas ${match.status_icon}"></i> ${match.status_display}`;
    }

    // Update task details with real-time data
    window.loadMatchTaskDetails(match.id);
}

// Load detailed task information for a specific match
function loadMatchTaskDetails(matchId) {
    fetch(`/admin/match_management/match-tasks/${matchId}`)
        .then(response => response.json())
        .then(data => {
            updateMatchTaskDetails(matchId, data);
        })
        .catch(error => {
            console.error(`Error loading task details for match ${matchId}:`, error);
            showTaskError(matchId, 'Failed to load task details');
        });
}

// Update the task details display for a match
function updateMatchTaskDetails(matchId, data) {
    const container = document.getElementById(`task-details-${matchId}`);
    
    if (!container) {
        console.error(`No container found for task-details-${matchId}`);
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

// Create a task card for display
function createTaskCard(taskType, task, matchId) {
    const statusColor = getStatusColor(task.status);
    const statusIcon = getStatusIcon(task.status);
    const typeName = task.type || (taskType === 'thread' ? 'Thread Creation' : 'Live Reporting');
    const typeIcon = taskType === 'thread' ? 'fa-comments' : 'fa-broadcast-tower';

    // Use human-readable message if available (from fallback logic)
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

    // Escape data for safe HTML attribute embedding
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

// Create a "no task" card
function createNoTaskCard(taskName, message) {
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

// Show task error
function showTaskError(matchId, error) {
    const container = document.getElementById(`task-details-${matchId}`);
    if (!container) return;
    
    // Show better display when Redis is unavailable
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

// Helper functions
function getStatusColor(status) {
    const statusColors = {
        'PENDING': 'warning',
        'STARTED': 'info', 
        'SUCCESS': 'success',
        'FAILURE': 'danger',
        'RETRY': 'warning',
        'REVOKED': 'secondary',
        'RUNNING': 'info',
        'FINISHED': 'success',
        'MISSING': 'danger',
        'Completed': 'success',
        'Scheduled': 'warning',
        'Active': 'info',
        'Issue': 'danger'
    };
    return statusColors[status] || 'secondary';
}

function getStatusIcon(status) {
    const statusIcons = {
        'PENDING': 'fa-clock',
        'STARTED': 'fa-play',
        'SUCCESS': 'fa-check',
        'FAILURE': 'fa-times',
        'RETRY': 'fa-redo',
        'REVOKED': 'fa-ban',
        'RUNNING': 'fa-play',
        'FINISHED': 'fa-check',
        'MISSING': 'fa-exclamation-triangle',
        'Completed': 'fa-check',
        'Scheduled': 'fa-clock',
        'Active': 'fa-play',
        'Issue': 'fa-exclamation-triangle'
    };
    return statusIcons[status] || 'fa-question';
}

function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${remainingMinutes}m`;
}

// Task control functions
function revokeTask(taskId, matchId, taskType) {
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
                    'X-CSRFToken': csrfToken
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
                    window.loadMatchTaskDetails(matchId);
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

function rescheduleTask(matchId, taskType) {
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
            // Use existing schedule match functionality
            window.matchMgmtScheduleMatch(matchId);
        }
    });
}

function showTaskInfo(taskId, taskType, taskData) {
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

// Load task details for all matches on the page
function loadAllTaskDetails() {
    // Find all match rows and load their task details, but exclude historical matches unless expanded
    const matchRows = document.querySelectorAll('[data-match-id]:not([data-match-type="historical"])');
    matchRows.forEach(row => {
        const matchId = row.getAttribute('data-match-id');
        if (matchId) {
            window.loadMatchTaskDetails(matchId);
        }
    });

    // Also load for expanded historical matches
    const historicalSection = document.getElementById('historicalMatches');
    if (historicalSection && historicalSection.classList.contains('show')) {
        const historicalRows = document.querySelectorAll('[data-match-type="historical"][data-match-id]');
        historicalRows.forEach(row => {
            const matchId = row.getAttribute('data-match-id');
            if (matchId) {
                window.loadMatchTaskDetails(matchId);
            }
        });
    }
}




function formatTaskETA(etaString) {
    if (!etaString) return 'Unknown';
    
    try {
        const etaDate = new Date(etaString);
        const now = new Date();
        const diff = etaDate - now;
        
        if (diff > 0) {
            const minutes = Math.floor(diff / (1000 * 60));
            const hours = Math.floor(minutes / 60);
            
            if (hours > 0) {
                return `${hours}h ${minutes % 60}m`;
            } else {
                return `${minutes}m`;
            }
        } else {
            return 'Now';
        }
    } catch (e) {
        return 'Invalid';
    }
}

function formatTTL(seconds) {
    if (!seconds || seconds <= 0) return 'No limit';
    
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    
    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    } else if (minutes > 0) {
        return `${minutes}m`;
    } else {
        return `${seconds}s`;
    }
}


function formatScheduledTime(isoString) {
    if (!isoString) return 'Unknown';
    
    try {
        const date = new Date(isoString);
        const now = new Date();
        const diff = date - now;
        
        if (diff > 0) {
            const hours = Math.floor(diff / (1000 * 60 * 60));
            const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
            
            if (hours > 24) {
                const days = Math.floor(hours / 24);
                const remainingHours = hours % 24;
                return `${days}d ${remainingHours}h`;
            } else if (hours > 0) {
                return `${hours}h ${minutes}m`;
            } else {
                return `${minutes}m`;
            }
        } else {
            return 'Overdue';
        }
    } catch (e) {
        return 'Invalid';
    }
}

function formatScheduledTimes() {
    // Format all scheduled time elements on the page
    document.querySelectorAll('[data-time][data-component="scheduled-time"]').forEach(element => {
        const isoTime = element.getAttribute('data-time');
        element.textContent = formatScheduledTime(isoTime);
    });
}

function getScheduleStatusColor(status) {
    const colors = {
        'not_started': 'secondary',
        'scheduled': 'warning',
        'running': 'success',
        'completed': 'info',
        'stopped': 'danger',
        'failed': 'danger'
    };
    return colors[status] || 'secondary';
}

function getScheduleStatusIcon(status) {
    const icons = {
        'not_started': 'fa-circle',
        'scheduled': 'fa-clock',
        'running': 'fa-play-circle',
        'completed': 'fa-check-circle',
        'stopped': 'fa-stop-circle',
        'failed': 'fa-exclamation-triangle'
    };
    return icons[status] || 'fa-circle';
}

function getStatusDisplay(status) {
    const displays = {
        'not_started': 'Not Started',
        'scheduled': 'Scheduled',
        'running': 'Running',
        'completed': 'Completed', 
        'stopped': 'Stopped',
        'failed': 'Failed'
    };
    return displays[status] || status;
}

// Match action functions
function matchMgmtScheduleMatch(matchId) {
    fetch(`/admin/match_management/schedule/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            window.refreshStatuses();
        } else {
            window.Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while scheduling the match.', 'error');
    });
}

function createThreadNow(matchId) {
    fetch(`/admin/match_management/create-thread/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            window.refreshStatuses();
        } else {
            window.Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while creating the thread.', 'error');
    });
}

function startLiveReporting(matchId) {
    fetch(`/admin/match_management/start-reporting/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            window.refreshStatuses();
        } else {
            window.Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while starting live reporting.', 'error');
    });
}

function stopLiveReporting(matchId) {
    fetch(`/admin/match_management/stop-reporting/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            window.refreshStatuses();
        } else {
            window.Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while stopping live reporting.', 'error');
    });
}

function showTaskDetails(matchId, taskId) {
    // Implementation for showing task details
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

function getTaskStatusColor(status) {
    const colors = {
        'PENDING': 'warning',
        'STARTED': 'info',
        'RETRY': 'warning',
        'FAILURE': 'danger',
        'SUCCESS': 'success'
    };
    return colors[status] || 'secondary';
}

function addMatchByDate() {
    const dateInput = document.getElementById('matchDate');
    const competitionInput = document.getElementById('matchCompetition');
    const date = dateInput.value;
    const competition = competitionInput.value;
    
    console.log('Selected competition:', competition);
    console.log('Competition dropdown options:', competitionInput.options);
    console.log('Selected index:', competitionInput.selectedIndex);
    
    if (!date) {
        window.Swal.fire('Error!', 'Please select a date.', 'error');
        return;
    }
    
    if (!competition) {
        window.Swal.fire('Error!', 'Please select a competition.', 'error');
        return;
    }
    
    const formData = new FormData();
    formData.append('date', date);
    formData.append('competition', competition);
    
    console.log('Sending competition to server:', competition);
    
    fetch('/admin/match_management/add-by-date', {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        },
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            setTimeout(() => location.reload(), 2000);
        } else {
            window.Swal.fire('Error!', data.message || data.error, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while adding matches.', 'error');
    });
}

function scheduleAllMatches() {
    window.Swal.fire({
        title: 'Schedule All Matches?',
        text: 'This will schedule Discord threads and live reporting for all matches.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, schedule all!'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch('/admin/match_management/schedule-all', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success');
                    window.refreshStatuses();
                } else {
                    window.Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error!', 'An error occurred while scheduling matches.', 'error');
            });
        }
    });
}

function fetchAllFromESPN() {
    window.Swal.fire({
        title: 'Fetch All Matches from ESPN?',
        text: 'This will fetch all matches for the current season from ESPN.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, fetch all!'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Fetching matches...',
                text: 'This may take a few moments.',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();
                }
            });
            
            fetch('/admin/match_management/fetch-all-from-espn', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success');
                    setTimeout(() => location.reload(), 2000);
                } else {
                    window.Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error!', 'An error occurred while fetching matches.', 'error');
            });
        }
    });
}

function clearAllMatches() {
    window.Swal.fire({
        title: 'Clear All Matches?',
        text: 'This will remove ALL matches from the database. This action cannot be undone!',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, clear all!',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch('/admin/match_management/clear-all', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success');
                    setTimeout(() => location.reload(), 2000);
                } else {
                    window.Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error!', 'An error occurred while clearing matches.', 'error');
            });
        }
    });
}

function matchMgmtEditMatch(matchId) {
    // Implementation for editing a match
    window.Swal.fire('Info', 'Edit match functionality to be implemented.', 'info');
}

function removeMatch(matchId) {
    window.Swal.fire({
        title: 'Remove Match?',
        text: 'This will remove the match from the database.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, remove it!',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/admin/match_management/remove/${matchId}`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success');
                    setTimeout(() => location.reload(), 2000);
                } else {
                    window.Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error!', 'An error occurred while removing the match.', 'error');
            });
        }
    });
}

// Queue management functions
function matchMgmtShowQueueStatus() {
    window.$('#queueStatusModal').modal('show');
    window.refreshQueueStatus();
}

function refreshQueueStatus() {
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

function displayQueueStatus(data) {
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

// Debug functions
function debugMatchTasks(matchId) {
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

function showDebugModal(debugInfo) {
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

function forceScheduleMatch(matchId) {
    window.Swal.fire({
        title: 'Force Schedule Match?',
        text: 'This will force schedule the match, bypassing normal checks.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, force schedule!'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`/admin/match_management/force-schedule/${matchId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success');
                    window.refreshStatuses();
                } else {
                    window.Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error!', 'An error occurred while force scheduling the match.', 'error');
            });
        }
    });
}

    // Initialize function
    function init() {
        if (_initialized) return;
        _initialized = true;

        // Initialize CSRF token
        initializeCSRFToken();

        // Format scheduled times on initial page load
        formatScheduledTimes();

        // Load task details for all matches after a short delay
        setTimeout(loadAllTaskDetails, 1000);

        // With background cache, we can refresh less frequently
        // Refresh task details every 60 seconds (cache updates every 3 minutes)
        setInterval(loadAllTaskDetails, 60000);

        // Auto-refresh every 60 seconds
        setInterval(refreshStatuses, 60000);

        // Handle historical matches toggle
        const historicalToggle = document.getElementById('historicalMatches');
        const historicalToggleIcon = document.getElementById('historicalToggleIcon');

        if (historicalToggle && historicalToggleIcon) {
            historicalToggle.addEventListener('show.bs.collapse', function () {
                historicalToggleIcon.classList.remove('ti-chevron-down');
                historicalToggleIcon.classList.add('ti-chevron-up');

                // Load task details for historical matches when expanded
                setTimeout(() => {
                    document.querySelectorAll('[data-match-type="historical"][data-match-id]').forEach(card => {
                        const matchId = card.dataset.matchId;
                        if (matchId) {
                            window.loadMatchTaskDetails(matchId);
                        }
                    });
                }, 100);
            });

            historicalToggle.addEventListener('hide.bs.collapse', function () {
                historicalToggleIcon.classList.remove('ti-chevron-up');
                historicalToggleIcon.classList.add('ti-chevron-down');
            });
        }
    }

// Show cache status
function showCacheStatus() {
    fetch('/admin/match_management/cache-status')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const stats = data.cache_stats;
                const modalHtml = `
                    <div class="modal fade" id="cacheStatusModal" tabindex="-1">
                        <div class="modal-dialog modal-lg">
                            <div class="modal-content">
                                <div class="modal-header">
                                    <h5 class="modal-title">
                                        <i class="ti ti-database me-2"></i>Cache System Status
                                    </h5>
                                    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                                </div>
                                <div class="modal-body">
                                    <div class="row mb-3">
                                        <div class="col-md-6">
                                            <div data-component="cache-stat-card" data-stat-type="entries" class="card bg-primary text-white">
                                                <div class="card-body text-center">
                                                    <h3 class="card-title">${stats.total_entries}</h3>
                                                    <p class="card-text mb-0">Cached Entries</p>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="col-md-6">
                                            <div data-component="cache-stat-card" data-stat-type="coverage" class="card bg-success text-white">
                                                <div class="card-body text-center">
                                                    <h3 class="card-title">${stats.cache_coverage_percent.toFixed(1)}%</h3>
                                                    <p class="card-text mb-0">Coverage</p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="row mb-3">
                                        <div class="col-md-6">
                                            <div data-component="cache-stat-card" data-stat-type="health" class="card bg-info text-white">
                                                <div class="card-body text-center">
                                                    <h3 class="card-title">${stats.health_score_percent.toFixed(1)}%</h3>
                                                    <p class="card-text mb-0">Health Score</p>
                                                </div>
                                            </div>
                                        </div>
                                        <div class="col-md-6">
                                            <div data-component="cache-stat-card" data-stat-type="ttl" class="card bg-warning text-white">
                                                <div class="card-body text-center">
                                                    <h3 class="card-title">${Math.round(stats.ttl_seconds / 60)}min</h3>
                                                    <p class="card-text mb-0">Cache TTL</p>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="table-responsive">
                                        <table class="table table-sm">
                                            <tbody>
                                                <tr><td><strong>Active Matches:</strong></td><td>${stats.active_matches}</td></tr>
                                                <tr><td><strong>Sample Size:</strong></td><td>${stats.sample_size}</td></tr>
                                                <tr><td><strong>Valid Entries:</strong></td><td>${stats.valid_entries}</td></tr>
                                                <tr><td><strong>Avg Entry Size:</strong></td><td>${(stats.avg_entry_size_bytes / 1024).toFixed(1)} KB</td></tr>
                                                <tr><td><strong>Est. Total Size:</strong></td><td>${(stats.estimated_total_size_bytes / 1024 / 1024).toFixed(1)} MB</td></tr>
                                                <tr><td><strong>Last Updated:</strong></td><td>${new Date(data.timestamp).toLocaleString()}</td></tr>
                                            </tbody>
                                        </table>
                                    </div>
                                    <div class="alert alert-info">
                                        <i class="ti ti-info-circle me-2"></i>
                                        Cache is updated automatically every 3 minutes by background tasks. 
                                        High coverage and health scores indicate optimal performance.
                                    </div>
                                </div>
                                <div class="modal-footer">
                                    <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                                </div>
                            </div>
                        </div>
                    </div>
                `;
                
                // Remove existing modal if present
                const existingModal = document.getElementById('cacheStatusModal');
                if (existingModal) {
                    existingModal.remove();
                }
                
                // Add modal to body
                document.body.insertAdjacentHTML('beforeend', modalHtml);
                
                // Show modal
                window.ModalManager.show('cacheStatusModal');
                
                // Clean up when modal is hidden
                document.getElementById('cacheStatusModal').addEventListener('hidden.bs.modal', function () {
                    this.remove();
                });
                
            } else {
                alert('Failed to load cache status: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error loading cache status:', error);
            alert('Error loading cache status');
        });
}

    // Export functions for template compatibility
    window.refreshStatuses = refreshStatuses;
    window.loadMatchTaskDetails = loadMatchTaskDetails;
    window.loadAllTaskDetails = loadAllTaskDetails;
    window.revokeTask = revokeTask;
    window.rescheduleTask = rescheduleTask;
    window.showTaskInfo = showTaskInfo;
    window.matchMgmtScheduleMatch = matchMgmtScheduleMatch;
    window.createThreadNow = createThreadNow;
    window.startLiveReporting = startLiveReporting;
    window.stopLiveReporting = stopLiveReporting;
    window.showTaskDetails = showTaskDetails;
    window.addMatchByDate = addMatchByDate;
    window.scheduleAllMatches = scheduleAllMatches;
    window.fetchAllFromESPN = fetchAllFromESPN;
    window.clearAllMatches = clearAllMatches;
    window.matchMgmtEditMatch = matchMgmtEditMatch;
    window.removeMatch = removeMatch;
    window.matchMgmtShowQueueStatus = matchMgmtShowQueueStatus;
    window.refreshQueueStatus = refreshQueueStatus;
    window.debugMatchTasks = debugMatchTasks;
    window.forceScheduleMatch = forceScheduleMatch;
    window.showCacheStatus = showCacheStatus;

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('match-management', init, {
            priority: 40,
            reinitializable: false,
            description: 'Match management admin page'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
