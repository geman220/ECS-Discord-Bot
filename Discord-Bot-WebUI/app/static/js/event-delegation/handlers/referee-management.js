import { EventDelegation } from '../core.js';

/**
 * Referee Management Action Handlers
 * Handles referee assignments and scheduling
 */

// REFEREE MANAGEMENT ACTIONS
// ============================================================================

/**
 * Assign Referee Action
 * Assigns a referee to a match via form submission
 */
EventDelegation.register('assign-referee', function(element, e) {
    e.preventDefault();

    const matchId = document.getElementById('matchId')?.value;
    const refId = document.getElementById('refSelect')?.value;

    if (!matchId || !refId) {
        console.error('[assign-referee] Missing match ID or referee ID');
        return;
    }

    // Call global function if exists
    if (typeof assignReferee === 'function') {
        assignReferee(e);
    } else {
        console.error('[assign-referee] assignReferee function not found');
    }
});

/**
 * Remove Referee Action
 * Removes a referee from a match
 */
EventDelegation.register('remove-referee', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId || document.getElementById('matchId')?.value;

    if (!matchId) {
        console.error('[remove-referee] Missing match ID');
        return;
    }

    // Call global function if exists
    if (typeof removeReferee === 'function') {
        removeReferee();
    } else {
        console.error('[remove-referee] removeReferee function not found');
    }
});

/**
 * Refresh Calendar Action
 * Reloads calendar events and available referees list
 */
EventDelegation.register('refresh-calendar', function(element, e) {
    e.preventDefault();

    // Check for calendar-specific refresh function
    if (typeof loadCalendarEvents === 'function' && typeof fetchAvailableReferees === 'function') {
        loadCalendarEvents();
        // Get calendar instance if available
        if (window.calendarInstance) {
            fetchAvailableReferees(window.calendarInstance.getDate());
        } else {
            fetchAvailableReferees(new Date());
        }
    } else if (typeof window.refreshCalendar === 'function') {
        window.refreshCalendar();
    } else {
        console.error('[refresh-calendar] No refresh function available');
    }
});

/**
 * View Referee Profile Action
 * Opens modal or page with referee details
 */
EventDelegation.register('view-referee-profile', function(element, e) {
    e.preventDefault();

    const refereeId = element.dataset.refereeId;

    if (!refereeId) {
        console.error('[view-referee-profile] Missing referee ID');
        return;
    }

    if (typeof viewRefereeProfile === 'function') {
        viewRefereeProfile(refereeId);
    } else {
        // Fallback: navigate to referee profile page
        const profileUrl = element.dataset.profileUrl || `/admin/referee/${refereeId}`;
        window.location.href = profileUrl;
    }
});

/**
 * Update Referee Status Action
 * Updates referee availability status
 */
EventDelegation.register('update-referee-status', function(element, e) {
    e.preventDefault();

    const refereeId = element.dataset.refereeId;
    const status = element.dataset.status;

    if (!refereeId || !status) {
        console.error('[update-referee-status] Missing referee ID or status');
        return;
    }

    if (typeof updateRefereeStatus === 'function') {
        updateRefereeStatus(refereeId, status);
    } else {
        console.error('[update-referee-status] updateRefereeStatus function not found');
    }
});

// ============================================================================

console.log('[EventDelegation] Referee management handlers loaded');
