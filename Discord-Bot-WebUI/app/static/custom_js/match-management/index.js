'use strict';

/**
 * Match Management Module
 * Aggregates all match management submodules
 * @module match-management
 */

// State management
import {
    isInitialized,
    setInitialized,
    initializeCSRFToken,
    isMatchManagementPage
} from './state.js';

// Helper functions
import {
    getStatusColor,
    getStatusIcon,
    formatDuration,
    formatTaskETA,
    formatTTL,
    formatScheduledTime,
    formatScheduledTimes,
    getScheduleStatusColor,
    getScheduleStatusIcon,
    getStatusDisplay,
    getTaskStatusColor
} from './helpers.js';

// Task display
import {
    createTaskCard,
    createNoTaskCard,
    showTaskError,
    updateMatchTaskDetails,
    updateMatchRow
} from './task-display.js';

// Task API
import {
    refreshStatuses,
    loadMatchTaskDetails,
    loadAllTaskDetails,
    revokeTask,
    rescheduleTask,
    showTaskInfo,
    showTaskDetails
} from './task-api.js';

// Match actions
import {
    matchMgmtScheduleMatch,
    createThreadNow,
    startLiveReporting,
    stopLiveReporting,
    addMatchByDate,
    scheduleAllMatches,
    fetchAllFromESPN,
    clearAllMatches,
    matchMgmtEditMatch,
    removeMatch,
    forceScheduleMatch
} from './match-actions.js';

// Queue management
import {
    matchMgmtShowQueueStatus,
    refreshQueueStatus,
    displayQueueStatus,
    debugMatchTasks,
    showDebugModal
} from './queue-management.js';

// Cache status
import { showCacheStatus } from './cache-status.js';

/**
 * Initialize match management module
 */
function initMatchManagement() {
    if (isInitialized()) return;
    setInitialized(true);

    // Initialize CSRF token (needed for any page that might use match actions)
    initializeCSRFToken();

    // PAGE GUARD: Only run match management features on the match management admin page
    if (!isMatchManagementPage()) {
        return;
    }

    // Format scheduled times on initial page load
    formatScheduledTimes();

    // Load task details for all matches after a short delay
    setTimeout(loadAllTaskDetails, 1000);

    // With background cache, we can refresh less frequently
    // Refresh task details every 60 seconds (cache updates every 3 minutes)
    setInterval(loadAllTaskDetails, 60000);

    // Auto-refresh every 60 seconds
    setInterval(refreshStatuses, 60000);

    // Handle historical matches toggle
    const historicalToggle = document.getElementById('historicalMatches');
    const historicalToggleIcon = document.getElementById('historicalToggleIcon');

    if (historicalToggle && historicalToggleIcon) {
        historicalToggle.addEventListener('show.bs.collapse', function () {
            historicalToggleIcon.classList.remove('ti-chevron-down');
            historicalToggleIcon.classList.add('ti-chevron-up');

            // Load task details for historical matches when expanded
            setTimeout(() => {
                document.querySelectorAll('[data-match-type="historical"][data-match-id]').forEach(card => {
                    const matchId = card.dataset.matchId;
                    if (matchId) {
                        loadMatchTaskDetails(matchId);
                    }
                });
            }, 100);
        });

        historicalToggle.addEventListener('hide.bs.collapse', function () {
            historicalToggleIcon.classList.remove('ti-chevron-up');
            historicalToggleIcon.classList.add('ti-chevron-down');
        });
    }
}

// Re-export all functions for ES module consumers
export {
    // State
    initializeCSRFToken,
    isMatchManagementPage,

    // Helpers
    getStatusColor,
    getStatusIcon,
    formatDuration,
    formatTaskETA,
    formatTTL,
    formatScheduledTime,
    formatScheduledTimes,
    getScheduleStatusColor,
    getScheduleStatusIcon,
    getStatusDisplay,
    getTaskStatusColor,

    // Task display
    createTaskCard,
    createNoTaskCard,
    showTaskError,
    updateMatchTaskDetails,
    updateMatchRow,

    // Task API
    refreshStatuses,
    loadMatchTaskDetails,
    loadAllTaskDetails,
    revokeTask,
    rescheduleTask,
    showTaskInfo,
    showTaskDetails,

    // Match actions
    matchMgmtScheduleMatch,
    createThreadNow,
    startLiveReporting,
    stopLiveReporting,
    addMatchByDate,
    scheduleAllMatches,
    fetchAllFromESPN,
    clearAllMatches,
    matchMgmtEditMatch,
    removeMatch,
    forceScheduleMatch,

    // Queue management
    matchMgmtShowQueueStatus,
    refreshQueueStatus,
    displayQueueStatus,
    debugMatchTasks,
    showDebugModal,

    // Cache status
    showCacheStatus,

    // Init
    initMatchManagement
};

// Window exports - only functions used by event delegation handlers
window.revokeTask = revokeTask;
window.rescheduleTask = rescheduleTask;
window.showTaskInfo = showTaskInfo;

// Register with InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('match-management', initMatchManagement, {
        priority: 40,
        reinitializable: false,
        description: 'Match management admin page'
    });
}

// Auto-initialize when imported
initMatchManagement();
