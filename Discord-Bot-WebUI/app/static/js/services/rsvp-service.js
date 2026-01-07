/**
 * RSVP Service - Centralizes all RSVP-related fetch calls
 * Consolidates: rsvp-unified.js, substitute-pool-management.js,
 * substitute-request-management.js
 *
 * @module services/rsvp-service
 */

/**
 * @typedef {Object} RSVPResponse
 * @property {string} status - RSVP status (yes, no, maybe, pending)
 * @property {string|null} reason - Reason for response
 * @property {boolean} needsSub - Whether substitute is needed
 */

/**
 * @typedef {Object} SubstituteRequest
 * @property {number} id - Request ID
 * @property {number} matchId - Match ID
 * @property {number} teamId - Team ID
 * @property {string} status - Request status
 */

// =====================
// RSVP Submission
// =====================

/**
 * Submit RSVP response for a match
 * @param {number} matchId - Match ID
 * @param {string} status - RSVP status (yes, no, maybe)
 * @param {Object} options - Additional options
 * @param {string} [options.reason] - Reason for response
 * @param {boolean} [options.needsSub] - Whether substitute is needed
 * @returns {Promise<Object>} RSVP result
 */
export async function submitRSVP(matchId, status, options = {}) {
    const response = await fetch(`/rsvp/match/${matchId}/respond`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            status,
            reason: options.reason || null,
            needs_sub: options.needsSub || false
        })
    });
    return response.json();
}

/**
 * Update existing RSVP response
 * @param {number} rsvpId - RSVP ID
 * @param {string} status - New status
 * @param {Object} options - Additional options
 * @returns {Promise<Object>} Update result
 */
export async function updateRSVP(rsvpId, status, options = {}) {
    const response = await fetch(`/rsvp/${rsvpId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            status,
            reason: options.reason || null,
            needs_sub: options.needsSub || false
        })
    });
    return response.json();
}

/**
 * Cancel RSVP response
 * @param {number} rsvpId - RSVP ID
 * @returns {Promise<Object>} Cancel result
 */
export async function cancelRSVP(rsvpId) {
    const response = await fetch(`/rsvp/${rsvpId}`, {
        method: 'DELETE'
    });
    return response.json();
}

// =====================
// RSVP Retrieval
// =====================

/**
 * Get RSVP status for a match
 * @param {number} matchId - Match ID
 * @returns {Promise<Object>} RSVP status data
 */
export async function getMatchRSVPStatus(matchId) {
    const response = await fetch(`/rsvp/match/${matchId}/status`);
    return response.json();
}

/**
 * Get all RSVP responses for a match
 * @param {number} matchId - Match ID
 * @returns {Promise<Array>} RSVP responses
 */
export async function getMatchRSVPs(matchId) {
    const response = await fetch(`/rsvp/match/${matchId}`);
    return response.json();
}

/**
 * Get user's RSVP history
 * @param {number} userId - User ID (optional, defaults to current user)
 * @returns {Promise<Array>} RSVP history
 */
export async function getUserRSVPHistory(userId = null) {
    let url = '/rsvp/history';
    if (userId) {
        url += `?user_id=${userId}`;
    }
    const response = await fetch(url);
    return response.json();
}

/**
 * Get team RSVP summary
 * @param {number} teamId - Team ID
 * @param {number} matchId - Match ID (optional)
 * @returns {Promise<Object>} Team RSVP summary
 */
export async function getTeamRSVPSummary(teamId, matchId = null) {
    let url = `/rsvp/team/${teamId}/summary`;
    if (matchId) {
        url += `?match_id=${matchId}`;
    }
    const response = await fetch(url);
    return response.json();
}

/**
 * Get pending RSVPs for current user
 * @returns {Promise<Array>} Pending RSVP requests
 */
export async function getPendingRSVPs() {
    const response = await fetch('/rsvp/pending');
    return response.json();
}

// =====================
// Substitute Pool
// =====================

/**
 * Get substitute pool for a match
 * @param {number} matchId - Match ID
 * @returns {Promise<Array>} Available substitutes
 */
export async function getSubstitutePool(matchId) {
    const response = await fetch(`/rsvp/match/${matchId}/substitute_pool`);
    return response.json();
}

/**
 * Join substitute pool
 * @param {number} matchId - Match ID
 * @param {Object} options - Pool options
 * @param {string} [options.preferredPosition] - Preferred position
 * @param {string} [options.notes] - Additional notes
 * @returns {Promise<Object>} Join result
 */
export async function joinSubstitutePool(matchId, options = {}) {
    const response = await fetch(`/rsvp/match/${matchId}/join_sub_pool`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            preferred_position: options.preferredPosition || null,
            notes: options.notes || null
        })
    });
    return response.json();
}

/**
 * Leave substitute pool
 * @param {number} matchId - Match ID
 * @returns {Promise<Object>} Leave result
 */
export async function leaveSubstitutePool(matchId) {
    const response = await fetch(`/rsvp/match/${matchId}/leave_sub_pool`, {
        method: 'POST'
    });
    return response.json();
}

/**
 * Get league substitute pool
 * @param {number} leagueId - League ID (optional)
 * @returns {Promise<Array>} League substitute pool
 */
export async function getLeagueSubstitutePool(leagueId = null) {
    let url = '/admin/substitute_pool';
    if (leagueId) {
        url += `?league_id=${leagueId}`;
    }
    const response = await fetch(url);
    return response.json();
}

// =====================
// Substitute Requests
// =====================

/**
 * Create substitute request
 * @param {number} matchId - Match ID
 * @param {number} teamId - Team ID
 * @param {Object} options - Request options
 * @param {string} [options.position] - Position needed
 * @param {string} [options.urgency] - Request urgency
 * @param {string} [options.notes] - Additional notes
 * @returns {Promise<Object>} Request result
 */
export async function createSubstituteRequest(matchId, teamId, options = {}) {
    const response = await fetch('/rsvp/substitute_request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            match_id: matchId,
            team_id: teamId,
            position: options.position || null,
            urgency: options.urgency || 'normal',
            notes: options.notes || null
        })
    });
    return response.json();
}

/**
 * Get pending substitute requests
 * @param {number} teamId - Team ID (optional)
 * @returns {Promise<Array>} Pending requests
 */
export async function getPendingSubstituteRequests(teamId = null) {
    let url = '/rsvp/substitute_requests/pending';
    if (teamId) {
        url += `?team_id=${teamId}`;
    }
    const response = await fetch(url);
    return response.json();
}

/**
 * Accept substitute request
 * @param {number} requestId - Request ID
 * @returns {Promise<Object>} Accept result
 */
export async function acceptSubstituteRequest(requestId) {
    const response = await fetch(`/rsvp/substitute_request/${requestId}/accept`, {
        method: 'POST'
    });
    return response.json();
}

/**
 * Decline substitute request
 * @param {number} requestId - Request ID
 * @param {string} reason - Decline reason (optional)
 * @returns {Promise<Object>} Decline result
 */
export async function declineSubstituteRequest(requestId, reason = null) {
    const response = await fetch(`/rsvp/substitute_request/${requestId}/decline`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason })
    });
    return response.json();
}

/**
 * Cancel substitute request
 * @param {number} requestId - Request ID
 * @returns {Promise<Object>} Cancel result
 */
export async function cancelSubstituteRequest(requestId) {
    const response = await fetch(`/rsvp/substitute_request/${requestId}`, {
        method: 'DELETE'
    });
    return response.json();
}

/**
 * Assign substitute to team
 * @param {number} requestId - Request ID
 * @param {number} playerId - Player ID to assign
 * @returns {Promise<Object>} Assignment result
 */
export async function assignSubstitute(requestId, playerId) {
    const response = await fetch(`/rsvp/substitute_request/${requestId}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ player_id: playerId })
    });
    return response.json();
}

// =====================
// RSVP Notifications
// =====================

/**
 * Send RSVP reminder
 * @param {number} matchId - Match ID
 * @param {number} teamId - Team ID (optional, sends to all if not specified)
 * @returns {Promise<Object>} Send result
 */
export async function sendRSVPReminder(matchId, teamId = null) {
    const response = await fetch(`/rsvp/match/${matchId}/send_reminder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ team_id: teamId })
    });
    return response.json();
}

/**
 * Send substitute request notification
 * @param {number} requestId - Request ID
 * @returns {Promise<Object>} Send result
 */
export async function notifySubstitutePool(requestId) {
    const response = await fetch(`/rsvp/substitute_request/${requestId}/notify`, {
        method: 'POST'
    });
    return response.json();
}

// =====================
// RSVP Settings
// =====================

/**
 * Get RSVP settings for a team
 * @param {number} teamId - Team ID
 * @returns {Promise<Object>} RSVP settings
 */
export async function getTeamRSVPSettings(teamId) {
    const response = await fetch(`/rsvp/team/${teamId}/settings`);
    return response.json();
}

/**
 * Update RSVP settings for a team
 * @param {number} teamId - Team ID
 * @param {Object} settings - New settings
 * @returns {Promise<Object>} Update result
 */
export async function updateTeamRSVPSettings(teamId, settings) {
    const response = await fetch(`/rsvp/team/${teamId}/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(settings)
    });
    return response.json();
}

// =====================
// Admin RSVP Functions
// =====================

/**
 * Get RSVP overview for admin
 * @param {Object} filters - Filter options
 * @param {number} [filters.seasonId] - Season ID
 * @param {number} [filters.leagueId] - League ID
 * @returns {Promise<Object>} RSVP overview
 */
export async function getAdminRSVPOverview(filters = {}) {
    const params = new URLSearchParams();
    if (filters.seasonId) params.append('season_id', filters.seasonId);
    if (filters.leagueId) params.append('league_id', filters.leagueId);

    const response = await fetch(`/admin/rsvp/overview?${params}`);
    return response.json();
}

/**
 * Bulk update RSVP responses (admin)
 * @param {Array} updates - Array of RSVP updates
 * @returns {Promise<Object>} Bulk update result
 */
export async function bulkUpdateRSVPs(updates) {
    const response = await fetch('/admin/rsvp/bulk_update', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ updates })
    });
    return response.json();
}

/**
 * Export RSVP data
 * @param {Object} options - Export options
 * @param {string} [options.format] - Export format (csv, xlsx)
 * @param {number} [options.matchId] - Match ID
 * @param {number} [options.seasonId] - Season ID
 * @returns {Promise<Blob>} Export file
 */
export async function exportRSVPData(options = {}) {
    const params = new URLSearchParams();
    if (options.format) params.append('format', options.format);
    if (options.matchId) params.append('match_id', options.matchId);
    if (options.seasonId) params.append('season_id', options.seasonId);

    const response = await fetch(`/admin/rsvp/export?${params}`);
    return response.blob();
}

export default {
    // RSVP Submission
    submitRSVP,
    updateRSVP,
    cancelRSVP,

    // RSVP Retrieval
    getMatchRSVPStatus,
    getMatchRSVPs,
    getUserRSVPHistory,
    getTeamRSVPSummary,
    getPendingRSVPs,

    // Substitute Pool
    getSubstitutePool,
    joinSubstitutePool,
    leaveSubstitutePool,
    getLeagueSubstitutePool,

    // Substitute Requests
    createSubstituteRequest,
    getPendingSubstituteRequests,
    acceptSubstituteRequest,
    declineSubstituteRequest,
    cancelSubstituteRequest,
    assignSubstitute,

    // Notifications
    sendRSVPReminder,
    notifySubstitutePool,

    // Settings
    getTeamRSVPSettings,
    updateTeamRSVPSettings,

    // Admin
    getAdminRSVPOverview,
    bulkUpdateRSVPs,
    exportRSVPData
};
