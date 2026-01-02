import { EventDelegation } from '../core.js';

/**
 * Match Management Action Handlers
 * Handles task scheduling, match verification, and match editing
 */

// MATCH MANAGEMENT ACTIONS
// ============================================================================

/**
 * Show Task Info Action
 * Displays detailed information about a scheduled task
 */
window.EventDelegation.register('show-task-info', function(element, e) {
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
window.EventDelegation.register('revoke-task', function(element, e) {
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
window.EventDelegation.register('reschedule-task', function(element, e) {
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

// ============================================================================
// TASK ACTIONS - Handled by monitoring-handlers.js
// ============================================================================
// Removed: refresh-tasks (duplicate of monitoring-handlers.js)

/**
 * Toggle Historical Matches Action
 * Shows/hides historical matches section
 */
window.EventDelegation.register('toggle-historical', function(element, e) {
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

// ============================================================================
// SCHEDULE MATCH - Handled by admin-match-operations.js
// ============================================================================
// Note: 'schedule-match' handler moved to admin-match-operations.js

/**
 * Verify Match Action
 * Opens match verification modal/page
 */
window.EventDelegation.register('verify-match', function(element, e) {
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

// ============================================================================
// EDIT MATCH - Handled by admin-match-operations.js
// ============================================================================
// Note: 'edit-match' handler moved to admin-match-operations.js

// ============================================================================
// LIVE REPORTING ACTIONS
// ============================================================================

/**
 * Force Sync Dashboard
 */
window.EventDelegation.register('force-sync', function(element, e) {
    e.preventDefault();
    if (typeof window.forceSync === 'function') {
        window.forceSync();
    }
}, { preventDefault: true });

/**
 * Refresh Dashboard
 */
window.EventDelegation.register('refresh-dashboard', function(element, e) {
    e.preventDefault();
    if (typeof window.refreshDashboard === 'function') {
        window.refreshDashboard();
    }
}, { preventDefault: true });

/**
 * Stop Session
 */
window.EventDelegation.register('stop-session', function(element, e) {
    e.preventDefault();
    const sessionId = element.dataset.sessionId;
    if (typeof window.stopSession === 'function') {
        window.stopSession(sessionId);
    }
}, { preventDefault: true });

// ============================================================================
// WALLET MANAGEMENT ACTIONS
// ============================================================================

// ============================================================================
// WALLET PASS ACTIONS - Handled by admin-wallet.js
// ============================================================================
// Removed: bulk-generate-wallet-passes (duplicate of admin-wallet.js)
// Removed: check-player-eligibility (duplicate of admin-wallet.js)

// ============================================================================
// MLS MATCH ACTIONS - Handled by mls-handlers.js
// ============================================================================
// Removed: schedule-all-matches (duplicate - use mls-schedule-all-matches for MLS)
// Removed: auto-assign-playoffs (duplicate of admin-league-management.js)

// ============================================================================
// SORTING AND FILTERING ACTIONS
// ============================================================================

/**
 * Change Sort Action
 * Updates URL with sort parameter and reloads page
 * Usage: <a data-action="change-sort" data-sort-type="name">Sort by Name</a>
 */
window.EventDelegation.register('change-sort', function(element, e) {
    e.preventDefault();
    const sortType = element.dataset.sortType;
    const currentUrl = new URL(window.location.href);

    if (sortType === 'default') {
        currentUrl.searchParams.delete('sort');
    } else {
        currentUrl.searchParams.set('sort', sortType);
    }

    window.location.href = currentUrl.toString();
}, { preventDefault: true });

// ============================================================================
// GENERIC UTILITY ACTIONS
// ============================================================================
// Removed: reload-page (duplicate of admin-wallet.js)

/**
 * Show Discord Channel Info
 * Displays info alert about Discord channel
 */
window.EventDelegation.register('show-discord-channel-info', function(element, e) {
    e.preventDefault();
    alert('Check Discord #pl-new-players channel for notifications');
}, { preventDefault: true });

// ============================================================================

// Match management handlers loaded
