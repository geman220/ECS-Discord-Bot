/**
 * Substitute Management - Configuration
 * API endpoints and configuration constants
 *
 * @module substitute-management/config
 */

'use strict';

/**
 * API endpoint configuration
 */
export const API = {
  pool: {
    statistics: (league) => `/admin/substitute-pools/${league}/statistics`,
    history: (league) => `/admin/substitute-pools/${league}/history`,
    requests: (league) => `/admin/substitute-pools/${league}/requests`,
    export: (league) => `/admin/substitute-pools/${league}/export`
  },
  request: {
    detail: (league, id) => `/admin/substitute-pools/${league}/requests/${id}`,
    resend: (league, id) => `/admin/substitute-pools/${league}/requests/${id}/resend`,
    cancel: (league, id) => `/admin/substitute-pools/${league}/requests/${id}/cancel`,
    assign: (league, id) => `/admin/substitute-pools/${league}/requests/${id}/assign`,
    delete: (id) => `/api/substitute-pools/requests/${id}`
  },
  match: {
    requests: (matchId) => `/admin/substitute-pools/match/${matchId}/requests`
  }
};

/**
 * League configuration with colors and icons
 */
export const LEAGUE_CONFIG = {
  'ECS FC': { name: 'ECS FC', icon: 'fas fa-futbol', colorKey: 'info' },
  'Classic': { name: 'Classic Division', icon: 'fas fa-trophy', colorKey: 'success' },
  'Premier': { name: 'Premier Division', icon: 'fas fa-crown', colorKey: 'danger' }
};

/**
 * Default timeout for API requests (ms)
 */
export const REQUEST_TIMEOUT = 10000;

/**
 * Get color from ECSTheme or fallback
 * @param {string} colorKey - Color key (primary, success, danger, etc.)
 * @returns {string} Color value
 */
export function getThemeColor(colorKey) {
  const fallbacks = {
    primary: '#0d6efd',
    secondary: '#6c757d',
    success: '#198754',
    danger: '#dc3545',
    warning: '#ffc107',
    info: '#0dcaf0'
  };

  if (typeof window.ECSTheme !== 'undefined') {
    return window.ECSTheme.getColor(colorKey) || fallbacks[colorKey] || fallbacks.primary;
  }
  return fallbacks[colorKey] || fallbacks.primary;
}

export default { API, LEAGUE_CONFIG, REQUEST_TIMEOUT, getThemeColor };
