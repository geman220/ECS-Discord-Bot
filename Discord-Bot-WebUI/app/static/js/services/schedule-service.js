/**
 * Schedule Service - Centralizes all schedule-related fetch calls
 * Consolidates: schedule-management.js, seasonal-schedule.js, ecs-fc-schedule.js,
 * auto-schedule-manager.js, manage-teams.js (schedule parts)
 *
 * @module services/schedule-service
 */

/**
 * @typedef {Object} ScheduleWeek
 * @property {number} weekNumber - Week number
 * @property {string} date - Week date
 * @property {string} type - Week type (Regular, TST, FUN, PLAYOFF, etc.)
 */

/**
 * @typedef {Object} Match
 * @property {number} id - Match ID
 * @property {number} home_team_id - Home team ID
 * @property {number} away_team_id - Away team ID
 * @property {string} match_date - Match date
 * @property {string} match_time - Match time
 * @property {string} status - Match status
 */

// =====================
// Schedule Generation
// =====================

/**
 * Generate schedule for a league
 * @param {Object} params - Schedule parameters
 * @param {number} params.leagueId - League ID
 * @param {string} params.startDate - Start date
 * @param {number} params.weeks - Number of weeks
 * @param {string} params.matchDay - Match day of week
 * @returns {Promise<Object>} Generated schedule
 */
export async function generateSchedule(params) {
    const response = await fetch('/admin/match_operations/generate_schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
    });
    return response.json();
}

/**
 * Generate auto schedule based on configuration
 * @param {Object} config - Auto schedule configuration
 * @returns {Promise<Object>} Generated schedule data
 */
export async function generateAutoSchedule(config) {
    const response = await fetch('/admin/match_operations/auto_generate_schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    });
    return response.json();
}

/**
 * Preview auto-generated schedule before saving
 * @param {Object} config - Auto schedule configuration
 * @returns {Promise<Object>} Preview data
 */
export async function previewAutoSchedule(config) {
    const response = await fetch('/admin/match_operations/preview_schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config)
    });
    return response.json();
}

// =====================
// Schedule Retrieval
// =====================

/**
 * Get schedule for a season
 * @param {number} seasonId - Season ID
 * @returns {Promise<Object>} Season schedule
 */
export async function getSeasonSchedule(seasonId) {
    const response = await fetch(`/admin/match_operations/seasons/${seasonId}/schedule`);
    return response.json();
}

/**
 * Get schedule for a league
 * @param {number} leagueId - League ID
 * @returns {Promise<Object>} League schedule
 */
export async function getLeagueSchedule(leagueId) {
    const response = await fetch(`/admin/match_operations/leagues/${leagueId}/schedule`);
    return response.json();
}

/**
 * Get schedule for a team
 * @param {number} teamId - Team ID
 * @returns {Promise<Object>} Team schedule
 */
export async function getTeamSchedule(teamId) {
    const response = await fetch(`/teams/${teamId}/schedule`);
    return response.json();
}

/**
 * Get weekly schedule view
 * @param {string} date - Date to get week for
 * @returns {Promise<Object>} Weekly schedule
 */
export async function getWeeklySchedule(date) {
    const response = await fetch(`/schedule/weekly?date=${encodeURIComponent(date)}`);
    return response.json();
}

/**
 * Get calendar events for date range
 * @param {string} start - Start date
 * @param {string} end - End date
 * @returns {Promise<Array>} Calendar events
 */
export async function getCalendarEvents(start, end) {
    const response = await fetch(`/schedule/events?start=${start}&end=${end}`);
    return response.json();
}

// =====================
// ECS FC Schedule
// =====================

/**
 * Get ECS FC schedule
 * @param {number} seasonId - Season ID (optional)
 * @returns {Promise<Object>} ECS FC schedule
 */
export async function getEcsFcSchedule(seasonId = null) {
    let url = '/admin_panel/ecs_fc/schedule';
    if (seasonId) {
        url += `?season_id=${seasonId}`;
    }
    const response = await fetch(url);
    return response.json();
}

/**
 * Save ECS FC schedule
 * @param {Object} scheduleData - Schedule data to save
 * @returns {Promise<Object>} Save result
 */
export async function saveEcsFcSchedule(scheduleData) {
    const response = await fetch('/admin_panel/ecs_fc/schedule/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scheduleData)
    });
    return response.json();
}

/**
 * Import ECS FC matches from external source
 * @param {Object} importData - Import data
 * @returns {Promise<Object>} Import result
 */
export async function importEcsFcMatches(importData) {
    const response = await fetch('/admin_panel/ecs_fc/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(importData)
    });
    return response.json();
}

// =====================
// Schedule Modification
// =====================

/**
 * Save schedule changes
 * @param {number} seasonId - Season ID
 * @param {Array} matches - Array of match data
 * @returns {Promise<Object>} Save result
 */
export async function saveSchedule(seasonId, matches) {
    const response = await fetch(`/admin/match_operations/seasons/${seasonId}/schedule/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ matches })
    });
    return response.json();
}

/**
 * Reschedule a match
 * @param {number} matchId - Match ID
 * @param {Object} newSchedule - New date/time
 * @returns {Promise<Object>} Reschedule result
 */
export async function rescheduleMatch(matchId, newSchedule) {
    const response = await fetch(`/admin/match_operations/matches/${matchId}/reschedule`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSchedule)
    });
    return response.json();
}

/**
 * Swap match positions in schedule
 * @param {number} match1Id - First match ID
 * @param {number} match2Id - Second match ID
 * @returns {Promise<Object>} Swap result
 */
export async function swapMatches(match1Id, match2Id) {
    const response = await fetch('/admin/match_operations/swap_matches', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ match1_id: match1Id, match2_id: match2Id })
    });
    return response.json();
}

/**
 * Bulk update schedule
 * @param {Array} updates - Array of match updates
 * @returns {Promise<Object>} Bulk update result
 */
export async function bulkUpdateSchedule(updates) {
    const response = await fetch('/admin/match_operations/bulk_schedule_update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates })
    });
    return response.json();
}

// =====================
// Schedule Validation
// =====================

/**
 * Validate schedule for conflicts
 * @param {Array} matches - Array of match data
 * @returns {Promise<Object>} Validation result
 */
export async function validateSchedule(matches) {
    const response = await fetch('/admin/match_operations/validate_schedule', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ matches })
    });
    return response.json();
}

/**
 * Check for scheduling conflicts
 * @param {number} teamId - Team ID
 * @param {string} date - Proposed date
 * @param {string} time - Proposed time
 * @returns {Promise<Object>} Conflict check result
 */
export async function checkConflicts(teamId, date, time) {
    const response = await fetch('/admin/match_operations/check_conflicts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team_id: teamId, date, time })
    });
    return response.json();
}

// =====================
// Season Week Management
// =====================

/**
 * Get season weeks configuration
 * @param {number} seasonId - Season ID
 * @returns {Promise<Array>} Season weeks
 */
export async function getSeasonWeeks(seasonId) {
    const response = await fetch(`/admin/match_operations/seasons/${seasonId}/weeks`);
    return response.json();
}

/**
 * Update season week configuration
 * @param {number} seasonId - Season ID
 * @param {Array} weeks - Week configuration
 * @returns {Promise<Object>} Update result
 */
export async function updateSeasonWeeks(seasonId, weeks) {
    const response = await fetch(`/admin/match_operations/seasons/${seasonId}/weeks`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ weeks })
    });
    return response.json();
}

/**
 * Add a bye week
 * @param {number} seasonId - Season ID
 * @param {string} date - Bye week date
 * @param {string} reason - Reason for bye week
 * @returns {Promise<Object>} Add result
 */
export async function addByeWeek(seasonId, date, reason = '') {
    const response = await fetch(`/admin/match_operations/seasons/${seasonId}/bye_week`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date, reason })
    });
    return response.json();
}

/**
 * Remove a bye week
 * @param {number} seasonId - Season ID
 * @param {string} date - Bye week date to remove
 * @returns {Promise<Object>} Remove result
 */
export async function removeByeWeek(seasonId, date) {
    const response = await fetch(`/admin/match_operations/seasons/${seasonId}/bye_week`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date })
    });
    return response.json();
}

// =====================
// Schedule Templates
// =====================

/**
 * Get available schedule templates
 * @returns {Promise<Array>} Schedule templates
 */
export async function getScheduleTemplates() {
    const response = await fetch('/admin/match_operations/schedule_templates');
    return response.json();
}

/**
 * Apply a schedule template
 * @param {number} seasonId - Season ID
 * @param {number} templateId - Template ID
 * @returns {Promise<Object>} Application result
 */
export async function applyScheduleTemplate(seasonId, templateId) {
    const response = await fetch(`/admin/match_operations/seasons/${seasonId}/apply_template`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ template_id: templateId })
    });
    return response.json();
}

/**
 * Save current schedule as template
 * @param {number} seasonId - Season ID
 * @param {string} name - Template name
 * @returns {Promise<Object>} Save result
 */
export async function saveAsTemplate(seasonId, name) {
    const response = await fetch(`/admin/match_operations/seasons/${seasonId}/save_template`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
    });
    return response.json();
}

// =====================
// Pub League Schedule
// =====================

/**
 * Get Pub League schedule
 * @param {string} division - Division (premier/classic)
 * @param {number} seasonId - Season ID (optional)
 * @returns {Promise<Object>} Pub League schedule
 */
export async function getPubLeagueSchedule(division, seasonId = null) {
    let url = `/schedule/pub_league/${division}`;
    if (seasonId) {
        url += `?season_id=${seasonId}`;
    }
    const response = await fetch(url);
    return response.json();
}

/**
 * Save Pub League schedule
 * @param {string} division - Division (premier/classic)
 * @param {Object} scheduleData - Schedule data
 * @returns {Promise<Object>} Save result
 */
export async function savePubLeagueSchedule(division, scheduleData) {
    const response = await fetch(`/admin/match_operations/pub_league/${division}/save`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(scheduleData)
    });
    return response.json();
}

export default {
    // Generation
    generateSchedule,
    generateAutoSchedule,
    previewAutoSchedule,

    // Retrieval
    getSeasonSchedule,
    getLeagueSchedule,
    getTeamSchedule,
    getWeeklySchedule,
    getCalendarEvents,

    // ECS FC
    getEcsFcSchedule,
    saveEcsFcSchedule,
    importEcsFcMatches,

    // Modification
    saveSchedule,
    rescheduleMatch,
    swapMatches,
    bulkUpdateSchedule,

    // Validation
    validateSchedule,
    checkConflicts,

    // Week Management
    getSeasonWeeks,
    updateSeasonWeeks,
    addByeWeek,
    removeByeWeek,

    // Templates
    getScheduleTemplates,
    applyScheduleTemplate,
    saveAsTemplate,

    // Pub League
    getPubLeagueSchedule,
    savePubLeagueSchedule
};
