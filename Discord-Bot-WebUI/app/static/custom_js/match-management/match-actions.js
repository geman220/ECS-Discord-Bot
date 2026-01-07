'use strict';

/**
 * Match Management Actions
 * Match scheduling, thread creation, and live reporting functions
 * @module match-management/match-actions
 */

import { getCSRFToken } from './state.js';
import { refreshStatuses } from './task-api.js';

/**
 * Schedule a match
 * @param {string|number} matchId
 */
export function matchMgmtScheduleMatch(matchId) {
    fetch(`/admin/match_management/schedule/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            refreshStatuses();
        } else {
            window.Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while scheduling the match.', 'error');
    });
}

/**
 * Create thread immediately
 * @param {string|number} matchId
 */
export function createThreadNow(matchId) {
    fetch(`/admin/match_management/create-thread/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            refreshStatuses();
        } else {
            window.Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while creating the thread.', 'error');
    });
}

/**
 * Start live reporting
 * @param {string|number} matchId
 */
export function startLiveReporting(matchId) {
    fetch(`/admin/match_management/start-reporting/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            refreshStatuses();
        } else {
            window.Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while starting live reporting.', 'error');
    });
}

/**
 * Stop live reporting
 * @param {string|number} matchId
 */
export function stopLiveReporting(matchId) {
    fetch(`/admin/match_management/stop-reporting/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire('Success!', data.message, 'success');
            refreshStatuses();
        } else {
            window.Swal.fire('Error!', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        window.Swal.fire('Error!', 'An error occurred while stopping live reporting.', 'error');
    });
}

/**
 * Add match by date
 */
export function addMatchByDate() {
    const dateInput = document.getElementById('matchDate');
    const competitionInput = document.getElementById('matchCompetition');
    const date = dateInput.value;
    const competition = competitionInput.value;

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

    fetch('/admin/match_management/add-by-date', {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCSRFToken()
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

/**
 * Schedule all matches
 */
export function scheduleAllMatches() {
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
                    'X-CSRFToken': getCSRFToken()
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success');
                    refreshStatuses();
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

/**
 * Fetch all matches from ESPN
 */
export function fetchAllFromESPN() {
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
                    'X-CSRFToken': getCSRFToken()
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

/**
 * Clear all matches
 */
export function clearAllMatches() {
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
                    'X-CSRFToken': getCSRFToken()
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

/**
 * Edit a match (placeholder)
 * @param {string|number} matchId
 */
export function matchMgmtEditMatch(matchId) {
    window.Swal.fire('Info', 'Edit match functionality to be implemented.', 'info');
}

/**
 * Remove a match
 * @param {string|number} matchId
 */
export function removeMatch(matchId) {
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
                    'X-CSRFToken': getCSRFToken()
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

/**
 * Force schedule a match
 * @param {string|number} matchId
 */
export function forceScheduleMatch(matchId) {
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
                    'X-CSRFToken': getCSRFToken()
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Success!', data.message, 'success');
                    refreshStatuses();
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
