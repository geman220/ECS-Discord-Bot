'use strict';

/**
 * Sync Review Progress
 * Progress bar and badge updates
 * @module sync-review/progress
 */

import { getSyncData, getResolutions } from './state.js';
import { updateInactivePlayerCount } from './inactive-players.js';

/**
 * Update progress bar based on resolutions
 */
export function updateProgressBar() {
    const syncData = getSyncData();
    const resolutions = getResolutions();

    const totalIssues = (syncData.flagged_multi_orders?.length || 0) +
                        (syncData.new_players?.length || 0) +
                        (syncData.email_mismatch_players?.length || 0);
    const resolvedIssues = Object.keys(resolutions.multiOrders).length +
                           Object.keys(resolutions.newPlayers).length +
                           Object.keys(resolutions.emailMismatches).length;

    const percentage = totalIssues === 0 ? 100 : Math.round((resolvedIssues / totalIssues) * 100);

    const progressBar = document.getElementById('resolutionProgress');
    const progressText = document.getElementById('progressText');

    if (progressBar) {
        progressBar.setAttribute('style', `width: ${percentage}%`);
        progressBar.setAttribute('aria-valuenow', percentage);
    }

    if (progressText) {
        progressText.textContent = `${percentage}% Complete (${resolvedIssues}/${totalIssues} resolved)`;
    }

    const issuesResolvedCount = document.getElementById('issuesResolvedCount');
    if (issuesResolvedCount) {
        issuesResolvedCount.textContent = resolvedIssues + '/' + totalIssues;
    }

    // Update badges
    const multiOrdersBadge = document.getElementById('multiOrdersBadge');
    const newPlayersBadge = document.getElementById('newPlayersBadge');
    const emailMismatchBadge = document.getElementById('emailMismatchBadge');

    if (multiOrdersBadge) {
        multiOrdersBadge.textContent = (syncData.flagged_multi_orders?.length || 0) - Object.keys(resolutions.multiOrders).length;
    }
    if (newPlayersBadge) {
        newPlayersBadge.textContent = (syncData.new_players?.length || 0) - Object.keys(resolutions.newPlayers).length;
    }
    if (emailMismatchBadge) {
        emailMismatchBadge.textContent = (syncData.email_mismatch_players?.length || 0) - Object.keys(resolutions.emailMismatches).length;
    }

    // Update inactive player count
    updateInactivePlayerCount();

    if (percentage === 100 && progressBar) {
        progressBar.classList.remove('progress-bar-striped', 'progress-bar-animated');
        progressBar.classList.add('bg-green-500');
    }
}

/**
 * Mark an issue as resolved in the UI
 * @param {string} issueType
 * @param {string} issueId
 * @param {string} status
 */
export function markIssueResolved(issueType, issueId, status) {
    const issueCard = document.querySelector(`[data-issue-type="${issueType}"][data-issue-id="${issueId}"]`);
    if (issueCard) {
        issueCard.classList.remove('issue-pending');
        issueCard.classList.add('issue-resolved');

        const statusBadge = issueCard.querySelector('.status-badge');
        if (statusBadge) {
            statusBadge.textContent = status;
            statusBadge.className = 'status-badge px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
        }
    }

    updateProgressBar();
}
