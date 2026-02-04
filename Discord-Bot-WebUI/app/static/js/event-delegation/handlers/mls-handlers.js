import { EventDelegation } from '../core.js';

/**
 * MLS Management Action Handlers
 * Handles MLS match management, scheduling, and live reporting
 */

// ============================================================================
// MLS MATCH MANAGEMENT
// ============================================================================

/**
 * Fetch ESPN Matches
 * Fetches match data from ESPN API
 */
window.EventDelegation.register('fetch-espn', function(element, e) {
    e.preventDefault();

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-2"></i>Fetching...';
    element.disabled = true;

    fetch('/admin-panel/mls/fetch-espn', { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.AdminPanel !== 'undefined') {
                    window.AdminPanel.showMobileToast(data.message, 'success');
                }
                setTimeout(() => location.reload(), 1500);
            } else {
                throw new Error(data.error || 'Failed to fetch matches');
            }
        })
        .catch(error => {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
            }
        })
        .finally(() => {
            element.innerHTML = originalText;
            element.disabled = false;
        });
});

/**
 * Schedule All MLS Matches
 * Schedules tasks for all upcoming MLS matches
 * Note: Renamed from 'schedule-all-matches' to avoid conflict with match-management.js
 */
window.EventDelegation.register('mls-schedule-all-matches', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Schedule All Matches?',
            text: 'Schedule tasks for all upcoming matches?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, Schedule',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                const originalText = element.innerHTML;
                element.innerHTML = '<i class="ti ti-loader spin me-2"></i>Scheduling...';
                element.disabled = true;

                fetch('/admin-panel/mls/schedule-all', { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            if (typeof window.AdminPanel !== 'undefined') {
                                window.AdminPanel.showMobileToast(data.message, 'success');
                            }
                        } else {
                            throw new Error(data.error || 'Failed to schedule matches');
                        }
                    })
                    .catch(error => {
                        if (typeof window.AdminPanel !== 'undefined') {
                            window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
                        }
                    })
                    .finally(() => {
                        element.innerHTML = '<i class="ti ti-calendar-event me-2"></i>Schedule All';
                        element.disabled = false;
                    });
            }
        });
    }
});

/**
 * Schedule MLS Match
 * Schedules tasks for a specific MLS match
 * Note: Renamed from 'schedule-match' to avoid conflict with match-management.js
 */
window.EventDelegation.register('mls-schedule-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[mls-schedule-match] Missing match ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    fetch(`/admin-panel/mls/schedule/${matchId}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.AdminPanel !== 'undefined') {
                    window.AdminPanel.showMobileToast(data.message, 'success');
                }
            } else {
                throw new Error(data.error || 'Failed to schedule match');
            }
        })
        .catch(error => {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
            }
        })
        .finally(() => {
            element.innerHTML = originalText;
            element.disabled = false;
        });
});

/**
 * Create Thread
 * Creates a Discord thread for a match
 */
window.EventDelegation.register('create-thread', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[create-thread] Missing match ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    fetch(`/admin-panel/mls/create-thread/${matchId}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.AdminPanel !== 'undefined') {
                    window.AdminPanel.showMobileToast(data.message, 'success');
                }
                setTimeout(() => location.reload(), 1500);
            } else {
                throw new Error(data.error || 'Failed to create thread');
            }
        })
        .catch(error => {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
            }
        })
        .finally(() => {
            element.innerHTML = originalText;
            element.disabled = false;
        });
});

/**
 * Start Reporting
 * Starts live reporting for a match
 */
window.EventDelegation.register('start-reporting', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[start-reporting] Missing match ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    fetch(`/admin-panel/mls/start-reporting/${matchId}`, { method: 'POST' })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.AdminPanel !== 'undefined') {
                    window.AdminPanel.showMobileToast(data.message, 'success');
                }
                setTimeout(() => location.reload(), 1500);
            } else {
                throw new Error(data.error || 'Failed to start reporting');
            }
        })
        .catch(error => {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
            }
        })
        .finally(() => {
            element.innerHTML = originalText;
            element.disabled = false;
        });
});

/**
 * Stop Reporting
 * Stops live reporting for a match
 */
window.EventDelegation.register('stop-reporting', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[stop-reporting] Missing match ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Stop Reporting?',
            text: 'Stop live reporting for this match?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, Stop',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                const originalText = element.innerHTML;
                element.innerHTML = '<i class="ti ti-loader spin"></i>';
                element.disabled = true;

                fetch(`/admin-panel/mls/stop-reporting/${matchId}`, { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            if (typeof window.AdminPanel !== 'undefined') {
                                window.AdminPanel.showMobileToast(data.message, 'success');
                            }
                            setTimeout(() => location.reload(), 1500);
                        } else {
                            throw new Error(data.error || 'Failed to stop reporting');
                        }
                    })
                    .catch(error => {
                        if (typeof window.AdminPanel !== 'undefined') {
                            window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
                        }
                    })
                    .finally(() => {
                        element.innerHTML = originalText;
                        element.disabled = false;
                    });
            }
        });
    }
});

/**
 * Resync Match
 * Resyncs a match to fix any issues
 */
window.EventDelegation.register('resync-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[resync-match] Missing match ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Resync Match?',
            text: 'Resync this match? This will check and fix any missing threads or tasks.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, Resync',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                const originalText = element.innerHTML;
                element.innerHTML = '<i class="ti ti-loader spin"></i>';
                element.disabled = true;

                fetch(`/admin-panel/mls/match/${matchId}/resync`, { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            let message = data.message;
                            if (data.actions && data.actions.length > 0) {
                                message += '\n\nActions:\n' + data.actions.join('\n');
                            }
                            if (typeof window.AdminPanel !== 'undefined') {
                                window.AdminPanel.showMobileToast(message, 'success');
                            }
                            setTimeout(() => location.reload(), 2000);
                        } else {
                            throw new Error(data.error || 'Failed to resync match');
                        }
                    })
                    .catch(error => {
                        if (typeof window.AdminPanel !== 'undefined') {
                            window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
                        }
                    })
                    .finally(() => {
                        element.innerHTML = originalText;
                        element.disabled = false;
                    });
            }
        });
    }
});

/**
 * Edit Match
 * Populates the edit match modal with data - Flowbite handles modal show/hide via data-modal-toggle
 */
window.EventDelegation.register('edit-match', function(element, e) {
    // Don't prevent default - let Flowbite handle the modal toggle

    const matchId = element.dataset.matchId;
    const opponent = element.dataset.opponent;
    const dateTime = element.dataset.dateTime;
    const venue = element.dataset.venue;
    const competition = element.dataset.competition;
    const isHome = element.dataset.isHome === 'true';

    if (!matchId) {
        console.error('[edit-match] Missing match ID');
        return;
    }

    // Populate form fields - modal is shown by Flowbite via data-modal-toggle
    document.getElementById('edit-match-id').value = matchId;
    document.getElementById('edit-opponent').value = opponent || '';
    document.getElementById('edit-venue').value = venue || '';
    document.getElementById('edit-competition').value = competition || 'usa.1';
    document.getElementById('edit-is-home').checked = isHome;

    // Format date-time for input (remove timezone info)
    if (dateTime) {
        const dt = new Date(dateTime);
        const localDateTime = new Date(dt.getTime() - (dt.getTimezoneOffset() * 60000))
            .toISOString()
            .slice(0, 16);
        document.getElementById('edit-date-time').value = localDateTime;
    }
});

/**
 * Remove Match
 * Removes a match from the system
 */
window.EventDelegation.register('remove-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[remove-match] Missing match ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Remove Match?',
            text: 'Are you sure you want to remove this match? This will also revoke any scheduled tasks.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, Remove',
            cancelButtonText: 'Cancel',
            confirmButtonColor: '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                const originalText = element.innerHTML;
                element.innerHTML = '<i class="ti ti-loader spin"></i>';
                element.disabled = true;

                fetch(`/admin-panel/mls/remove/${matchId}`, { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            if (typeof window.AdminPanel !== 'undefined') {
                                window.AdminPanel.showMobileToast(data.message, 'success');
                            }
                            const row = document.getElementById(`match-row-${matchId}`);
                            if (row) row.remove();
                        } else {
                            throw new Error(data.error || 'Failed to remove match');
                        }
                    })
                    .catch(error => {
                        if (typeof window.AdminPanel !== 'undefined') {
                            window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
                        }
                    })
                    .finally(() => {
                        element.innerHTML = originalText;
                        element.disabled = false;
                    });
            }
        });
    }
});

/**
 * Refresh Statuses
 * Refreshes status display for all matches
 */
window.EventDelegation.register('refresh-match-statuses', function(element, e) {
    e.preventDefault();

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-2"></i>';
    element.disabled = true;

    fetch('/admin-panel/mls/api/statuses')
        .then(response => response.json())
        .then(data => {
            if (data.statuses) {
                const colorMap = {
                    'success': 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
                    'danger': 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
                    'warning': 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
                    'info': 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
                    'primary': 'bg-ecs-green-100 text-ecs-green-800 dark:bg-ecs-green-900 dark:text-ecs-green-300',
                    'secondary': 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
                };
                data.statuses.forEach(status => {
                    const el = document.getElementById(`status-${status.id}`);
                    if (el) {
                        const badgeClasses = colorMap[status.status_color] || colorMap['secondary'];
                        el.className = `px-2 py-0.5 text-xs font-medium rounded ${badgeClasses}`;
                        el.innerHTML = `<i class="ti ${status.status_icon} me-1"></i>${status.status_display}`;
                    }
                });
                if (typeof window.AdminPanel !== 'undefined') {
                    window.AdminPanel.showMobileToast('Statuses refreshed', 'success');
                }
            }
        })
        .catch(error => {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Error refreshing statuses', 'danger');
            }
        })
        .finally(() => {
            element.innerHTML = '<i class="ti ti-refresh me-2"></i>Refresh';
            element.disabled = false;
        });
});

// ============================================================================
// LIVE REPORTING DASHBOARD
// ============================================================================

/**
 * Toggle Auto Refresh
 * Toggles auto-refresh for live reporting dashboard
 * Note: Renamed from 'toggle-auto-refresh' to avoid conflict with admin-panel-performance.js
 */
window.EventDelegation.register('mls-toggle-auto-refresh', function(element, e) {
    const isChecked = element.checked;

    if (typeof window.LiveReportingDashboard !== 'undefined') {
        if (isChecked) {
            window.LiveReportingDashboard.startAutoRefresh();
        } else {
            window.LiveReportingDashboard.stopAutoRefresh();
        }
    }
});

/**
 * Manual Refresh Dashboard
 * Manually refreshes the live reporting dashboard
 */
window.EventDelegation.register('refresh-live-dashboard', function(element, e) {
    e.preventDefault();

    if (typeof window.LiveReportingDashboard !== 'undefined') {
        window.LiveReportingDashboard.refresh();
    } else {
        location.reload();
    }
});

// ============================================================================
// TASK MONITORING
// ============================================================================

/**
 * Retry MLS Task
 * Retries a failed MLS task
 * Note: Renamed from 'retry-task' to avoid conflict with monitoring-handlers.js
 */
window.EventDelegation.register('mls-retry-task', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;

    if (!taskId) {
        console.error('[mls-retry-task] Missing task ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/mls/retry-task', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ task_id: taskId })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast('Task retried', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to retry task');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

/**
 * Expire Task
 * Marks a task as expired
 */
window.EventDelegation.register('expire-task', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;

    if (!taskId) {
        console.error('[expire-task] Missing task ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Expire Task?',
            text: 'Mark this task as expired?',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, Expire',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                const originalText = element.innerHTML;
                element.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-current border-t-transparent rounded-full spin"></span>';
                element.disabled = true;

                fetch(`/admin-panel/mls/task/${taskId}/expire`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        if (typeof window.AdminPanel !== 'undefined') {
                            window.AdminPanel.showMobileToast(data.message || 'Task expired', 'success');
                        }
                        setTimeout(() => location.reload(), 1500);
                    } else {
                        throw new Error(data.error || 'Failed to expire task');
                    }
                })
                .catch(error => {
                    if (typeof window.AdminPanel !== 'undefined') {
                        window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
                    }
                })
                .finally(() => {
                    element.innerHTML = originalText;
                    element.disabled = false;
                });
            }
        });
    }
});

/**
 * Toggle Auto Refresh Status
 * Toggles auto-refresh for task monitoring page
 */
window.EventDelegation.register('toggle-auto-refresh-status', function(element, e) {
    // Toggle auto-refresh state stored in a global or element data attribute
    const currentState = element.dataset.autoRefresh !== 'false';
    const newState = !currentState;
    element.dataset.autoRefresh = String(newState);
    element.textContent = `Auto-refresh: ${newState ? 'ON' : 'OFF'}`;
    element.classList.toggle('bg-secondary', !newState);
    element.classList.toggle('bg-success', newState);

    // Store the state for the auto-refresh interval to check
    window.taskMonitorAutoRefresh = newState;
});

/**
 * Manual Refresh
 * Manually refreshes the task monitoring page
 */
window.EventDelegation.register('manual-refresh', function(element, e) {
    e.preventDefault();
    location.reload();
});

/**
 * View MLS Task Logs
 * Shows logs for a specific MLS task
 * Note: Renamed from 'view-task-logs' to avoid conflict with monitoring-handlers.js
 */
window.EventDelegation.register('mls-view-task-logs', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;

    if (!taskId) {
        console.error('[mls-view-task-logs] Missing task ID');
        return;
    }

    fetch(`/admin-panel/mls/task-logs/${taskId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        title: 'Task Logs',
                        html: `<pre class="text-start scroll-container-md">${data.logs || 'No logs available'}</pre>`,
                        width: '800px'
                    });
                }
            } else {
                throw new Error(data.error || 'Failed to load logs');
            }
        })
        .catch(error => {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', error.message, 'error');
            }
        });
});

// ============================================================================
// MATCH CREATE/EDIT FORM HANDLERS
// ============================================================================

/**
 * Helper function to hide a Flowbite modal
 */
function hideFlowbiteModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        // Use Flowbite's modal instance if available
        if (modal._flowbiteModal) {
            modal._flowbiteModal.hide();
        } else {
            // Fallback: click the close button
            const closeBtn = modal.querySelector('[data-modal-hide]');
            if (closeBtn) {
                closeBtn.click();
            } else {
                // Last resort: manually hide
                modal.classList.add('hidden');
                modal.setAttribute('aria-hidden', 'true');
            }
        }
    }
}

/**
 * Initialize Create Match Form
 * Sets up the create match form submission handler
 */
document.addEventListener('DOMContentLoaded', function() {
    const createForm = document.getElementById('createMatchForm');
    if (createForm) {
        createForm.addEventListener('submit', function(e) {
            e.preventDefault();

            const submitBtn = createForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            submitBtn.innerHTML = '<i class="ti ti-loader spin mr-2"></i>Creating...';
            submitBtn.disabled = true;

            const formData = {
                opponent: document.getElementById('create-opponent').value,
                date_time: document.getElementById('create-date-time').value,
                venue: document.getElementById('create-venue').value,
                competition: document.getElementById('create-competition').value,
                is_home_game: document.getElementById('create-is-home').checked,
                auto_schedule: document.getElementById('create-auto-schedule').checked
            };

            fetch('/admin-panel/mls/create', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (typeof window.AdminPanel !== 'undefined') {
                        window.AdminPanel.showMobileToast(data.message, 'success');
                    }
                    // Hide modal using Flowbite pattern
                    hideFlowbiteModal('createMatchModal');
                    setTimeout(() => location.reload(), 1500);
                } else {
                    throw new Error(data.error || 'Failed to create match');
                }
            })
            .catch(error => {
                if (typeof window.AdminPanel !== 'undefined') {
                    window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
                } else if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', error.message, 'error');
                }
            })
            .finally(() => {
                submitBtn.innerHTML = originalText;
                submitBtn.disabled = false;
            });
        });
    }

    const editForm = document.getElementById('editMatchForm');
    if (editForm) {
        editForm.addEventListener('submit', function(e) {
            e.preventDefault();

            const matchId = document.getElementById('edit-match-id').value;
            const submitBtn = editForm.querySelector('button[type="submit"]');
            const originalText = submitBtn.innerHTML;
            submitBtn.innerHTML = '<i class="ti ti-loader spin mr-2"></i>Saving...';
            submitBtn.disabled = true;

            const formData = {
                opponent: document.getElementById('edit-opponent').value,
                date_time: document.getElementById('edit-date-time').value,
                venue: document.getElementById('edit-venue').value,
                competition: document.getElementById('edit-competition').value,
                is_home_game: document.getElementById('edit-is-home').checked
            };

            fetch(`/admin-panel/mls/edit/${matchId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(formData)
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    let message = data.message;
                    if (data.tasks_rescheduled) {
                        message += ' Tasks were rescheduled.';
                    }
                    if (typeof window.AdminPanel !== 'undefined') {
                        window.AdminPanel.showMobileToast(message, 'success');
                    }
                    // Hide modal using Flowbite pattern
                    hideFlowbiteModal('editMatchModal');
                    setTimeout(() => location.reload(), 1500);
                } else {
                    throw new Error(data.error || 'Failed to update match');
                }
            })
            .catch(error => {
                if (typeof window.AdminPanel !== 'undefined') {
                    window.AdminPanel.showMobileToast('Error: ' + error.message, 'danger');
                } else if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', error.message, 'error');
                }
            })
            .finally(() => {
                submitBtn.innerHTML = originalText;
                submitBtn.disabled = false;
            });
        });
    }
});

// Handlers loaded
