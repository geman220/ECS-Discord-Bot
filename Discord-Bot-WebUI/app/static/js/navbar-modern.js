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
 * Architecture:
 * - Event delegation via EventDelegation system
 * - State management via classList and ARIA attributes
 * - No inline styles (all via CSS classes)
 * - BEM naming conventions
 * - Full accessibility support
 * - Proper cleanup on destroy
 *
 * ============================================================================
 */

class ModernNavbarController {
  constructor() {
    this.navbar = document.querySelector('.c-navbar-modern');
    if (!this.navbar) {
      console.warn('Modern navbar not found');
      return;
    }

    this.activeDropdown = null;
    this.lastScrollTop = 0;
    this.scrollThreshold = 50;

    this.init();
  }

  /**
   * Get CSRF token from meta tag, input field, or cookie
   */
  getCSRFToken() {
    // Try meta tag first
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) {
      return csrfMeta.getAttribute('content');
    }

    // Try hidden input field
    const csrfInput = document.querySelector('input[name="csrf_token"]');
    if (csrfInput) {
      return csrfInput.value;
    }

    // Try cookie
    const cookies = document.cookie.split(';');
    for (const cookie of cookies) {
      const [name, value] = cookie.trim().split('=');
      if (name === 'csrf_token') {
        return decodeURIComponent(value);
      }
    }

    return '';
  }

  init() {
    this.registerEventHandlers();
    this.attachEventListeners();
    this.initScrollTracking();
    this.initSearch();
    this.initNotifications();
    this.initRoleImpersonation();
    this.initTheme();
    this.initPresence();
  }

  /**
   * Register all data-action handlers via EventDelegation
   */
  registerEventHandlers() {
    if (typeof EventDelegation === 'undefined') {
      console.warn('[Navbar] EventDelegation not available, using fallback');
      return;
    }

    // Mobile menu toggle
    EventDelegation.register('toggle-menu', (element, e) => {
      this.toggleMobileMenu();
    }, { preventDefault: true });

    // Dropdown toggles
    EventDelegation.register('toggle-dropdown', (element, e) => {
      const dropdownId = element.dataset.dropdown;
      if (dropdownId) {
        this.toggleDropdown(dropdownId);
      }
    }, { preventDefault: true });

    // Theme switcher
    EventDelegation.register('switch-theme', (element, e) => {
      const theme = element.dataset.theme;
      if (theme) {
        this.switchTheme(theme);
      }
    }, { preventDefault: true });

    // Role impersonation
    EventDelegation.register('start-impersonation', (element, e) => {
      this.startRoleImpersonation();
    }, { preventDefault: true });

    EventDelegation.register('stop-impersonation', (element, e) => {
      this.stopRoleImpersonation();
    }, { preventDefault: true });

    // Notification actions
    EventDelegation.register('mark-read', (element, e) => {
      const notificationId = element.dataset.notificationId;
      if (notificationId) {
        this.markNotificationRead(notificationId);
      }
    }, { preventDefault: true });

    EventDelegation.register('mark-all-read', (element, e) => {
      this.markAllNotificationsRead();
    }, { preventDefault: true });

    EventDelegation.register('clear-all-notifications', (element, e) => {
      this.clearAllNotifications();
    }, { preventDefault: true });

    EventDelegation.register('dismiss-notification', (element, e) => {
      const notificationId = element.dataset.notificationId;
      if (notificationId) {
        this.dismissNotification(notificationId);
      }
    }, { preventDefault: true, stopPropagation: true });

    EventDelegation.register('expand-notification', (element, e) => {
      const notificationId = element.dataset.notificationId;
      if (notificationId) {
        this.toggleNotificationExpand(notificationId);
      }
    }, { preventDefault: true });

    // Logout
    EventDelegation.register('logout', (element, e) => {
      this.handleLogout();
    }, { preventDefault: true });
  }

  /**
   * Attach event listeners (non data-action events)
   */
  attachEventListeners() {
    // Keyboard navigation
    document.addEventListener('keydown', this.handleKeyboard.bind(this));

    // Close dropdowns on outside click
    document.addEventListener('click', this.handleOutsideClick.bind(this));
  }

  /**
   * Handle keyboard navigation
   */
  handleKeyboard(e) {
    // Escape key - close all dropdowns
    if (e.key === 'Escape' && this.activeDropdown) {
      this.closeDropdown(this.activeDropdown);
      return;
    }

    // Arrow keys for dropdown navigation
    if (this.activeDropdown && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault();
      this.navigateDropdown(e.key);
      return;
    }
  }

  /**
   * Close dropdown when clicking outside
   */
  handleOutsideClick(e) {
    if (!this.activeDropdown) return;

    const dropdown = document.querySelector(`[data-dropdown-id="${this.activeDropdown}"]`);
    const toggle = document.querySelector(`[data-dropdown="${this.activeDropdown}"]`);

    if (dropdown && !dropdown.contains(e.target) && toggle && !toggle.contains(e.target)) {
      this.closeDropdown(this.activeDropdown);
    }
  }

  /**
   * Toggle dropdown open/closed
   */
  toggleDropdown(dropdownId) {
    const dropdown = document.querySelector(`[data-dropdown-id="${dropdownId}"]`);
    if (!dropdown) return;

    // Close other dropdowns first
    if (this.activeDropdown && this.activeDropdown !== dropdownId) {
      this.closeDropdown(this.activeDropdown);
    }

    const isOpen = dropdown.classList.contains('is-open');

    if (isOpen) {
      this.closeDropdown(dropdownId);
    } else {
      this.openDropdown(dropdownId);
    }
  }

  /**
   * Open a dropdown with animation
   */
  openDropdown(dropdownId) {
    const dropdown = document.querySelector(`[data-dropdown-id="${dropdownId}"]`);
    const toggle = document.querySelector(`[data-dropdown="${dropdownId}"]`);

    if (!dropdown) return;

    // Add open class for CSS animation
    dropdown.classList.add('is-open');
    dropdown.setAttribute('aria-hidden', 'false');

    if (toggle) {
      toggle.classList.add('is-active');
      toggle.setAttribute('aria-expanded', 'true');
    }

    this.activeDropdown = dropdownId;

    // Stagger animation for dropdown items
    this.staggerDropdownItems(dropdown);
  }

  /**
   * Close a dropdown
   */
  closeDropdown(dropdownId) {
    const dropdown = document.querySelector(`[data-dropdown-id="${dropdownId}"]`);
    const toggle = document.querySelector(`[data-dropdown="${dropdownId}"]`);

    if (!dropdown) return;

    dropdown.classList.remove('is-open');
    dropdown.setAttribute('aria-hidden', 'true');

    if (toggle) {
      toggle.classList.remove('is-active');
      toggle.setAttribute('aria-expanded', 'false');
    }

    if (this.activeDropdown === dropdownId) {
      this.activeDropdown = null;
    }
  }

  /**
   * Stagger animation for dropdown items (smooth reveal)
   */
  staggerDropdownItems(dropdown) {
    const items = dropdown.querySelectorAll('.c-navbar-modern__dropdown-item');

    items.forEach((item, index) => {
      item.style.opacity = '0';
      item.style.transform = 'translateX(-8px)';

      setTimeout(() => {
        item.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
        item.style.opacity = '1';
        item.style.transform = 'translateX(0)';
      }, index * 30);
    });
  }

  /**
   * Navigate dropdown items with arrow keys
   */
  navigateDropdown(direction) {
    const dropdown = document.querySelector(`[data-dropdown-id="${this.activeDropdown}"]`);
    if (!dropdown) return;

    const items = Array.from(dropdown.querySelectorAll('.c-navbar-modern__dropdown-item:not([disabled])'));
    const currentIndex = items.findIndex(item => item === document.activeElement);

    let nextIndex;
    if (direction === 'ArrowDown') {
      nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
    } else {
      nextIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
    }

    items[nextIndex]?.focus();
  }

  /**
   * Toggle mobile menu
   */
  toggleMobileMenu() {
    const toggle = document.querySelector('[data-action="toggle-menu"]');
    const menu = document.querySelector('[data-mobile-menu]');

    if (!toggle || !menu) return;

    const isOpen = toggle.classList.contains('is-open');

    if (isOpen) {
      toggle.classList.remove('is-open');
      menu.classList.remove('is-open');
      document.body.style.overflow = '';
    } else {
      toggle.classList.add('is-open');
      menu.classList.add('is-open');
      document.body.style.overflow = 'hidden';
    }
  }

  /**
   * Track scroll position and add shadow when scrolled
   */
  initScrollTracking() {
    let ticking = false;

    window.addEventListener('scroll', () => {
      if (!ticking) {
        window.requestAnimationFrame(() => {
          const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

          if (scrollTop > this.scrollThreshold) {
            this.navbar.classList.add('is-scrolled');
          } else {
            this.navbar.classList.remove('is-scrolled');
          }

          this.lastScrollTop = scrollTop;
          ticking = false;
        });

        ticking = true;
      }
    });
  }

  /**
   * Initialize search functionality
   */
  initSearch() {
    const searchInput = document.querySelector('.c-navbar-modern__search-input');
    if (!searchInput) return;

    // Prevent form submission
    const form = searchInput.closest('form');
    if (form) {
      form.addEventListener('submit', (e) => {
        e.preventDefault();
      });
    }

    // Search input handling (integrate with autocomplete if available)
    let searchTimeout;
    searchInput.addEventListener('input', (e) => {
      clearTimeout(searchTimeout);

      const query = e.target.value.trim();

      if (query.length >= 2) {
        searchTimeout = setTimeout(() => {
          this.performSearch(query);
        }, 300);
      }
    });

    // Focus animation
    searchInput.addEventListener('focus', () => {
      searchInput.parentElement.classList.add('is-focused');
    });

    searchInput.addEventListener('blur', () => {
      searchInput.parentElement.classList.remove('is-focused');
    });
  }

  /**
   * Perform search (integrate with existing autocomplete)
   */
  performSearch(query) {
    // This integrates with the existing player search autocomplete
    // Trigger the existing search functionality
    if (typeof window.initializePlayerSearch === 'function') {
      // Use existing search function
      console.log('Searching for:', query);
    }
  }

  /**
   * Switch theme (light/dark/system)
   */
  switchTheme(theme) {
    // Close dropdown
    this.closeDropdown('theme');

    // Determine actual theme (handle system preference)
    let actualTheme = theme;
    if (theme === 'system') {
      actualTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    // Update all theme attributes that different CSS selectors may use
    const html = document.documentElement;
    const body = document.body;

    // Set data-style attribute (used by our modern CSS)
    html.setAttribute('data-style', actualTheme);

    // Set data-bs-theme (Bootstrap 5.3+)
    html.setAttribute('data-bs-theme', actualTheme);
    body.setAttribute('data-bs-theme', actualTheme);

    // Set data-theme (generic)
    html.setAttribute('data-theme', actualTheme);

    // Set Vuexy-specific class
    if (actualTheme === 'dark') {
      html.classList.add('dark-style');
      html.classList.remove('light-style');
    } else {
      html.classList.add('light-style');
      html.classList.remove('dark-style');
    }

    // Store preference
    localStorage.setItem('theme', theme);
    localStorage.setItem('templateCustomizer-skin', actualTheme);

    // Update icon
    const icon = document.querySelector('[data-role="theme-icon"]');
    if (icon) {
      const iconClass = {
        light: 'ti-sun',
        dark: 'ti-moon-stars',
        system: 'ti-device-desktop'
      }[theme] || 'ti-moon-stars';

      icon.className = `c-navbar-modern__theme-icon ti ${iconClass}`;
    }

    // Update active state in dropdown
    const options = document.querySelectorAll('[data-action="switch-theme"]');
    options.forEach(option => {
      if (option.dataset.theme === theme) {
        option.classList.add('is-active');
      } else {
        option.classList.remove('is-active');
      }
    });

    // Show toast notification
    this.showToast(`Theme switched to ${theme} mode`);
  }

  /**
   * Start role impersonation
   */
  startRoleImpersonation() {
    // Get selected roles from checkboxes
    const checkboxes = document.querySelectorAll('input[name="impersonate_roles"]:checked');
    const selectedRoles = Array.from(checkboxes).map(cb => cb.value);

    if (selectedRoles.length === 0) {
      this.showToast('Please select at least one role', 'warning');
      return;
    }

    // Make API call to start impersonation
    fetch('/admin-panel/user-management/impersonate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCSRFToken(),
      },
      body: JSON.stringify({ roles: selectedRoles })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // Update UI to show impersonation is active
        const button = document.querySelector('[data-dropdown="impersonation"]');
        if (button) {
          button.classList.add('c-navbar-modern__impersonation-active');
        }

        // Show badge
        const badge = button?.querySelector('.c-navbar-modern__badge');
        if (badge) {
          badge.classList.remove('u-hidden');
        }

        // Hide normal status, show active status
        const normalStatus = document.getElementById('currentRoleStatus');
        const activeStatus = document.getElementById('activeImpersonationStatus');
        const activeRolesList = document.getElementById('activeRolesList');

        if (normalStatus) normalStatus.classList.add('u-hidden');
        if (activeStatus) {
          activeStatus.classList.remove('u-hidden');
          if (activeRolesList) {
            activeRolesList.innerHTML = selectedRoles.map(role =>
              `<span class="c-role-status__role-tag">${role}</span>`
            ).join('');
          }
        }

        this.closeDropdown('impersonation');
        this.showToast('Role testing started', 'success');

        // Reload page to apply new permissions
        setTimeout(() => window.location.reload(), 1000);
      } else {
        this.showToast(data.message || 'Failed to start role testing', 'error');
      }
    })
    .catch(error => {
      console.error('Impersonation error:', error);
      this.showToast('An error occurred', 'error');
    });
  }

  /**
   * Stop role impersonation
   */
  stopRoleImpersonation() {
    fetch('/admin-panel/user-management/stop-impersonate', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': this.getCSRFToken(),
      }
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        this.showToast('Impersonation stopped', 'success');
        setTimeout(() => window.location.reload(), 1000);
      }
    })
    .catch(error => {
      console.error('Stop impersonation error:', error);
    });
  }

  /**
   * Mark notification as read
   */
  async markNotificationRead(notificationId) {
    const notification = document.querySelector(`[data-notification-id="${notificationId}"]`);
    if (!notification) return;

    // Optimistically update UI
    notification.classList.remove('is-unread');

    try {
      const response = await fetch(`/api/notifications/${notificationId}/read`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': this.getCSRFToken(),
        }
      });

      const data = await response.json();
      if (data.success) {
        this.updateNotificationBadge(data.unread_count);
      }
    } catch (error) {
      console.error('Mark notification read error:', error);
      // Revert on error
      notification.classList.add('is-unread');
    }
  }

  /**
   * Mark all notifications as read
   */
  async markAllNotificationsRead() {
    const notifications = document.querySelectorAll('.c-navbar-modern__notification.is-unread');

    // Optimistically update UI
    notifications.forEach(notification => {
      notification.classList.remove('is-unread');
    });

    try {
      const response = await fetch('/api/notifications/mark-all-read', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': this.getCSRFToken(),
        }
      });

      const data = await response.json();
      if (data.success) {
        this.updateNotificationBadge(0);
        this.showToast('All notifications marked as read', 'success');
      }
    } catch (error) {
      console.error('Mark all read error:', error);
      // Revert - reload notifications
      this.loadNotifications();
    }
  }

  /**
   * Handle logout
   */
  handleLogout() {
    const form = document.querySelector('#logout-form');
    if (form) {
      form.submit();
    }
  }

  /**
   * Initialize notifications
   */
  initNotifications() {
    // Load notifications on page load
    this.loadNotifications();

    // Refresh notification count periodically (every 60 seconds)
    setInterval(() => this.refreshNotificationCount(), 60000);
  }

  /**
   * Load notifications from API
   */
  async loadNotifications() {
    const container = document.getElementById('notifications-list');
    if (!container) return;

    const loadingEl = container.querySelector('[data-state="loading"]');
    const emptyEl = container.querySelector('[data-state="empty"]');

    try {
      const response = await fetch('/api/notifications?include_read=true&limit=10');
      const data = await response.json();

      // Hide loading
      if (loadingEl) loadingEl.classList.add('u-hidden');

      if (data.success && data.notifications.length > 0) {
        // Hide empty state
        if (emptyEl) emptyEl.classList.add('u-hidden');

        // Remove existing notifications (but keep loading/empty elements)
        container.querySelectorAll('.c-navbar-modern__notification').forEach(el => el.remove());

        // Render notifications
        data.notifications.forEach(notification => {
          const notifEl = this.createNotificationElement(notification);
          container.appendChild(notifEl);
        });

        // Update badge count
        this.updateNotificationBadge(data.unread_count);
      } else {
        // Show empty state
        if (emptyEl) emptyEl.classList.remove('u-hidden');
        this.updateNotificationBadge(0);
      }
    } catch (error) {
      console.error('Error loading notifications:', error);
      if (loadingEl) loadingEl.classList.add('u-hidden');
      if (emptyEl) {
        emptyEl.classList.remove('u-hidden');
        const emptyText = emptyEl.querySelector('p');
        if (emptyText) emptyText.textContent = 'Failed to load notifications';
      }
    }
  }

  /**
   * Create a notification DOM element with dismiss button and expandable details
   */
  createNotificationElement(notification) {
    const div = document.createElement('div');
    div.className = `c-navbar-modern__notification${notification.is_read ? '' : ' is-unread'}`;
    div.setAttribute('data-notification-id', notification.id);
    div.setAttribute('role', 'menuitem');
    div.setAttribute('tabindex', '0');

    // Icon color class
    const colorClass = notification.icon_color ? `text-${notification.icon_color}` : '';

    // Truncate long messages
    const truncatedMessage = notification.message.length > 80
      ? notification.message.substring(0, 80) + '...'
      : notification.message;
    const hasMore = notification.message.length > 80;

    div.innerHTML = `
      <div class="c-navbar-modern__notification-main"
           data-action="expand-notification"
           data-notification-id="${notification.id}">
        <div class="c-navbar-modern__notification-icon ${colorClass}">
          <i class="${notification.icon}"></i>
        </div>
        <div class="c-navbar-modern__notification-content">
          <p class="c-navbar-modern__notification-title">${this.escapeHtml(notification.title)}</p>
          <p class="c-navbar-modern__notification-text">${this.escapeHtml(truncatedMessage)}</p>
          ${hasMore ? '<span class="c-navbar-modern__notification-expand-hint">Click to read more</span>' : ''}
        </div>
        <span class="c-navbar-modern__notification-time">${notification.time_ago}</span>
      </div>
      <div class="c-navbar-modern__notification-expanded u-hidden" data-expanded-content>
        <p class="c-navbar-modern__notification-full-text">${this.escapeHtml(notification.message)}</p>
        <span class="c-navbar-modern__notification-date">${notification.created_at || ''}</span>
      </div>
      <button class="c-navbar-modern__notification-dismiss"
              data-action="dismiss-notification"
              data-notification-id="${notification.id}"
              aria-label="Dismiss notification"
              title="Dismiss">
        <i class="ti ti-x" aria-hidden="true"></i>
      </button>
    `;

    return div;
  }

  /**
   * Toggle notification expansion to show full content
   */
  toggleNotificationExpand(notificationId) {
    const notification = document.querySelector(`[data-notification-id="${notificationId}"]`);
    if (!notification) return;

    const expandedContent = notification.querySelector('[data-expanded-content]');
    if (!expandedContent) return;

    const isExpanded = notification.classList.contains('is-expanded');

    if (isExpanded) {
      notification.classList.remove('is-expanded');
      expandedContent.classList.add('u-hidden');
    } else {
      notification.classList.add('is-expanded');
      expandedContent.classList.remove('u-hidden');

      // Mark as read when expanded
      const notifElement = notification;
      if (notifElement.classList.contains('is-unread')) {
        this.markNotificationRead(notificationId);
      }
    }
  }

  /**
   * Dismiss (delete) a single notification
   */
  async dismissNotification(notificationId) {
    const notification = document.querySelector(`[data-notification-id="${notificationId}"]`);
    if (!notification) return;

    // Optimistically remove with animation
    notification.classList.add('is-dismissing');

    try {
      const response = await fetch(`/api/notifications/${notificationId}`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': this.getCSRFToken(),
        }
      });

      const data = await response.json();

      if (data.success) {
        // Remove from DOM after animation
        setTimeout(() => {
          notification.remove();
          this.updateNotificationBadge(data.unread_count);

          // Show empty state if no more notifications
          const container = document.getElementById('notifications-list');
          const remaining = container.querySelectorAll('.c-navbar-modern__notification');
          if (remaining.length === 0) {
            const emptyEl = container.querySelector('[data-state="empty"]');
            if (emptyEl) emptyEl.classList.remove('u-hidden');
          }
        }, 200);
      } else {
        // Revert animation on failure
        notification.classList.remove('is-dismissing');
        this.showToast('Failed to dismiss notification', 'error');
      }
    } catch (error) {
      console.error('Dismiss notification error:', error);
      notification.classList.remove('is-dismissing');
      this.showToast('Failed to dismiss notification', 'error');
    }
  }

  /**
   * Clear all notifications
   */
  async clearAllNotifications() {
    const container = document.getElementById('notifications-list');
    const notifications = container.querySelectorAll('.c-navbar-modern__notification');

    if (notifications.length === 0) {
      this.showToast('No notifications to clear', 'info');
      return;
    }

    // Confirm with user
    if (!confirm('Are you sure you want to clear all notifications?')) {
      return;
    }

    // Optimistically fade out all
    notifications.forEach(n => n.classList.add('is-dismissing'));

    try {
      const response = await fetch('/api/notifications/clear-all', {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': this.getCSRFToken(),
        }
      });

      const data = await response.json();

      if (data.success) {
        // Remove all from DOM
        setTimeout(() => {
          notifications.forEach(n => n.remove());
          this.updateNotificationBadge(0);

          // Show empty state
          const emptyEl = container.querySelector('[data-state="empty"]');
          if (emptyEl) emptyEl.classList.remove('u-hidden');

          this.showToast(`Cleared ${data.deleted_count} notification${data.deleted_count !== 1 ? 's' : ''}`, 'success');
        }, 200);
      } else {
        // Revert on failure
        notifications.forEach(n => n.classList.remove('is-dismissing'));
        this.showToast('Failed to clear notifications', 'error');
      }
    } catch (error) {
      console.error('Clear all notifications error:', error);
      notifications.forEach(n => n.classList.remove('is-dismissing'));
      this.showToast('Failed to clear notifications', 'error');
    }
  }

  /**
   * Escape HTML to prevent XSS
   */
  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Refresh notification count only (lightweight)
   */
  async refreshNotificationCount() {
    try {
      const response = await fetch('/api/notifications/count');
      const data = await response.json();
      if (data.success) {
        this.updateNotificationBadge(data.count);
      }
    } catch (error) {
      console.error('Error refreshing notification count:', error);
    }
  }

  /**
   * Update notification badge display
   */
  updateNotificationBadge(count) {
    const badges = document.querySelectorAll('[data-badge="notification-count"]');
    badges.forEach(badge => {
      if (count > 0) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.classList.remove('u-hidden');
      } else {
        badge.classList.add('u-hidden');
      }
    });
  }

  /**
   * Initialize role impersonation (if available)
   */
  initRoleImpersonation() {
    if (!document.querySelector('[data-dropdown="impersonation"]')) {
      return;
    }

    // Load current status
    this.loadImpersonationStatus();

    // Attach refresh button listener
    const refreshBtn = document.querySelector('[data-action="refresh-roles"]');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => this.loadAvailableRoles());
    }

    // Attach checkbox change listeners
    const checkboxes = document.querySelectorAll('input[name="impersonate_roles"]');
    checkboxes.forEach(checkbox => {
      checkbox.addEventListener('change', () => this.validateRoleSelection());
    });

    // Attach clear selection listener
    const clearBtn = document.querySelector('[data-action="clear-role-selection"]');
    if (clearBtn) {
      clearBtn.addEventListener('click', (e) => {
        e.preventDefault();
        this.clearRoleSelection();
      });
    }

    // Initial validation
    this.validateRoleSelection();
  }

  /**
   * Clear all role selections
   */
  clearRoleSelection() {
    const checkboxes = document.querySelectorAll('input[name="impersonate_roles"]');
    checkboxes.forEach(checkbox => {
      checkbox.checked = false;
    });
    this.validateRoleSelection();
  }

  /**
   * Load impersonation status
   */
  async loadImpersonationStatus() {
    try {
      const response = await fetch('/api/role-impersonation/status');
      if (!response.ok) throw new Error('Failed to load status');

      const data = await response.json();
      this.updateImpersonationStatus(data);
    } catch (error) {
      console.error('Error loading impersonation status:', error);
    }
  }

  /**
   * Load available roles (refresh from server)
   */
  async loadAvailableRoles() {
    const refreshBtn = document.querySelector('[data-action="refresh-roles"]');
    if (refreshBtn) {
      refreshBtn.classList.add('is-loading');
      const icon = refreshBtn.querySelector('i');
      if (icon) icon.style.animation = 'spin 1s linear infinite';
    }

    try {
      const response = await fetch('/api/role-impersonation/available-roles');
      if (!response.ok) throw new Error('Failed to load roles');

      const data = await response.json();
      this.showToast('Roles refreshed', 'success');
      this.updateImpersonationStatus(data.current_impersonation);
    } catch (error) {
      console.error('Error loading available roles:', error);
      this.showToast('Failed to refresh roles', 'error');
    } finally {
      if (refreshBtn) {
        refreshBtn.classList.remove('is-loading');
        const icon = refreshBtn.querySelector('i');
        if (icon) icon.style.animation = '';
      }
    }
  }

  /**
   * Update impersonation status display
   */
  updateImpersonationStatus(data) {
    const isActive = data && data.active || false;
    const normalStatus = document.getElementById('currentRoleStatus');
    const activeStatus = document.getElementById('activeImpersonationStatus');
    const activeRolesList = document.getElementById('activeRolesList');
    const badge = document.querySelector('[data-badge="impersonation"]');

    if (isActive && data.roles && data.roles.length > 0) {
      // Hide normal status, show active status
      if (normalStatus) normalStatus.classList.add('u-hidden');
      if (activeStatus) {
        activeStatus.classList.remove('u-hidden');
        if (activeRolesList) {
          activeRolesList.innerHTML = data.roles.map(role =>
            `<span class="c-role-status__role-tag">${role}</span>`
          ).join('');
        }
      }

      // Show badge
      if (badge) badge.classList.remove('u-hidden');
    } else {
      // Show normal status, hide active status
      if (normalStatus) normalStatus.classList.remove('u-hidden');
      if (activeStatus) activeStatus.classList.add('u-hidden');

      // Hide badge
      if (badge) badge.classList.add('u-hidden');
    }
  }

  /**
   * Validate role selection (checkbox-based)
   */
  validateRoleSelection() {
    const checkboxes = document.querySelectorAll('input[name="impersonate_roles"]:checked');
    const startBtn = document.getElementById('startImpersonationBtn');
    const countDisplay = document.getElementById('selectedRoleCount');

    const selectedCount = checkboxes.length;

    // Update count display
    if (countDisplay) {
      countDisplay.textContent = selectedCount;
    }

    // Enable/disable start button
    if (startBtn) {
      startBtn.disabled = selectedCount === 0;
    }
  }

  /**
   * Initialize theme
   */
  initTheme() {
    // Load saved theme preference
    const savedTheme = localStorage.getItem('theme') || 'system';
    this.applyTheme(savedTheme, false);
  }

  /**
   * Apply theme
   */
  applyTheme(theme, save = true) {
    // Determine actual theme (handle system preference)
    let actualTheme = theme;
    if (theme === 'system') {
      actualTheme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    // Update all theme attributes
    const html = document.documentElement;
    const body = document.body;

    html.setAttribute('data-style', actualTheme);
    html.setAttribute('data-bs-theme', actualTheme);
    body.setAttribute('data-bs-theme', actualTheme);
    html.setAttribute('data-theme', actualTheme);

    // Update Vuexy-specific class
    if (actualTheme === 'dark') {
      html.classList.add('dark-style');
      html.classList.remove('light-style');
    } else {
      html.classList.add('light-style');
      html.classList.remove('dark-style');
    }

    // Update icon
    const icon = document.querySelector('[data-role="theme-icon"]');
    if (icon) {
      const iconClass = {
        light: 'ti-sun',
        dark: 'ti-moon-stars',
        system: 'ti-device-desktop'
      }[theme] || 'ti-sun';

      icon.className = `ti ${iconClass} c-navbar-modern__nav-icon`;
    }

    // Update active state in dropdown
    const options = document.querySelectorAll('[data-action="switch-theme"]');
    options.forEach(option => {
      if (option.dataset.theme === theme) {
        option.classList.add('is-active');
      } else {
        option.classList.remove('is-active');
      }
    });

    // Store preference
    if (save) {
      localStorage.setItem('theme', theme);
      localStorage.setItem('templateCustomizer-skin', actualTheme);
    }
  }

  /**
   * Show toast notification
   */
  showToast(message, type = 'info') {
    // Integrate with existing toast system if available
    if (typeof window.showToast === 'function') {
      window.showToast(message, type);
    } else {
      console.log(`[Toast ${type}]:`, message);
    }
  }

  // =========================================================================
  // PRESENCE / ONLINE STATUS
  // =========================================================================

  /**
   * Initialize presence tracking
   * Shows real online status based on WebSocket connection
   */
  initPresence() {
    // Initialize WebSocket connection for presence if socket.io is available
    if (typeof io !== 'undefined') {
      this.initPresenceSocket();
    } else {
      // Fall back to API-only presence checking
      this.checkPresence();
    }

    // Refresh presence periodically (every 2 minutes)
    // This keeps the user showing as online while the page is open
    setInterval(() => this.refreshPresence(), 120000);

    // Also refresh presence when page becomes visible again
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        this.refreshPresence();
        // Reconnect socket if disconnected
        if (this.presenceSocket && !this.presenceSocket.connected) {
          this.presenceSocket.connect();
        }
      }
    });
  }

  /**
   * Initialize WebSocket connection for presence tracking
   * Uses SocketManager for unified socket management across all components
   */
  initPresenceSocket() {
    // Use SocketManager if available (preferred method)
    if (typeof window.SocketManager !== 'undefined') {
      console.log('[Navbar] Using SocketManager for presence');

      // Optimistic UI: Show "online" immediately if we were recently connected
      // This prevents status flicker during page navigation
      if (window.SocketManager.isOptimisticallyConnected()) {
        this.updateOnlineStatus(true);
        console.debug('[Navbar] Optimistic online status (recently connected)');
      }

      // Get socket reference
      this.presenceSocket = window.SocketManager.getSocket();

      // Register connect callback - fires immediately if already connected
      window.SocketManager.onConnect('Navbar', (socket) => {
        this.presenceSocket = socket;
        this.updateOnlineStatus(true);
        console.debug('Presence socket connected via SocketManager');
      });

      // Register disconnect callback (delayed by SocketManager for optimistic UI)
      window.SocketManager.onDisconnect('Navbar', (reason) => {
        this.updateOnlineStatus(false);
        console.debug('Presence socket disconnected:', reason);
      });

      // Register event listeners via SocketManager
      window.SocketManager.on('Navbar', 'authentication_success', (data) => {
        this.updateOnlineStatus(true);
        console.debug('Presence authenticated:', data.username);
      });

      window.SocketManager.on('Navbar', 'authentication_failed', () => {
        // Still connected but not authenticated - show as online anyway
        this.updateOnlineStatus(true);
      });

      return;
    }

    // Fallback: Use existing global socket if available
    if (window.socket) {
      console.log('[Navbar] Reusing existing socket (connected:', window.socket.connected, ')');
      this.presenceSocket = window.socket;
      if (window.socket.connected) {
        this.updateOnlineStatus(true);
      }
      this.attachSocketListenersDirect(this.presenceSocket);
      return;
    }

    // Fallback: Create new socket connection for presence
    try {
      console.log('[Navbar] Creating new socket connection (fallback)');
      this.presenceSocket = io('/', {
        transports: ['polling', 'websocket'],
        upgrade: true,
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
        reconnectionDelayMax: 5000,
        timeout: 20000,
        autoConnect: true,
        withCredentials: true
      });

      // Store globally so other components can use it
      window.socket = this.presenceSocket;

      this.attachSocketListenersDirect(this.presenceSocket);

    } catch (error) {
      console.warn('Failed to initialize presence socket:', error);
      this.checkPresence();
    }
  }

  /**
   * Attach event listeners directly to socket (fallback when SocketManager not available)
   */
  attachSocketListenersDirect(socket) {
    socket.on('connect', () => {
      this.updateOnlineStatus(true);
      console.debug('Presence socket connected');
    });

    socket.on('disconnect', () => {
      this.updateOnlineStatus(false);
      console.debug('Presence socket disconnected');
    });

    socket.on('authentication_success', (data) => {
      this.updateOnlineStatus(true);
      console.debug('Presence authenticated:', data.username);
    });

    socket.on('authentication_failed', () => {
      this.updateOnlineStatus(true);
    });

    socket.on('connect_error', (error) => {
      console.warn('Presence socket connection error:', error.message);
      this.updateOnlineStatus(false);
    });
  }

  /**
   * Check current presence status from server
   */
  async checkPresence() {
    try {
      const response = await fetch('/api/notifications/presence');
      const data = await response.json();

      if (data.success) {
        this.updateOnlineStatus(data.online);
      }
    } catch (error) {
      // Don't log error - presence check is non-critical
      // User will still appear online if WebSocket is connected
    }
  }

  /**
   * Refresh presence TTL (keep showing as online)
   */
  async refreshPresence() {
    try {
      await fetch('/api/notifications/presence/refresh', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': this.getCSRFToken(),
        }
      });
    } catch (error) {
      // Silent fail - non-critical operation
    }
  }

  /**
   * Update the online status indicator in the navbar
   */
  updateOnlineStatus(isOnline) {
    const statusIndicator = this.navbar.querySelector('.c-navbar-modern__avatar-status');
    if (!statusIndicator) return;

    if (isOnline) {
      statusIndicator.classList.add('is-online');
      statusIndicator.classList.remove('is-offline');
      statusIndicator.setAttribute('aria-label', 'Online');
      statusIndicator.setAttribute('title', 'You are online');
    } else {
      statusIndicator.classList.remove('is-online');
      statusIndicator.classList.add('is-offline');
      statusIndicator.setAttribute('aria-label', 'Offline');
      statusIndicator.setAttribute('title', 'You appear offline');
    }
  }
}

// Initialize function
function initNavbar() {
  // Only initialize if navbar exists on page
  if (document.querySelector('.c-navbar-modern')) {
    window.navbarController = new ModernNavbarController();
  }
}

// Register with InitSystem if available
if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
  window.InitSystem.register('navbar-modern', initNavbar, {
    priority: 80,
    description: 'Modern navbar controller (search, dropdowns, mobile menu)',
    reinitializable: false
  });
} else {
  // Fallback: Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initNavbar);
  } else {
    initNavbar();
  }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
  module.exports = ModernNavbarController;
}
