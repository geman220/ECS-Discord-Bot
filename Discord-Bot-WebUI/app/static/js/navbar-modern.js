'use strict';

/**
 * ============================================================================
 * MODERN NAVBAR CONTROLLER - BEM ARCHITECTURE
 * ============================================================================
 *
 * Handles all navbar interactions with smooth animations and proper state management.
 * Uses EventDelegation for optimal performance and maintainability.
 *
 * Features:
 * - Dropdown management (theme, notifications, profile, impersonation)
 * - Search autocomplete integration
 * - Scroll state tracking
 * - Mobile menu toggle
 * - Keyboard navigation (Escape to close, Arrow keys for items)
 * - Outside click detection
 * - Badge animations
 * - Role impersonation management
 *
 * Refactored to use modular subcomponents in ./navbar/:
 * - config.js: Configuration constants
 * - state.js: State management
 * - dropdown-manager.js: Dropdown open/close, animation, keyboard navigation
 * - search-handler.js: Search functionality
 * - notifications.js: Notification loading, rendering, marking as read
 * - impersonation.js: Role impersonation functionality
 * - theme-manager.js: Theme switching
 * - presence.js: Online/offline status
 * - scroll-tracker.js: Scroll position tracking
 *
 * ============================================================================
 */

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';

// Import from submodules
import { CONFIG, getCSRFToken, escapeHtml, showToast } from './navbar/config.js';
import { initState, getNavbar, getActiveDropdown, setActiveDropdown } from './navbar/state.js';

import {
  toggleDropdown,
  openDropdown,
  closeDropdown,
  navigateDropdown,
  handleKeyboard,
  handleOutsideClick,
  toggleMobileMenu
} from './navbar/dropdown-manager.js';

import { initSearch, performSearch } from './navbar/search-handler.js';

import {
  initNotifications,
  loadNotifications,
  createNotificationElement,
  toggleNotificationExpand,
  markNotificationRead,
  markAllNotificationsRead,
  dismissNotification,
  clearAllNotifications,
  refreshNotificationCount,
  updateNotificationBadge
} from './navbar/notifications.js';

import {
  initRoleImpersonation,
  startRoleImpersonation,
  stopRoleImpersonation,
  loadImpersonationStatus,
  loadAvailableRoles,
  updateImpersonationStatus,
  clearRoleSelection,
  validateRoleSelection
} from './navbar/impersonation.js';

import { initTheme, switchTheme, applyTheme } from './navbar/theme-manager.js';
import { initPresence, checkPresence, refreshPresence, updateOnlineStatus } from './navbar/presence.js';
import { initScrollTracking } from './navbar/scroll-tracker.js';

/**
 * Modern Navbar Controller Class
 * Provides backward-compatible class interface
 */
class ModernNavbarController {
  constructor() {
    this.navbar = initState();
    if (!this.navbar) {
      console.warn('Modern navbar not found');
      return;
    }

    this.init();
  }

  init() {
    this.attachEventListeners();
    initScrollTracking();
    initSearch();
    initNotifications();
    initRoleImpersonation();
    initTheme();
    initPresence();
    this.initAvatarFallbacks();
  }

  /**
   * Initialize avatar image fallbacks
   */
  initAvatarFallbacks() {
    const avatars = this.navbar.querySelectorAll('.js-avatar-fallback');
    avatars.forEach(img => {
      img.addEventListener('error', () => {
        img.classList.add('is-hidden');
        const fallback = img.nextElementSibling;
        if (fallback && fallback.dataset.fallback === 'initials') {
          fallback.classList.remove('is-hidden');
        }
      });
    });
  }

  /**
   * Attach event listeners (non data-action events)
   */
  attachEventListeners() {
    document.addEventListener('keydown', handleKeyboard);
    document.addEventListener('click', handleOutsideClick);
  }

  // Delegate to submodules (for backward compatibility)
  getCSRFToken() { return getCSRFToken(); }
  toggleDropdown(dropdownId) { toggleDropdown(dropdownId); }
  openDropdown(dropdownId) { openDropdown(dropdownId); }
  closeDropdown(dropdownId) { closeDropdown(dropdownId); }
  navigateDropdown(direction) { navigateDropdown(direction); }
  toggleMobileMenu() { toggleMobileMenu(); }
  handleKeyboard(e) { handleKeyboard(e); }
  handleOutsideClick(e) { handleOutsideClick(e); }
  switchTheme(theme) { switchTheme(theme); }
  applyTheme(theme, save) { applyTheme(theme, save); }
  startRoleImpersonation() { startRoleImpersonation(); }
  stopRoleImpersonation() { stopRoleImpersonation(); }
  markNotificationRead(id) { markNotificationRead(id); }
  markAllNotificationsRead() { markAllNotificationsRead(); }
  dismissNotification(id) { dismissNotification(id); }
  clearAllNotifications() { clearAllNotifications(); }
  toggleNotificationExpand(id) { toggleNotificationExpand(id); }
  loadNotifications() { loadNotifications(); }
  refreshNotificationCount() { refreshNotificationCount(); }
  updateNotificationBadge(count) { updateNotificationBadge(count); }
  loadImpersonationStatus() { loadImpersonationStatus(); }
  loadAvailableRoles() { loadAvailableRoles(); }
  updateImpersonationStatus(data) { updateImpersonationStatus(data); }
  clearRoleSelection() { clearRoleSelection(); }
  validateRoleSelection() { validateRoleSelection(); }
  checkPresence() { checkPresence(); }
  refreshPresence() { refreshPresence(); }
  updateOnlineStatus(isOnline) { updateOnlineStatus(isOnline); }
  escapeHtml(text) { return escapeHtml(text); }
  showToast(message, type) { showToast(message, type); }

  handleLogout() {
    const form = document.querySelector('#logout-form');
    if (form) {
      form.submit();
    }
  }
}

// Initialize function with guard
if (typeof window._navbarInitialized === 'undefined') {
  window._navbarInitialized = false;
}

function initNavbar() {
  // Guard against double initialization
  if (window._navbarInitialized) {
    console.debug('[Navbar] Already initialized, skipping');
    return;
  }

  // Only initialize if navbar exists on page
  if (document.querySelector('.c-navbar-modern')) {
    console.log('[Navbar] Initializing ModernNavbarController');
    window.navbarController = new ModernNavbarController();
    window._navbarInitialized = true;
  }
}

// Register with InitSystem
window.InitSystem.register('navbar-modern', initNavbar, {
  priority: 80,
  description: 'Modern navbar controller (search, dropdowns, mobile menu)',
  reinitializable: false
});

// ============================================================================
// EVENT DELEGATION HANDLERS
// ============================================================================

function registerNavbarEventHandlers() {
  if (typeof window.EventDelegation === 'undefined' || typeof window.EventDelegation.register !== 'function') {
    console.warn('[Navbar] EventDelegation not available, handlers not registered');
    return;
  }

  // Prevent double registration
  if (window._navbarHandlersRegistered) {
    return;
  }
  window._navbarHandlersRegistered = true;

  // Mobile menu toggle
  window.EventDelegation.register('toggle-menu', () => {
    if (window.navbarController) {
      window.navbarController.toggleMobileMenu();
    }
  }, { preventDefault: true });

  // Dropdown toggles
  window.EventDelegation.register('toggle-navbar-dropdown', (element) => {
    const dropdownId = element.dataset.dropdown;
    if (dropdownId && window.navbarController) {
      window.navbarController.toggleDropdown(dropdownId);
    }
  }, { preventDefault: true });

  // Theme switcher
  window.EventDelegation.register('switch-theme', (element) => {
    const theme = element.dataset.theme;
    if (theme && window.navbarController) {
      window.navbarController.switchTheme(theme);
    }
  }, { preventDefault: true });

  // Role impersonation
  window.EventDelegation.register('start-impersonation', () => {
    if (window.navbarController) {
      window.navbarController.startRoleImpersonation();
    }
  }, { preventDefault: true });

  window.EventDelegation.register('stop-impersonation', () => {
    if (window.navbarController) {
      window.navbarController.stopRoleImpersonation();
    }
  }, { preventDefault: true });

  // Notification actions
  window.EventDelegation.register('mark-read', (element) => {
    const notificationId = element.dataset.notificationId;
    if (notificationId && window.navbarController) {
      window.navbarController.markNotificationRead(notificationId);
    }
  }, { preventDefault: true });

  window.EventDelegation.register('mark-all-read', () => {
    if (window.navbarController) {
      window.navbarController.markAllNotificationsRead();
    }
  }, { preventDefault: true });

  window.EventDelegation.register('clear-all-notifications', () => {
    if (window.navbarController) {
      window.navbarController.clearAllNotifications();
    }
  }, { preventDefault: true });

  window.EventDelegation.register('dismiss-notification', (element) => {
    const notificationId = element.dataset.notificationId;
    if (notificationId && window.navbarController) {
      window.navbarController.dismissNotification(notificationId);
    }
  }, { preventDefault: true, stopPropagation: true });

  window.EventDelegation.register('expand-notification', (element) => {
    const notificationId = element.dataset.notificationId;
    if (notificationId && window.navbarController) {
      window.navbarController.toggleNotificationExpand(notificationId);
    }
  }, { preventDefault: true });

  // Logout
  window.EventDelegation.register('logout', () => {
    if (window.navbarController) {
      window.navbarController.handleLogout();
    }
  }, { preventDefault: true });

  console.log('[Navbar] EventDelegation handlers registered');
}

// Register handlers
registerNavbarEventHandlers();

// Backward compatibility
window.ModernNavbarController = ModernNavbarController;

// Export for ES modules
export {
  ModernNavbarController,
  initNavbar,
  CONFIG,
  getCSRFToken,
  escapeHtml,
  showToast,
  toggleDropdown,
  openDropdown,
  closeDropdown,
  toggleMobileMenu,
  switchTheme,
  applyTheme,
  initTheme,
  initSearch,
  initNotifications,
  loadNotifications,
  markNotificationRead,
  markAllNotificationsRead,
  dismissNotification,
  clearAllNotifications,
  toggleNotificationExpand,
  updateNotificationBadge,
  initRoleImpersonation,
  startRoleImpersonation,
  stopRoleImpersonation,
  initPresence,
  checkPresence,
  refreshPresence,
  updateOnlineStatus,
  initScrollTracking
};

export default ModernNavbarController;
