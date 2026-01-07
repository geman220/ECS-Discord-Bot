/**
 * Match API Service
 * Centralized API client for all match-related operations
 *
 * This service consolidates fetch calls that were previously scattered across:
 * - report_match.js
 * - match-management.js
 * - admin-match-operations.js
 * - admin-panel-match-list.js
 * - admin-match-detail.js
 * - seasonal-schedule.js
 * - And other match-related files
 *
 * Benefits:
 * - Single source of truth for match API endpoints
 * - Consistent error handling
 * - Automatic CSRF token handling (via csrf-fetch.js)
 * - Type documentation for IDE support
 * - Easy mocking for tests
 *
 * @module services/match-api
 */

/**
 * @typedef {Object} Match
 * @property {number} id - Match identifier
 * @property {number} home_team_id - Home team ID
 * @property {number} away_team_id - Away team ID
 * @property {string} home_team_name - Home team name
 * @property {string} away_team_name - Away team name
 * @property {number|null} home_team_score - Home team score
 * @property {number|null} away_team_score - Away team score
 * @property {string} match_date - Match date (ISO format)
 * @property {string} match_time - Match time
 * @property {string} status - Match status
 */

/**
 * @typedef {Object} MatchTask
 * @property {string} task_id - Celery task ID
 * @property {string} status - Task status
 * @property {string} task_type - Type of task (schedule, thread, reporting)
 */

/**
 * @typedef {Object} ApiResponse
 * @property {boolean} success - Whether the operation succeeded
 * @property {string} [message] - Success or error message
 * @property {*} [data] - Response data
 * @property {string} [error] - Error details
 */

/**
 * Base URL for admin panel match operations
 */
const ADMIN_PANEL_BASE = '/admin-panel';

/**
 * Base URL for match management
 */
const MATCH_MANAGEMENT_BASE = '/admin/match_management';

/**
 * Handle API response and throw on error
 * @param {Response} response - Fetch response
 * @returns {Promise<ApiResponse>}
 */
async function handleResponse(response) {
    const data = await response.json();

    if (!response.ok) {
        const error = new Error(data.message || data.error || `HTTP ${response.status}`);
        error.status = response.status;
        error.data = data;
        throw error;
    }

    return data;
}

/**
 * Get JSON request options with CSRF token
 * @param {string} method - HTTP method
 * @param {Object} [body] - Request body
 * @returns {RequestInit}
 */
function jsonRequest(method, body = null) {
    const options = {
        method,
        headers: {
            'Content-Type': 'application/json'
        }
    };

    if (body) {
        options.body = JSON.stringify(body);
    }

    return options;
}

// ============================================================================
// Match Details & CRUD
// ============================================================================

/**
 * Get match details by ID
 * @param {number} matchId - Match ID
 * @returns {Promise<Match>}
 */
export async function getMatchDetails(matchId) {
    const response = await fetch(`${ADMIN_PANEL_BASE}/matches/${matchId}/details`);
    return handleResponse(response);
}

/**
 * Delete a match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function deleteMatch(matchId) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/matches/${matchId}/delete`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Update match details
 * @param {number} matchId - Match ID
 * @param {Object} data - Match data to update
 * @returns {Promise<ApiResponse>}
 */
export async function updateMatch(matchId, data) {
    const response = await fetch(
        `/auto-schedule/update-match`,
        jsonRequest('POST', { match_id: matchId, ...data })
    );
    return handleResponse(response);
}

/**
 * Add a new match
 * @param {Object} matchData - Match data
 * @returns {Promise<ApiResponse>}
 */
export async function addMatch(matchData) {
    const response = await fetch(
        '/auto-schedule/add-match',
        jsonRequest('POST', matchData)
    );
    return handleResponse(response);
}

// ============================================================================
// Match Reporting
// ============================================================================

/**
 * Report match results
 * @param {number} matchId - Match ID
 * @param {FormData} formData - Match report form data
 * @returns {Promise<ApiResponse>}
 */
export async function reportMatch(matchId, formData) {
    const response = await fetch(`/teams/report_match/${matchId}`, {
        method: 'POST',
        body: formData
    });
    return handleResponse(response);
}

/**
 * Get match data for editing
 * @param {number} matchId - Match ID
 * @returns {Promise<Match>}
 */
export async function getMatchData(matchId) {
    const response = await fetch(`/auto-schedule/get-match-data?match_id=${matchId}`);
    return handleResponse(response);
}

// ============================================================================
// Match Scheduling & Thread Management
// ============================================================================

/**
 * Schedule a match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function scheduleMatch(matchId) {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/schedule/${matchId}`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Create Discord thread for match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function createMatchThread(matchId) {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/create-thread/${matchId}`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Start live reporting for a match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function startReporting(matchId) {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/start-reporting/${matchId}`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Stop live reporting for a match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function stopReporting(matchId) {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/stop-reporting/${matchId}`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Force schedule a match (for debugging)
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function forceScheduleMatch(matchId) {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/force-schedule/${matchId}`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

// ============================================================================
// Match Tasks & Status
// ============================================================================

/**
 * Get all match statuses
 * @returns {Promise<Object>}
 */
export async function getMatchStatuses() {
    const response = await fetch(`${MATCH_MANAGEMENT_BASE}/statuses`);
    return handleResponse(response);
}

/**
 * Get tasks for a specific match
 * @param {number} matchId - Match ID
 * @returns {Promise<MatchTask[]>}
 */
export async function getMatchTasks(matchId) {
    const response = await fetch(`${MATCH_MANAGEMENT_BASE}/match-tasks/${matchId}`);
    return handleResponse(response);
}

/**
 * Get queue status
 * @returns {Promise<Object>}
 */
export async function getQueueStatus() {
    const response = await fetch(`${MATCH_MANAGEMENT_BASE}/queue-status`);
    return handleResponse(response);
}

/**
 * Get cache status
 * @returns {Promise<Object>}
 */
export async function getCacheStatus() {
    const response = await fetch(`${MATCH_MANAGEMENT_BASE}/cache-status`);
    return handleResponse(response);
}

/**
 * Debug tasks for a match
 * @param {number} matchId - Match ID
 * @returns {Promise<Object>}
 */
export async function debugMatchTasks(matchId) {
    const response = await fetch(`${MATCH_MANAGEMENT_BASE}/debug-tasks/${matchId}`);
    return handleResponse(response);
}

/**
 * Revoke a Celery task
 * @param {string} taskId - Task ID to revoke
 * @returns {Promise<ApiResponse>}
 */
export async function revokeTask(taskId) {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/revoke-task`,
        jsonRequest('POST', { task_id: taskId })
    );
    return handleResponse(response);
}

// ============================================================================
// Bulk Operations
// ============================================================================

/**
 * Perform bulk action on matches
 * @param {string} action - Action to perform
 * @param {number[]} matchIds - Array of match IDs
 * @returns {Promise<ApiResponse>}
 */
export async function bulkMatchAction(action, matchIds) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/matches/bulk-actions`,
        jsonRequest('POST', { action, match_ids: matchIds })
    );
    return handleResponse(response);
}

/**
 * Schedule all matches
 * @returns {Promise<ApiResponse>}
 */
export async function scheduleAllMatches() {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/schedule-all`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Fetch all matches from ESPN
 * @returns {Promise<ApiResponse>}
 */
export async function fetchAllFromEspn() {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/fetch-all-from-espn`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Clear all matches
 * @returns {Promise<ApiResponse>}
 */
export async function clearAllMatches() {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/clear-all`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Remove a match from management
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function removeMatch(matchId) {
    const response = await fetch(
        `${MATCH_MANAGEMENT_BASE}/remove/${matchId}`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

// ============================================================================
// MLS Matches (Admin Panel)
// ============================================================================

/**
 * Get MLS match statuses
 * @returns {Promise<Object>}
 */
export async function getMlsMatchStatuses() {
    const response = await fetch(`${ADMIN_PANEL_BASE}/mls/match-statuses-api`);
    return handleResponse(response);
}

/**
 * Schedule MLS match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function scheduleMlsMatch(matchId) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/mls/schedule-match/${matchId}`,
        { method: 'POST' }
    );
    return handleResponse(response);
}

/**
 * Create MLS match thread
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function createMlsThread(matchId) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/mls/create-thread/${matchId}`,
        { method: 'POST' }
    );
    return handleResponse(response);
}

/**
 * Start MLS reporting
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function startMlsReporting(matchId) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/mls/start-reporting/${matchId}`,
        { method: 'POST' }
    );
    return handleResponse(response);
}

/**
 * Stop MLS reporting
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function stopMlsReporting(matchId) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/mls/stop-reporting/${matchId}`,
        { method: 'POST' }
    );
    return handleResponse(response);
}

/**
 * Resync MLS match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function resyncMlsMatch(matchId) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/mls/resync-match/${matchId}`,
        { method: 'POST' }
    );
    return handleResponse(response);
}

/**
 * Remove MLS match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function removeMlsMatch(matchId) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/mls/remove-match/${matchId}`,
        { method: 'POST' }
    );
    return handleResponse(response);
}

// ============================================================================
// ECS FC Matches
// ============================================================================

/**
 * Get ECS FC team matches for calendar
 * @param {number} teamId - Team ID
 * @param {string} startDate - Start date
 * @param {string} endDate - End date
 * @returns {Promise<Match[]>}
 */
export async function getEcsFcTeamMatches(teamId, startDate, endDate) {
    const response = await fetch(
        `/api/ecs-fc/teams/${teamId}/matches/calendar?start_date=${startDate}&end_date=${endDate}`
    );
    return handleResponse(response);
}

/**
 * Get ECS FC match RSVP status
 * @param {number} matchId - Match ID
 * @returns {Promise<Object>}
 */
export async function getEcsFcMatchRsvp(matchId) {
    const response = await fetch(`/api/ecs-fc/matches/${matchId}/rsvp`);
    return handleResponse(response);
}

/**
 * Update ECS FC match
 * @param {number} matchId - Match ID
 * @param {Object} data - Match data
 * @returns {Promise<ApiResponse>}
 */
export async function updateEcsFcMatch(matchId, data) {
    const response = await fetch(
        `/api/ecs-fc/matches/${matchId}`,
        jsonRequest('PUT', data)
    );
    return handleResponse(response);
}

/**
 * Update ECS FC match RSVP
 * @param {number} matchId - Match ID
 * @param {Object} data - RSVP data
 * @returns {Promise<ApiResponse>}
 */
export async function updateEcsFcRsvp(matchId, data) {
    const response = await fetch(
        `/api/ecs-fc/matches/${matchId}/rsvp`,
        jsonRequest('POST', data)
    );
    return handleResponse(response);
}

/**
 * Send ECS FC match reminder
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function sendEcsFcReminder(matchId) {
    const response = await fetch(
        `/api/ecs-fc/matches/${matchId}/remind`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

/**
 * Import ECS FC matches
 * @param {FormData} formData - Import form data
 * @returns {Promise<ApiResponse>}
 */
export async function importEcsFcMatches(formData) {
    const response = await fetch('/api/ecs-fc/matches/import', {
        method: 'POST',
        body: formData
    });
    return handleResponse(response);
}

/**
 * Delete ECS FC match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function deleteEcsFcMatch(matchId) {
    const response = await fetch(
        `${ADMIN_PANEL_BASE}/ecs-fc/match/${matchId}/delete`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

// ============================================================================
// Match Stats
// ============================================================================

/**
 * Get match stat for editing
 * @param {number} statId - Stat ID
 * @returns {Promise<Object>}
 */
export async function getMatchStat(statId) {
    const response = await fetch(`/players/edit_match_stat/${statId}`);
    return handleResponse(response);
}

/**
 * Update match stat
 * @param {number} statId - Stat ID
 * @param {Object} data - Stat data
 * @returns {Promise<ApiResponse>}
 */
export async function updateMatchStat(statId, data) {
    const response = await fetch(
        `/players/edit_match_stat/${statId}`,
        jsonRequest('POST', data)
    );
    return handleResponse(response);
}

/**
 * Remove match stat
 * @param {number} statId - Stat ID
 * @returns {Promise<ApiResponse>}
 */
export async function removeMatchStat(statId) {
    const response = await fetch(
        `/players/remove_match_stat/${statId}`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

// ============================================================================
// Pub League Schedule
// ============================================================================

/**
 * Delete Pub League match
 * @param {number} matchId - Match ID
 * @returns {Promise<ApiResponse>}
 */
export async function deletePubLeagueMatch(matchId) {
    const response = await fetch(
        `/publeague/schedules/delete_match/${matchId}`,
        jsonRequest('POST')
    );
    return handleResponse(response);
}

// Default export for convenience
export default {
    // Match CRUD
    getMatchDetails,
    deleteMatch,
    updateMatch,
    addMatch,
    getMatchData,

    // Reporting
    reportMatch,

    // Scheduling
    scheduleMatch,
    createMatchThread,
    startReporting,
    stopReporting,
    forceScheduleMatch,

    // Status & Tasks
    getMatchStatuses,
    getMatchTasks,
    getQueueStatus,
    getCacheStatus,
    debugMatchTasks,
    revokeTask,

    // Bulk Operations
    bulkMatchAction,
    scheduleAllMatches,
    fetchAllFromEspn,
    clearAllMatches,
    removeMatch,

    // MLS
    getMlsMatchStatuses,
    scheduleMlsMatch,
    createMlsThread,
    startMlsReporting,
    stopMlsReporting,
    resyncMlsMatch,
    removeMlsMatch,

    // ECS FC
    getEcsFcTeamMatches,
    getEcsFcMatchRsvp,
    updateEcsFcMatch,
    updateEcsFcRsvp,
    sendEcsFcReminder,
    importEcsFcMatches,
    deleteEcsFcMatch,

    // Stats
    getMatchStat,
    updateMatchStat,
    removeMatchStat,

    // Pub League
    deletePubLeagueMatch
};
