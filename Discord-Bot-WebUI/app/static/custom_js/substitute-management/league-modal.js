/**
 * Substitute Management - League Modal
 * League management modal functions
 *
 * @module substitute-management/league-modal
 */

'use strict';

import { LEAGUE_CONFIG, getThemeColor } from './config.js';
import { loadLeagueStatistics } from './loaders.js';

/**
 * Open the league management modal
 * @param {string} league - League type (ECS FC, Classic, Premier)
 */
export function openLeagueManagementModal(league) {
  // Get league configuration
  const config = LEAGUE_CONFIG[league] || LEAGUE_CONFIG['ECS FC'];

  // Get theme color for the league
  const leagueColor = getThemeColor(config.colorKey);

  // Set modal title and icon
  window.$('#leagueIcon').attr('class', config.icon + ' me-2');
  window.$('#leagueTitle').text(config.name);

  // Load league statistics
  loadLeagueStatistics(league);

  // Store current league for modal actions
  window.$('#leagueManagementModal').data('current-league', league);
}

/**
 * Get current league from modal
 * @returns {string|null} Current league or null
 */
export function getCurrentLeague() {
  const modal = document.getElementById('leagueManagementModal');
  return modal ? modal.dataset.currentLeague : null;
}

export default {
  openLeagueManagementModal,
  getCurrentLeague
};
