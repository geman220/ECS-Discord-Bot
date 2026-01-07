'use strict';

/**
 * Sync Review State
 * Module state management
 * @module sync-review/state
 */

// Module state
let syncData = {};
let resolutions = {
    multiOrders: {},
    newPlayers: {},
    emailMismatches: {}
};
let taskId = '';
let playersWithOrders = new Set();
let searchTimeout;

/**
 * Get sync data
 * @returns {Object}
 */
export function getSyncData() {
    return syncData;
}

/**
 * Set sync data
 * @param {Object} data
 */
export function setSyncData(data) {
    syncData = data;
}

/**
 * Get resolutions
 * @returns {Object}
 */
export function getResolutions() {
    return resolutions;
}

/**
 * Set resolution for multi-orders
 * @param {string} issueId
 * @param {Array} assignments
 */
export function setMultiOrderResolution(issueId, assignments) {
    resolutions.multiOrders[issueId] = assignments;
}

/**
 * Set resolution for new players
 * @param {string} issueId
 * @param {Object} resolution
 */
export function setNewPlayerResolution(issueId, resolution) {
    resolutions.newPlayers[issueId] = resolution;
}

/**
 * Set resolution for email mismatches
 * @param {string} issueId
 * @param {Object} resolution
 */
export function setEmailMismatchResolution(issueId, resolution) {
    resolutions.emailMismatches[issueId] = resolution;
}

/**
 * Get task ID
 * @returns {string}
 */
export function getTaskId() {
    return taskId;
}

/**
 * Set task ID
 * @param {string} id
 */
export function setTaskId(id) {
    taskId = id;
}

/**
 * Get players with orders set
 * @returns {Set}
 */
export function getPlayersWithOrders() {
    return playersWithOrders;
}

/**
 * Get search timeout
 * @returns {number|undefined}
 */
export function getSearchTimeout() {
    return searchTimeout;
}

/**
 * Set search timeout
 * @param {number} timeout
 */
export function setSearchTimeout(timeout) {
    searchTimeout = timeout;
}

/**
 * Clear search timeout
 */
export function clearSearchTimeoutRef() {
    clearTimeout(searchTimeout);
}

/**
 * Get CSRF token
 * @returns {string}
 */
export function getCSRFToken() {
    return window._syncReviewCsrfToken || '';
}

/**
 * Set CSRF token
 * @param {string} token
 */
export function setCSRFToken(token) {
    window._syncReviewCsrfToken = token;
}

/**
 * Calculate total issues
 * @returns {number}
 */
export function getTotalIssues() {
    return syncData.flagged_multi_orders?.length || 0 +
           syncData.new_players?.length || 0 +
           syncData.email_mismatch_players?.length || 0;
}

/**
 * Calculate resolved issues
 * @returns {number}
 */
export function getResolvedIssues() {
    return Object.keys(resolutions.multiOrders).length +
           Object.keys(resolutions.newPlayers).length +
           Object.keys(resolutions.emailMismatches).length;
}
