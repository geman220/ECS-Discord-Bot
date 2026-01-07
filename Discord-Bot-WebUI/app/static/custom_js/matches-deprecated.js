/**
 * ============================================================================
 * MATCHES DEPRECATED - matches-deprecated.js
 * ============================================================================
 *
 * [DEPRECATED] External JavaScript for matches.html (deprecated page)
 * This file should be removed once matches.html is fully retired.
 *
 * Handles match editing, deletion, and live reporting controls
 *
 * Event Delegation Pattern:
 *   - data-action="edit-match-schedule" (schedule editing - date/time)
 *   - data-action="remove-match"
 *   - data-action="clear-matches"
 *   - data-action="start-reporting"
 *   - data-action="stop-reporting"
 *
 * NOTE: "edit-match" is reserved for match REPORTING (scores/goals/cards)
 *       handled by report_match.js - DO NOT use here
 *
 * ============================================================================
 */
import { InitSystem } from '../js/init-system.js';

// Competition mappings
const competitionMappings = {
    "MLS": "usa.1",
    "US Open Cup": "usa.open",
    "FIFA Club World Cup": "fifa.cwc",
    "Concacaf": "concacaf.league",
    "Concacaf Champions League": "concacaf.champions",
};

const inverseCompetitionMappings = Object.fromEntries(
    Object.entries(competitionMappings).map(([key, value]) => [value, key])
);

let _initialized = false;

/**
 * Initialize match management
 */
function init() {
    // Guard against duplicate initialization
    if (_initialized) return;
    _initialized = true;

    // Event delegation for all match actions
    document.addEventListener('click', handleMatchActions);

    // Initialize date pickers
    initializeDatePickers();

    // Update match statuses on load and periodically
    updateAllMatchStatuses();
    setInterval(updateAllMatchStatuses, 30000);
}

/**
 * Handle all match action clicks
 */
function handleMatchActions(e) {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.dataset.action;
    const matchId = target.dataset.matchId;

    switch(action) {
        case 'edit-match-schedule':
            e.preventDefault();
            editMatchSchedule(matchId);
            break;
        case 'remove-match':
            e.preventDefault();
            removeMatch(matchId);
            break;
        case 'clear-matches':
            e.preventDefault();
            clearAllMatches();
            break;
        case 'start-reporting':
            startLiveReporting(matchId);
            break;
        case 'stop-reporting':
            stopLiveReporting(matchId);
            break;
        case 'save-row':
            e.preventDefault();
            saveMatch(matchId);
            break;
        case 'cancel-edit':
            e.preventDefault();
            cancelEdit(matchId);
            break;
    }
}

/**
 * Initialize Flatpickr date pickers
 */
function initializeDatePickers() {
    if (typeof window.flatpickr !== 'undefined') {
        window.flatpickr('.flatpickr', {
            enableTime: true,
            dateFormat: "Y-m-d H:i",
            time_24hr: true
        });
    }
}

/**
 * Edit match schedule (date/time/competition) - NOT for match reporting
 * For match reporting (scores/goals), use report_match.js handleEditButtonClick
 */
function editMatchSchedule(matchId) {
    const row = document.querySelector(`tr[data-match-id="${matchId}"]`);
    if (!row) {
        console.error(`Row with match ID ${matchId} not found`);
        return;
    }

    const dateCell = row.querySelector('td:nth-child(2)');
    const competitionCell = row.querySelector('td:nth-child(3)');
    const actionsCell = row.querySelector('td:last-child');

    // Save original values
    dateCell.setAttribute('data-original-value', dateCell.textContent);
    competitionCell.setAttribute('data-original-value', competitionCell.textContent);

    // Replace date with input
    dateCell.innerHTML = `<input type="text" id="edit-date-${matchId}" class="form-control flatpickr" value="${dateCell.textContent.trim()}" data-form-control>`;

    // Re-initialize Flatpickr for the new input
    if (typeof window.flatpickr !== 'undefined') {
        window.flatpickr(`#edit-date-${matchId}`, {
            enableTime: true,
            dateFormat: "Y-m-d H:i",
            time_24hr: true
        });
    }

    // Create competition dropdown
    let selectHtml = `<select class="form-select" id="edit-competition-${matchId}" data-form-select>`;
    for (const [friendlyName, actualValue] of Object.entries(competitionMappings)) {
        const selected = competitionCell.textContent.trim() === friendlyName ? 'selected' : '';
        selectHtml += `<option value="${friendlyName}" ${selected}>${friendlyName}</option>`;
    }
    selectHtml += '</select>';
    competitionCell.innerHTML = selectHtml;

    // Replace actions with save/cancel
    actionsCell.innerHTML = `
        <button type="button" class="btn btn-sm btn-success" data-action="save-row" data-match-id="${matchId}">
            <i class="fas fa-save"></i> Save
        </button>
        <button type="button" class="btn btn-sm btn-secondary" data-action="cancel-edit" data-match-id="${matchId}">
            <i class="fas fa-times"></i> Cancel
        </button>
    `;
}

/**
 * Save match edits
 */
function saveMatch(matchId) {
    const row = document.querySelector(`tr[data-match-id="${matchId}"]`);
    const dateValue = document.getElementById(`edit-date-${matchId}`)?.value.trim();
    const competitionValue = document.getElementById(`edit-competition-${matchId}`)?.value.trim();
    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;

    if (!dateValue || !competitionValue) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Validation Error', 'Date and Competition fields cannot be empty.', 'warning');
        }
        return;
    }

    fetch(`/bot/admin/update_match/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            date: dateValue,
            competition: competitionValue
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Update cells with new values
            const newFormattedDate = formatDate(dateValue);
            row.querySelector('td:nth-child(2)').textContent = newFormattedDate;

            const newCompetitionText = inverseCompetitionMappings[competitionValue] || competitionValue;
            row.querySelector('td:nth-child(3)').textContent = newCompetitionText;

            resetActionButtons(matchId);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Saved', 'Match updated successfully.', 'success');
            }
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Failed to save changes.', 'error');
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to save changes. Please try again.', 'error');
        }
    });
}

/**
 * Cancel edit mode
 */
function cancelEdit(matchId) {
    const row = document.querySelector(`tr[data-match-id="${matchId}"]`);
    const dateCell = row.querySelector('td:nth-child(2)');
    const competitionCell = row.querySelector('td:nth-child(3)');

    // Revert to original values
    dateCell.textContent = dateCell.getAttribute('data-original-value');
    competitionCell.textContent = competitionCell.getAttribute('data-original-value');

    resetActionButtons(matchId);
}

/**
 * Reset action buttons to default state
 */
function resetActionButtons(matchId) {
    const row = document.querySelector(`tr[data-match-id="${matchId}"]`);
    if (!row) return;

    const actionsCell = row.querySelector('td:last-child');
    const statusElement = row.querySelector('td:nth-child(4) span');
    const currentStatus = statusElement?.textContent.toLowerCase().trim() || 'stopped';

    actionsCell.innerHTML = `
        <div class="c-match-actions">
            <div class="c-match-actions__dropdown dropdown d-inline-block me-2">
                <button class="btn btn-link text-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false" data-dropdown-toggle aria-label="More options"><i class="fas fa-ellipsis-v"></i></button>
                <ul class="dropdown-menu dropdown-menu-end" data-dropdown-menu>
                    <li>
                        <a class="dropdown-item" href="#" data-action="edit-match-schedule" data-match-id="${matchId}">
                            <i class="fas fa-edit me-1"></i> Edit Schedule
                        </a>
                    </li>
                    <li>
                        <a class="dropdown-item text-danger" href="#" data-action="remove-match" data-match-id="${matchId}">
                            <i class="fas fa-trash-alt me-1"></i> Delete
                        </a>
                    </li>
                </ul>
            </div>
            <button class="c-match-actions__button c-match-actions__button--primary" data-action="start-reporting" data-match-id="${matchId}" ${currentStatus === 'running' ? 'disabled' : ''}>
                ${currentStatus === 'scheduled' ? 'Force Start' : currentStatus === 'running' ? 'Running' : 'Start'}
            </button>
            <button class="c-match-actions__button c-match-actions__button--danger" data-action="stop-reporting" data-match-id="${matchId}" ${currentStatus !== 'running' ? 'disabled' : ''}>
                Stop
            </button>
        </div>
    `;
}

/**
 * Remove match with confirmation
 */
function removeMatch(matchId) {
    if (typeof window.Swal === 'undefined') return;

    const confirmDelete = window.Swal.fire({
        title: 'Delete Match?',
        text: "This action cannot be undone.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: 'Yes, delete it!',
        cancelButtonText: 'Cancel'
    });

    confirmDelete.then((result) => {
        if (result.isConfirmed) {
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;

            fetch(`/bot/admin/matches/remove/${matchId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const row = document.querySelector(`tr[data-match-id="${matchId}"]`);
                    if (row) row.remove();

                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire('Deleted!', data.message, 'success');
                    }
                } else {
                    throw new Error(data.message || 'Failed to remove the match.');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', error.message, 'error');
                }
            });
        }
    });
}

/**
 * Clear all matches
 */
function clearAllMatches() {
    if (typeof window.Swal === 'undefined') return;

    const confirmClear = window.Swal.fire({
        title: 'Clear All Matches?',
        text: "This will delete ALL matches. This action cannot be undone.",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: 'Yes, clear all!',
        cancelButtonText: 'Cancel'
    });

    confirmClear.then((result) => {
        if (result.isConfirmed) {
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;
            const clearUrl = document.querySelector('[data-action="clear-matches"]')?.getAttribute('href') || '/bot/admin/clear_all_mls_matches';

            fetch(clearUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire('Cleared!', 'All matches have been cleared.', 'success').then(() => {
                            location.reload();
                        });
                    } else {
                        location.reload();
                    }
                } else {
                    throw new Error('Failed to clear matches.');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', error.message, 'error');
                }
            });
        }
    });
}

/**
 * Start live reporting
 */
function startLiveReporting(matchId) {
    const startButton = document.querySelector(`[data-action="start-reporting"][data-match-id="${matchId}"]`);
    const stopButton = document.querySelector(`[data-action="stop-reporting"][data-match-id="${matchId}"]`);

    if (startButton) startButton.disabled = true;

    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;

    fetch(`/bot/admin/start_live_reporting/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        if (data.success) {
            updateMatchStatus(matchId, 'running');
            console.log(`Live reporting started. Task ID: ${data.task_id}`);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Started', 'Live reporting has been started.', 'success');
            }
        } else {
            if (startButton) startButton.disabled = false;
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message, 'error');
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (startButton) startButton.disabled = false;
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to start live reporting. Please try again.', 'error');
        }
    });
}

/**
 * Stop live reporting
 */
function stopLiveReporting(matchId) {
    const stopButton = document.querySelector(`[data-action="stop-reporting"][data-match-id="${matchId}"]`);

    if (stopButton) stopButton.disabled = true;

    const csrfToken = document.querySelector('input[name="csrf_token"]')?.value;

    fetch(`/bot/admin/stop_live_reporting/${matchId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => {
        if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
        return response.json();
    })
    .then(data => {
        if (data.success) {
            updateMatchStatus(matchId, 'stopped');
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Stopped', 'Live reporting has been stopped.', 'success');
            }
        } else {
            if (stopButton) stopButton.disabled = false;
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message, 'error');
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (stopButton) stopButton.disabled = false;
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to stop live reporting. Please try again.', 'error');
        }
    });
}

/**
 * Update match status display
 */
function updateMatchStatus(matchId, status) {
    const statusSpan = document.getElementById(`status-${matchId}`);
    const startButton = document.querySelector(`[data-action="start-reporting"][data-match-id="${matchId}"]`);
    const stopButton = document.querySelector(`[data-action="stop-reporting"][data-match-id="${matchId}"]`);

    if (statusSpan && startButton && stopButton) {
        statusSpan.textContent = status.charAt(0).toUpperCase() + status.slice(1);
        statusSpan.className = `c-live-status c-live-status--${status}`;

        if (status === 'running') {
            startButton.textContent = 'Running';
            startButton.disabled = true;
            stopButton.disabled = false;
        } else if (status === 'scheduled') {
            startButton.textContent = 'Force Start';
            startButton.disabled = false;
            stopButton.disabled = true;
        } else {
            startButton.textContent = 'Start';
            startButton.disabled = false;
            stopButton.disabled = true;
        }
    }
}

/**
 * Update all match statuses
 */
function updateAllMatchStatuses() {
    fetch('/bot/admin/get_all_match_statuses')
        .then(response => response.json())
        .then(data => {
            Object.entries(data).forEach(([matchId, matchData]) => {
                updateMatchStatus(matchId, matchData.status);
            });
        })
        .catch(error => console.error('Error updating statuses:', error));
}

/**
 * Format date string
 */
function formatDate(dateString) {
    const dateObj = new Date(dateString);
    dateObj.setHours(dateObj.getHours() + 25); // Adjust as per original logic
    const options = {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hour12: true
    };
    return dateObj.toLocaleString('en-US', options).replace(',', '');
}

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('matches-management', init, {
        priority: 40,
        reinitializable: false,
        description: 'Matches management (deprecated page)'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.init = init;
window.handleMatchActions = handleMatchActions;
window.initializeDatePickers = initializeDatePickers;
window.editMatchSchedule = editMatchSchedule;
window.saveMatch = saveMatch;
window.cancelEdit = cancelEdit;
window.resetActionButtons = resetActionButtons;
window.removeMatch = removeMatch;
window.clearAllMatches = clearAllMatches;
window.startLiveReporting = startLiveReporting;
window.stopLiveReporting = stopLiveReporting;
window.updateMatchStatus = updateMatchStatus;
window.updateAllMatchStatuses = updateAllMatchStatuses;
window.formatDate = formatDate;
