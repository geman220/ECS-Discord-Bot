/**
 * Navbar - Main Entry Point
 * Modern navbar controller
 *
 * @module navbar
 */

// Re-export everything
export * from './config.js';
export * from './state.js';
export * from './dropdown-manager.js';
export * from './search-handler.js';
export * from './notifications.js';
export * from './impersonation.js';
export * from './theme-manager.js';
export * from './presence.js';
export * from './scroll-tracker.js';

// Import for initialization
import { initState, getNavbar } from './state.js';
import { handleKeyboard, handleOutsideClick, toggleDropdown, toggleMobileMenu } from './dropdown-manager.js';
import { initSearch } from './search-handler.js';
import { initNotifications, markNotificationRead, markAllNotificationsRead, dismissNotification, clearAllNotifications, toggleNotificationExpand } from './notifications.js';
import { initRoleImpersonation, startRoleImpersonation, stopRoleImpersonation } from './impersonation.js';
import { initTheme, switchTheme } from './theme-manager.js';
import { initPresence } from './presence.js';
import { initScrollTracking } from './scroll-tracker.js';

/**
 * Initialize avatar image fallbacks
 */
function initAvatarFallbacks() {
  const navbar = getNavbar();
  if (!navbar) return;

  const avatars = navbar.querySelectorAll('.js-avatar-fallback');
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
 * Handle logout
 */
export function handleLogout() {
  const form = document.querySelector('#logout-form');
  if (form) {
    form.submit();
  }
}

/**
 * Initialize navbar
 */
export function initNavbar() {
  const navbar = initState();
  if (!navbar) {
    console.warn('Modern navbar not found');
    return;
  }

  // Attach event listeners
  document.addEventListener('keydown', handleKeyboard);
  document.addEventListener('click', handleOutsideClick);

  // Initialize components
  initScrollTracking();
  initSearch();
  initNotifications();
  initRoleImpersonation();
  initTheme();
  initPresence();
  initAvatarFallbacks();

  console.log('[Navbar] Initialized');
}

// Register event delegation handlers
function registerEventHandlers() {
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
    toggleMobileMenu();
  }, { preventDefault: true });

  // Dropdown toggles
  window.EventDelegation.register('toggle-navbar-dropdown', (element) => {
    const dropdownId = element.dataset.dropdown;
    if (dropdownId) {
      toggleDropdown(dropdownId);
    }
  }, { preventDefault: true });

  // Theme switcher
  window.EventDelegation.register('switch-theme', (element) => {
    const theme = element.dataset.theme;
    if (theme) {
      switchTheme(theme);
    }
  }, { preventDefault: true });

  // Role impersonation
  window.EventDelegation.register('start-impersonation', () => {
    startRoleImpersonation();
  }, { preventDefault: true });

  window.EventDelegation.register('stop-impersonation', () => {
    stopRoleImpersonation();
  }, { preventDefault: true });

  // Notification actions
  window.EventDelegation.register('mark-read', (element) => {
    const notificationId = element.dataset.notificationId;
    if (notificationId) {
      markNotificationRead(notificationId);
    }
  }, { preventDefault: true });

  window.EventDelegation.register('mark-all-read', () => {
    markAllNotificationsRead();
  }, { preventDefault: true });

  window.EventDelegation.register('clear-all-notifications', () => {
    clearAllNotifications();
  }, { preventDefault: true });

  window.EventDelegation.register('dismiss-notification', (element) => {
    const notificationId = element.dataset.notificationId;
    if (notificationId) {
      dismissNotification(notificationId);
    }
  }, { preventDefault: true, stopPropagation: true });

  window.EventDelegation.register('expand-notification', (element) => {
    const notificationId = element.dataset.notificationId;
    if (notificationId) {
      toggleNotificationExpand(notificationId);
    }
  }, { preventDefault: true });

  // Logout
  window.EventDelegation.register('logout', () => {
    handleLogout();
  }, { preventDefault: true });

  console.log('[Navbar] EventDelegation handlers registered');
}

// Register handlers
registerEventHandlers();

// Register with InitSystem
if (window.InitSystem && window.InitSystem.register) {
  window.InitSystem.register('navbar-modern', initNavbar, {
    priority: 80,
    description: 'Modern navbar controller (search, dropdowns, mobile menu)',
    reinitializable: false
  });
}

export default {
  initNavbar,
  handleLogout
};
