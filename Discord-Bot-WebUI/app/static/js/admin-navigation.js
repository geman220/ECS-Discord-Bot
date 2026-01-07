'use strict';

/**
 * ============================================================================
 * ADMIN NAVIGATION CONTROLLER
 * ============================================================================
 *
 * Modern, production-ready navigation controller following architectural standards:
 * - Event delegation (single listener on container)
 * - Data-* attribute hooks (no binding to styling classes)
 * - State-driven via CSS classes (is-open, is-active)
 * - No inline styles or event handlers
 * - Accessible keyboard navigation
 * - Mobile-friendly touch interactions
 *
 * Dependencies: None (vanilla JS)
 *
 * ============================================================================
 */

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';

/**
 * Admin Navigation Controller
 * Handles all navigation interactions via event delegation
 */
class AdminNavigationController {
  constructor(element) {
    this.nav = element;
    this.activeDropdown = null;
    this.init();
  }

  /**
   * Initialize the controller
   */
  init() {
    // Keyboard navigation
    this.nav.addEventListener('keydown', this.handleKeyboard.bind(this));

    // Close dropdowns when clicking outside
    document.addEventListener('click', this.handleOutsideClick.bind(this));

    // Close dropdowns on escape key
    document.addEventListener('keydown', this.handleEscapeKey.bind(this));

    // Register actions with window.EventDelegation
    this.registerActions();
  }

  /**
   * Register actions - now a no-op since handlers are registered at module scope
   * Kept for backward compatibility
   */
  registerActions() {
    // Handlers are now registered at module scope for proper timing
    // See bottom of file for window.EventDelegation.register() calls
  }

  /**
   * Handle toggle dropdown action
   * @param {Element} element - The element that was clicked (from window.EventDelegation)
   * @param {Event} e - The click event
   */
  handleToggleDropdown(element, e) {
    this.toggleDropdown(element);
  }

  /**
   * Handle close dropdown action
   * @param {Element} element - The element that was clicked (from window.EventDelegation)
   * @param {Event} e - The click event
   */
  handleCloseDropdown(element, e) {
    this.closeDropdown(element);
  }

  /**
   * Handle keyboard navigation
   * @param {KeyboardEvent} e - Keyboard event
   */
  handleKeyboard(e) {
    const target = e.target;

    // Enter or Space on dropdown toggle
    if ((e.key === 'Enter' || e.key === ' ') &&
        target.dataset.action === 'toggle-admin-dropdown') {
      e.preventDefault();
      this.toggleDropdown(target);
    }

    // Arrow keys in dropdown
    if (this.activeDropdown && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      this.navigateDropdown(e.key);
    }
  }

  /**
   * Handle escape key to close dropdowns
   * @param {KeyboardEvent} e - Keyboard event
   */
  handleEscapeKey(e) {
    if (e.key === 'Escape' && this.activeDropdown) {
      this.closeAllDropdowns();
      // Return focus to the toggle button
      const toggle = this.activeDropdown.previousElementSibling;
      if (toggle) toggle.focus();
    }
  }

  /**
   * Handle clicks outside nav to close dropdowns
   * @param {Event} e - Click event
   */
  handleOutsideClick(e) {
    if (!this.nav.contains(e.target) && this.activeDropdown) {
      this.closeAllDropdowns();
    }
  }

  /**
   * Toggle dropdown menu
   * @param {HTMLElement} toggle - The dropdown toggle button
   */
  toggleDropdown(toggle) {
    const dropdownItem = toggle.closest('[data-dropdown]');
    if (!dropdownItem) return;

    const dropdown = dropdownItem.querySelector('.c-admin-nav__dropdown');
    if (!dropdown) return;

    const isOpen = dropdownItem.classList.contains('is-open');

    // Close all other dropdowns first
    this.closeAllDropdowns();

    if (!isOpen) {
      // Open this dropdown
      dropdownItem.classList.add('is-open');
      toggle.classList.add('is-open');
      toggle.setAttribute('aria-expanded', 'true');
      dropdown.setAttribute('aria-hidden', 'false');

      this.activeDropdown = dropdown;

      // Focus first dropdown item for keyboard navigation
      const firstItem = dropdown.querySelector('.c-admin-nav__dropdown-item');
      if (firstItem) firstItem.focus();
    } else {
      // Close this dropdown
      this.closeDropdown(dropdownItem);
    }
  }

  /**
   * Close specific dropdown
   * @param {HTMLElement} element - Dropdown item or toggle
   */
  closeDropdown(element) {
    const dropdownItem = element.closest('[data-dropdown]');
    if (!dropdownItem) return;

    const toggle = dropdownItem.querySelector('[data-action="toggle-admin-dropdown"]');
    const dropdown = dropdownItem.querySelector('.c-admin-nav__dropdown');

    dropdownItem.classList.remove('is-open');
    if (toggle) {
      toggle.classList.remove('is-open');
      toggle.setAttribute('aria-expanded', 'false');
    }
    if (dropdown) {
      dropdown.setAttribute('aria-hidden', 'true');
    }

    if (this.activeDropdown === dropdown) {
      this.activeDropdown = null;
    }
  }

  /**
   * Close all dropdowns
   */
  closeAllDropdowns() {
    const openDropdowns = this.nav.querySelectorAll('[data-dropdown].is-open');
    openDropdowns.forEach(item => this.closeDropdown(item));
  }

  /**
   * Navigate within dropdown using arrow keys
   * @param {string} direction - 'ArrowUp' or 'ArrowDown'
   */
  navigateDropdown(direction) {
    if (!this.activeDropdown) return;

    const items = Array.from(
      this.activeDropdown.querySelectorAll('.c-admin-nav__dropdown-item:not(.is-disabled)')
    );

    const currentIndex = items.indexOf(document.activeElement);

    let nextIndex;
    if (direction === 'ArrowDown') {
      nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
    } else {
      nextIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
    }

    items[nextIndex].focus();
  }

  /**
   * Handle navigation (could add analytics here)
   * @param {HTMLElement} element - The clicked link
   * @param {Event} e - Click event
   */
  handleNavigation(element, e) {
    // window.EventDelegation passes (element, event) - element is the clicked link
    if (!element || !element.classList) return;

    // Remove active state from all links
    const allLinks = this.nav.querySelectorAll('.c-admin-nav__link');
    allLinks.forEach(l => l.classList.remove('is-active'));

    // Add active state to clicked link
    element.classList.add('is-active');
  }

  /**
   * Destroy the controller
   */
  destroy() {
    this.nav.removeEventListener('keydown', this.handleKeyboard);
    document.removeEventListener('click', this.handleOutsideClick);
    document.removeEventListener('keydown', this.handleEscapeKey);
  }
}

/**
 * Auto-initialize all admin navigation components
 */
function initAdminNavigation() {
  // Page guard: only run on admin pages
  const isAdminPage = document.querySelector('[data-controller="admin-nav"]') ||
                      document.querySelector('.c-admin-nav') ||
                      window.location.pathname.includes('/admin');

  if (!isAdminPage) {
    return;
  }

  const navElements = document.querySelectorAll('[data-controller="admin-nav"]');

  if (navElements.length === 0) {
    // Try fallback to class selector
    const altNav = document.querySelector('.c-admin-nav');
    if (altNav && !altNav.hasAttribute('data-controller')) {
      altNav.setAttribute('data-controller', 'admin-nav');
      altNav.adminNavController = new AdminNavigationController(altNav);
    }
    return;
  }

  navElements.forEach(nav => {
    // Avoid double initialization
    if (nav.adminNavController) return;

    // Create and attach controller
    nav.adminNavController = new AdminNavigationController(nav);
  });
}

// Register with window.InitSystem
window.InitSystem.register('admin-navigation', initAdminNavigation, {
  priority: 70,
  reinitializable: true,
  description: 'Admin panel navigation controller'
});

// Fallback
// window.InitSystem handles initialization

// ========================================================================
// EVENT DELEGATION - Registered at module scope
// ========================================================================
// Handlers registered when module executes, ensuring window.EventDelegation is available.
// Handlers find the controller instance on the closest nav element.

/**
 * Helper to find the controller instance for an element
 */
function getController(element) {
  const nav = element.closest('[data-controller="admin-nav"]') || element.closest('.c-admin-nav');
  return nav ? nav.adminNavController : null;
}

// Register window.EventDelegation handlers
window.EventDelegation.register('toggle-admin-dropdown', (element, e) => {
  const controller = getController(element);
  if (controller) {
    controller.toggleDropdown(element);
  }
}, { preventDefault: true });

window.EventDelegation.register('admin-navigate', (element, e) => {
  const controller = getController(element);
  if (controller) {
    controller.handleNavigation(element, e);
  }
}, { preventDefault: false });

window.EventDelegation.register('close-admin-dropdown', (element, e) => {
  const controller = getController(element);
  if (controller) {
    controller.closeDropdown(element);
  }
}, { preventDefault: true });

// Backward compatibility
window.AdminNavigationController = AdminNavigationController;
window.initAdminNavigation = initAdminNavigation;

/**
 * ============================================================================
 * USAGE NOTES
 * ============================================================================
 *
 * AUTOMATIC INITIALIZATION:
 * - Runs automatically on DOMContentLoaded
 * - Finds all elements with data-controller="admin-nav"
 * - Creates controller instance for each
 *
 * MANUAL INITIALIZATION:
 * window.initAdminNavigation(); // Re-init all
 *
 * const nav = document.querySelector('.c-admin-nav');
 * nav.adminNavController = new AdminNavigationController(nav);
 *
 * DESTROY:
 * nav.adminNavController.destroy();
 * nav.adminNavController = null;
 *
 * REQUIRED HTML STRUCTURE:
 * <nav class="c-admin-nav" data-controller="admin-nav">
 *   <ul class="c-admin-nav__list">
 *     <li class="c-admin-nav__item" data-dropdown>
 *       <button class="c-admin-nav__link c-admin-nav__dropdown-toggle"
 *               data-action="toggle-admin-dropdown">
 *         Menu
 *       </button>
 *       <ul class="c-admin-nav__dropdown">...</ul>
 *     </li>
 *   </ul>
 * </nav>
 *
 * DATA ATTRIBUTES:
 * - data-controller="admin-nav" - Marks nav container (required)
 * - data-action="toggle-admin-dropdown" - Toggle dropdown (scoped to avoid collision)
 * - data-action="admin-navigate" - Track navigation (scoped to avoid collision)
 * - data-dropdown - Marks dropdown parent
 *
 * STATE CLASSES (CSS DRIVEN):
 * - is-open - Dropdown is open
 * - is-active - Nav item is active
 * - is-disabled - Nav item is disabled
 *
 * EVENTS:
 * Controller handles all events via delegation
 * No inline onclick or event handlers needed
 *
 * ============================================================================
 */
