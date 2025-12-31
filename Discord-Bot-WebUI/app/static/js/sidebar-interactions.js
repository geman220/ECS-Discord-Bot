/**
 * ============================================================================
 * SIDEBAR INTERACTIONS - MODERN EVENT DELEGATION
 * ============================================================================
 *
 * Handles all sidebar navigation interactions using event delegation.
 * Zero inline event handlers - all actions use data-action attributes.
 *
 * Features:
 * - Sidebar toggle (mobile & desktop)
 * - Submenu expansion/collapse
 * - Active state management
 * - Keyboard navigation support
 * - Touch-friendly interactions
 * - Accessibility (ARIA attributes)
 *
 * Architecture:
 * - Event delegation from document root
 * - Data-action attribute routing
 * - State classes (is-open, is-active)
 * - No direct DOM manipulation outside state classes
 * - Mobile-first responsive behavior
 *
 * ============================================================================
 */

(function () {
  'use strict';

  /**
   * Configuration
   */
  const CONFIG = {
    selectors: {
      sidebar: '.c-sidebar',
      sidebarToggle: '[data-action="toggle-sidebar"]',
      submenuToggle: '[data-action="toggle-submenu"]',
      expandableItem: '[data-expandable]',
      noActiveSeason: '[data-action="no-active-season"]',
    },
    classes: {
      open: 'is-open',
      active: 'is-active',
      collapsed: 'layout-menu-collapsed',
    },
    storage: {
      collapsedKey: 'sidebar-collapsed',
    },
    breakpoints: {
      desktop: 1200,
    },
  };

  /**
   * State management
   */
  const State = {
    isDesktop: window.innerWidth >= CONFIG.breakpoints.desktop,
    isSidebarOpen: false,
    collapsedState: localStorage.getItem(CONFIG.storage.collapsedKey) === 'true',
    // Initialization guards
    _initialized: false,
    _eventDelegationSetup: false,
    _keyboardNavSetup: false,
    _resizeHandlerSetup: false,
  };

  /**
   * DOM references (cached for performance)
   */
  let sidebar = null;

  /**
   * ============================================================================
   * INITIALIZATION
   * ============================================================================
   */

  function init() {
    // Guard against duplicate initialization
    if (State._initialized) return;
    State._initialized = true;

    // Cache DOM references
    sidebar = document.querySelector(CONFIG.selectors.sidebar);

    if (!sidebar) {
      console.warn('Sidebar not found');
      return;
    }

    // Restore collapsed state on desktop
    if (State.isDesktop && State.collapsedState) {
      document.body.classList.add(CONFIG.classes.collapsed);
    }

    // Set up event delegation
    window.setupEventDelegation();

    // Set up keyboard navigation
    setupKeyboardNavigation();

    // Handle window resize
    setupResizeHandler();

    // Set initial ARIA attributes
    setupAriaAttributes();

    console.log('Sidebar interactions initialized');
  }

  /**
   * ============================================================================
   * EVENT DELEGATION
   * ============================================================================
   */

  function setupEventDelegation() {
    // Guard against duplicate setup
    if (State._eventDelegationSetup) return;
    State._eventDelegationSetup = true;

    // Global click handler for all sidebar actions
    document.addEventListener('click', handleClick);

    // Close sidebar when clicking outside on mobile
    document.addEventListener('click', handleOutsideClick);
  }

  function handleClick(event) {
    const target = event.target;
    const actionElement = target.closest('[data-action]');
    const action = actionElement?.getAttribute('data-action');

    if (!action) return;

    // Route to appropriate handler
    switch (action) {
      case 'toggle-sidebar':
      case 'toggle-menu':
        // Both toggle-sidebar (from sidebar) and toggle-menu (from navbar) do the same thing
        event.preventDefault();
        handleSidebarToggle();
        break;

      case 'close-menu':
        // Close menu action (from overlay)
        event.preventDefault();
        if (!State.isDesktop) {
          closeSidebar();
        }
        break;

      case 'toggle-submenu':
        event.preventDefault();
        handleSubmenuToggle(actionElement);  // Pass the actual button, not the click target
        break;

      case 'no-active-season':
        event.preventDefault();
        handleNoActiveSeason();
        break;

      case 'navigate':
      case 'navigate-home':
        // Allow default navigation
        // Close sidebar on mobile after navigation
        if (!State.isDesktop) {
          closeSidebar();
        }
        break;
    }
  }

  function handleOutsideClick(event) {
    // Only on mobile
    if (State.isDesktop) return;

    // Only if sidebar is open
    if (!State.isSidebarOpen) return;

    // Check if click is outside sidebar
    if (!sidebar.contains(event.target)) {
      closeSidebar();
    }
  }

  /**
   * ============================================================================
   * SIDEBAR TOGGLE
   * ============================================================================
   */

  function handleSidebarToggle() {
    if (State.isDesktop) {
      // Desktop: Toggle collapsed state
      toggleCollapsedState();
    } else {
      // Mobile: Toggle open/close
      toggleMobileSidebar();
    }
  }

  function toggleCollapsedState() {
    const isCollapsed = document.body.classList.toggle(CONFIG.classes.collapsed);
    State.collapsedState = isCollapsed;

    // Save to localStorage
    localStorage.setItem(CONFIG.storage.collapsedKey, isCollapsed);

    // Update ARIA
    const toggle = sidebar.querySelector(CONFIG.selectors.sidebarToggle);
    if (toggle) {
      toggle.setAttribute('aria-label', isCollapsed ? 'Expand navigation menu' : 'Collapse navigation menu');
    }

    console.log('Sidebar collapsed state:', isCollapsed);
  }

  function toggleMobileSidebar() {
    if (State.isSidebarOpen) {
      closeSidebar();
    } else {
      openSidebar();
    }
  }

  function openSidebar() {
    sidebar.classList.add(CONFIG.classes.open);
    State.isSidebarOpen = true;

    // Add layout-menu-expanded class to HTML for CSS compatibility with foundation.css
    document.documentElement.classList.add('layout-menu-expanded');

    // Show the existing overlay (from base.html)
    const overlay = document.querySelector('.layout-overlay');
    if (overlay) {
      overlay.classList.add('show');
    }

    // Update ARIA
    sidebar.setAttribute('aria-hidden', 'false');

    // Trap focus in sidebar
    trapFocus(sidebar);

    console.log('Sidebar opened');
  }

  function closeSidebar() {
    sidebar.classList.remove(CONFIG.classes.open);
    State.isSidebarOpen = false;

    // Remove layout-menu-expanded class from HTML
    document.documentElement.classList.remove('layout-menu-expanded');

    // Hide the existing overlay
    const overlay = document.querySelector('.layout-overlay');
    if (overlay) {
      overlay.classList.remove('show');
    }

    // Update ARIA
    sidebar.setAttribute('aria-hidden', 'true');

    // Release focus trap
    releaseFocus();

    console.log('Sidebar closed');
  }

  /**
   * ============================================================================
   * SUBMENU TOGGLE
   * ============================================================================
   */

  function handleSubmenuToggle(button) {
    const item = button.closest(CONFIG.selectors.expandableItem);
    if (!item) return;

    const isOpen = item.classList.toggle(CONFIG.classes.open);

    // Update ARIA
    button.setAttribute('aria-expanded', isOpen);

    // Close other submenus at the same level (optional - comment out for accordion behavior)
    // closeOtherSubmenus(item);

    console.log('Submenu toggled:', isOpen);
  }

  function closeOtherSubmenus(currentItem) {
    const parent = currentItem.parentElement;
    const siblings = Array.from(parent.children).filter(
      child => child !== currentItem && child.matches(CONFIG.selectors.expandableItem)
    );

    siblings.forEach(sibling => {
      sibling.classList.remove(CONFIG.classes.open);
      const toggle = sibling.querySelector(CONFIG.selectors.submenuToggle);
      if (toggle) {
        toggle.setAttribute('aria-expanded', 'false');
      }
    });
  }

  /**
   * ============================================================================
   * SPECIAL ACTIONS
   * ============================================================================
   */

  function handleNoActiveSeason() {
    alert('No active Pub League season');
  }

  /**
   * ============================================================================
   * KEYBOARD NAVIGATION
   * ============================================================================
   */

  function setupKeyboardNavigation() {
    // Guard against duplicate setup
    if (State._keyboardNavSetup) return;
    State._keyboardNavSetup = true;

    sidebar.addEventListener('keydown', handleKeyDown);
  }

  function handleKeyDown(event) {
    const { key, target } = event;

    // Escape closes sidebar on mobile
    if (key === 'Escape' && !State.isDesktop) {
      closeSidebar();
      return;
    }

    // Only handle navigation within links and buttons
    if (!target.matches('a, button')) return;

    switch (key) {
      case 'ArrowUp':
        event.preventDefault();
        focusPreviousItem(target);
        break;

      case 'ArrowDown':
        event.preventDefault();
        focusNextItem(target);
        break;

      case 'Home':
        event.preventDefault();
        focusFirstItem();
        break;

      case 'End':
        event.preventDefault();
        focusLastItem();
        break;
    }
  }

  function focusPreviousItem(currentElement) {
    const focusable = getFocusableElements();
    const currentIndex = focusable.indexOf(currentElement);
    const previousIndex = currentIndex > 0 ? currentIndex - 1 : focusable.length - 1;
    focusable[previousIndex]?.focus();
  }

  function focusNextItem(currentElement) {
    const focusable = getFocusableElements();
    const currentIndex = focusable.indexOf(currentElement);
    const nextIndex = currentIndex < focusable.length - 1 ? currentIndex + 1 : 0;
    focusable[nextIndex]?.focus();
  }

  function focusFirstItem() {
    const focusable = getFocusableElements();
    focusable[0]?.focus();
  }

  function focusLastItem() {
    const focusable = getFocusableElements();
    focusable[focusable.length - 1]?.focus();
  }

  function getFocusableElements() {
    return Array.from(
      sidebar.querySelectorAll('a[href], button:not([disabled])')
    ).filter(el => !el.closest('.c-sidebar__link--disabled'));
  }

  /**
   * ============================================================================
   * ARIA ATTRIBUTES
   * ============================================================================
   */

  function setupAriaAttributes() {
    // Set sidebar role and label
    if (!sidebar.hasAttribute('role')) {
      sidebar.setAttribute('role', 'navigation');
    }
    if (!sidebar.hasAttribute('aria-label')) {
      sidebar.setAttribute('aria-label', 'Main navigation');
    }

    // Set initial aria-hidden for mobile
    if (!State.isDesktop) {
      sidebar.setAttribute('aria-hidden', 'true');
    }

    // Set aria-expanded for all toggle buttons
    const toggles = sidebar.querySelectorAll(CONFIG.selectors.submenuToggle);
    toggles.forEach(toggle => {
      const item = toggle.closest(CONFIG.selectors.expandableItem);
      const isOpen = item?.classList.contains(CONFIG.classes.open);
      toggle.setAttribute('aria-expanded', isOpen);
    });
  }

  /**
   * ============================================================================
   * FOCUS TRAP (MOBILE)
   * ============================================================================
   */

  let focusTrapActive = false;
  let firstFocusableElement = null;
  let lastFocusableElement = null;

  function trapFocus(container) {
    const focusableElements = getFocusableElements();
    firstFocusableElement = focusableElements[0];
    lastFocusableElement = focusableElements[focusableElements.length - 1];

    focusTrapActive = true;

    // Focus first element
    firstFocusableElement?.focus();

    // Handle tab key
    document.addEventListener('keydown', handleFocusTrap);
  }

  function releaseFocus() {
    focusTrapActive = false;
    document.removeEventListener('keydown', handleFocusTrap);
  }

  function handleFocusTrap(event) {
    if (!focusTrapActive || event.key !== 'Tab') return;

    if (event.shiftKey) {
      // Shift + Tab
      if (document.activeElement === firstFocusableElement) {
        event.preventDefault();
        lastFocusableElement?.focus();
      }
    } else {
      // Tab
      if (document.activeElement === lastFocusableElement) {
        event.preventDefault();
        firstFocusableElement?.focus();
      }
    }
  }

  /**
   * ============================================================================
   * BACKDROP (MOBILE)
   * ============================================================================
   */

  function createBackdrop() {
    if (document.querySelector('.c-sidebar-backdrop')) return;

    const backdrop = document.createElement('div');
    backdrop.className = 'c-sidebar-backdrop';
    backdrop.style.cssText = `
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(0, 0, 0, 0.5);
      z-index: ${parseInt(getComputedStyle(sidebar).zIndex) - 1};
      transition: opacity 0.3s ease;
    `;
    document.body.appendChild(backdrop);

    // Fade in
    setTimeout(() => {
      backdrop.style.opacity = '1';
    }, 10);
  }

  function removeBackdrop() {
    const backdrop = document.querySelector('.c-sidebar-backdrop');
    if (!backdrop) return;

    backdrop.style.opacity = '0';
    setTimeout(() => {
      backdrop.remove();
    }, 300);
  }

  /**
   * ============================================================================
   * RESIZE HANDLER
   * ============================================================================
   */

  function setupResizeHandler() {
    // Guard against duplicate setup
    if (State._resizeHandlerSetup) return;
    State._resizeHandlerSetup = true;

    let resizeTimeout;

    window.addEventListener('resize', () => {
      clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(handleResize, 150);
    });
  }

  function handleResize() {
    const wasDesktop = State.isDesktop;
    State.isDesktop = window.innerWidth >= CONFIG.breakpoints.desktop;

    // Desktop to mobile transition
    if (wasDesktop && !State.isDesktop) {
      // Close mobile sidebar
      closeSidebar();
      // Remove collapsed class
      document.body.classList.remove(CONFIG.classes.collapsed);
    }

    // Mobile to desktop transition
    if (!wasDesktop && State.isDesktop) {
      // Close mobile sidebar
      closeSidebar();
      // Restore collapsed state
      if (State.collapsedState) {
        document.body.classList.add(CONFIG.classes.collapsed);
      }
    }
  }

  /**
   * ============================================================================
   * PUBLIC API
   * ============================================================================
   */

  window.SidebarInteractions = {
    open: openSidebar,
    close: closeSidebar,
    toggle: handleSidebarToggle,
    collapse: () => {
      if (State.isDesktop && !State.collapsedState) {
        toggleCollapsedState();
      }
    },
    expand: () => {
      if (State.isDesktop && State.collapsedState) {
        toggleCollapsedState();
      }
    },
  };

  /**
   * ============================================================================
   * AUTO-INITIALIZE
   * ============================================================================
   */

  // Register with InitSystem if available
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('sidebar-interactions', init, {
      priority: 80,
      description: 'Sidebar toggle, collapse, and mobile drawer interactions',
      reinitializable: false
    });
  }

  // ALSO run fallback to ensure initialization even if InitSystem fails to run
  // The internal guard (State._initialized) prevents double initialization
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
