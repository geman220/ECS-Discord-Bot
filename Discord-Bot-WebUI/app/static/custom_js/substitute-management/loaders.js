/**
 * Substitute Management - Loaders
 * Data loading functions
 *
 * @module substitute-management/loaders
 */

'use strict';

import { showTableLoading, showTableError } from './utils.js';
import {
  fetchLeagueStatistics,
  fetchRecentActivity,
  fetchSubstituteRequests,
  fetchMatchSubstituteRequests
} from './api.js';
import {
  displayRecentActivity,
  displaySubstituteRequests,
  displayMatchSubstituteRequests
} from './render.js';

/**
 * Load league statistics for modal
 * @param {string} league - League type
 */
export function loadLeagueStatistics(league) {
  // Get stats from the main page first
  const activeCount = window.$(`#active-count-${league}`).text() || '0';
  const pendingCount = window.$(`#pending-count-${league}`).text() || '0';

  window.$('#modalTotalActive').text(activeCount);
  window.$('#modalPendingApproval').text(pendingCount);

  // Load additional statistics via API
  fetchLeagueStatistics(league)
    .then(response => {
      if (response.success) {
        const stats = response.statistics;
        const totalRequests = document.getElementById('modalTotalRequests');
        const matchesPlayed = document.getElementById('modalMatchesPlayed');
        if (totalRequests) totalRequests.textContent = stats.total_requests_sent || 0;
        if (matchesPlayed) matchesPlayed.textContent = stats.total_matches_played || 0;
      }
    })
    .catch(() => {
      console.warn('Could not load detailed statistics');
    });

  // Load activity and requests
  loadRecentActivity(league);
  loadSubstituteRequests(league);
}

/**
 * Load recent activity for a league
 * @param {string} league - League type
 */
export async function loadRecentActivity(league) {
  const table = document.getElementById('recentActivityTable');
  if (!table) return;

  showTableLoading(table, 'Loading activity...', 4);

  try {
    const data = await fetchRecentActivity(league);

    if (data.success && data.history) {
      displayRecentActivity(data.history.slice(0, 10));
    } else {
      displayRecentActivity([]);
    }
  } catch (error) {
    console.error('Error loading activity:', error);
    let errorMessage = 'Unable to load activity history';

    if (error.name === 'AbortError') {
      errorMessage = 'Request timed out - server may be slow';
    }

    showTableError(table, errorMessage, 'retry-activity', { league }, 4);
  }
}

/**
 * Load substitute requests for a league
 * @param {string} league - League type
 */
export async function loadSubstituteRequests(league) {
  const table = document.getElementById('substituteRequestsTable');
  if (!table) return;

  showTableLoading(table, 'Loading substitute requests...', 5);

  try {
    const data = await fetchSubstituteRequests(league);

    if (data.success && data.requests) {
      displaySubstituteRequests(data.requests);
    } else {
      displaySubstituteRequests([]);
    }
  } catch (error) {
    console.error('Error loading substitute requests:', error);
    showTableError(table, 'Unable to load substitute requests', 'retry-requests', { league }, 5);
  }
}

/**
 * Load substitute requests for a specific match
 * @param {string|number} matchId - Match ID
 */
export async function loadMatchSubstituteRequests(matchId) {
  if (!matchId) {
    console.warn('No match ID provided for loading substitute requests');
    return;
  }

  const table = document.getElementById('matchSubstituteRequestsTable');
  if (!table) return;

  showTableLoading(table, 'Loading substitute requests...', 5);

  try {
    const data = await fetchMatchSubstituteRequests(matchId);

    if (data.success && data.requests) {
      displayMatchSubstituteRequests(data.requests);
    } else {
      displayMatchSubstituteRequests([]);
    }
  } catch (error) {
    console.error('Error loading match substitute requests:', error);
    showTableError(table, 'Unable to load substitute requests', 'retry-match-requests', { 'match-id': matchId }, 5);
  }
}

export default {
  loadLeagueStatistics,
  loadRecentActivity,
  loadSubstituteRequests,
  loadMatchSubstituteRequests
};
