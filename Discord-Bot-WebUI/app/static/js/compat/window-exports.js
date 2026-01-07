/**
 * Window Exports - Backward Compatibility Layer
 *
 * This module provides backward compatibility for legacy code that relies on
 * window.* globals. It imports from the new modular services and exposes them
 * globally with deprecation warnings in development mode.
 *
 * Usage:
 *   Import this module in main-entry.js to ensure all legacy globals are available.
 *
 * Migration Path:
 *   1. Import this module to maintain compatibility
 *   2. Update code to use ES module imports
 *   3. Remove this module when all legacy code is migrated
 *
 * @module compat/window-exports
 */

'use strict';

// Import services
import { showToast, showSuccess, showError, showWarning, showInfo } from '../services/toast-service.js';
import { showLoading, hideLoading, showLoadingModal, hideLoadingModal } from '../services/loading-service.js';
import { SharedUtils } from '../utils/shared-utils.js';
import { EventDelegation } from '../event-delegation/core.js';

/**
 * Whether to show deprecation warnings
 * Set to false in production
 */
const SHOW_DEPRECATION_WARNINGS = typeof process !== 'undefined' && process.env?.NODE_ENV !== 'production';

/**
 * Create a deprecated property on window with warning
 * @param {string} name - Property name
 * @param {*} value - Property value
 * @param {string} replacement - Suggested replacement
 */
function exposeWithWarning(name, value, replacement) {
  if (typeof window === 'undefined') return;

  // If already exists, don't override
  if (window[name] !== undefined) return;

  if (SHOW_DEPRECATION_WARNINGS) {
    let hasWarned = false;
    Object.defineProperty(window, name, {
      get() {
        if (!hasWarned) {
          console.warn(
            `[Deprecated] window.${name} is deprecated. ` +
            `Use: ${replacement}`
          );
          hasWarned = true;
        }
        return value;
      },
      configurable: true
    });
  } else {
    // In production, just expose without warning
    window[name] = value;
  }
}

/**
 * Expose value without warning (for stable APIs)
 * @param {string} name - Property name
 * @param {*} value - Property value
 */
function exposeStable(name, value) {
  if (typeof window === 'undefined') return;
  if (window[name] !== undefined) return;
  window[name] = value;
}

// ============================================================================
// Toast Service Exports
// ============================================================================

// Stable exports (these are commonly used and likely to remain)
exposeStable('showToast', showToast);
exposeStable('ToastService', {
  show: showToast,
  success: showSuccess,
  error: showError,
  warning: showWarning,
  info: showInfo
});

// ============================================================================
// Loading Service Exports
// ============================================================================

exposeStable('showLoading', showLoading);
exposeStable('hideLoading', hideLoading);
exposeStable('showLoadingModal', showLoadingModal);
exposeStable('hideLoadingModal', hideLoadingModal);
exposeStable('LoadingService', {
  show: showLoading,
  hide: hideLoading,
  showModal: showLoadingModal,
  hideModal: hideLoadingModal
});

// ============================================================================
// Shared Utils Exports
// ============================================================================

exposeStable('SharedUtils', SharedUtils);

// Individual utility exports (for legacy code using window.formatDate etc.)
exposeStable('formatDate', SharedUtils.formatDate);
exposeStable('formatTime', SharedUtils.formatTime);
exposeStable('formatDateTime', SharedUtils.formatDateTime);
exposeStable('formatRelativeTime', SharedUtils.formatRelativeTime);
exposeStable('truncate', SharedUtils.truncate);
exposeStable('capitalize', SharedUtils.capitalize);
exposeStable('toTitleCase', SharedUtils.toTitleCase);
exposeStable('formatNumber', SharedUtils.formatNumber);
exposeStable('formatCurrency', SharedUtils.formatCurrency);
exposeStable('debounce', SharedUtils.debounce);
exposeStable('throttle', SharedUtils.throttle);
exposeStable('isEmpty', SharedUtils.isEmpty);
exposeStable('isValidEmail', SharedUtils.isValidEmail);

// ============================================================================
// Event Delegation Export
// ============================================================================

exposeStable('EventDelegation', EventDelegation);

// ============================================================================
// Legacy Function Aliases
// ============================================================================

// Some code uses showAlert instead of showToast
exposeStable('showAlert', (type, message) => {
  // Handle reversed argument order
  if (['success', 'error', 'warning', 'info', 'danger'].includes(type)) {
    showToast(message, type);
  } else {
    showToast(type, message);
  }
});

// Legacy showNotification
exposeStable('showNotification', (title, message, type = 'info') => {
  showToast(message, type, { title });
});

// ============================================================================
// Template-specific Exports
// ============================================================================

// These are specifically called from templates and MUST be available

// For onboarding.html
if (typeof window !== 'undefined') {
  window.toggleSmsConsent = window.toggleSmsConsent || function() {
    console.warn('[Compat] toggleSmsConsent called but not implemented');
  };

  window.toggleSmsVerification = window.toggleSmsVerification || function() {
    console.warn('[Compat] toggleSmsVerification called but not implemented');
  };
}

// ============================================================================
// ECS Namespace (consolidated access point)
// ============================================================================

/**
 * Consolidated ECS namespace for organized access
 * This provides a clean API for accessing all services and modules
 *
 * Structure:
 *   window.ECS.Toast - Toast notifications
 *   window.ECS.Loading - Loading indicators
 *   window.ECS.Utils - Shared utilities
 *   window.ECS.Events - Event delegation
 *   window.ECS.Admin - Admin modules (populated by admin modules)
 *   window.ECS.Features - Feature modules (populated by feature modules)
 *   window.ECS.Mobile - Mobile modules (populated by mobile modules)
 *   window.ECS.Theme - Theme utilities
 */
if (typeof window !== 'undefined') {
  window.ECS = window.ECS || {};

  // Core services
  window.ECS.Toast = {
    show: showToast,
    success: showSuccess,
    error: showError,
    warning: showWarning,
    info: showInfo
  };

  window.ECS.Loading = {
    show: showLoading,
    hide: hideLoading,
    showModal: showLoadingModal,
    hideModal: hideLoadingModal
  };

  window.ECS.Utils = SharedUtils;
  window.ECS.Events = EventDelegation;

  // Module categories (populated by individual modules)
  window.ECS.Admin = window.ECS.Admin || {};
  window.ECS.Features = window.ECS.Features || {};
  window.ECS.Mobile = window.ECS.Mobile || {};
  window.ECS.User = window.ECS.User || {};
  window.ECS.Match = window.ECS.Match || {};
  window.ECS.Draft = window.ECS.Draft || {};
  window.ECS.Wallet = window.ECS.Wallet || {};

  // Theme reference (ECSTheme is defined elsewhere)
  Object.defineProperty(window.ECS, 'Theme', {
    get() {
      return window.ECSTheme || null;
    },
    configurable: true
  });

  // Design System reference
  Object.defineProperty(window.ECS, 'DesignSystem', {
    get() {
      return window.ECSDesignSystem || null;
    },
    configurable: true
  });

  // Helper to register modules under ECS namespace
  window.ECS.register = function(category, name, module) {
    if (!window.ECS[category]) {
      window.ECS[category] = {};
    }
    window.ECS[category][name] = module;
  };
}

// ============================================================================
// Export for ES modules
// ============================================================================

export {
  showToast,
  showSuccess,
  showError,
  showWarning,
  showInfo,
  showLoading,
  hideLoading,
  showLoadingModal,
  hideLoadingModal,
  SharedUtils,
  EventDelegation
};

export default {
  // Flag to indicate compat layer is loaded
  loaded: true,
  version: '1.0.0'
};
