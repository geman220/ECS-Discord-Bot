import { EventDelegation } from '../../event-delegation/core.js';

/**
 * Match Management Action Handlers
 * Handles task scheduling, match verification, and match editing
 */
// Uses global EventDelegation from core.js

// MATCH MANAGEMENT ACTIONS
// ============================================================================

/**
 * Show Task Info Action
 * Displays detailed information about a scheduled task
 */
EventDelegation.register('show-task-info', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;
    const taskType = element.dataset.taskType;
    const taskDataStr = element.dataset.taskData;

    if (!taskId || !taskType) {
        console.error('[show-task-info] Missing required data attributes');
        return;
    }

    let taskData;
    try {
        taskData = taskDataStr ? JSON.parse(taskDataStr) : {};
    } catch (err) {
        console.error('[show-task-info] Failed to parse task data:', err);
        taskData = {};
    }

    if (typeof showTaskInfo === 'function') {
        window.showTaskInfo(taskId, taskType, taskData);
    } else {
        console.error('[show-task-info] Function not found');
    }
});

/**
 * Revoke Task Action
 * Cancels a scheduled task (thread creation, reporting, etc.)
 */
EventDelegation.register('revoke-task', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;
    const matchId = element.dataset.matchId;
    const taskType = element.dataset.taskType;

    if (!taskId || !matchId || !taskType) {
        console.error('[revoke-task] Missing required data attributes');
        return;
    }

    if (typeof revokeTask === 'function') {
        window.revokeTask(taskId, matchId, taskType);
    } else {
        console.error('[revoke-task] Function not found');
    }
});

/**
 * Reschedule Task Action
 * Re-schedules a task to run at a different time
 */
EventDelegation.register('reschedule-task', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const taskType = element.dataset.taskType;

    if (!matchId || !taskType) {
        console.error('[reschedule-task] Missing required data attributes');
        return;
    }

    if (typeof rescheduleTask === 'function') {
        window.rescheduleTask(matchId, taskType);
    } else {
        console.error('[reschedule-task] Function not found');
    }
});

/**
 * Refresh Tasks Action
 * Manually refreshes task status for all matches
 */
EventDelegation.register('refresh-tasks', function(element, e) {
    e.preventDefault();

    if (typeof loadAllTaskDetails === 'function') {
        window.loadAllTaskDetails();
    } else if (typeof refreshStatuses === 'function') {
        window.refreshStatuses();
    } else {
        console.error('[refresh-tasks] No refresh function found');
    }
});

/**
 * Toggle Historical Matches Action
 * Shows/hides historical matches section
 */
EventDelegation.register('toggle-historical', function(element, e) {
    e.preventDefault();

    const targetId = element.dataset.target;
    if (!targetId) {
        console.error('[toggle-historical] Missing target ID');
        return;
    }

    const target = document.querySelector(targetId);
    if (target && window.bootstrap) {
        const collapse = window.bootstrap.Collapse.getOrCreateInstance(target);
        collapse.toggle();
    }
});

/**
 * Schedule Match Action
 * Schedules all tasks for a match (thread + reporting)
 */
EventDelegation.register('schedule-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[schedule-match] Missing match ID');
        return;
    }

    if (typeof scheduleMatch === 'function') {
        scheduleMatch(matchId);
    } else {
        console.error('[schedule-match] Function not found');
    }
});

/**
 * Verify Match Action
 * Opens match verification modal/page
 */
EventDelegation.register('verify-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[verify-match] Missing match ID');
        return;
    }

    // Navigate to verification page or open modal
    if (typeof verifyMatch === 'function') {
        verifyMatch(matchId);
    } else {
        // Fallback: navigate to verification page
        const verifyUrl = element.dataset.verifyUrl || `/admin/match_verification/${matchId}`;
        window.location.href = verifyUrl;
    }
});

/**
 * Edit Match Action
 * Opens match editing modal/page
 */
EventDelegation.register('edit-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[edit-match] Missing match ID');
        return;
    }

    if (typeof editMatch === 'function') {
        editMatch(matchId);
    } else {
        console.error('[edit-match] Function not found');
    }
});

// ============================================================================
// LIVE REPORTING ACTIONS
// ============================================================================

/**
 * Force Sync Dashboard
 */
EventDelegation.register('force-sync', function(element, e) {
    e.preventDefault();
    if (typeof window.forceSync === 'function') {
        window.forceSync();
    }
}, { preventDefault: true });

/**
 * Refresh Dashboard
 */
EventDelegation.register('refresh-dashboard', function(element, e) {
    e.preventDefault();
    if (typeof window.refreshDashboard === 'function') {
        window.refreshDashboard();
    }
}, { preventDefault: true });

/**
 * Stop Session
 */
EventDelegation.register('stop-session', function(element, e) {
    e.preventDefault();
    const sessionId = element.dataset.sessionId;
    if (typeof window.stopSession === 'function') {
        window.stopSession(sessionId);
    }
}, { preventDefault: true });

// ============================================================================
// WALLET MANAGEMENT ACTIONS
// ============================================================================

/**
 * Bulk Generate Passes
 */
EventDelegation.register('bulk-generate-wallet-passes', function(element, e) {
    e.preventDefault();
    if (typeof window.bulkGeneratePasses === 'function') {
        window.bulkGeneratePasses();
    }
}, { preventDefault: true });

/**
 * Check Player Eligibility
 */
EventDelegation.register('check-player-eligibility', function(element, e) {
    e.preventDefault();
    const playerId = element.dataset.playerId;
    if (typeof window.checkPlayerEligibility === 'function') {
        window.checkPlayerEligibility(playerId);
    }
}, { preventDefault: true });

// ============================================================================
// MLS MATCH ACTIONS
// ============================================================================

/**
 * Schedule All Matches
 * Schedules all MLS matches at once
 */
EventDelegation.register('schedule-all-matches', function(element, e) {
    e.preventDefault();
    if (typeof window.scheduleAllMatches === 'function') {
        window.scheduleAllMatches();
    }
}, { preventDefault: true });

/**
 * Auto Assign Playoffs
 * Automatically assigns teams to playoff matches based on standings
 */
EventDelegation.register('auto-assign-playoffs', function(element, e) {
    e.preventDefault();
    const leagueId = element.dataset.leagueId;
    if (typeof window.autoAssignPlayoffs === 'function') {
        window.autoAssignPlayoffs(leagueId);
    }
}, { preventDefault: true });

// ============================================================================
// GENERIC UTILITY ACTIONS
// ============================================================================

/**
 * Reload Page
 * Simple page refresh action
 */
EventDelegation.register('reload-page', function(element, e) {
    e.preventDefault();
    location.reload();
}, { preventDefault: true });

/**
 * Show Discord Channel Info
 * Displays info alert about Discord channel
 */
EventDelegation.register('show-discord-channel-info', function(element, e) {
    e.preventDefault();
    alert('Check Discord #pl-new-players channel for notifications');
}, { preventDefault: true });

// ============================================================================

console.log('[EventDelegation] Match management handlers loaded');
