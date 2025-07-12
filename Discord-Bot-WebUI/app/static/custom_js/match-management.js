/**
 * Match Management JavaScript
 * Handles match scheduling, status updates, task management, and administrative functions
 * 
 * Dependencies: jQuery, Bootstrap 5, SweetAlert2
 */

// Global variables
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
    fetch('/admin/match_management/statuses')
        .then(response => response.json())
        .then(data => {
            if (data.statuses) {
                data.statuses.forEach(match => {
                    updateMatchRow(match);
                });
            }
            document.getElementById('lastUpdated').textContent = 
                `Last updated: ${new Date().toLocaleTimeString()}`;
        })
        .catch(error => console.error('Error refreshing statuses:', error));
}

function updateMatchRow(match) {
    const statusBadge = document.getElementById(`status-${match.id}`);
    if (statusBadge) {
        statusBadge.className = `badge bg-${match.status_color}`;
        statusBadge.innerHTML = `<i class="fas ${match.status_icon}"></i> ${match.status_display}`;
    }
    
    // Update task details with new task details structure
    const taskDetailsContainer = document.getElementById(`task-details-${match.id}`);
    if (taskDetailsContainer && match.task_details) {
        updateTaskDetailsFromCelery(match.id, match.task_details);
    }
}

function updateTaskDetails(matchId, scheduledTasks, activeTaskId) {
    const container = document.getElementById(`task-details-${matchId}`);
    if (!container) return;
    
    let html = '';
    let hasScheduledTasks = false;
    
    // Check for active task first
    if (activeTaskId) {
        html += `
            <div class="mb-2">
                <span class="badge bg-success mb-1">
                    <i class="fas fa-play"></i> Running
                </span>
                <div class="font-monospace small text-truncate" style="max-width: 120px;" title="${activeTaskId}">
                    ${activeTaskId.substring(0, 8)}...
                </div>
                <button class="btn btn-xs btn-outline-info mt-1" onclick="showTaskDetails('${matchId}', '${activeTaskId}')">
                    <i class="fas fa-info-circle"></i> Details
                </button>
            </div>
        `;
    }
    
    // Show scheduled thread task
    if (scheduledTasks.thread && scheduledTasks.thread.scheduled) {
        hasScheduledTasks = true;
        const scheduledTime = formatScheduledTime(scheduledTasks.thread.scheduled_time);
        html += `
            <div class="mb-1">
                <span class="badge bg-warning text-dark mb-1">
                    <i class="fas fa-comments"></i> Thread Queued
                </span>
                <div class="small">
                    <div class="font-monospace text-truncate" style="max-width: 120px;" title="${scheduledTasks.thread.task_id}">
                        ${scheduledTasks.thread.task_id ? scheduledTasks.thread.task_id.substring(0, 8) + '...' : 'N/A'}
                    </div>
                    <div class="text-muted">Due: ${scheduledTime}</div>
                </div>
            </div>
        `;
    }
    
    // Show scheduled reporting task
    if (scheduledTasks.reporting && scheduledTasks.reporting.scheduled) {
        hasScheduledTasks = true;
        const scheduledTime = formatScheduledTime(scheduledTasks.reporting.scheduled_time);
        html += `
            <div class="mb-1">
                <span class="badge bg-info mb-1">
                    <i class="fas fa-chart-line"></i> Report Queued
                </span>
                <div class="small">
                    <div class="font-monospace text-truncate" style="max-width: 120px;" title="${scheduledTasks.reporting.task_id}">
                        ${scheduledTasks.reporting.task_id ? scheduledTasks.reporting.task_id.substring(0, 8) + '...' : 'N/A'}
                    </div>
                    <div class="text-muted">Due: ${scheduledTime}</div>
                </div>
            </div>
        `;
    }
    
    if (!hasScheduledTasks && !activeTaskId) {
        html = '<small class="text-muted">No scheduled tasks</small>';
    }
    
    container.innerHTML = html;
}

function loadTaskDetails(matchId) {
    fetch(`/admin/match_management/task-details/${matchId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                updateTaskDetails(matchId, data.scheduled_tasks, data.active_task_id);
            } else {
                const container = document.getElementById(`task-details-${matchId}`);
                if (container) {
                    container.innerHTML = '<small class="text-danger">Failed to load task info</small>';
                }
            }
        })
        .catch(error => {
            console.error('Error loading task details:', error);
            const container = document.getElementById(`task-details-${matchId}`);
            if (container) {
                container.innerHTML = '<small class="text-danger">Error loading tasks</small>';
            }
        });
}

function updateTaskDetailsFromCelery(matchId, taskDetails) {
    const container = document.getElementById(`task-details-${matchId}`);
    if (!container) return;
    
    let html = '';
    
    if (taskDetails.active_tasks && taskDetails.active_tasks.length > 0) {
        taskDetails.active_tasks.forEach(task => {
            const eta = task.eta ? formatTaskETA(task.eta) : 'Unknown';
            const ttl = task.ttl ? formatTTL(task.ttl) : 'No limit';
            
            html += `
                <div class="mb-2">
                    <span class="badge bg-${getTaskStatusColor(task.state)} mb-1">
                        <i class="fas fa-play"></i> ${task.state}
                    </span>
                    <div class="font-monospace small text-truncate" style="max-width: 120px;" title="${task.task_id}">
                        ${task.task_id.substring(0, 8)}...
                    </div>
                    <div class="small text-muted">
                        ETA: ${eta} | TTL: ${ttl}
                    </div>
                    <button class="btn btn-xs btn-outline-info mt-1" onclick="showTaskDetails('${matchId}', '${task.task_id}')">
                        <i class="fas fa-info-circle"></i> Details
                    </button>
                </div>
            `;
        });
    }
    
    if (taskDetails.scheduled_tasks && taskDetails.scheduled_tasks.length > 0) {
        taskDetails.scheduled_tasks.forEach(task => {
            const scheduledTime = formatScheduledTime(task.eta);
            
            html += `
                <div class="mb-1">
                    <span class="badge bg-warning text-dark mb-1">
                        <i class="fas fa-clock"></i> Scheduled
                    </span>
                    <div class="small">
                        <div class="font-monospace text-truncate" style="max-width: 120px;" title="${task.task_id}">
                            ${task.task_id.substring(0, 8)}...
                        </div>
                        <div class="text-muted">Due: ${scheduledTime}</div>
                    </div>
                </div>
            `;
        });
    }
    
    if (!html) {
        html = '<small class="text-muted">No scheduled tasks</small>';
    }
    
    container.innerHTML = html;
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

function loadAllTaskDetails() {
    // Make a single request to get all match statuses
    fetch('/admin/match_management/statuses')
        .then(response => response.json())
        .then(data => {
            if (data.statuses) {
                data.statuses.forEach(match => {
                    if (match.task_details) {
                        updateTaskDetailsFromCelery(match.id, match.task_details);
                    } else {
                        const container = document.getElementById(`task-details-${match.id}`);
                        if (container) {
                            container.innerHTML = '<small class="text-muted">No scheduled tasks</small>';
                        }
                    }
                });
            }
        })
        .catch(error => {
            console.error('Error loading task details:', error);
            // Update all containers to show error state
            document.querySelectorAll('[id^="task-details-"]').forEach(container => {
                container.innerHTML = '<small class="text-danger">Failed to load task info</small>';
            });
        });
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
    document.querySelectorAll('.scheduled-time').forEach(element => {
        const isoTime = element.getAttribute('data-time');
        element.textContent = formatScheduledTime(isoTime);
    });
}

function getStatusColor(status) {
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

function getStatusIcon(status) {
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
function scheduleMatch(matchId) {
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
            Swal.fire('Success!', data.message, 'success');
            refreshStatuses();
        } else {
            Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        Swal.fire('Error!', 'An error occurred while scheduling the match.', 'error');
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
            Swal.fire('Success!', data.message, 'success');
            refreshStatuses();
        } else {
            Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        Swal.fire('Error!', 'An error occurred while creating the thread.', 'error');
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
            Swal.fire('Success!', data.message, 'success');
            refreshStatuses();
        } else {
            Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        Swal.fire('Error!', 'An error occurred while starting live reporting.', 'error');
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
            Swal.fire('Success!', data.message, 'success');
            refreshStatuses();
        } else {
            Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        Swal.fire('Error!', 'An error occurred while stopping live reporting.', 'error');
    });
}

function showTaskDetails(matchId, taskId) {
    // Implementation for showing task details
    Swal.fire({
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
    const date = dateInput.value;
    
    if (!date) {
        Swal.fire('Error!', 'Please select a date.', 'error');
        return;
    }
    
    const formData = new FormData();
    formData.append('date', date);
    formData.append('competition', 'MLS'); // Default competition
    
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
            Swal.fire('Success!', data.message, 'success');
            setTimeout(() => location.reload(), 2000);
        } else {
            Swal.fire('Error!', data.message || data.error, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        Swal.fire('Error!', 'An error occurred while adding matches.', 'error');
    });
}

function scheduleAllMatches() {
    Swal.fire({
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
                    Swal.fire('Success!', data.message, 'success');
                    refreshStatuses();
                } else {
                    Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                Swal.fire('Error!', 'An error occurred while scheduling matches.', 'error');
            });
        }
    });
}

function fetchAllFromESPN() {
    Swal.fire({
        title: 'Fetch All Matches from ESPN?',
        text: 'This will fetch all matches for the current season from ESPN.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, fetch all!'
    }).then((result) => {
        if (result.isConfirmed) {
            Swal.fire({
                title: 'Fetching matches...',
                text: 'This may take a few moments.',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
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
                    Swal.fire('Success!', data.message, 'success');
                    setTimeout(() => location.reload(), 2000);
                } else {
                    Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                Swal.fire('Error!', 'An error occurred while fetching matches.', 'error');
            });
        }
    });
}

function clearAllMatches() {
    Swal.fire({
        title: 'Clear All Matches?',
        text: 'This will remove ALL matches from the database. This action cannot be undone!',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, clear all!',
        confirmButtonColor: '#d33'
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
                    Swal.fire('Success!', data.message, 'success');
                    setTimeout(() => location.reload(), 2000);
                } else {
                    Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                Swal.fire('Error!', 'An error occurred while clearing matches.', 'error');
            });
        }
    });
}

function editMatch(matchId) {
    // Implementation for editing a match
    Swal.fire('Info', 'Edit match functionality to be implemented.', 'info');
}

function removeMatch(matchId) {
    Swal.fire({
        title: 'Remove Match?',
        text: 'This will remove the match from the database.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, remove it!',
        confirmButtonColor: '#d33'
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
                    Swal.fire('Success!', data.message, 'success');
                    setTimeout(() => location.reload(), 2000);
                } else {
                    Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                Swal.fire('Error!', 'An error occurred while removing the match.', 'error');
            });
        }
    });
}

// Queue management functions
function showQueueStatus() {
    $('#queueStatusModal').modal('show');
    refreshQueueStatus();
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
                    <td><span class="badge bg-${getTaskStatusColor(task.state)}">${task.state}</span></td>
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
                    <div class="card">
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
                Swal.fire('Error!', data.message, 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            Swal.fire('Error!', 'An error occurred while fetching debug information.', 'error');
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
    
    Swal.fire({
        title: 'Debug Information',
        html: html,
        width: '80%',
        confirmButtonText: 'Close'
    });
}

function forceScheduleMatch(matchId) {
    Swal.fire({
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
                    Swal.fire('Success!', data.message, 'success');
                    refreshStatuses();
                } else {
                    Swal.fire('Error!', data.message, 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                Swal.fire('Error!', 'An error occurred while force scheduling the match.', 'error');
            });
        }
    });
}

// Initialize match management when DOM is ready
$(document).ready(function() {
    // Initialize CSRF token
    initializeCSRFToken();
    
    // Format scheduled times on initial page load
    formatScheduledTimes();
    
    // Load task details for all matches after a short delay
    setTimeout(loadAllTaskDetails, 1000);
    
    // Auto-refresh every 30 seconds
    setInterval(refreshStatuses, 30000);
});