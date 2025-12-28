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

(function() {
  'use strict';

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

      // Register actions with EventDelegation
      this.registerActions();
    }

    /**
     * Register actions with EventDelegation or fallback to direct handlers
     */
    registerActions() {
      // Use window.EventDelegation for ES module compatibility (Vite bundles each module separately)
      if (window.EventDelegation && typeof window.EventDelegation.register === 'function') {
        window.EventDelegation.register('toggle-dropdown', this.handleToggleDropdown.bind(this), { preventDefault: true });
        window.EventDelegation.register('navigate', this.handleNavigation.bind(this), { preventDefault: false });
        window.EventDelegation.register('close-dropdown', this.handleCloseDropdown.bind(this), { preventDefault: true });
        console.log('[AdminNavigation] Registered handlers with EventDelegation');
      } else {
        // Fallback: Add direct click handler on nav container when EventDelegation isn't available
        console.log('[AdminNavigation] EventDelegation not found, using fallback click handler');
        this.nav.addEventListener('click', this.handleFallbackClick.bind(this));
      }
    }

    /**
     * Fallback click handler when EventDelegation is unavailable
     * @param {Event} e - Click event
     */
    handleFallbackClick(e) {
      const target = e.target.closest('[data-action]');
      if (!target) return;

      const action = target.dataset.action;

      switch (action) {
        case 'toggle-dropdown':
          e.preventDefault();
          this.toggleDropdown(target);
          break;
        case 'close-dropdown':
          e.preventDefault();
          this.closeDropdown(target);
          break;
        case 'navigate':
          this.handleNavigation(target, e);
          break;
      }
    }

    /**
     * Handle toggle dropdown action
     * @param {Element} element - The element that was clicked (from EventDelegation)
     * @param {Event} e - The click event
     */
    handleToggleDropdown(element, e) {
      this.toggleDropdown(element);
    }

    /**
     * Handle close dropdown action
     * @param {Element} element - The element that was clicked (from EventDelegation)
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
          target.dataset.action === 'toggle-dropdown') {
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

      const toggle = dropdownItem.querySelector('[data-action="toggle-dropdown"]');
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
     * @param {Event} e - Click event
     * @param {HTMLElement} link - The clicked link
     */
    handleNavigation(element, e) {
      // EventDelegation passes (element, event) - element is the clicked link
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

  /**
   * Initialize on DOM ready
   */
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAdminNavigation);
  } else {
    initAdminNavigation();
  }

  /**
   * Re-initialize on dynamic content updates (HTMX, Turbo, etc.)
   * Uncomment if using HTMX or Turbo:
   */
  // document.body.addEventListener('htmx:afterSwap', initAdminNavigation);
  // document.addEventListener('turbo:load', initAdminNavigation);

  /**
   * Export for manual initialization if needed
   */
  window.AdminNavigationController = AdminNavigationController;
  window.initAdminNavigation = initAdminNavigation;

})();

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
 *               data-action="toggle-dropdown">
 *         Menu
 *       </button>
 *       <ul class="c-admin-nav__dropdown">...</ul>
 *     </li>
 *   </ul>
 * </nav>
 *
 * DATA ATTRIBUTES:
 * - data-controller="admin-nav" - Marks nav container (required)
 * - data-action="toggle-dropdown" - Toggle dropdown
 * - data-action="navigate" - Track navigation
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
