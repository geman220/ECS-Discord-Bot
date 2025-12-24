/**
 * ECS Soccer League Responsive System
 *
 * A comprehensive responsive management system that handles device detection,
 * responsive behavior, and UI enhancements across all screen sizes and devices.
 *
 * REFACTORED: All inline style manipulations replaced with CSS class-based approach
 * for better maintainability, performance, and separation of concerns.
 */
(function () {
  'use strict';

  // Main responsive system controller
  const ResponsiveSystem = {
    // Device detection states
    device: {
      isMobile: false,
      isTablet: false,
      isDesktop: false,
      isIOS: false,
      isAndroid: false,
      hasTouch: false,
      hasMouse: false
    },

    /**
     * Initialize the responsive system
     */
    init: function () {
      this.detectDevice();
      this.applyDeviceClasses();
      this.fixIOSViewportHeight();
      this.setupTouchFeedback();
      this.enhanceModals();
      this.enhanceFormControls();
      this.enhanceTables();
      this.enhanceNavigation();
      this.improveScrolling();
      this.monitorNetworkStatus();
      this.attachEventListeners();
      this.setupMutationObserver();

      // Log initialization
      // console.log('ResponsiveSystem initialized', this.device);
    },

    /**
     * Detect device capabilities and properties
     */
    detectDevice: function () {
      // Touch capability detection
      this.device.hasTouch = ('ontouchstart' in window) ||
        (navigator.maxTouchPoints > 0) ||
        (navigator.msMaxTouchPoints > 0);

      // Mouse capability detection
      this.device.hasMouse = matchMedia('(hover: hover) and (pointer: fine)').matches;

      // Screen size detection
      const screenWidth = window.innerWidth;
      this.device.isMobile = screenWidth < 768;
      this.device.isTablet = screenWidth >= 768 && screenWidth < 992;
      this.device.isDesktop = screenWidth >= 992;

      // OS detection
      const userAgent = navigator.userAgent.toLowerCase();
      this.device.isIOS = /iphone|ipad|ipod/.test(userAgent);
      this.device.isAndroid = /android/.test(userAgent);
    },

    /**
     * Apply device-specific classes to the body element
     */
    applyDeviceClasses: function () {
      const body = document.body;

      // Remove existing classes to prevent duplicates
      body.classList.remove(
        'mobile-device', 'tablet-device', 'desktop-device',
        'ios-device', 'android-device', 'touch-device', 'mouse-device'
      );

      // Add device type classes
      if (this.device.isMobile) body.classList.add('mobile-device');
      if (this.device.isTablet) body.classList.add('tablet-device');
      if (this.device.isDesktop) body.classList.add('desktop-device');

      // Add OS type classes
      if (this.device.isIOS) body.classList.add('ios-device');
      if (this.device.isAndroid) body.classList.add('android-device');

      // Add input type classes
      if (this.device.hasTouch) body.classList.add('touch-device');
      if (this.device.hasMouse) body.classList.add('mouse-device');
    },

    /**
     * Fix iOS 100vh issue with CSS custom property
     * REFACTORED: Using CSS custom property instead of inline styles
     */
    fixIOSViewportHeight: function () {
      const setVh = () => {
        const vh = window.innerHeight * 0.01;
        // CSS custom property - this is acceptable as it's dynamic viewport calculation
        document.documentElement.style.setProperty('--vh', `${vh}px`);
      };

      // Set initially and on viewport changes
      setVh();
      window.addEventListener('resize', setVh);
      window.addEventListener('orientationchange', () => {
        // Wait for orientation change to complete before setting new height
        setTimeout(setVh, 100);
      });

      // Special handling for iOS keyboard
      if (this.device.isIOS) {
        const inputs = document.querySelectorAll('input, textarea, select');
        inputs.forEach(input => {
          // Skip checkboxes and radio buttons - they don't need keyboard
          if (input.type === 'checkbox' || input.type === 'radio') {
            return;
          }

          // Add class when keyboard is visible
          input.addEventListener('focus', () => {
            document.documentElement.classList.add('keyboard-visible');
          });

          // Remove class when keyboard is hidden
          input.addEventListener('blur', () => {
            document.documentElement.classList.remove('keyboard-visible');
          });
        });
      }
    },

    /**
     * Set up touch feedback for interactive elements
     */
    setupTouchFeedback: function () {
      if (this.device.hasTouch) {
        const touchElements = document.querySelectorAll('button, .btn, a.nav-link, .card-header');

        touchElements.forEach(el => {
          // Use opacity change instead of transform for feedback
          el.addEventListener('touchstart', function () {
            this.classList.add('touch-active');

            // Add haptic feedback for buttons (handled by mobile-haptics.js auto-init)
            // Individual haptic calls are in mobile-haptics.js, so no need to duplicate here
          }, { passive: true });

          el.addEventListener('touchend', function () {
            this.classList.remove('touch-active');
          }, { passive: true });
        });
      }
    },

    /**
     * Enhance modal behavior on mobile devices
     * REFACTORED: Replaced inline styles with CSS classes
     */
    enhanceModals: function () {
      const modals = document.querySelectorAll('[data-modal]');

      modals.forEach(modal => {
        const modalDialog = modal.querySelector('[data-modal-dialog]');

        // Auto-convert modals to bottom sheets on mobile (unless explicitly disabled)
        if (this.device.isMobile && !modal.hasAttribute('data-no-bottom-sheet') && modalDialog) {
          // Don't convert if modal-keep-centered class is present
          if (!modalDialog.classList.contains('modal-keep-centered')) {
            // Remove any size classes that would interfere
            modalDialog.classList.remove('modal-lg', 'modal-xl', 'modal-sm');
          }
        }

        // Setup swipe-to-dismiss on mobile bottom sheets
        if (this.device.isMobile && modal.getAttribute('data-dismiss-on-swipe') === 'true') {
          this.setupModalSwipeDismiss(modal);
        }

        // Focus management and scrolling improvements
        modal.addEventListener('shown.bs.modal', () => {
          // Haptic feedback when modal opens
          if (window.Haptics) {
            window.Haptics.modalOpen();
          }

          // Prevent body scroll on iOS
          // REFACTORED: Using CSS class instead of inline styles
          if (this.device.isIOS) {
            document.body.classList.add('scroll-locked');
          }

          // Focus first interactive element
          const focusable = modal.querySelector('input:not([type="hidden"]), button.btn-close, button:not(.close), [tabindex]:not([tabindex="-1"])');
          if (focusable) {
            setTimeout(() => focusable.focus(), 100);
          }

          // iOS-specific modal fixes
          // REFACTORED: Using CSS class instead of inline styles
          if (this.device.isIOS) {
            const modalBody = modal.querySelector('[data-modal-body]');
            if (modalBody) {
              modalBody.classList.add('modal-body-scrollable');
            }
          }

          // Mobile optimization for bottom sheets
          // REFACTORED: Using CSS class instead of inline styles
          if (this.device.isMobile) {
            const modalContent = modal.querySelector('[data-modal-content]');
            if (modalContent && !modalDialog.classList.contains('modal-keep-centered')) {
              modalContent.classList.add('modal-content-mobile');
            }
          }

          // Handle keyboard open state
          this.handleModalKeyboard(modal);
        });

        // Cleanup when modal is closed
        modal.addEventListener('hidden.bs.modal', () => {
          // Haptic feedback when modal closes
          if (window.Haptics) {
            window.Haptics.modalClose();
          }

          // Restore body scroll on iOS
          // REFACTORED: Using CSS class removal instead of inline style removal
          if (this.device.isIOS) {
            document.body.classList.remove('scroll-locked');
          }

          // Remove keyboard open class
          document.body.classList.remove('keyboard-open');

          // Cleanup modal body scrollable class
          const modalBody = modal.querySelector('[data-modal-body]');
          if (modalBody) {
            modalBody.classList.remove('modal-body-scrollable');
          }

          // Cleanup modal content mobile class
          const modalContent = modal.querySelector('[data-modal-content]');
          if (modalContent) {
            modalContent.classList.remove('modal-content-mobile');
          }

          this.cleanupModalBackdrops();
        });

        // Add haptic feedback to close buttons
        const closeButtons = modal.querySelectorAll('.btn-close, [data-bs-dismiss="modal"]');
        closeButtons.forEach(btn => {
          btn.addEventListener('click', () => {
            if (window.Haptics) {
              window.Haptics.light();
            }
          }, { passive: true });
        });
      });
    },

    /**
     * Setup swipe-to-dismiss functionality for mobile modals
     * REFACTORED: Replaced inline styles with CSS classes
     */
    setupModalSwipeDismiss: function (modal) {
      if (!this.device.isMobile) return;

      const modalDialog = modal.querySelector('[data-modal-dialog]');
      const modalHeader = modal.querySelector('[data-modal-header]');

      if (!modalDialog || !modalHeader) return;

      let startY = 0;
      let currentY = 0;
      let isDragging = false;

      // Touch start
      modalHeader.addEventListener('touchstart', (e) => {
        startY = e.touches[0].clientY;
        isDragging = true;
        modalDialog.classList.add('swiping');
      }, { passive: true });

      // Touch move
      modalHeader.addEventListener('touchmove', (e) => {
        if (!isDragging) return;

        currentY = e.touches[0].clientY;
        const deltaY = currentY - startY;

        // Only allow downward swipe
        // REFACTORED: Using CSS custom property for dynamic transform
        if (deltaY > 0) {
          e.preventDefault();
          // Use CSS custom property for dynamic transform value
          modalDialog.style.setProperty('--swipe-offset', `${deltaY}px`);
          modalDialog.style.transform = `translateY(var(--swipe-offset))`;
          modalDialog.classList.add('transition-none');
        }
      });

      // Touch end
      modalHeader.addEventListener('touchend', (e) => {
        if (!isDragging) return;

        isDragging = false;
        modalDialog.classList.remove('swiping');

        const deltaY = currentY - startY;
        const threshold = 100; // Pixels to swipe before dismissing

        if (deltaY > threshold) {
          // Dismiss modal
          if (window.Haptics) {
            window.Haptics.light();
          }

          // Animate out
          // REFACTORED: Using CSS classes for animation
          modalDialog.classList.remove('transition-none');
          modalDialog.classList.add('swipe-animating', 'swipe-dismiss');

          setTimeout(() => {
            const bsModal = bootstrap.Modal.getInstance(modal);
            if (bsModal) {
              bsModal.hide();
            }
            // Reset transform
            // REFACTORED: Using CSS classes instead of inline styles
            modalDialog.classList.remove('swipe-animating', 'swipe-dismiss');
            modalDialog.style.removeProperty('--swipe-offset');
            modalDialog.style.removeProperty('transform');
          }, 300);
        } else {
          // Snap back
          // REFACTORED: Using CSS classes for animation
          modalDialog.classList.remove('transition-none');
          modalDialog.classList.add('swipe-animating', 'swipe-reset');

          setTimeout(() => {
            modalDialog.classList.remove('swipe-animating', 'swipe-reset');
            modalDialog.style.removeProperty('--swipe-offset');
            modalDialog.style.removeProperty('transform');
          }, 300);
        }

        currentY = 0;
      }, { passive: true });
    },

    /**
     * Handle keyboard open/close for modals
     */
    handleModalKeyboard: function (modal) {
      if (!this.device.isMobile) return;

      const inputs = modal.querySelectorAll('input, textarea, select');

      inputs.forEach(input => {
        input.addEventListener('focus', () => {
          document.body.classList.add('keyboard-open');

          // Scroll input into view
          setTimeout(() => {
            input.scrollIntoView({ behavior: 'smooth', block: 'center' });
          }, 300);
        });

        input.addEventListener('blur', () => {
          // Check if another input in the same modal has focus
          setTimeout(() => {
            const activeElement = document.activeElement;
            const isInputFocused = modal.contains(activeElement) &&
                                   (activeElement.tagName === 'INPUT' ||
                                    activeElement.tagName === 'TEXTAREA' ||
                                    activeElement.tagName === 'SELECT');

            if (!isInputFocused) {
              document.body.classList.remove('keyboard-open');
            }
          }, 100);
        });
      });
    },

    /**
     * Enhance form controls for better mobile experience
     * REFACTORED: Replaced inline styles with CSS classes
     */
    enhanceFormControls: function () {
      // Enhance standard form controls
      if (this.device.isMobile || this.device.isTablet) {
        const formControls = document.querySelectorAll('[data-form-control], [data-form-select]');
        formControls.forEach(control => {
          // Ensure minimum touch target size
          // REFACTORED: Using CSS class instead of inline style
          if (control.offsetHeight < 44) {
            control.classList.add('form-control-touch-target');
          }

          // iOS date input fixes
          // REFACTORED: Using CSS class instead of inline styles
          if (this.device.isIOS && (control.type === 'date' || control.type === 'time' || control.type === 'datetime-local')) {
            control.classList.add('form-control-ios-date');
          }
        });
      }

      // Enhance Select2 if available
      if (typeof $.fn !== 'undefined' && typeof $.fn.select2 !== 'undefined') {
        try {
          setTimeout(() => {
            $('.select2-container').each(function () {
              const selectElement = $(this).siblings('select');
              if (selectElement.length) {
                // Configure Select2 with mobile-friendly options
                const config = {
                  theme: 'bootstrap-5',
                  width: '100%',
                  // Set dropdown to modal if in modal context
                  dropdownParent: $(selectElement).closest('.modal').length ?
                    $(selectElement).closest('.modal') : $('body')
                };

                // Set appropriate placeholder
                config.placeholder = selectElement.data('placeholder') ||
                  (selectElement.is('[multiple]') ? 'Select multiple options' : 'Select an option');

                // Initialize Select2
                selectElement.select2(config);
              }
            });
          }, 300);
        } catch (e) {
          // console.warn('Error enhancing Select2:', e);
        }
      }
    },

    /**
     * Enhance tables for better mobile experience
     * REFACTORED: Replaced inline styles with CSS classes
     */
    enhanceTables: function () {
      const tables = document.querySelectorAll('[data-table-responsive]');

      tables.forEach(table => {
        // Ensure touch scrolling works well
        // REFACTORED: Using CSS class instead of inline style
        table.classList.add('table-responsive-touch');

        // Add faded edge indicators for scrollable tables on mobile
        if (this.device.isMobile && !table.querySelector('.table-scroll-hint')) {
          const tableWidth = table.scrollWidth;
          const containerWidth = table.clientWidth;

          if (tableWidth > containerWidth) {
            // Add scroll hint indicator
            const scrollHint = document.createElement('div');
            scrollHint.className = 'table-scroll-hint';
            scrollHint.innerHTML = '<small class="text-muted"><i class="ti ti-arrows-horizontal me-1"></i>swipe to see more</small>';

            table.parentNode.insertBefore(scrollHint, table.nextSibling);

            // Hide hint when user has scrolled
            // REFACTORED: Using CSS classes instead of inline styles
            table.addEventListener('scroll', function() {
              if (this.scrollLeft > 20) {
                scrollHint.classList.add('hidden');
              }
            });
          }
        }
      });
    },

    /**
     * Enhance navigation elements for touch devices
     * REFACTORED: Replaced inline styles with CSS classes
     */
    enhanceNavigation: function () {
      // Make tabs scrollable on mobile
      const tabContainers = document.querySelectorAll('[data-tabs], .js-tabs');

      tabContainers.forEach(container => {
        // Check prerequisites first
        const tabs = container.querySelectorAll('.nav-link');
        const isOnMobile = window.innerWidth < 768;
        const hasMultipleTabs = tabs.length > 1;
        const hasOverflow = container.scrollWidth > container.clientWidth;

        // Only show on mobile with multiple tabs that actually overflow
        if (isOnMobile && hasMultipleTabs && hasOverflow) {
          // Apply scrolling styles
          // REFACTORED: Using CSS class instead of inline styles
          container.classList.add('scrollable-tabs');

          // Add scroll indicator if not present
          if (!container.nextElementSibling || !container.nextElementSibling.classList.contains('tabs-scroll-hint')) {
            const scrollHint = document.createElement('div');
            scrollHint.className = 'tabs-scroll-hint';
            scrollHint.innerHTML = '<small class="text-muted"><i class="ti ti-arrows-horizontal me-1"></i>swipe</small>';

            container.parentNode.insertBefore(scrollHint, container.nextSibling);
          }
        } else {
          // Remove any existing swipe hints on desktop or single tabs
          const existingHint = container.nextElementSibling;
          if (existingHint && existingHint.classList.contains('tabs-scroll-hint')) {
            existingHint.remove();
          }
        }
      });

      // Enhance sidebar menu on mobile
      const sidebarMenu = document.querySelector('.layout-menu');
      if (sidebarMenu && (this.device.isMobile || this.device.isTablet)) {
        const menuItems = sidebarMenu.querySelectorAll('.menu-item');

        menuItems.forEach(item => {
          // Make dropdown toggles more touch-friendly
          // REFACTORED: Using CSS class instead of inline style
          if (item.classList.contains('menu-item-has-children')) {
            const toggle = item.querySelector('.menu-toggle');
            if (toggle) {
              toggle.classList.add('menu-toggle-touch');
            }
          }

          // Make all menu links more touch-friendly
          // REFACTORED: Using CSS class instead of inline style
          const link = item.querySelector('.menu-link');
          if (link) {
            link.classList.add('menu-link-touch');
          }
        });
      }
    },

    /**
     * Improve scrolling behavior site-wide
     */
    improveScrolling: function () {
      // Enable smooth scrolling for anchor links
      document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        if (anchor.getAttribute('href').length > 1) {
          anchor.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href');
            if (targetId === '#' || !targetId) return;

            const targetElement = document.querySelector(targetId);
            if (targetElement) {
              e.preventDefault();

              // Scroll smoothly to target
              targetElement.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
              });
            }
          });
        }
      });
    },

    /**
     * Monitor network status and display notifications
     */
    monitorNetworkStatus: function () {
      window.addEventListener('online', () => {
        this.showNetworkStatus(true);
      });

      window.addEventListener('offline', () => {
        this.showNetworkStatus(false);
      });
    },

    /**
     * Show network status toast notification
     * REFACTORED: Replaced inline styles with CSS classes
     */
    showNetworkStatus: function (isOnline) {
      const statusDiv = document.createElement('div');
      statusDiv.className = 'network-status-indicator';

      if (isOnline) {
        statusDiv.classList.add('online');
        statusDiv.innerHTML = '<i class="ti ti-wifi me-2"></i> Connected';
      } else {
        statusDiv.classList.add('offline');
        statusDiv.innerHTML = '<i class="ti ti-wifi-off me-2"></i> Disconnected';
      }

      document.body.appendChild(statusDiv);

      // Animate in
      // REFACTORED: Using CSS class instead of inline style
      setTimeout(() => {
        statusDiv.classList.add('visible');
      }, 10);

      // Hide after delay
      setTimeout(() => {
        statusDiv.classList.remove('visible');

        setTimeout(() => {
          if (statusDiv.parentNode) {
            document.body.removeChild(statusDiv);
          }
        }, 300);
      }, 3000);
    },

    /**
     * Attach global event listeners
     */
    attachEventListeners: function () {
      // Handle orientation changes
      window.addEventListener('orientationchange', () => {
        // Run after orientation change completes
        setTimeout(() => {
          this.fixIOSViewportHeight();
          this.enhanceNavigation();

          // Dispatch custom event for other components
          document.dispatchEvent(new CustomEvent('app:orientationchange'));
        }, 200);
      });

      // Handle resize (debounced)
      let resizeTimer;
      window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          // Update device detection and classes
          this.detectDevice();
          this.applyDeviceClasses();
          this.fixIOSViewportHeight();

          // Re-enhance components after resize
          this.enhanceNavigation();
          this.enhanceTables();

          // Notify other components
          document.dispatchEvent(new CustomEvent('app:resize'));
        }, 250);
      });

      // Fix modal backdrop issues
      document.addEventListener('click', () => {
        setTimeout(this.cleanupModalBackdrops.bind(this), 300);
      });

      // Fix iOS tab bar hiding issue
      if (this.device.isIOS) {
        window.addEventListener('scroll', () => {
          // Force address bar to show/hide properly
          document.body.scrollTop = document.body.scrollTop + 1;
          document.body.scrollTop = document.body.scrollTop - 1;
        }, { passive: true });
      }
    },

    /**
     * Clean up any stray modal backdrops
     * REFACTORED: Using removeProperty instead of direct style manipulation
     */
    cleanupModalBackdrops: function () {
      const openModals = document.querySelectorAll('.modal.show');
      const modalBackdrops = document.querySelectorAll('.modal-backdrop');

      // If there are no open modals but we have backdrops, clean them up
      if (openModals.length === 0 && modalBackdrops.length > 0) {
        modalBackdrops.forEach(backdrop => {
          if (backdrop.parentNode) {
            backdrop.parentNode.removeChild(backdrop);
          }
        });

        // Fix body classes and styles
        // REFACTORED: Using removeProperty instead of setting empty string
        document.body.classList.remove('modal-open');
        document.body.style.removeProperty('overflow');
        document.body.style.removeProperty('padding-right');
      }
    },

    /**
     * Set up observer to watch for dynamically added elements
     */
    setupMutationObserver: function () {
      // Create MutationObserver instance
      const observer = new MutationObserver((mutations) => {
        let shouldEnhance = false;

        // Check if we need to enhance elements
        mutations.forEach(mutation => {
          if (mutation.addedNodes.length) {
            // Look for meaningful DOM changes that would require enhancement
            for (let i = 0; i < mutation.addedNodes.length; i++) {
              const node = mutation.addedNodes[i];
              if (node.nodeType === 1) { // Only element nodes
                if (
                  node.hasAttribute && (
                    node.hasAttribute('data-modal') ||
                    node.hasAttribute('data-form-control') ||
                    node.hasAttribute('data-form-select') ||
                    node.hasAttribute('data-tabs') ||
                    node.hasAttribute('data-table-responsive')
                  )
                ) {
                  shouldEnhance = true;
                  break;
                }

                // Check if added node contains elements we care about
                if (
                  node.querySelector && (
                    node.querySelector('[data-modal]') ||
                    node.querySelector('[data-form-control]') ||
                    node.querySelector('[data-form-select]') ||
                    node.querySelector('[data-tabs], .js-tabs') ||
                    node.querySelector('[data-table-responsive]')
                  )
                ) {
                  shouldEnhance = true;
                  break;
                }
              }
            }
          }
        });

        // Enhance new elements if needed
        if (shouldEnhance) {
          setTimeout(() => {
            this.enhanceNewElements();
          }, 100);
        }
      });

      // Start observing the document
      observer.observe(document.body, {
        childList: true,
        subtree: true
      });
    },

    /**
     * Enhance dynamically added elements
     */
    enhanceNewElements: function () {
      this.setupTouchFeedback();
      this.enhanceFormControls();
      this.enhanceTables();
      this.enhanceNavigation();
      this.enhanceModals();
    }
  };

  // Make available globally
  window.ResponsiveSystem = ResponsiveSystem;

  // Register with InitSystem if available
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('responsive-system', function() {
      ResponsiveSystem.init();
    }, {
      priority: 85,
      description: 'Responsive system (mobile detection, touch feedback, form/table/modal enhancements)',
      reinitializable: true
    });
  } else {
    // Fallback: Initialize when DOM is ready
    document.addEventListener('DOMContentLoaded', function () {
      ResponsiveSystem.init();
    });
  }
})();
