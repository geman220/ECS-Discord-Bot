/**
 * Mobile Keyboard - Soft Keyboard Handler
 *
 * Handles mobile keyboard interactions, viewport adjustments, and input optimization.
 * Addresses common issues: iOS keyboard overlap, Android soft keyboard, scroll-into-view.
 *
 * Features:
 * - Keyboard show/hide detection
 * - Automatic scroll input into view
 * - Dropdown positioning aware of keyboard
 * - Input type optimization
 * - iOS-specific fixes
 *
 * REFACTORED: All inline style manipulations replaced with CSS classes
 */
// ES Module
'use strict';

import { InitSystem } from './init-system.js';

let _initialized = false;

/**
   * Mobile Keyboard Controller
   */
export const MobileKeyboard = {
    /**
     * Current keyboard state
     */
    state: {
      isVisible: false,
      keyboardHeight: 0,
      activeInput: null,
      originalViewportHeight: window.innerHeight
    },

    /**
     * Check if device is mobile
     * @returns {boolean}
     */
    isMobile: function () {
      return window.innerWidth < 768;
    },

    /**
     * Check if device is iOS
     * @returns {boolean}
     */
    isIOS: function () {
      return /iPhone|iPad|iPod/.test(navigator.userAgent);
    },

    /**
     * Check if device is Android
     * @returns {boolean}
     */
    isAndroid: function () {
      return /Android/.test(navigator.userAgent);
    },

    /**
     * Detect keyboard visibility by viewport height change
     */
    detectKeyboard: function () {
      const currentHeight = window.innerHeight;
      const heightDiff = this.state.originalViewportHeight - currentHeight;

      // Keyboard is considered visible if viewport shrinks by more than 150px
      if (heightDiff > 150) {
        if (!this.state.isVisible) {
          this.state.isVisible = true;
          this.state.keyboardHeight = heightDiff;
          this.onKeyboardShow();
        }
      } else {
        if (this.state.isVisible) {
          this.state.isVisible = false;
          this.state.keyboardHeight = 0;
          this.onKeyboardHide();
        }
      }
    },

    /**
     * Called when keyboard is shown
     */
    onKeyboardShow: function () {
      document.documentElement.classList.add('keyboard-visible');
      document.body.classList.add('keyboard-visible');

      // Dispatch custom event
      const event = new CustomEvent('mobile:keyboardshow', {
        detail: { height: this.state.keyboardHeight }
      });
      window.dispatchEvent(event);

      // Adjust modals
      this.adjustModalsForKeyboard();

      // Adjust dropdowns
      this.adjustDropdownsForKeyboard();

      console.log('Keyboard shown, height:', this.state.keyboardHeight);
    },

    /**
     * Called when keyboard is hidden
     */
    onKeyboardHide: function () {
      document.documentElement.classList.remove('keyboard-visible');
      document.body.classList.remove('keyboard-visible');

      // Dispatch custom event
      const event = new CustomEvent('mobile:keyboardhide');
      window.dispatchEvent(event);

      // Reset modal adjustments
      this.resetModalAdjustments();

      console.log('Keyboard hidden');
    },

    /**
     * Adjust modal position when keyboard is visible
     * REFACTORED: Using CSS classes instead of inline styles
     */
    adjustModalsForKeyboard: function () {
      document.querySelectorAll('[data-modal].show').forEach(modal => {
        const modalDialog = modal.querySelector('[data-modal-dialog]');
        if (!modalDialog) return;

        // Calculate available space
        const availableHeight = window.innerHeight - this.state.keyboardHeight;
        const modalHeight = modalDialog.offsetHeight;

        if (modalHeight > availableHeight) {
          // Modal is taller than available space, make it scrollable
          modalDialog.classList.add('modal-keyboard-visible');
        }

        // Move modal up if keyboard would cover active input
        if (this.state.activeInput) {
          const inputRect = this.state.activeInput.getBoundingClientRect();
          const keyboardTop = window.innerHeight - this.state.keyboardHeight;

          if (inputRect.bottom > keyboardTop) {
            modalDialog.classList.add('modal-keyboard-shift');
          }
        }
      });
    },

    /**
     * Reset modal adjustments after keyboard hide
     * REFACTORED: Using CSS classes instead of inline styles
     */
    resetModalAdjustments: function () {
      document.querySelectorAll('[data-modal].show [data-modal-dialog]').forEach(modalDialog => {
        modalDialog.classList.remove('modal-keyboard-visible', 'modal-keyboard-shift');
      });
    },

    /**
     * Adjust dropdown position to avoid keyboard
     * REFACTORED: Using CSS classes instead of inline styles
     */
    adjustDropdownsForKeyboard: function () {
      document.querySelectorAll('[data-dropdown].show, [data-select-dropdown]').forEach(dropdown => {
        const rect = dropdown.getBoundingClientRect();
        const keyboardTop = window.innerHeight - this.state.keyboardHeight;

        if (rect.bottom > keyboardTop) {
          // Dropdown would be covered by keyboard, position it above
          dropdown.classList.add('dropdown-above-keyboard');
        }
      });
    },

    /**
     * Scroll input into view when focused
     * @param {HTMLElement} input
     */
    scrollInputIntoView: function (input) {
      if (!this.isMobile()) return;

      // Wait for keyboard to appear (iOS delay)
      setTimeout(() => {
        const rect = input.getBoundingClientRect();
        const keyboardTop = window.innerHeight - this.state.keyboardHeight;
        const inputBottom = rect.bottom;

        // Check if input is covered by keyboard
        if (inputBottom > keyboardTop) {
          // Calculate scroll amount
          const scrollAmount = inputBottom - keyboardTop + 20;

          // Scroll the input into view
          input.scrollIntoView({
            behavior: 'smooth',
            block: 'center',
            inline: 'nearest'
          });

          // Additional scroll if in modal
          const modal = input.closest('[data-modal-body]');
          if (modal) {
            modal.scrollTop += scrollAmount;
          }
        }
      }, 300); // Delay to let keyboard animation complete
    },

    /**
     * Optimize input types for better mobile keyboards
     * REFACTORED: Using CSS class for iOS font size fix
     * @param {HTMLElement} input
     */
    optimizeInputType: function (input) {
      const type = input.type;
      const name = input.name || '';
      const id = input.id || '';
      const placeholder = input.placeholder || '';

      // Email inputs
      if (type === 'email' || name.includes('email') || id.includes('email')) {
        input.type = 'email';
        input.autocomplete = 'email';
        input.inputMode = 'email';
      }

      // Phone inputs
      if (name.includes('phone') || name.includes('tel') || id.includes('phone')) {
        input.type = 'tel';
        input.autocomplete = 'tel';
        input.inputMode = 'tel';
      }

      // Number inputs
      if (type === 'number' || name.includes('number') || placeholder.includes('number')) {
        input.inputMode = 'numeric';
        input.pattern = '[0-9]*'; // iOS numeric keyboard
      }

      // URL inputs
      if (name.includes('url') || name.includes('website') || id.includes('url')) {
        input.type = 'url';
        input.autocomplete = 'url';
        input.inputMode = 'url';
      }

      // Search inputs
      if (type === 'search' || name.includes('search') || id.includes('search')) {
        input.type = 'search';
      }

      // Username/password
      if (name.includes('username') || id.includes('username')) {
        input.autocomplete = 'username';
      }

      if (type === 'password') {
        input.autocomplete = 'current-password';
      }

      // Prevent iOS zoom on focus (16px minimum)
      // REFACTORED: Using CSS class instead of inline style
      if (this.isIOS()) {
        const fontSize = window.getComputedStyle(input).fontSize;
        if (parseInt(fontSize) < 16) {
          input.classList.add('ios-no-zoom');
        }
      }
    },

    /**
     * Setup input focus handlers
     */
    setupInputHandlers: function () {
      // Focus event for all inputs
      document.addEventListener('focusin', (e) => {
        const input = e.target;

        // Only handle form inputs
        if (!['INPUT', 'TEXTAREA', 'SELECT'].includes(input.tagName)) return;

        this.state.activeInput = input;

        // Add focused class to body for CSS styling
        document.body.classList.add('input-focused');

        // Scroll input into view
        this.scrollInputIntoView(input);

        // Trigger keyboard detection
        setTimeout(() => this.detectKeyboard(), 100);

      }, true);

      // Blur event
      document.addEventListener('focusout', (e) => {
        this.state.activeInput = null;
        document.body.classList.remove('input-focused');

        // Check if keyboard is hiding
        setTimeout(() => this.detectKeyboard(), 100);
      }, true);

      // Optimize all existing inputs
      document.querySelectorAll('input, textarea').forEach(input => {
        this.optimizeInputType(input);
      });
    },

    /**
     * iOS-specific fixes
     * REFACTORED: Using CSS classes and custom properties instead of inline styles
     */
    setupIOSFixes: function () {
      if (!this.isIOS()) return;

      // Fix for iOS viewport height with keyboard
      const setVH = () => {
        const vh = window.innerHeight * 0.01;
        document.documentElement.style.setProperty('--vh', `${vh}px`);
      };

      setVH();
      window.addEventListener('resize', setVH);

      // Fix for iOS scroll position after keyboard hide
      window.addEventListener('focusout', () => {
        setTimeout(() => {
          window.scrollTo(0, 0);
        }, 100);
      });

      // Fix for iOS date inputs
      // REFACTORED: Using CSS class instead of inline styles
      document.querySelectorAll('input[type="date"], input[type="datetime-local"], input[type="time"]').forEach(input => {
        input.classList.add('ios-date-input');
      });

      // Prevent rubber band scrolling when keyboard is open
      document.addEventListener('touchmove', (e) => {
        if (this.state.isVisible && this.state.activeInput) {
          const scrollable = e.target.closest('[data-modal-body], [data-table-responsive], [data-scrollable]');
          if (!scrollable) {
            e.preventDefault();
          }
        }
      }, { passive: false });
    },

    /**
     * Android-specific fixes
     */
    setupAndroidFixes: function () {
      if (!this.isAndroid()) return;

      // Android soft keyboard detection via resize
      let resizeTimeout;
      window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
          this.detectKeyboard();
        }, 100);
      });

      // Fix for Android keyboard not pushing content up
      if (this.state.isVisible && this.state.activeInput) {
        const metaViewport = document.querySelector('meta[name="viewport"]');
        if (metaViewport) {
          // Temporarily adjust viewport to force resize
          const originalContent = metaViewport.content;
          metaViewport.content = 'width=device-width, initial-scale=1.0, maximum-scale=1.0';
          setTimeout(() => {
            metaViewport.content = originalContent;
          }, 300);
        }
      }
    },

    /**
     * Setup form validation with keyboard awareness
     * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
     */
    _formValidationRegistered: false,
    setupFormValidation: function () {
      if (this._formValidationRegistered) return;
      this._formValidationRegistered = true;

      const self = this;

      // Delegated submit handler for all forms
      document.addEventListener('submit', function(e) {
        const form = e.target;
        if (form.tagName !== 'FORM') return;

        // Find first invalid input
        const firstInvalid = form.querySelector(':invalid');

        if (firstInvalid) {
          e.preventDefault();

          // Focus and scroll to first invalid input
          firstInvalid.focus();
          self.scrollInputIntoView(firstInvalid);

          // Haptic feedback if available
          if (window.Haptics) {
            window.Haptics.validationError();
          }
        }
      }, true); // Capture phase for submit

      // Delegated invalid handler (uses capture since invalid doesn't bubble)
      document.addEventListener('invalid', function(e) {
        if (e.target.matches('input, textarea, select')) {
          if (window.Haptics) {
            window.Haptics.validationError();
          }
        }
      }, true); // Capture phase required - invalid doesn't bubble

      // Delegated input handler for real-time validation
      document.addEventListener('input', function(e) {
        const input = e.target;
        if (!input.matches('input, textarea, select')) return;

        if (input.validity.valid && input.classList.contains('is-invalid')) {
          input.classList.remove('is-invalid');
          input.classList.add('is-valid');
        }
      });
    },

    /**
     * Setup mutation observer for dynamically added inputs
     * REFACTORED: Uses UnifiedMutationObserver to prevent cascade effects
     */
    _unifiedObserverRegistered: false,
    setupMutationObserver: function () {
      // Only register once
      if (this._unifiedObserverRegistered) return;
      this._unifiedObserverRegistered = true;

      const self = this;

      // Use unified observer if available
      if (window.UnifiedMutationObserver) {
        window.UnifiedMutationObserver.register('mobile-keyboard', {
          onAddedNodes: function(nodes) {
            nodes.forEach(node => {
              // Check if added node is an input
              if (['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName)) {
                self.optimizeInputType(node);
              }

              // Check for inputs within added node
              if (node.querySelectorAll) {
                node.querySelectorAll('input, textarea, select').forEach(input => {
                  self.optimizeInputType(input);
                });
              }
            });
          },
          filter: function(node) {
            // Only process nodes that are or contain form inputs
            return ['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName) ||
                   (node.querySelectorAll && node.querySelectorAll('input, textarea, select').length > 0);
          },
          priority: 90 // Run early for input optimization
        });
      }
    },

    /**
     * Add CSS for keyboard-aware styling
     * NOTE: Core styles moved to mobile-utils.css, keeping minimal dynamic styles
     */
    addKeyboardStyles: function () {
      if (document.getElementById('mobile-keyboard-styles')) return;

      const style = document.createElement('style');
      style.id = 'mobile-keyboard-styles';
      style.textContent = `
        /* Keyboard visible state */
        body.keyboard-visible {
          /* Optional: adjust fixed elements */
        }

        /* Input focused state */
        body.input-focused .navbar-fixed-bottom,
        body.input-focused .mobile-bottom-nav {
          transform: translateY(100%);
          transition: transform 0.3s ease;
        }

        /* Ensure inputs are visible above keyboard */
        [data-form-control]:focus,
        [data-form-select]:focus,
        textarea:focus {
          position: relative;
          z-index: 10;
        }

        /* iOS-specific: fix 100vh with keyboard */
        @supports (-webkit-touch-callout: none) {
          [data-modal-dialog],
          [data-full-height] {
            height: calc(var(--vh, 1vh) * 100);
          }
        }

        /* Smooth transitions for keyboard adjustments */
        [data-modal-dialog] {
          transition: transform 0.3s ease, max-height 0.3s ease;
        }
      `;
      document.head.appendChild(style);
    },

    /**
     * Initialize keyboard handler
     */
    init: function () {
      if (_initialized) return;

      if (!this.isMobile()) {
        console.log('MobileKeyboard: Not a mobile device, skipping initialization');
        return;
      }

      _initialized = true;

      // Setup handlers
      this.setupInputHandlers();
      this.setupFormValidation();
      this.setupMutationObserver();

      // Platform-specific fixes
      if (this.isIOS()) {
        this.setupIOSFixes();
      }

      if (this.isAndroid()) {
        this.setupAndroidFixes();
      }

      // Add styles
      this.addKeyboardStyles();

      // Update viewport height on orientation change
      window.addEventListener('orientationchange', () => {
        setTimeout(() => {
          this.state.originalViewportHeight = window.innerHeight;
          this.detectKeyboard();
        }, 200);
      });

      console.log('MobileKeyboard: Initialized successfully');
    }
  };

  // Expose globally (MUST be before any callbacks or registrations)
  window.MobileKeyboard = MobileKeyboard;

  // Register with InitSystem
  if (InitSystem && InitSystem.register) {
    InitSystem.register('mobile-keyboard', () => MobileKeyboard.init(), {
      priority: 45,
      reinitializable: false,
      description: 'Mobile keyboard handlers'
    });
  }

  // Fallback
// InitSystem handles initialization

