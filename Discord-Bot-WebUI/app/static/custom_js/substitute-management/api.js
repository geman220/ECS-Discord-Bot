/**
 * Substitute Management - API
 * Server communication functions
 *
 * @module substitute-management/api
 */

'use strict';

import { API, REQUEST_TIMEOUT } from './config.js';

/**
 * Fetch with timeout and abort controller
 * @param {string} url - Request URL
 * @param {Object} options - Fetch options
 * @param {number} timeout - Timeout in ms
 * @returns {Promise<Object>} Response data
 */
async function fetchWithTimeout(url, options = {}, timeout = REQUEST_TIMEOUT) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        ...options.headers
      }
    });

    clearTimeout(timeoutId);
    return await response.json();
  } catch (error) {
    clearTimeout(timeoutId);
    throw error;
  }
}

/**
 * Fetch league statistics
 * @param {string} league - League type
 * @returns {Promise<Object>} Statistics data
 */
export async function fetchLeagueStatistics(league) {
  return fetchWithTimeout(API.pool.statistics(league), { method: 'GET' });
}

/**
 * Fetch recent activity history
 * @param {string} league - League type
 * @returns {Promise<Object>} History data
 */
export async function fetchRecentActivity(league) {
  return fetchWithTimeout(API.pool.history(league), { method: 'GET' });
}

/**
 * Fetch substitute requests for a league
 * @param {string} league - League type
 * @returns {Promise<Object>} Requests data
 */
export async function fetchSubstituteRequests(league) {
  return fetchWithTimeout(API.pool.requests(league), { method: 'GET' });
}

/**
 * Fetch substitute requests for a specific match
 * @param {string|number} matchId - Match ID
 * @returns {Promise<Object>} Requests data
 */
export async function fetchMatchSubstituteRequests(matchId) {
  return fetchWithTimeout(API.match.requests(matchId), { method: 'GET' });
}

/**
 * Fetch request details
 * @param {string} league - League type
 * @param {string|number} requestId - Request ID
 * @returns {Promise<Object>} Request details
 */
export async function fetchRequestDetails(league, requestId) {
  return fetchWithTimeout(API.request.detail(league, requestId), { method: 'GET' });
}

/**
 * Resend substitute request notifications
 * @param {string} league - League type
 * @param {string|number} requestId - Request ID
 * @returns {Promise<Object>} Response data
 */
export async function resendRequest(league, requestId) {
  const response = await fetch(API.request.resend(league, requestId), {
    method: 'POST',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  });
  return { response, data: await response.json() };
}

/**
 * Cancel a substitute request
 * @param {string} league - League type
 * @param {string|number} requestId - Request ID
 * @returns {Promise<Object>} Response data
 */
export async function cancelRequest(league, requestId) {
  const response = await fetch(API.request.cancel(league, requestId), {
    method: 'POST',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  });
  return response.json();
}

/**
 * Delete a substitute request
 * @param {string|number} requestId - Request ID
 * @returns {Promise<Object>} Response data
 */
export async function deleteRequest(requestId) {
  const response = await fetch(API.request.delete(requestId), {
    method: 'DELETE',
    headers: { 'X-Requested-With': 'XMLHttpRequest' }
  });
  return response.json();
}

/**
 * Assign a substitute to a request
 * @param {string} league - League type
 * @param {string|number} requestId - Request ID
 * @param {string|number} playerId - Player ID
 * @param {string} position - Position assigned
 * @param {string} notes - Additional notes
 * @returns {Promise<Object>} Response data
 */
export async function assignSubstituteToRequest(league, requestId, playerId, position = '', notes = '') {
  const response = await fetch(API.request.assign(league, requestId), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'XMLHttpRequest'
    },
    body: JSON.stringify({
      player_id: playerId,
      position_assigned: position,
      notes: notes
    })
  });
  return response.json();
}

export default {
  fetchWithTimeout,
  fetchLeagueStatistics,
  fetchRecentActivity,
  fetchSubstituteRequests,
  fetchMatchSubstituteRequests,
  fetchRequestDetails,
  resendRequest,
  cancelRequest,
  deleteRequest,
  assignSubstituteToRequest
};
