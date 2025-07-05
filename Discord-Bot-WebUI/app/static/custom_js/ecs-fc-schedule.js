/**
 * ECS FC Schedule Management JavaScript
 * 
 * This module handles all client-side functionality for ECS FC schedule management
 * including match creation, editing, calendar display, and RSVP handling.
 */

// Global variables
let currentTeamId = null;
let calendar = null;
let currentMatches = [];

// Initialize ECS FC schedule management
document.addEventListener('DOMContentLoaded', function() {
    initializeEcsFcSchedule();
});

/**
 * Initialize ECS FC schedule functionality
 */
function initializeEcsFcSchedule() {
    // Get team ID from page data
    const teamData = document.getElementById('team-data');
    if (teamData) {
        currentTeamId = parseInt(teamData.dataset.teamId);
    }

    // Initialize components
    if (currentTeamId) {
        initializeCalendar();
        initializeEventHandlers();
        loadTeamMatches();
    }
}

/**
 * Initialize event handlers for ECS FC schedule management
 */
function initializeEventHandlers() {
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
        if (e.target.classList.contains('rsvp-btn')) {
            handleRsvpResponse(e.target);
        }
        if (e.target.classList.contains('edit-match-btn')) {
            editMatch(e.target.dataset.matchId);
        }
        if (e.target.classList.contains('delete-match-btn')) {
            deleteMatch(e.target.dataset.matchId);
        }
        if (e.target.classList.contains('send-reminder-btn')) {
            sendRsvpReminder(e.target.dataset.matchId);
        }
    });

    // Real-time updates via WebSocket
    if (typeof io !== 'undefined') {
        const socket = io();
        socket.on('rsvp_update', handleRsvpUpdate);
        socket.on('match_update', handleMatchUpdate);
    }
}

/**
 * Initialize FullCalendar for ECS FC matches
 */
function initializeCalendar() {
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
function loadCalendarEvents(start, end, successCallback, failureCallback) {
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
function loadTeamMatches(upcomingOnly = true) {
    const url = `/api/ecs-fc/teams/${currentTeamId}/matches?upcoming_only=${upcomingOnly}`;
    
    fetch(url)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                currentMatches = data.data.matches;
                renderMatchesList(currentMatches);
            } else {
                showAlert('error', 'Failed to load matches: ' + data.message);
            }
        })
        .catch(error => {
            console.error('Error loading matches:', error);
            showAlert('error', 'Error loading matches');
        });
}

/**
 * Render matches list
 */
function renderMatchesList(matches) {
    const container = document.getElementById('matches-list-container');
    if (!container) return;

    if (matches.length === 0) {
        container.innerHTML = `
            <div class="alert alert-info">
                <i class="fas fa-info-circle me-2"></i>
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
function createMatchCard(match) {
    const matchDate = new Date(match.match_date + 'T' + match.match_time);
    const isUpcoming = matchDate > new Date();
    const statusBadge = getStatusBadge(match.status);
    const homeAwayBadge = match.is_home_match 
        ? '<span class="badge bg-success">Home</span>'
        : '<span class="badge bg-primary">Away</span>';

    return `
        <div class="card mb-3 match-card" data-match-id="${match.id}">
            <div class="card-header d-flex justify-content-between align-items-center">
                <h6 class="mb-0">
                    <i class="fas fa-futbol me-2"></i>
                    ${match.team_name} vs ${match.opponent_name}
                </h6>
                <div>
                    ${homeAwayBadge}
                    ${statusBadge}
                </div>
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-6">
                        <p class="mb-1"><strong>Date:</strong> ${formatDate(match.match_date)}</p>
                        <p class="mb-1"><strong>Time:</strong> ${formatTime(match.match_time)}</p>
                        <p class="mb-1"><strong>Location:</strong> ${match.location}</p>
                        ${match.field_name ? `<p class="mb-1"><strong>Field:</strong> ${match.field_name}</p>` : ''}
                    </div>
                    <div class="col-md-6">
                        <div class="rsvp-summary" id="rsvp-summary-${match.id}">
                            <div class="spinner-border spinner-border-sm" role="status">
                                <span class="visually-hidden">Loading...</span>
                            </div>
                        </div>
                    </div>
                </div>
                ${match.notes ? `<div class="mt-2"><strong>Notes:</strong> ${match.notes}</div>` : ''}
                
                <div class="mt-3 d-flex flex-wrap gap-2">
                    ${isUpcoming ? `
                        <button class="btn btn-sm btn-success rsvp-btn" data-match-id="${match.id}" data-response="yes">
                            <i class="fas fa-check me-1"></i>Yes
                        </button>
                        <button class="btn btn-sm btn-danger rsvp-btn" data-match-id="${match.id}" data-response="no">
                            <i class="fas fa-times me-1"></i>No
                        </button>
                        <button class="btn btn-sm btn-warning rsvp-btn" data-match-id="${match.id}" data-response="maybe">
                            <i class="fas fa-question me-1"></i>Maybe
                        </button>
                        <button class="btn btn-sm btn-info send-reminder-btn" data-match-id="${match.id}">
                            <i class="fas fa-bell me-1"></i>Send Reminder
                        </button>
                    ` : ''}
                    
                    <button class="btn btn-sm btn-outline-primary edit-match-btn" data-match-id="${match.id}">
                        <i class="fas fa-edit me-1"></i>Edit
                    </button>
                    <button class="btn btn-sm btn-outline-danger delete-match-btn" data-match-id="${match.id}">
                        <i class="fas fa-trash me-1"></i>Delete
                    </button>
                </div>
            </div>
        </div>
    `;
}

/**
 * Get status badge HTML
 */
function getStatusBadge(status) {
    switch (status) {
        case 'SCHEDULED':
            return '<span class="badge bg-info">Scheduled</span>';
        case 'COMPLETED':
            return '<span class="badge bg-success">Completed</span>';
        case 'CANCELLED':
            return '<span class="badge bg-danger">Cancelled</span>';
        default:
            return '<span class="badge bg-secondary">Unknown</span>';
    }
}

/**
 * Load and display RSVP summary for a match
 */
function loadRsvpSummary(matchId) {
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
function renderRsvpSummary(matchId, summary) {
    const container = document.getElementById(`rsvp-summary-${matchId}`);
    if (!container) return;

    const total = summary.yes + summary.no + summary.maybe + summary.no_response;
    const responseRate = total > 0 ? ((summary.yes + summary.no + summary.maybe) / total * 100).toFixed(0) : 0;

    container.innerHTML = `
        <div class="rsvp-counts">
            <small class="text-muted">RSVP Status:</small>
            <div class="d-flex justify-content-between mt-1">
                <span class="badge bg-success">✓ ${summary.yes}</span>
                <span class="badge bg-danger">✗ ${summary.no}</span>
                <span class="badge bg-warning">? ${summary.maybe}</span>
                <span class="badge bg-secondary">- ${summary.no_response}</span>
            </div>
            <small class="text-muted">${responseRate}% responded</small>
        </div>
    `;
}

/**
 * Show create match modal
 */
function showCreateMatchModal(selectedDate = null) {
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
    const bootstrapModal = new bootstrap.Modal(modal);
    bootstrapModal.show();
}

/**
 * Handle match form submission
 */
function handleMatchFormSubmit(e) {
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
            showAlert('success', data.message);
            
            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('createMatchModal'));
            if (modal) modal.hide();
            
            // Refresh displays
            loadTeamMatches();
            if (calendar) calendar.refetchEvents();
        } else {
            showAlert('error', 'Failed to save match: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error saving match:', error);
        showAlert('error', 'Error saving match');
    });
}

/**
 * Edit a match
 */
function editMatch(matchId) {
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

    // Update modal title
    const modalTitle = document.querySelector('#createMatchModal .modal-title');
    if (modalTitle) {
        modalTitle.textContent = 'Edit Match';
    }

    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('createMatchModal'));
    modal.show();
}

/**
 * Delete a match
 */
function deleteMatch(matchId) {
    if (!confirm('Are you sure you want to delete this match? This action cannot be undone.')) {
        return;
    }

    fetch(`/api/ecs-fc/matches/${matchId}`, {
        method: 'DELETE'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('success', data.message);
            loadTeamMatches();
            if (calendar) calendar.refetchEvents();
        } else {
            showAlert('error', 'Failed to delete match: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error deleting match:', error);
        showAlert('error', 'Error deleting match');
    });
}

/**
 * Handle RSVP response
 */
function handleRsvpResponse(button) {
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
            showAlert('success', 'RSVP updated successfully');
            loadRsvpSummary(matchId);
        } else {
            showAlert('error', 'Failed to update RSVP: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error updating RSVP:', error);
        showAlert('error', 'Error updating RSVP');
    });
}

/**
 * Send RSVP reminder
 */
function sendRsvpReminder(matchId) {
    fetch(`/api/ecs-fc/matches/${matchId}/remind`, {
        method: 'POST'
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('success', data.message);
        } else {
            showAlert('error', 'Failed to send reminders: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error sending reminders:', error);
        showAlert('error', 'Error sending reminders');
    });
}

/**
 * Show import matches modal
 */
function showImportMatchesModal() {
    const modal = document.getElementById('importMatchesModal');
    if (!modal) return;

    const bootstrapModal = new bootstrap.Modal(modal);
    bootstrapModal.show();
}

/**
 * Handle import form submission
 */
function handleImportFormSubmit(e) {
    e.preventDefault();
    
    const csvInput = document.getElementById('csv-matches');
    const csvText = csvInput.value.trim();
    
    if (!csvText) {
        showAlert('error', 'Please enter CSV data');
        return;
    }

    // Parse CSV
    const matches = parseMatchesCsv(csvText);
    if (matches.length === 0) {
        showAlert('error', 'No valid matches found in CSV data');
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
            showAlert('success', data.message);
            
            // Close modal
            const modal = bootstrap.Modal.getInstance(document.getElementById('importMatchesModal'));
            if (modal) modal.hide();
            
            // Refresh displays
            loadTeamMatches();
            if (calendar) calendar.refetchEvents();
        } else {
            showAlert('error', 'Import failed: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error importing matches:', error);
        showAlert('error', 'Error importing matches');
    });
}

/**
 * Parse CSV data into matches array
 */
function parseMatchesCsv(csvText) {
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
function handleRsvpUpdate(data) {
    if (data.match_type === 'ecs_fc' && data.match_id) {
        loadRsvpSummary(data.match_id);
    }
}

/**
 * Handle real-time match updates
 */
function handleMatchUpdate(data) {
    if (data.match_type === 'ecs_fc') {
        loadTeamMatches();
        if (calendar) calendar.refetchEvents();
    }
}

/**
 * Utility functions
 */
function formatDate(dateString) {
    return new Date(dateString).toLocaleDateString('en-US', {
        weekday: 'short',
        year: 'numeric',
        month: 'short',
        day: 'numeric'
    });
}

function formatTime(timeString) {
    const [hours, minutes] = timeString.split(':');
    const date = new Date();
    date.setHours(parseInt(hours), parseInt(minutes));
    return date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        hour12: true
    });
}

function showAlert(type, message) {
    // Create alert element
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

    // Find alerts container or create one
    let container = document.getElementById('alerts-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'alerts-container';
        container.className = 'fixed-top p-3';
        container.style.zIndex = '9999';
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

// Export functions for global access
window.EcsFcSchedule = {
    loadTeamMatches,
    showCreateMatchModal,
    editMatch,
    deleteMatch,
    sendRsvpReminder
};