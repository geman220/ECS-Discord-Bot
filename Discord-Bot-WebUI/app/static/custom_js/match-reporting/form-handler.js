/**
 * Match Reporting - Form Handler
 * Handles form data collection, validation, and event comparison
 *
 * @module match-reporting/form-handler
 */

import { getContainerId } from './player-options.js';
import { getInitialEvents } from './state.js';

/**
 * Map container base names to form field names
 * @param {string} baseName - Container base name
 * @returns {string} Form field name
 */
function getFormBaseName(baseName) {
    const nameMap = {
        'yellowCards': 'yellow_cards',
        'redCards': 'red_cards',
        'goalScorers': 'goalScorers',
        'assistProviders': 'assistProviders',
        'ownGoals': 'own_goals'
    };
    return nameMap[baseName] || baseName;
}

/**
 * Collect stat IDs that have been marked for removal
 * @param {string|number} matchId - Match ID
 * @param {string} eventType - Event type
 * @returns {Array} Array of removed stat IDs
 */
export function collectRemovedStatIds(matchId, eventType) {
    const containerId = getContainerId(eventType, matchId);
    const baseName = containerId.split('Container-')[0];
    const formBaseName = getFormBaseName(baseName);
    const removedIds = [];

    window.$(`#${containerId}`).find('.player-event-entry.to-be-removed').each(function () {
        const statId = window.$(this).find(`input[name="${formBaseName}-stat_id[]"]`).val();
        if (statId && statId.trim() !== '') {
            removedIds.push(statId);
        }
    });

    return removedIds;
}

/**
 * Collect removed own goal stat IDs
 * @param {string|number} matchId - Match ID
 * @returns {Array} Array of removed stat IDs
 */
export function collectRemovedOwnGoalIds(matchId) {
    const containerId = `ownGoalsContainer-${matchId}`;
    const removedIds = [];

    window.$(`#${containerId}`).find('.own-goal-event-entry.to-be-removed').each(function () {
        const statId = window.$(this).find('input[name="own_goals-stat_id[]"]').val();
        if (statId && statId.trim() !== '') {
            removedIds.push(statId);
        }
    });

    return removedIds;
}

/**
 * Get final events from the form
 * @param {string|number} matchId - Match ID
 * @param {string} eventType - Event type
 * @returns {Array} Array of event objects
 */
export function getFinalEvents(matchId, eventType) {
    const events = [];
    const containerId = getContainerId(eventType, matchId);
    const baseName = containerId.split('Container-')[0];
    const formBaseName = getFormBaseName(baseName);

    // Handle own goals differently since they use team_id instead of player_id
    if (eventType === 'own_goals') {
        window.$(`#${containerId}`).find('.own-goal-event-entry:not(.to-be-removed)').each(function () {
            const statId = window.$(this).find('input[name="own_goals-stat_id[]"]').val();
            const teamId = window.$(this).find('select[name="own_goals-team_id[]"]').val();
            const minute = window.$(this).find('input[name="own_goals-minute[]"]').val();
            const uniqueId = window.$(this).attr('data-unique-id');

            if (teamId) {
                events.push({
                    stat_id: statId || '',
                    team_id: teamId,
                    minute: minute || '',
                    unique_id: uniqueId
                });
            }
        });
    } else {
        // Only get visible entries (exclude ones marked for removal)
        window.$(`#${containerId}`).find('.player-event-entry:not(.to-be-removed)').each(function () {
            let statId = window.$(this).find(`input[name="${formBaseName}-stat_id[]"]`).val();
            let playerId = window.$(this).find(`select[name="${formBaseName}-player_id[]"]`).val();
            let minute = window.$(this).find(`input[name="${formBaseName}-minute[]"]`).val();
            const uniqueId = window.$(this).attr('data-unique-id');

            // Skip entries without player_id (which is required)
            if (!playerId) return;

            // Convert values to strings or null
            statId = statId ? String(statId) : null;
            playerId = playerId ? String(playerId) : null;
            minute = minute ? String(minute) : null;

            events.push({ unique_id: uniqueId, stat_id: statId, player_id: playerId, minute: minute });
        });
    }

    return events;
}

/**
 * Check if an event exists in an array
 * @param {Object} event - Event to check
 * @param {Array} eventsArray - Array to search
 * @returns {boolean} True if event exists
 */
export function eventExists(event, eventsArray) {
    // If element is marked for removal, treat as non-existent
    if (event.element && event.element.classList && event.element.classList.contains('to-be-removed')) {
        return false;
    }

    // If both have stat_id, compare them (for existing events)
    if (event.stat_id) {
        return eventsArray.some(e => e.stat_id && String(e.stat_id) === String(event.stat_id));
    }
    // For new events or when comparing by unique_id
    else if (event.unique_id) {
        return eventsArray.some(e => String(e.unique_id) === String(event.unique_id));
    }

    return false;
}

/**
 * Check if an own goal exists in a list
 * @param {Object} ownGoal - Own goal to check
 * @param {Array} ownGoalList - List to search
 * @returns {boolean} True if own goal exists
 */
export function ownGoalExists(ownGoal, ownGoalList) {
    return ownGoalList.some(og => {
        // Check by stat_id if both have it
        if (ownGoal.stat_id && og.stat_id) {
            return ownGoal.stat_id === og.stat_id;
        }
        // Check by unique_id if both have it
        if (ownGoal.unique_id && og.unique_id) {
            return ownGoal.unique_id === og.unique_id;
        }
        // Check by team_id and minute as fallback
        return ownGoal.team_id === og.team_id && ownGoal.minute === og.minute;
    });
}

/**
 * Calculate events to add and remove based on initial vs final state
 * @param {string|number} matchId - Match ID
 * @returns {Object} Object with add/remove arrays for each event type
 */
export function calculateEventChanges(matchId) {
    const initialEvents = getInitialEvents(matchId);

    // Get final events
    const finalGoals = getFinalEvents(matchId, 'goal_scorers');
    const finalAssists = getFinalEvents(matchId, 'assist_providers');
    const finalYellowCards = getFinalEvents(matchId, 'yellow_cards');
    const finalRedCards = getFinalEvents(matchId, 'red_cards');
    const finalOwnGoals = getFinalEvents(matchId, 'own_goals');

    // Get initial events
    const initialGoals = initialEvents.goals || [];
    const initialAssists = initialEvents.assists || [];
    const initialYellowCards = initialEvents.yellowCards || [];
    const initialRedCards = initialEvents.redCards || [];
    const initialOwnGoals = initialEvents.ownGoals || [];

    // Get removed IDs
    const removedGoalIds = collectRemovedStatIds(matchId, 'goal_scorers');
    const removedAssistIds = collectRemovedStatIds(matchId, 'assist_providers');
    const removedYellowCardIds = collectRemovedStatIds(matchId, 'yellow_cards');
    const removedRedCardIds = collectRemovedStatIds(matchId, 'red_cards');
    const removedOwnGoalIds = collectRemovedOwnGoalIds(matchId);

    // Events to add: in final but not in initial
    const goalsToAdd = finalGoals.filter(goal => !eventExists(goal, initialGoals));
    const assistsToAdd = finalAssists.filter(assist => !eventExists(assist, initialAssists));
    const yellowCardsToAdd = finalYellowCards.filter(card => !eventExists(card, initialYellowCards));
    const redCardsToAdd = finalRedCards.filter(card => !eventExists(card, initialRedCards));
    const ownGoalsToAdd = finalOwnGoals.filter(og => !ownGoalExists(og, initialOwnGoals));

    // Events to remove
    const goalsToRemove = buildRemovalList(removedGoalIds, initialGoals, finalGoals, eventExists);
    const assistsToRemove = buildRemovalList(removedAssistIds, initialAssists, finalAssists, eventExists);
    const yellowCardsToRemove = buildRemovalList(removedYellowCardIds, initialYellowCards, finalYellowCards, eventExists);
    const redCardsToRemove = buildRemovalList(removedRedCardIds, initialRedCards, finalRedCards, eventExists);
    const ownGoalsToRemove = buildRemovalList(removedOwnGoalIds, initialOwnGoals, finalOwnGoals, ownGoalExists);

    return {
        goalsToAdd, goalsToRemove,
        assistsToAdd, assistsToRemove,
        yellowCardsToAdd, yellowCardsToRemove,
        redCardsToAdd, redCardsToRemove,
        ownGoalsToAdd, ownGoalsToRemove
    };
}

/**
 * Build removal list from removed IDs and missing items
 * @param {Array} removedIds - Explicitly removed stat IDs
 * @param {Array} initialItems - Initial items
 * @param {Array} finalItems - Final items
 * @param {Function} existsFunc - Function to check if item exists
 * @returns {Array} Items to remove
 */
function buildRemovalList(removedIds, initialItems, finalItems, existsFunc) {
    const toRemove = [];

    // Add explicitly removed items
    removedIds.forEach(id => {
        const item = initialItems.find(i => i.stat_id === id);
        if (item) {
            toRemove.push(item);
        } else {
            toRemove.push({ stat_id: id });
        }
    });

    // Add items in initial but missing from final
    initialItems.forEach(item => {
        if (!existsFunc(item, finalItems) && !toRemove.some(r => r.stat_id === item.stat_id)) {
            toRemove.push(item);
        }
    });

    return toRemove;
}

// Backward compatibility exports
window.collectRemovedStatIds = collectRemovedStatIds;
window.collectRemovedOwnGoalIds = collectRemovedOwnGoalIds;
window.getFinalEvents = getFinalEvents;
window.eventExists = eventExists;
window.ownGoalExists = ownGoalExists;

export default {
    collectRemovedStatIds,
    collectRemovedOwnGoalIds,
    getFinalEvents,
    eventExists,
    ownGoalExists,
    calculateEventChanges
};
