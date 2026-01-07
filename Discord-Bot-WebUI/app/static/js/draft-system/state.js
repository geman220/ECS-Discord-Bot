/**
 * Draft System - State Management
 * Shared state for the draft system
 *
 * @module draft-system/state
 */

/**
 * @typedef {Object} DraftState
 * @property {string|null} leagueName - Current league name
 * @property {Object|null} socket - Socket.io connection
 * @property {string|null} currentPlayerId - Currently selected player
 * @property {boolean} isConnected - Socket connection status
 * @property {Object} searchState - Search/filter state
 */

// Initialize global state if not exists
if (typeof window._draftSystemState === 'undefined') {
    window._draftSystemState = {
        leagueName: null,
        socket: null,
        currentPlayerId: null,
        isConnected: false,
        searchState: {
            query: '',
            positionFilter: 'all',
            statusFilter: 'all'
        }
    };
}

/**
 * Get draft system state
 * @returns {DraftState}
 */
export function getState() {
    return window._draftSystemState;
}

/**
 * Set league name
 * @param {string} name
 */
export function setLeagueName(name) {
    window._draftSystemState.leagueName = name;
}

/**
 * Get league name
 * @returns {string|null}
 */
export function getLeagueName() {
    return window._draftSystemState.leagueName;
}

/**
 * Set socket connection
 * @param {Object} socket
 */
export function setSocket(socket) {
    window._draftSystemState.socket = socket;
}

/**
 * Get socket connection
 * @returns {Object|null}
 */
export function getSocket() {
    return window._draftSystemState.socket;
}

/**
 * Set connection status
 * @param {boolean} status
 */
export function setConnected(status) {
    window._draftSystemState.isConnected = status;
}

/**
 * Check if connected
 * @returns {boolean}
 */
export function isConnected() {
    return window._draftSystemState.isConnected;
}

/**
 * Set current player ID
 * @param {string|null} playerId
 */
export function setCurrentPlayerId(playerId) {
    window._draftSystemState.currentPlayerId = playerId;
}

/**
 * Get current player ID
 * @returns {string|null}
 */
export function getCurrentPlayerId() {
    return window._draftSystemState.currentPlayerId;
}

/**
 * Update search state
 * @param {Object} updates
 */
export function updateSearchState(updates) {
    Object.assign(window._draftSystemState.searchState, updates);
}

/**
 * Get search state
 * @returns {Object}
 */
export function getSearchState() {
    return window._draftSystemState.searchState;
}

export default {
    getState,
    setLeagueName,
    getLeagueName,
    setSocket,
    getSocket,
    setConnected,
    isConnected,
    setCurrentPlayerId,
    getCurrentPlayerId,
    updateSearchState,
    getSearchState
};
