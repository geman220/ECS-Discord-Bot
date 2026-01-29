/**
 * ECS FC Schedule Management JavaScript
 *
 * This module handles all client-side functionality for ECS FC schedule management
 * including match creation, editing, calendar display, and RSVP handling.
 *
 * Component Name: ecs-fc-schedule
 * Priority: 30 (Page-specific features)
 */
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

// Module state
let _initialized = false;
let currentTeamId = null;
let calendar = null;
let currentMatches = [];

/**
 * Initialize ECS FC schedule functionality
 */
export function initializeEcsFcSchedule() {
    if (_initialized) return;

    // Get team ID from page data
    const teamData = document.getElementById('team-data');
    if (!teamData) return; // Not on ECS FC schedule page

    currentTeamId = parseInt(teamData.dataset.teamId);
    if (!currentTeamId) return;

    _initialized = true;

    // Initialize components
    initializeCalendar();
    ecsFcInitializeEventHandlers();
    loadTeamMatches();
}

/**
 * Initialize event handlers for ECS FC schedule management
 */
export function ecsFcInitializeEventHandlers() {
    // Create match button
    const createMatchBtn = document.getElementById('create-match-btn');
    if (createMatchBtn) {
        createMatchBtn.addEventListener('click', showCreateMatchModal);
    }

    // Import matches button
    const importMatchesBtn = document.getElementById('import-matches-btn');
    if (importMatchesBtn) {
        importMatchesBtn.addEventListener('click', showImportMatchesModal);
    }

    // Match form submission
    const matchForm = document.getElementById('ecs-fc-match-form');
    if (matchForm) {
        matchForm.addEventListener('submit', handleMatchFormSubmit);
    }

    // Import form submission
    const importForm = document.getElementById('ecs-fc-import-form');
    if (importForm) {
        importForm.addEventListener('submit', handleImportFormSubmit);
    }

    // RSVP form submissions
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('js-rsvp-btn')) {
            handleRsvpResponse(e.target);
        }
        if (e.target.classList.contains('js-edit-match-btn')) {
            ecsFcEditMatch(e.target.dataset.matchId);
        }
        if (e.target.classList.contains('js-delete-match-btn')) {
            ecsFcDeleteMatch(e.target.dataset.matchId);
        }
        if (e.target.classList.contains('js-send-reminder-btn')) {
            sendRsvpReminder(e.target.dataset.matchId);
        }
    });

    // Real-time updates via WebSocket
    if (typeof window.io !== 'undefined') {
        const socket = window.io();
        window.socket.on('rsvp_update', handleRsvpUpdate);
        window.socket.on('match_update', handleMatchUpdate);
    }
}

/**
 * Initialize FullCalendar for ECS FC matches
 */
export function initializeCalendar() {
    const calendarEl = document.getElementById('ecs-fc-calendar');
    if (!calendarEl) return;

    calendar = new FullCalendar.Calendar(calendarEl, {
        initialView: 'dayGridMonth',
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'dayGridMonth,timeGridWeek,listWeek'
        },
        events: function(fetchInfo, successCallback, failureCallback) {
            loadCalendarEvents(fetchInfo.start, fetchInfo.end, successCallback, failureCallback);
        },
        eventClick: function(info) {
            showMatchDetails(info.event.id);
        },
        selectable: true,
        select: function(selectInfo) {
            showCreateMatchModal(selectInfo.start);
        },
        height: 'auto',
        eventDisplay: 'block',
        dayMaxEvents: 3
    });

    calendar.render();
}

/**
 * Load calendar events for date range
 */
export function loadCalendarEvents(start, end, successCallback, failureCallback) {
    const startDate = start.toISOString().split('T')[0];
    const endDate = end.toISOString().split('T')[0];

    fetch(`/api/ecs-fc/teams/${currentTeamId}/matches/calendar?start_date=${startDate}&end_date=${endDate}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                successCallback(data.data.events);
            } else {
                console.error('Failed to load calendar events:', data.message);
                failureCallback(data.message);
            }
        })
        .catch(error => {
            console.error('Error loading calendar events:', error);
            failureCallback(error);
        });
}

/**
 * Load team matches for list view
 */
export function loadTeamMatches(upcomingOnly = true) {
    const url = `/api/ecs-fc/teams/${currentTeamId}/matches?upcoming_only=${upcomingOnly}`;

    fetch(url)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                currentMatches = data.data.matches;
                renderMatchesList(currentMatches);
            } else {
                ecsFcShowAlert('error', 'Failed to load matches: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Error loading matches:', error);
            ecsFcShowAlert('error', 'Error loading matches');
        });
}

/**
 * Render matches list
 */
export function renderMatchesList(matches) {
    const container = document.getElementById('matches-list-container');
    if (!container) return;

    if (matches.length === 0) {
        container.innerHTML = `
            <div class="p-4 text-sm text-blue-800 rounded-lg bg-blue-50 dark:bg-gray-800 dark:text-blue-400" role="alert">
                <i class="ti ti-info-circle mr-2"></i>
                No matches found. Create your first match using the "Create Match" button.
            </div>
        `;
        return;
    }

    const matchesHtml = matches.map(match => createMatchCard(match)).join('');
    container.innerHTML = matchesHtml;

    // Load RSVP summaries for each match
    matches.forEach(match => {
        loadRsvpSummary(match.id);
    });
}

/**
 * Create HTML card for a match
 */
export function createMatchCard(match) {
    const matchDate = new Date(match.match_date + 'T' + match.match_time);
    const isUpcoming = matchDate > new Date();
    const statusBadge = getStatusBadge(match.status);
    const homeAwayBadge = match.is_home_match
        ? '<span class="px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300">Home</span>'
        : '<span class="px-2 py-0.5 text-xs font-medium rounded bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300">Away</span>';

    return `
        <div class="bg-white border border-gray-200 rounded-lg shadow-sm dark:bg-gray-800 dark:border-gray-700 mb-3 js-match-card" data-match-id="${match.id}">
            <div class="flex justify-between items-center p-4 border-b border-gray-200 dark:border-gray-700">
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white">
                    <i class="ti ti-ball-football mr-2"></i>
                    ${match.team_name} vs ${match.opponent_name}
                </h6>
                <div class="flex gap-2">
                    ${homeAwayBadge}
                    ${statusBadge}
                </div>
            </div>
            <div class="p-4">
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                        <p class="text-sm text-gray-700 dark:text-gray-300 mb-1"><strong>Date:</strong> ${ecsFcFormatDate(match.match_date)}</p>
                        <p class="text-sm text-gray-700 dark:text-gray-300 mb-1"><strong>Time:</strong> ${formatTime(match.match_time)}</p>
                        <p class="text-sm text-gray-700 dark:text-gray-300 mb-1"><strong>Location:</strong> ${match.location}</p>
                        ${match.field_name ? `<p class="text-sm text-gray-700 dark:text-gray-300 mb-1"><strong>Field:</strong> ${match.field_name}</p>` : ''}
                    </div>
                    <div>
                        <div class="js-rsvp-summary" id="rsvp-summary-${match.id}">
                            <div class="inline-block w-4 h-4 border-2 border-ecs-green border-t-transparent rounded-full animate-spin" role="status">
                                <span class="sr-only">Loading...</span>
                            </div>
                        </div>
                    </div>
                </div>
                ${match.notes ? `<div class="mt-2 text-sm text-gray-700 dark:text-gray-300"><strong>Notes:</strong> ${match.notes}</div>` : ''}

                <div class="mt-4 flex flex-wrap gap-2">
                    ${isUpcoming ? `
                        <button class="text-white bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-xs px-3 py-1.5 js-rsvp-btn" data-match-id="${match.id}" data-response="yes">
                            <i class="ti ti-check mr-1"></i>Yes
                        </button>
                        <button class="text-white bg-red-600 hover:bg-red-700 focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-xs px-3 py-1.5 js-rsvp-btn" data-match-id="${match.id}" data-response="no">
                            <i class="ti ti-x mr-1"></i>No
                        </button>
                        <button class="text-white bg-yellow-500 hover:bg-yellow-600 focus:ring-4 focus:ring-yellow-300 font-medium rounded-lg text-xs px-3 py-1.5 js-rsvp-btn" data-match-id="${match.id}" data-response="maybe">
                            <i class="ti ti-question-mark mr-1"></i>Maybe
                        </button>
                        <button class="text-white bg-blue-600 hover:bg-blue-700 focus:ring-4 focus:ring-blue-300 font-medium rounded-lg text-xs px-3 py-1.5 js-send-reminder-btn" data-match-id="${match.id}">
                            <i class="ti ti-bell mr-1"></i>Send Reminder
                        </button>
                    ` : ''}

                    <button class="text-ecs-green border border-ecs-green hover:bg-ecs-green hover:text-white focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-xs px-3 py-1.5 js-edit-match-btn" data-match-id="${match.id}">
                        <i class="ti ti-edit mr-1"></i>Edit
                    </button>
                    <button class="text-red-600 border border-red-600 hover:bg-red-600 hover:text-white focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-xs px-3 py-1.5 js-delete-match-btn" data-match-id="${match.id}">
                        <i class="ti ti-trash mr-1"></i>Delete
                    </button>
                </div>
            </div>
        </div>
    `;
}

/**
 * Get status badge HTML
 */
export function getStatusBadge(status) {
    switch (status) {
        case 'SCHEDULED':
            return '<span class="px-2 py-0.5 text-xs font-medium rounded bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300">Scheduled</span>';
        case 'COMPLETED':
            return '<span class="px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300">Completed</span>';
        case 'CANCELLED':
            return '<span class="px-2 py-0.5 text-xs font-medium rounded bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300">Cancelled</span>';
        default:
            return '<span class="px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300">Unknown</span>';
    }
}

/**
 * Load and display RSVP summary for a match
 */
export function loadRsvpSummary(matchId) {
    fetch(`/api/ecs-fc/matches/${matchId}/rsvp`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                renderRsvpSummary(matchId, data.data.rsvp_summary);
            } else {
                console.error('Failed to load RSVP summary:', data.message);
            }
        })
        .catch(error => {
            console.error('Error loading RSVP summary:', error);
        });
}

/**
 * Render RSVP summary
 */
export function renderRsvpSummary(matchId, summary) {
    const container = document.getElementById(`rsvp-summary-${matchId}`);
    if (!container) return;

    const total = summary.yes + summary.no + summary.maybe + summary.no_response;
    const responseRate = total > 0 ? ((summary.yes + summary.no + summary.maybe) / total * 100).toFixed(0) : 0;

    container.innerHTML = `
        <div class="js-rsvp-counts">
            <p class="text-xs text-gray-500 dark:text-gray-400 mb-1">RSVP Status:</p>
            <div class="flex justify-between gap-1 mt-1">
                <span class="px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300">${summary.yes}</span>
                <span class="px-2 py-0.5 text-xs font-medium rounded bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300">${summary.no}</span>
                <span class="px-2 py-0.5 text-xs font-medium rounded bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300">? ${summary.maybe}</span>
                <span class="px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300">- ${summary.no_response}</span>
            </div>
            <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">${responseRate}% responded</p>
        </div>
    `;
}

/**
 * Show create match modal
 */
export function showCreateMatchModal(selectedDate = null) {
    const modal = document.getElementById('createMatchModal');
    if (!modal) return;

    // Reset form
    const form = document.getElementById('ecs-fc-match-form');
    if (form) {
        form.reset();

        // Set default date if provided
        if (selectedDate) {
            const dateInput = form.querySelector('[name="match_date"]');
            if (dateInput) {
                dateInput.value = selectedDate.toISOString().split('T')[0];
            }
        }
    }

    // Show modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show(modal.id);
    }
}

/**
 * Handle match form submission
 */
export function handleMatchFormSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const formData = new FormData(form);
    const matchData = Object.fromEntries(formData.entries());

    // Convert boolean fields
    matchData.is_home_match = formData.get('is_home_match') === 'on';
    matchData.team_id = currentTeamId;

    // Create or update match
    const matchId = form.dataset.matchId;
    const url = matchId
        ? `/api/ecs-fc/matches/${matchId}`
        : '/api/ecs-fc/matches';
    const method = matchId ? 'PUT' : 'POST';

    fetch(url, {
        method: method,
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(matchData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            ecsFcShowAlert('success', data.message);

            // Close modal
            const modalEl = document.getElementById('createMatchModal');
            const modal = modalEl?._flowbiteModal;
            if (modal) modal.hide();

            // Refresh displays
            loadTeamMatches();
            if (calendar) calendar.refetchEvents();
        } else {
            ecsFcShowAlert('error', 'Failed to save match: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error saving match:', error);
        ecsFcShowAlert('error', 'Error saving match');
    });
}

/**
 * Edit a match
 */
export function ecsFcEditMatch(matchId) {
    // Find match data
    const match = currentMatches.find(m => m.id == matchId);
    if (!match) return;

    // Populate form
    const form = document.getElementById('ecs-fc-match-form');
    if (!form) return;

    form.dataset.matchId = matchId;
    form.querySelector('[name="opponent_name"]').value = match.opponent_name;
    form.querySelector('[name="match_date"]').value = match.match_date;
    form.querySelector('[name="match_time"]').value = match.match_time;
    form.querySelector('[name="location"]').value = match.location;
    form.querySelector('[name="field_name"]').value = match.field_name || '';
    form.querySelector('[name="is_home_match"]').checked = match.is_home_match;
    form.querySelector('[name="notes"]').value = match.notes || '';

    // Update modal title (new pattern: {modalId}-title, fallback: old .modal-title selector)
    const modalTitle = document.getElementById('createMatchModal-title') || document.querySelector('#createMatchModal .modal-title');
    if (modalTitle) {
        modalTitle.textContent = 'Edit Match';
    }

    // Show modal
    const createModal = document.getElementById('createMatchModal');
    if (createModal && typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('createMatchModal');
    }
}

/**
 * Delete a match
 */
export function ecsFcDeleteMatch(matchId) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Delete Match',
            text: 'Are you sure you want to delete this match? This action cannot be undone.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#3085d6',
            confirmButtonText: 'Yes, delete it!'
        }).then((result) => {
            if (result.isConfirmed) {
                performDeleteMatch(matchId);
            }
        });
    }
}

/**
 * Perform the actual match deletion
 */
function performDeleteMatch(matchId) {
    fetch(`/api/ecs-fc/matches/${matchId}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            ecsFcShowAlert('success', data.message);
            loadTeamMatches();
            if (calendar) calendar.refetchEvents();
        } else {
            ecsFcShowAlert('error', 'Failed to delete match: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error deleting match:', error);
        ecsFcShowAlert('error', 'Error deleting match');
    });
}

/**
 * Handle RSVP response
 */
export function handleRsvpResponse(button) {
    const matchId = button.dataset.matchId;
    const response = button.dataset.response;

    fetch(`/api/ecs-fc/matches/${matchId}/rsvp`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ response: response })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            ecsFcShowAlert('success', 'RSVP updated successfully');
            loadRsvpSummary(matchId);
        } else {
            ecsFcShowAlert('error', 'Failed to update RSVP: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error updating RSVP:', error);
        ecsFcShowAlert('error', 'Error updating RSVP');
    });
}

/**
 * Send RSVP reminder
 */
export function sendRsvpReminder(matchId) {
    fetch(`/api/ecs-fc/matches/${matchId}/remind`, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            ecsFcShowAlert('success', data.message);
        } else {
            ecsFcShowAlert('error', 'Failed to send reminders: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error sending reminders:', error);
        ecsFcShowAlert('error', 'Error sending reminders');
    });
}

/**
 * Show import matches modal
 */
export function showImportMatchesModal() {
    const modal = document.getElementById('importMatchesModal');
    if (!modal) return;

    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show(modal.id);
    }
}

/**
 * Handle import form submission
 */
export function handleImportFormSubmit(e) {
    e.preventDefault();

    const csvInput = document.getElementById('csv-matches');
    const csvText = csvInput.value.trim();

    if (!csvText) {
        ecsFcShowAlert('error', 'Please enter CSV data');
        return;
    }

    // Parse CSV
    const matches = parseMatchesCsv(csvText);
    if (matches.length === 0) {
        ecsFcShowAlert('error', 'No valid matches found in CSV data');
        return;
    }

    // Import matches
    fetch('/api/ecs-fc/matches/import', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            team_id: currentTeamId,
            matches: matches
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            ecsFcShowAlert('success', data.message);

            // Close modal
            const modalEl = document.getElementById('importMatchesModal');
            const modal = modalEl?._flowbiteModal;
            if (modal) modal.hide();

            // Refresh displays
            loadTeamMatches();
            if (calendar) calendar.refetchEvents();
        } else {
            ecsFcShowAlert('error', 'Import failed: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error importing matches:', error);
        ecsFcShowAlert('error', 'Error importing matches');
    });
}

/**
 * Parse CSV data into matches array
 */
export function parseMatchesCsv(csvText) {
    const lines = csvText.split('\n').map(line => line.trim()).filter(line => line);
    const matches = [];

    // Skip header if present
    let startIndex = 0;
    if (lines[0] && lines[0].toLowerCase().includes('opponent')) {
        startIndex = 1;
    }

    for (let i = startIndex; i < lines.length; i++) {
        const fields = lines[i].split(',').map(field => field.trim().replace(/^["']|["']$/g, ''));

        if (fields.length >= 5) {
            const match = {
                opponent_name: fields[0],
                match_date: fields[1],
                match_time: fields[2],
                location: fields[3],
                is_home_match: fields[4].toLowerCase() === 'home' || fields[4].toLowerCase() === 'true',
                field_name: fields[5] || null,
                notes: fields[6] || null
            };

            // Validate required fields
            if (match.opponent_name && match.match_date && match.match_time && match.location) {
                matches.push(match);
            }
        }
    }

    return matches;
}

/**
 * Handle real-time RSVP updates
 */
export function handleRsvpUpdate(data) {
    if (data.match_type === 'ecs_fc' && data.match_id) {
        loadRsvpSummary(data.match_id);
    }
}

/**
 * Handle real-time match updates
 */
export function handleMatchUpdate(data) {
    if (data.match_type === 'ecs_fc') {
        loadTeamMatches();
        if (calendar) calendar.refetchEvents();
    }
}

/**
 * Utility functions
 */
export function ecsFcFormatDate(dateString) {
    return new Date(dateString).toLocaleDateString('en-US', {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

export function formatTime(timeString) {
    const [hours, minutes] = timeString.split(':');
    const date = new Date();
    date.setHours(parseInt(hours), parseInt(minutes));
    return date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
    });
}

export function ecsFcShowAlert(type, message) {
    // Map type to Tailwind colors
    const typeColors = {
        'success': 'text-green-800 bg-green-50 dark:bg-gray-800 dark:text-green-400',
        'error': 'text-red-800 bg-red-50 dark:bg-gray-800 dark:text-red-400',
        'danger': 'text-red-800 bg-red-50 dark:bg-gray-800 dark:text-red-400',
        'warning': 'text-yellow-800 bg-yellow-50 dark:bg-gray-800 dark:text-yellow-400',
        'info': 'text-blue-800 bg-blue-50 dark:bg-gray-800 dark:text-blue-400'
    };
    const colorClass = typeColors[type] || typeColors['info'];

    // Create alert element
    const alertDiv = document.createElement('div');
    alertDiv.className = `p-4 mb-2 text-sm rounded-lg ${colorClass} js-alert-message`;
    alertDiv.setAttribute('role', 'alert');
    alertDiv.innerHTML = `
        <div class="flex items-center justify-between">
            <span>${message}</span>
            <button type="button" class="ml-2 -mx-1.5 -my-1.5 rounded-lg p-1.5 inline-flex items-center justify-center h-8 w-8 hover:bg-gray-200 dark:hover:bg-gray-700" onclick="this.closest('[role=alert]').remove()">
                <span class="sr-only">Close</span>
                <svg class="w-3 h-3" fill="none" viewBox="0 0 14 14"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/></svg>
            </button>
        </div>
    `;

    // Find alerts container or create one
    let container = document.getElementById('alerts-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'alerts-container';
        container.className = 'fixed top-4 right-4 z-50 w-80 js-alerts-container';
        document.body.appendChild(container);
    }

    // Add alert
    container.appendChild(alertDiv);

    // Auto-dismiss after 5 seconds
    setTimeout(() => {
        if (alertDiv.parentNode) {
            alertDiv.remove();
        }
    }, 5000);
}

// Export public API for programmatic access
window.EcsFcSchedule = {
    loadTeamMatches,
    showCreateMatchModal,
    editMatch: ecsFcEditMatch,
    deleteMatch: ecsFcDeleteMatch,
    sendRsvpReminder
};

// Register with window.InitSystem
if (window.InitSystem.register) {
    window.InitSystem.register('ecs-fc-schedule', initializeEcsFcSchedule, {
        priority: 30,
        reinitializable: false,
        description: 'ECS FC schedule management'
    });
}
