/**
 * Match Reporting - State Management
 * Handles match data, player choices, and initial events tracking
 *
 * @module match-reporting/state
 */

// Global state initialization
if (typeof window._reportMatchInitialized === 'undefined') {
    window._reportMatchInitialized = false;
}

if (typeof window._editMatchButtonsSetup === 'undefined') {
    window._editMatchButtonsSetup = false;
}

// Initialize playerChoices if not defined
if (typeof window.playerChoices === 'undefined') {
    window.playerChoices = {};
}

// Define initialEvents as an object to store initial events per matchId
if (typeof window.initialEvents === 'undefined') {
    window.initialEvents = {};
}

/**
 * Mark report match as initialized
 */
export function setInitialized() {
    window._reportMatchInitialized = true;
}

/**
 * Check if report match is initialized
 * @returns {boolean}
 */
export function isInitialized() {
    return window._reportMatchInitialized === true;
}

/**
 * Mark edit buttons as setup
 */
export function setEditButtonsSetup() {
    window._editMatchButtonsSetup = true;
}

/**
 * Check if edit buttons are setup
 * @returns {boolean}
 */
export function areEditButtonsSetup() {
    return window._editMatchButtonsSetup === true;
}

/**
 * Get player choices for a match
 * @param {string|number} matchId - Match ID
 * @returns {Object} Player choices by team
 */
export function getPlayerChoices(matchId) {
    return window.playerChoices[matchId] || {};
}

/**
 * Set player choices for a match
 * @param {string|number} matchId - Match ID
 * @param {Object} choices - Player choices by team
 */
export function setPlayerChoices(matchId, choices) {
    window.playerChoices[matchId] = choices;
}

/**
 * Initialize player choices for a match from data
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Match data containing team players
 */
export function initializePlayerChoices(matchId, data) {
    window.playerChoices[matchId] = {};

    // Add home team players
    if (data.home_team && data.home_team.players) {
        const homeTeamName = data.home_team.name || 'Home Team';
        window.playerChoices[matchId][homeTeamName] = {};
        data.home_team.players.forEach(player => {
            window.playerChoices[matchId][homeTeamName][player.id] = player.name;
        });
    }

    // Add away team players
    if (data.away_team && data.away_team.players) {
        const awayTeamName = data.away_team.name || 'Away Team';
        window.playerChoices[matchId][awayTeamName] = {};
        data.away_team.players.forEach(player => {
            window.playerChoices[matchId][awayTeamName][player.id] = player.name;
        });
    }

    return window.playerChoices[matchId];
}

/**
 * Get initial events for a match
 * @param {string|number} matchId - Match ID
 * @returns {Object} Initial events
 */
export function getInitialEvents(matchId) {
    return window.initialEvents[matchId] || {
        goals: [],
        assists: [],
        yellowCards: [],
        redCards: [],
        ownGoals: []
    };
}

/**
 * Set initial events for a match
 * @param {string|number} matchId - Match ID
 * @param {Object} events - Initial events object
 */
export function setInitialEvents(matchId, events) {
    window.initialEvents[matchId] = events;
}

/**
 * Initialize initial events from match data
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Match data
 */
export function initializeInitialEvents(matchId, data) {
    const goal_scorers = data.goal_scorers || [];
    const assist_providers = data.assist_providers || [];
    const yellow_cards = data.yellow_cards || [];
    const red_cards = data.red_cards || [];
    const own_goals = data.own_goals || [];

    window.initialEvents[matchId] = {
        goals: goal_scorers.map(goal => ({
            unique_id: String(goal.id),
            stat_id: String(goal.id),
            player_id: String(goal.player_id),
            minute: goal.minute || null
        })),
        assists: assist_providers.map(assist => ({
            unique_id: String(assist.id),
            stat_id: String(assist.id),
            player_id: String(assist.player_id),
            minute: assist.minute || null
        })),
        yellowCards: yellow_cards.map(card => ({
            unique_id: String(card.id),
            stat_id: String(card.id),
            player_id: String(card.player_id),
            minute: card.minute || null
        })),
        redCards: red_cards.map(card => ({
            unique_id: String(card.id),
            stat_id: String(card.id),
            player_id: String(card.player_id),
            minute: card.minute || null
        })),
        ownGoals: own_goals.map(ownGoal => ({
            unique_id: String(ownGoal.id),
            stat_id: String(ownGoal.id),
            team_id: String(ownGoal.team_id),
            minute: ownGoal.minute || null
        }))
    };

    return window.initialEvents[matchId];
}

/**
 * Get current match data
 * @returns {Object|null} Current match data
 */
export function getCurrentMatchData() {
    return window.currentMatchData || null;
}

/**
 * Set current match data
 * @param {Object} data - Match data
 */
export function setCurrentMatchData(data) {
    window.currentMatchData = data;
}

export default {
    setInitialized,
    isInitialized,
    setEditButtonsSetup,
    areEditButtonsSetup,
    getPlayerChoices,
    setPlayerChoices,
    initializePlayerChoices,
    getInitialEvents,
    setInitialEvents,
    initializeInitialEvents,
    getCurrentMatchData,
    setCurrentMatchData
};
