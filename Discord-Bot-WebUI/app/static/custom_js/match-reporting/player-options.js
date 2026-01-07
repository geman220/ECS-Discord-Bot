/**
 * Match Reporting - Player/Team Options
 * Generates player and team select options for match events
 *
 * @module match-reporting/player-options
 */

import { getPlayerChoices, getCurrentMatchData } from './state.js';

/**
 * Create player options grouped by team for a select element
 * @param {string|number} matchId - Match ID
 * @returns {string} HTML string of option elements
 */
export function createPlayerOptions(matchId) {
    let options = '<option value="" selected>Select a player</option>';
    const playerChoices = getPlayerChoices(matchId);

    if (playerChoices && Object.keys(playerChoices).length > 0) {
        for (const teamName in playerChoices) {
            options += `<optgroup label="${teamName}">`;
            for (const playerId in playerChoices[teamName]) {
                options += `<option value="${playerId}">${playerChoices[teamName][playerId]}</option>`;
            }
            options += `</optgroup>`;
        }
    }
    return options;
}

/**
 * Create team options for own goals select element
 * @param {string|number} matchId - Match ID
 * @returns {string} HTML string of option elements
 */
export function createTeamOptions(matchId) {
    let options = '<option value="" selected>Select a team</option>';

    // Try to get team info from stored match data
    const currentMatchData = getCurrentMatchData();
    if (currentMatchData && currentMatchData.matchId == matchId) {
        const homeTeamId = currentMatchData.home_team ? currentMatchData.home_team.id : null;
        const awayTeamId = currentMatchData.away_team ? currentMatchData.away_team.id : null;
        const homeTeamName = currentMatchData.home_team_name || 'Home Team';
        const awayTeamName = currentMatchData.away_team_name || 'Away Team';

        if (homeTeamId) options += `<option value="${homeTeamId}">${homeTeamName}</option>`;
        if (awayTeamId) options += `<option value="${awayTeamId}">${awayTeamName}</option>`;
    } else {
        // Fallback to window variables
        const homeTeamName = window['homeTeamName_' + matchId] || 'Home Team';
        const awayTeamName = window['awayTeamName_' + matchId] || 'Away Team';
        const homeTeamId = window['homeTeamId_' + matchId];
        const awayTeamId = window['awayTeamId_' + matchId];

        if (homeTeamId) options += `<option value="${homeTeamId}">${homeTeamName}</option>`;
        if (awayTeamId) options += `<option value="${awayTeamId}">${awayTeamName}</option>`;
    }

    return options;
}

/**
 * Get the container ID for a specific event type
 * @param {string} eventType - Event type (goal_scorers, assist_providers, etc.)
 * @param {string|number} matchId - Match ID
 * @returns {string} Container element ID
 */
export function getContainerId(eventType, matchId) {
    const containerMap = {
        'goal_scorers': 'goalScorersContainer-',
        'assist_providers': 'assistProvidersContainer-',
        'yellow_cards': 'yellowCardsContainer-',
        'red_cards': 'redCardsContainer-',
        'own_goals': 'ownGoalsContainer-'
    };

    return (containerMap[eventType] || '') + matchId;
}

/**
 * Get team data for a match (for own goals)
 * @param {string|number} matchId - Match ID
 * @returns {Object} Team data with names and IDs
 */
export function getTeamData(matchId) {
    let homeTeamName = window['homeTeamName_' + matchId];
    let awayTeamName = window['awayTeamName_' + matchId];
    let homeTeamId = window['homeTeamId_' + matchId];
    let awayTeamId = window['awayTeamId_' + matchId];

    // If not available, try to get from stored match data
    const currentMatchData = getCurrentMatchData();
    if (currentMatchData && currentMatchData.matchId == matchId) {
        homeTeamName = currentMatchData.home_team_name || homeTeamName;
        awayTeamName = currentMatchData.away_team_name || awayTeamName;
        homeTeamId = currentMatchData.home_team ? currentMatchData.home_team.id : homeTeamId;
        awayTeamId = currentMatchData.away_team ? currentMatchData.away_team.id : awayTeamId;
    }

    return {
        homeTeamName: homeTeamName || 'Home Team',
        awayTeamName: awayTeamName || 'Away Team',
        homeTeamId: homeTeamId,
        awayTeamId: awayTeamId
    };
}

export default {
    createPlayerOptions,
    createTeamOptions,
    getContainerId,
    getTeamData
};
