import { EventDelegation } from '../core.js';

/**
 * Match Reporting Action Handlers
 * Handles goals, assists, cards, and match events
 */

// MATCH REPORTING ACTIONS
// ============================================================================

/**
 * Edit Match Report Action
 * Opens modal to edit/create match report
 */
EventDelegation.register('edit-match-report', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[edit-match-report] Missing match ID');
        return;
    }

    // Call the global function that handles the edit button click
    if (typeof handleEditButtonClick === 'function') {
        handleEditButtonClick(matchId);
    } else {
        console.error('[edit-match-report] handleEditButtonClick function not found');
    }
});

/**
 * Add Goal Action
 * Adds goal scorer to match report
 */
EventDelegation.register('add-goal', function(element, e) {
    e.preventDefault();

    // Extract matchId from onclick attribute or data attribute
    let matchId = element.dataset.matchId;
    if (!matchId) {
        const onclickAttr = element.getAttribute('onclick');
        if (onclickAttr) {
            const match = onclickAttr.match(/'([^']+)'/);
            if (match) matchId = match[1];
        }
    }

    if (!matchId) {
        console.error('[add-goal] Missing match ID');
        return;
    }

    const containerId = `goalScorersContainer-${matchId}`;

    if (typeof window.addEvent === 'function') {
        window.addEvent(matchId, containerId);
    } else {
        console.error('[add-goal] addEvent function not found');
    }
});

/**
 * Add Assist Action
 * Adds assist provider to match report
 */
EventDelegation.register('add-assist', function(element, e) {
    e.preventDefault();

    // Extract matchId from onclick attribute or data attribute
    let matchId = element.dataset.matchId;
    if (!matchId) {
        const onclickAttr = element.getAttribute('onclick');
        if (onclickAttr) {
            const match = onclickAttr.match(/'([^']+)'/);
            if (match) matchId = match[1];
        }
    }

    if (!matchId) {
        console.error('[add-assist] Missing match ID');
        return;
    }

    const containerId = `assistProvidersContainer-${matchId}`;

    if (typeof window.addEvent === 'function') {
        window.addEvent(matchId, containerId);
    } else {
        console.error('[add-assist] addEvent function not found');
    }
});

/**
 * Add Yellow Card Action
 * Adds yellow card to match report
 */
EventDelegation.register('add-yellow-card', function(element, e) {
    e.preventDefault();

    // Extract matchId from onclick attribute or data attribute
    let matchId = element.dataset.matchId;
    if (!matchId) {
        const onclickAttr = element.getAttribute('onclick');
        if (onclickAttr) {
            const match = onclickAttr.match(/'([^']+)'/);
            if (match) matchId = match[1];
        }
    }

    if (!matchId) {
        console.error('[add-yellow-card] Missing match ID');
        return;
    }

    const containerId = `yellowCardsContainer-${matchId}`;

    if (typeof window.addEvent === 'function') {
        window.addEvent(matchId, containerId);
    } else {
        console.error('[add-yellow-card] addEvent function not found');
    }
});

/**
 * Add Red Card Action
 * Adds red card to match report
 */
EventDelegation.register('add-red-card', function(element, e) {
    e.preventDefault();

    // Extract matchId from onclick attribute or data attribute
    let matchId = element.dataset.matchId;
    if (!matchId) {
        const onclickAttr = element.getAttribute('onclick');
        if (onclickAttr) {
            const match = onclickAttr.match(/'([^']+)'/);
            if (match) matchId = match[1];
        }
    }

    if (!matchId) {
        console.error('[add-red-card] Missing match ID');
        return;
    }

    const containerId = `redCardsContainer-${matchId}`;

    if (typeof window.addEvent === 'function') {
        window.addEvent(matchId, containerId);
    } else {
        console.error('[add-red-card] addEvent function not found');
    }
});

/**
 * Remove Event Action (Generic)
 * Removes any event entry (goal, assist, card) from match report
 */
EventDelegation.register('remove-event', function(element, e) {
    e.preventDefault();

    if (typeof window.removeEvent === 'function') {
        window.removeEvent(element);
    } else {
        console.error('[remove-event] removeEvent function not found');
    }
});

/**
 * Remove Own Goal Action
 * Removes own goal from match report
 */
EventDelegation.register('remove-own-goal', function(element, e) {
    e.preventDefault();

    if (typeof window.removeEvent === 'function') {
        window.removeEvent(element);
    } else {
        console.error('[remove-own-goal] removeEvent function not found');
    }
});

// ============================================================================

console.log('[EventDelegation] Match reporting handlers loaded');
