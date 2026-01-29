/**
 * Live Match Reporting Client
 *
 * This module provides client-side functionality for the multi-user live match
 * reporting system. It handles WebSocket communication, UI updates, and
 * synchronization of match data between multiple reporters.
 */
import { InitSystem } from '../js/init-system.js';

let _initialized = false;

// Initialize SocketIO with the live reporting namespace
let socket;
let matchId;
let teamId;
let matchState;
let activeReporters = [];
let playerShifts = [];
let timerInterval;
let isTimerRunning = false;

/**
 * Initialize the live reporting module
 * @param {Object} config - Configuration options
 * @param {number} config.matchId - ID of the match being reported
 * @param {number} config.teamId - ID of the team the user is reporting for
 * @param {string} config.socketUrl - WebSocket server URL (optional)
 */
export function initLiveReporting(config) {
    matchId = config.matchId;
    teamId = config.teamId;

    // Connect to SocketIO server
    const socketUrl = config.socketUrl || window.location.origin;
    socket = window.io(socketUrl + '/live');

    // Setup event listeners
    setupSocketListeners();
    setupUIListeners();

    // Join the match room when connected
    socket.on('connect', () => {
        // Connected to live reporting server
        joinMatch();
    });
}

/**
 * Set up all socket event listeners
 */
export function setupSocketListeners() {
    if (!socket) return;

    // Connection events
    socket.on('disconnect', () => {
        // Disconnected from live reporting server
        liveReportingShowNotification('Connection lost. Attempting to reconnect...', 'warning');

        // Stop the timer if it's running
        if (timerInterval) {
            clearInterval(timerInterval);
            timerInterval = null;
        }
    });

    socket.on('error', (error) => {
        // Socket error
        liveReportingShowNotification('Error: ' + error.message, 'danger');
    });

    // Match state events
    socket.on('match_state', (state) => {
        // Received match state
        matchState = state;
        updateMatchUI(state);
    });

    socket.on('active_reporters', (reporters) => {
        // Active reporters
        activeReporters = reporters;
        updateReportersUI(reporters);
    });

    socket.on('player_shifts', (shifts) => {
        // Player shifts
        playerShifts = shifts;
        updateShiftsUI(shifts);
    });

    // Live updates
    socket.on('reporter_joined', (data) => {
        // Reporter joined
        liveReportingShowNotification(`${data.username} joined as a reporter for ${data.team_name}`, 'info');

        // Add to active reporters if not already present
        if (!activeReporters.find(r => r.user_id === data.user_id)) {
            activeReporters.push(data);
            updateReportersUI(activeReporters);
        }
    });

    socket.on('reporter_left', (data) => {
        // Reporter left
        liveReportingShowNotification(`${data.username} is no longer reporting`, 'info');

        // Remove from active reporters
        activeReporters = activeReporters.filter(r => r.user_id !== data.user_id);
        updateReportersUI(activeReporters);
    });

    socket.on('score_updated', (data) => {
        // Score updated

        // Update match state
        if (matchState) {
            matchState.home_score = data.home_score;
            matchState.away_score = data.away_score;
            updateScoreUI(data.home_score, data.away_score);
        }

        liveReportingShowNotification(`Score updated to ${data.home_score}-${data.away_score} by ${data.updated_by_name}`, 'success');
    });

    socket.on('timer_updated', (data) => {
        // Timer updated

        // Update match state
        if (matchState) {
            matchState.elapsed_seconds = data.elapsed_seconds;
            matchState.timer_running = data.is_running;
            if (data.period) {
                matchState.period = data.period;
            }

            updateTimerUI(data.elapsed_seconds, data.is_running, data.period);
        }

        liveReportingShowNotification(`Timer updated by ${data.updated_by_name}`, 'info');
    });

    socket.on('event_added', (data) => {
        // Event added
        const event = data.event;

        // Add to match events
        if (matchState && matchState.events) {
            matchState.events.push(event);
            updateEventsUI(matchState.events);
        }

        let eventMessage = `${event.event_type}`;
        if (event.player_name) {
            eventMessage += ` by ${event.player_name}`;
        }
        if (event.team_name) {
            eventMessage += ` (${event.team_name})`;
        }
        if (event.minute) {
            eventMessage += ` at ${event.minute}'`;
        }

        liveReportingShowNotification(`New event: ${eventMessage}`, 'success');
    });

    socket.on('player_shift_updated', (data) => {
        // Player shift updated

        // Only process shift updates for our team
        if (data.team_id === teamId) {
            // Update the shift if it exists, or add a new one
            const existingShiftIndex = playerShifts.findIndex(s => s.player_id === data.player_id);

            if (existingShiftIndex >= 0) {
                playerShifts[existingShiftIndex].is_active = data.is_active;
                playerShifts[existingShiftIndex].last_updated = new Date().toISOString();
            } else {
                playerShifts.push({
                    player_id: data.player_id,
                    player_name: data.player_name,
                    is_active: data.is_active,
                    last_updated: new Date().toISOString()
                });
            }

            updateShiftsUI(playerShifts);
            liveReportingShowNotification(`Player ${data.player_name} shift ${data.is_active ? 'started' : 'ended'}`, 'info');
        }
    });

    socket.on('report_submitted', (data) => {
        // Report submitted

        // Update match state
        if (matchState) {
            matchState.report_submitted = true;
            matchState.report_submitted_by = data.submitted_by;
            updateMatchStatusUI('completed');
        }

        liveReportingShowNotification(`Final report submitted by ${data.submitted_by_name}`, 'success');

        // Disable reporting controls
        disableReportingControls();

        // Show completion message
        window.$('#reportCompleteMessage').removeClass('u-hidden');
    });

    socket.on('report_submission_error', (data) => {
        // Report submission error
        liveReportingShowNotification(`Error submitting report: ${data.message}`, 'danger');
    });
}

/**
 * Set up UI event listeners
 */
export function setupUIListeners() {
    // Score controls
    window.$('#increaseHomeScore').on('click', function() {
        if (!matchState) return;

        const newScore = matchState.home_score + 1;
        updateScore(newScore, matchState.away_score);
    });

    window.$('#decreaseHomeScore').on('click', function() {
        if (!matchState || matchState.home_score <= 0) return;

        const newScore = matchState.home_score - 1;
        updateScore(newScore, matchState.away_score);
    });

    window.$('#increaseAwayScore').on('click', function() {
        if (!matchState) return;

        const newScore = matchState.away_score + 1;
        updateScore(matchState.home_score, newScore);
    });

    window.$('#decreaseAwayScore').on('click', function() {
        if (!matchState || matchState.away_score <= 0) return;

        const newScore = matchState.away_score - 1;
        updateScore(matchState.home_score, newScore);
    });

    // Timer controls
    window.$('#startStopTimer').on('click', function() {
        if (!matchState) return;

        const newTimerState = !isTimerRunning;
        toggleTimer(newTimerState);
    });

    window.$('#resetTimer').on('click', function() {
        if (!matchState) return;

        // Ask for confirmation before resetting
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Reset Timer',
                text: 'Are you sure you want to reset the timer to 0?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#3085d6',
                cancelButtonColor: '#d33',
                confirmButtonText: 'Yes, reset it!'
            }).then((result) => {
                if (result.isConfirmed) {
                    updateTimer(0, isTimerRunning);
                }
            });
        }
    });

    // Period selection
    window.$('#periodSelector').on('change', function() {
        if (!matchState) return;

        const newPeriod = window.$(this).val();
        updatePeriod(newPeriod);
    });

    // Event form
    window.$('#addEventForm').on('submit', function(e) {
        e.preventDefault();

        const eventType = window.$('#eventType').val();
        const eventTeamId = window.$('#eventTeam').val();
        const eventPlayerId = window.$('#eventPlayer').val();
        const eventMinute = window.$('#eventMinute').val();

        addEvent({
            event_type: eventType,
            team_id: parseInt(eventTeamId),
            player_id: eventPlayerId ? parseInt(eventPlayerId) : null,
            minute: eventMinute ? parseInt(eventMinute) : null,
            period: matchState ? matchState.period : null
        });

        // Reset form
        this.reset();

        // Update player dropdown based on team selection
        const defaultTeam = window.$('#eventTeam option:first').val();
        updatePlayerDropdown(defaultTeam);
    });

    // Team selection changes player dropdown
    window.$('#eventTeam').on('change', function() {
        const selectedTeamId = window.$(this).val();
        updatePlayerDropdown(selectedTeamId);
    });

    // Player shift toggles
    window.$('#playerShiftsContainer').on('click', '.js-player-shift-toggle', function() {
        const playerId = window.$(this).data('player-id');
        const isActive = window.$(this).data('active') !== true;

        // Toggle the active state
        togglePlayerShift(playerId, isActive);
    });

    // Submit report button
    window.$('#submitReportBtn').on('click', function() {
        if (!matchState) return;

        // Ask for confirmation
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Submit Final Report',
                text: 'Are you sure you want to submit the final match report? This action cannot be undone.',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#3085d6',
                cancelButtonColor: '#d33',
                confirmButtonText: 'Yes, submit it!'
            }).then((result) => {
                if (result.isConfirmed) {
                    submitFinalReport();
                }
            });
        }
    });

    // Event type changes UI elements shown
    window.$('#eventType').on('change', function() {
        const eventType = window.$(this).val();

        // Show/hide player selection based on event type
        if (['GOAL', 'YELLOW_CARD', 'RED_CARD', 'SUBSTITUTION'].includes(eventType)) {
            window.$('#playerSelectGroup').removeClass('u-hidden');
        } else {
            window.$('#playerSelectGroup').addClass('u-hidden');
        }

        // Show additional fields for substitutions
        if (eventType === 'SUBSTITUTION') {
            window.$('#substitutionFields').removeClass('u-hidden');
        } else {
            window.$('#substitutionFields').addClass('u-hidden');
        }
    });
}

/**
 * Join a match room
 */
export function joinMatch() {
    if (!socket) return;
    socket.emit('join_match', {
        match_id: matchId,
        team_id: teamId
    });
}

/**
 * Leave a match room
 */
export function leaveMatch() {
    if (!socket) return;
    socket.emit('leave_match', {
        match_id: matchId
    });
}

/**
 * Update the match score
 */
export function updateScore(homeScore, awayScore) {
    if (!socket) return;
    socket.emit('update_score', {
        match_id: matchId,
        home_score: homeScore,
        away_score: awayScore
    });
}

/**
 * Update the match timer
 */
export function updateTimer(elapsedSeconds, isRunning, period = null) {
    const data = {
        match_id: matchId,
        elapsed_seconds: elapsedSeconds,
        is_running: isRunning
    };

    if (period) {
        data.period = period;
    }

    if (!socket) return;
    socket.emit('update_timer', data);
}

/**
 * Update the match period
 */
export function updatePeriod(period) {
    // Use the timer update event to also update the period
    if (matchState) {
        updateTimer(matchState.elapsed_seconds, isTimerRunning, period);
    }
}

/**
 * Toggle the timer state
 */
export function toggleTimer(shouldRun) {
    if (!matchState) return;

    if (shouldRun !== isTimerRunning) {
        isTimerRunning = shouldRun;

        if (shouldRun) {
            // Start the timer locally
            startTimerInterval();

            // Update the server
            updateTimer(matchState.elapsed_seconds, true);

            // Update UI
            window.$('#startStopTimer').text('Pause Timer');
            window.$('#startStopTimer').removeClass('timer-stopped').addClass('timer-running');
        } else {
            // Stop the timer locally
            if (timerInterval) {
                clearInterval(timerInterval);
                timerInterval = null;
            }

            // Update the server
            updateTimer(matchState.elapsed_seconds, false);

            // Update UI
            window.$('#startStopTimer').text('Start Timer');
            window.$('#startStopTimer').removeClass('timer-running').addClass('timer-stopped');
        }
    }
}

/**
 * Start the local timer interval
 */
export function startTimerInterval() {
    if (timerInterval) {
        clearInterval(timerInterval);
    }

    // Update every second
    timerInterval = setInterval(() => {
        if (matchState && isTimerRunning) {
            matchState.elapsed_seconds++;
            updateTimerDisplay(matchState.elapsed_seconds);
        }
    }, 1000);
}

/**
 * Add a match event
 */
export function addEvent(eventData) {
    if (!socket) return;
    socket.emit('add_event', {
        match_id: matchId,
        event: eventData
    });
}

/**
 * Toggle a player's shift status
 */
export function togglePlayerShift(playerId, isActive) {
    if (!socket) return;
    socket.emit('update_player_shift', {
        match_id: matchId,
        player_id: playerId,
        is_active: isActive,
        team_id: teamId
    });
}

/**
 * Submit the final match report
 */
export function submitFinalReport() {
    if (!socket) return;
    const notes = window.$('#matchNotes').val();

    socket.emit('submit_report', {
        match_id: matchId,
        report_data: {
            notes: notes
        }
    });
}

/**
 * Update the match UI with current state
 */
export function updateMatchUI(state) {
    // Update score
    updateScoreUI(state.home_score, state.away_score);

    // Update timer
    updateTimerUI(state.elapsed_seconds, state.timer_running, state.period);

    // Update events
    updateEventsUI(state.events);

    // Update match status
    updateMatchStatusUI(state.status);

    // Update team names
    window.$('#homeTeamName').text(state.home_team_name);
    window.$('#awayTeamName').text(state.away_team_name);

    // If report is already submitted, disable controls
    if (state.report_submitted) {
        disableReportingControls();
        window.$('#reportCompleteMessage').removeClass('u-hidden');
    }
}

/**
 * Update the score display
 */
export function updateScoreUI(homeScore, awayScore) {
    window.$('#homeScore').text(homeScore);
    window.$('#awayScore').text(awayScore);
}

/**
 * Update the timer display
 */
export function updateTimerUI(elapsedSeconds, isRunning, period) {
    // Update period selector
    if (period && window.$('#periodSelector').val() !== period) {
        window.$('#periodSelector').val(period);
    }

    // Update timer display
    updateTimerDisplay(elapsedSeconds);

    // Update timer state
    if (isRunning !== isTimerRunning) {
        toggleTimer(isRunning);
    }
}

/**
 * Update the timer display format
 */
export function updateTimerDisplay(elapsedSeconds) {
    const minutes = Math.floor(elapsedSeconds / 60);
    const seconds = elapsedSeconds % 60;

    window.$('#timerDisplay').text(
        `${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`
    );
}

/**
 * Update the events list
 */
export function updateEventsUI(events) {
    const $eventsList = window.$('#eventsList');
    $eventsList.empty();

    if (!events || events.length === 0) {
        $eventsList.append('<li class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">No events recorded yet</li>');
        return;
    }

    // Sort events by timestamp (most recent first)
    events.sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

    events.forEach(event => {
        let eventText = `${event.event_type}`;
        if (event.player_name) {
            eventText += ` - ${event.player_name}`;
        }
        if (event.team_name) {
            eventText += ` (${event.team_name})`;
        }
        if (event.minute) {
            eventText += ` - ${event.minute}'`;
        }

        let eventClass = 'px-4 py-3 text-sm border-b border-gray-200 dark:border-gray-700 js-event-item';
        switch (event.event_type) {
            case 'GOAL':
                eventClass += ' bg-green-50 text-green-800 dark:bg-green-900/20 dark:text-green-300';
                break;
            case 'YELLOW_CARD':
                eventClass += ' bg-yellow-50 text-yellow-800 dark:bg-yellow-900/20 dark:text-yellow-300';
                break;
            case 'RED_CARD':
                eventClass += ' bg-red-50 text-red-800 dark:bg-red-900/20 dark:text-red-300';
                break;
            default:
                eventClass += ' text-gray-900 dark:text-white';
        }

        $eventsList.append(`<li class="${eventClass}">${eventText}</li>`);
    });
}

/**
 * Update the match status display
 */
export function updateMatchStatusUI(status) {
    window.$('#matchStatus').text(status);

    let statusClass = 'badge js-match-status-badge ';
    switch (status) {
        case 'in_progress':
            statusClass += 'match-status-in-progress';
            break;
        case 'completed':
            statusClass += 'match-status-completed';
            break;
        case 'canceled':
            statusClass += 'match-status-canceled';
            break;
        default:
            statusClass += 'match-status-unknown';
    }

    window.$('#matchStatusBadge').attr('class', statusClass);
}

/**
 * Update the active reporters list
 */
export function updateReportersUI(reporters) {
    const $reportersList = window.$('#reportersList');
    $reportersList.empty();

    if (!reporters || reporters.length === 0) {
        $reportersList.append('<li class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">No other reporters</li>');
        return;
    }

    reporters.forEach(reporter => {
        const lastActive = new Date(reporter.last_active);
        const timeSince = timeSinceLastActive(lastActive);

        $reportersList.append(`
            <li class="px-4 py-3 text-sm border-b border-gray-200 dark:border-gray-700 flex justify-between items-center js-reporter-item">
                <span class="text-gray-900 dark:text-white">${reporter.username} (${reporter.team_name})</span>
                <span class="px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300">${timeSince}</span>
            </li>
        `);
    });
}

/**
 * Format time since last active
 */
export function timeSinceLastActive(lastActive) {
    const now = new Date();
    const diffMs = now - lastActive;
    const diffSec = Math.floor(diffMs / 1000);

    if (diffSec < 60) {
        return 'just now';
    } else if (diffSec < 3600) {
        const mins = Math.floor(diffSec / 60);
        return `${mins}m ago`;
    } else {
        const hours = Math.floor(diffSec / 3600);
        return `${hours}h ago`;
    }
}

/**
 * Update the player shifts display
 */
export function updateShiftsUI(shifts) {
    const $shiftsContainer = window.$('#playerShiftsContainer');
    $shiftsContainer.empty();

    if (!shifts || shifts.length === 0) {
        $shiftsContainer.append('<p class="text-sm text-gray-500 dark:text-gray-400">No player shifts recorded</p>');
        return;
    }

    // Group shifts by active/inactive
    const activeShifts = shifts.filter(s => s.is_active);
    const inactiveShifts = shifts.filter(s => !s.is_active);

    // Add active players section
    $shiftsContainer.append('<h5 class="text-sm font-semibold text-gray-900 dark:text-white mt-3 mb-2">Active Players</h5>');
    if (activeShifts.length === 0) {
        $shiftsContainer.append('<p class="text-sm text-gray-500 dark:text-gray-400">No active players</p>');
    } else {
        const $activeList = window.$('<div class="grid grid-cols-1 md:grid-cols-2 gap-2"></div>');

        activeShifts.forEach(shift => {
            $activeList.append(`
                <button class="w-full text-white bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-4 py-2 js-player-shift-toggle"
                        data-player-id="${shift.player_id}"
                        data-active="true">
                    ${shift.player_name}
                </button>
            `);
        });

        $shiftsContainer.append($activeList);
    }

    // Add inactive players section
    $shiftsContainer.append('<h5 class="text-sm font-semibold text-gray-900 dark:text-white mt-4 mb-2">Available Players</h5>');
    if (inactiveShifts.length === 0) {
        $shiftsContainer.append('<p class="text-sm text-gray-500 dark:text-gray-400">No available players</p>');
    } else {
        const $inactiveList = window.$('<div class="grid grid-cols-1 md:grid-cols-2 gap-2"></div>');

        inactiveShifts.forEach(shift => {
            $inactiveList.append(`
                <button class="w-full text-gray-700 bg-white border border-gray-300 hover:bg-gray-100 focus:ring-4 focus:ring-gray-200 font-medium rounded-lg text-sm px-4 py-2 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600 dark:hover:bg-gray-700 js-player-shift-toggle"
                        data-player-id="${shift.player_id}"
                        data-active="false">
                    ${shift.player_name}
                </button>
            `);
        });

        $shiftsContainer.append($inactiveList);
    }
}

/**
 * Update the player dropdown based on selected team
 */
export function updatePlayerDropdown(selectedTeamId) {
    if (!matchState) return;

    const $playerSelect = window.$('#eventPlayer');
    $playerSelect.empty();

    // Add empty option
    $playerSelect.append('<option value="">Select Player</option>');

    // Determine which team's players to show
    let players = [];
    if (parseInt(selectedTeamId) === matchState.home_team_id) {
        // Show home team players
        players = window.$('#homeTeamPlayers').data('players') || [];
    } else if (parseInt(selectedTeamId) === matchState.away_team_id) {
        // Show away team players
        players = window.$('#awayTeamPlayers').data('players') || [];
    }

    // Add players to dropdown
    players.forEach(player => {
        $playerSelect.append(`<option value="${player.id}">${player.name}</option>`);
    });
}

/**
 * Disable all reporting controls when report is submitted
 */
export function disableReportingControls() {
    // Disable score controls
    window.$('#increaseHomeScore, #decreaseHomeScore, #increaseAwayScore, #decreaseAwayScore').prop('disabled', true);

    // Disable timer controls
    window.$('#startStopTimer, #resetTimer, #periodSelector').prop('disabled', true);

    // Disable event form
    window.$('#addEventForm :input').prop('disabled', true);

    // Disable player shifts
    window.$('.js-player-shift-toggle').prop('disabled', true);

    // Disable submit report button
    window.$('#submitReportBtn').prop('disabled', true);

    // Stop timer if running
    if (timerInterval) {
        clearInterval(timerInterval);
        timerInterval = null;
        isTimerRunning = false;
    }
}

/**
 * Show a notification message
 */
export function liveReportingShowNotification(message, type = 'info') {
    const $notifications = window.$('#notifications');

    // Map type to Tailwind colors
    const typeColors = {
        'success': 'text-green-800 bg-green-50 dark:bg-gray-800 dark:text-green-400',
        'error': 'text-red-800 bg-red-50 dark:bg-gray-800 dark:text-red-400',
        'danger': 'text-red-800 bg-red-50 dark:bg-gray-800 dark:text-red-400',
        'warning': 'text-yellow-800 bg-yellow-50 dark:bg-gray-800 dark:text-yellow-400',
        'info': 'text-blue-800 bg-blue-50 dark:bg-gray-800 dark:text-blue-400'
    };
    const colorClass = typeColors[type] || typeColors['info'];

    // Create notification element
    const $notification = window.$(`
        <div class="p-4 mb-2 text-sm rounded-lg ${colorClass}" role="alert">
            <div class="flex items-center justify-between">
                <span>${message}</span>
                <button type="button" class="ml-2 -mx-1.5 -my-1.5 rounded-lg p-1.5 inline-flex items-center justify-center h-8 w-8 hover:bg-gray-200 dark:hover:bg-gray-700" onclick="this.closest('[role=alert]').remove()" aria-label="Close">
                    <svg class="w-3 h-3" fill="none" viewBox="0 0 14 14"><path stroke="currentColor" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="m1 1 6 6m0 0 6 6M7 7l6-6M7 7l-6 6"/></svg>
                </button>
            </div>
        </div>
    `);

    // Add to notifications container
    $notifications.append($notification);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        $notification.remove();
    }, 5000);
}

// Export module functions
window.LiveReporting = {
    init: initLiveReporting,
    join: joinMatch,
    leave: leaveMatch
};

// Initialize function
function initLiveReportingModule() {
    if (_initialized) return;
    _initialized = true;

    // LiveReporting is initialized manually via window.LiveReporting.init(config)
    // when the page provides the required configuration
}

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('live-reporting', initLiveReportingModule, {
        priority: 45,
        reinitializable: false,
        description: 'Live match reporting client'
    });
}

// Fallback
// window.InitSystem handles initialization

// Window exports - only functions used by event delegation handlers
window.addEvent = addEvent;
