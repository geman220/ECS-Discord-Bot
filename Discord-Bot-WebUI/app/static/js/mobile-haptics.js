/**
 * Mobile Haptics - Vibration API Wrapper
 *
 * Provides tactile feedback for mobile user interactions using the Vibration API.
 * Enhances UX by confirming actions, indicating errors, and providing feedback.
 *
 * Browser Support:
 * - Chrome Android 32+
 * - Firefox Android 79+
 * - Safari iOS 13+ (limited)
 * - Gracefully degrades on unsupported devices
 */
// ES Module
'use strict';

/**
   * Haptics controller with various vibration patterns
   */
  export const Haptics = {
    /**
     * Check if Vibration API is supported
     * @returns {boolean}
     */
    isSupported: function () {
      return 'vibrate' in navigator || 'mozVibrate' in navigator || 'webkitVibrate' in navigator;
    },

    /**
     * Normalize vibration method across browsers
     * @private
     */
    _vibrate: function (pattern) {
      if (!this.isSupported()) {
        return false;
      }

      // Check if vibration is enabled in settings (could be stored in localStorage)
      if (this.isDisabled()) {
        return false;
      }

      try {
        if (navigator.vibrate) {
          return navigator.vibrate(pattern);
        } else if (navigator.mozVibrate) {
          return navigator.mozVibrate(pattern);
        } else if (navigator.webkitVibrate) {
          return navigator.webkitVibrate(pattern);
        }
      } catch (e) {
        console.warn('Haptics error:', e);
        return false;
      }
    },

    /**
     * Check if haptics is disabled by user preference
     * @returns {boolean}
     */
    isDisabled: function () {
      return localStorage.getItem('haptics-disabled') === 'true';
    },

    /**
     * Enable haptic feedback
     */
    enable: function () {
      localStorage.removeItem('haptics-disabled');
    },

    /**
     * Disable haptic feedback
     */
    disable: function () {
      localStorage.setItem('haptics-disabled', 'true');
    },

    /**
     * Toggle haptic feedback on/off
     * @returns {boolean} New state (true = enabled)
     */
    toggle: function () {
      if (this.isDisabled()) {
        this.enable();
        return true;
      } else {
        this.disable();
        return false;
      }
    },

    /**
     * Stop any ongoing vibration
     */
    stop: function () {
      this._vibrate(0);
    },

    /* ===== Intensity Levels ===== */

    /**
     * Light haptic feedback (10ms)
     * Use for: hover states, selections, minor interactions
     */
    light: function () {
      return this._vibrate(10);
    },

    /**
     * Medium haptic feedback (20ms)
     * Use for: button taps, form submissions, standard interactions
     */
    medium: function () {
      return this._vibrate(20);
    },

    /**
     * Heavy haptic feedback (30ms)
     * Use for: important actions, confirmations, alerts
     */
    heavy: function () {
      return this._vibrate(30);
    },

    /* ===== Notification Patterns ===== */

    /**
     * Success pattern (short-pause-short)
     * Use for: successful submissions, confirmations, completions
     */
    success: function () {
      return this._vibrate([10, 50, 10]);
    },

    /**
     * Error pattern (long-pause-long)
     * Use for: validation errors, failed actions, warnings
     */
    error: function () {
      return this._vibrate([30, 100, 30]);
    },

    /**
     * Warning pattern (medium-pause-medium)
     * Use for: caution messages, important notices
     */
    warning: function () {
      return this._vibrate([20, 50, 20]);
    },

    /**
     * Notification pattern (short pulses)
     * Use for: new messages, alerts, reminders
     */
    notification: function () {
      return this._vibrate([10, 30, 10, 30, 10]);
    },

    /* ===== Interaction Patterns ===== */

    /**
     * Selection pattern (single short pulse)
     * Use for: selecting items, toggling checkboxes, radio buttons
     */
    selection: function () {
      return this._vibrate(15);
    },

    /**
     * Deselection pattern (two very short pulses)
     * Use for: deselecting items, clearing selections
     */
    deselection: function () {
      return this._vibrate([8, 20, 8]);
    },

    /**
     * Swipe pattern (quick pulse)
     * Use for: swipe gestures, page transitions
     */
    swipe: function () {
      return this._vibrate(12);
    },

    /**
     * Long press pattern (sustained vibration)
     * Use for: indicating long press is detected, context menus
     */
    longPress: function () {
      return this._vibrate(50);
    },

    /**
     * Double tap pattern (two short pulses)
     * Use for: double tap gestures, quick actions
     */
    doubleTap: function () {
      return this._vibrate([15, 30, 15]);
    },

    /* ===== Draft-Specific Patterns ===== */

    /**
     * Player drafted pattern (celebratory)
     * Use for: successful draft picks
     */
    drafted: function () {
      return this._vibrate([20, 50, 20, 50, 30]);
    },

    /**
     * Invalid selection pattern (rejection)
     * Use for: trying to draft ineligible players
     */
    invalidSelection: function () {
      return this._vibrate([40, 60, 40]);
    },

    /**
     * Time warning pattern (urgent)
     * Use for: draft timer running low
     */
    timeWarning: function () {
      return this._vibrate([25, 100, 25, 100, 25]);
    },

    /* ===== Form Patterns ===== */

    /**
     * Input focus pattern (subtle)
     * Use for: focusing form inputs
     */
    inputFocus: function () {
      return this._vibrate(8);
    },

    /**
     * Input validation error pattern
     * Use for: real-time validation errors
     */
    validationError: function () {
      return this._vibrate([25, 50, 25]);
    },

    /**
     * Form submission pattern
     * Use for: form submit button taps
     */
    formSubmit: function () {
      return this._vibrate(18);
    },

    /* ===== Navigation Patterns ===== */

    /**
     * Menu open pattern
     * Use for: opening sidebar, dropdowns
     */
    menuOpen: function () {
      return this._vibrate(15);
    },

    /**
     * Menu close pattern
     * Use for: closing sidebar, dropdowns
     */
    menuClose: function () {
      return this._vibrate(12);
    },

    /**
     * Modal open pattern
     * Use for: opening modals, bottom sheets
     */
    modalOpen: function () {
      return this._vibrate([10, 30, 15]);
    },

    /**
     * Modal close pattern
     * Use for: closing modals, bottom sheets
     */
    modalClose: function () {
      return this._vibrate(15);
    },

    /* ===== Table/List Patterns ===== */

    /**
     * Refresh pattern (pull-to-refresh)
     * Use for: refresh actions, data reloads
     */
    refresh: function () {
      return this._vibrate([15, 50, 15, 50, 20]);
    },

    /**
     * Delete pattern (destructive action)
     * Use for: swipe-to-delete, item removal
     */
    delete: function () {
      return this._vibrate([35, 60, 35]);
    },

    /**
     * Archive pattern
     * Use for: archiving items
     */
    archive: function () {
      return this._vibrate([12, 40, 12]);
    },

    /* ===== Custom Pattern ===== */

    /**
     * Play a custom vibration pattern
     * @param {number|number[]} pattern - Duration or array of [vibrate, pause, vibrate, ...]
     * @returns {boolean} Success
     */
    custom: function (pattern) {
      return this._vibrate(pattern);
    }
  };

  /**
   * Initialize haptics with event delegation
   * ROOT CAUSE FIX: Uses document-level event delegation instead of per-element listeners
   */
  window.Haptics._initialized = false;
  window.Haptics.init = function () {
    // Only initialize once - event delegation handles all elements
    if (this._initialized) return;
    this._initialized = true;

    if (!this.isSupported()) {
      console.log('Haptics: Vibration API not supported');
      return;
    }

    const self = this;

    // Single delegated click listener for ALL buttons and nav links
    document.addEventListener('click', function(e) {
      // Handle buttons
      const btn = e.target.closest('.btn:not([data-haptics="false"])');
      if (btn) {
        if (btn.classList.contains('btn-success')) {
          self.success();
        } else if (btn.classList.contains('btn-danger')) {
          self.warning();
        } else {
          self.medium();
        }
        return;
      }

      // Handle nav links
      const navLink = e.target.closest('.nav-link:not([data-haptics="false"])');
      if (navLink) {
        self.light();
        return;
      }
    }, { passive: true });

    // Single delegated focusin listener for ALL form inputs
    document.addEventListener('focusin', function(e) {
      const input = e.target;
      if (input.classList.contains('form-control') || input.classList.contains('form-select')) {
        self.inputFocus();
      }
    }, { passive: true });

    // Single delegated invalid listener for ALL form inputs
    document.addEventListener('invalid', function(e) {
      const input = e.target;
      if (input.classList.contains('form-control') || input.classList.contains('form-select')) {
        self.validationError();
      }
    }, true); // Use capture phase for invalid events

    // Single delegated change listener for ALL checkboxes and radios
    document.addEventListener('change', function(e) {
      const input = e.target;
      if (input.type === 'checkbox' || input.type === 'radio') {
        if (input.checked) {
          self.selection();
        } else {
          self.deselection();
        }
      }
    }, { passive: true });

    // Note: Modal haptics are handled by responsive-system.js via delegation
    // No need to duplicate here - keeping for backwards compatibility with older code
    // that may call Haptics.modalOpen() / Haptics.modalClose() directly

    console.log('Haptics: Initialized with event delegation');
  };

  // Expose globally (MUST be before any callbacks or registrations)
  window.Haptics = Haptics;

  // Auto-initialize
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => window.Haptics.init());
  } else {
    window.Haptics.init();
  }

