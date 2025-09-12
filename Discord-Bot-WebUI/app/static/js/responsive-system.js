/**
 * ECS Soccer League Responsive System
 *
 * A comprehensive responsive management system that handles device detection,
 * responsive behavior, and UI enhancements across all screen sizes and devices.
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
     */
    fixIOSViewportHeight: function () {
      const setVh = () => {
        const vh = window.innerHeight * 0.01;
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
          }, { passive: true });

          el.addEventListener('touchend', function () {
            this.classList.remove('touch-active');
          }, { passive: true });
        });
      }
    },

    /**
     * Enhance modal behavior on mobile devices
     */
    enhanceModals: function () {
      const modals = document.querySelectorAll('.modal');

      modals.forEach(modal => {
        // Focus management and scrolling improvements
        modal.addEventListener('shown.bs.modal', () => {
          // Focus first interactive element
          const focusable = modal.querySelector('input:not([type="hidden"]), button.btn-close, button:not(.close), [tabindex]:not([tabindex="-1"])');
          if (focusable) {
            setTimeout(() => focusable.focus(), 100);
          }

          // iOS-specific modal fixes
          if (this.device.isIOS) {
            const modalBody = modal.querySelector('.modal-body');
            if (modalBody) {
              modalBody.style.maxHeight = `calc(100vh - 200px)`;
              modalBody.style.overflowY = 'auto';
              modalBody.style.webkitOverflowScrolling = 'touch';
            }
          }

          // Mobile optimization
          if (this.device.isMobile) {
            const modalContent = modal.querySelector('.modal-content');
            if (modalContent) {
              modalContent.style.maxHeight = `calc(100vh - 3.5rem)`;
            }
          }
        });

        // Cleanup when modal is closed
        modal.addEventListener('hidden.bs.modal', () => {
          this.cleanupModalBackdrops();
        });
      });
    },

    /**
     * Enhance form controls for better mobile experience
     */
    enhanceFormControls: function () {
      // Enhance standard form controls
      if (this.device.isMobile || this.device.isTablet) {
        const formControls = document.querySelectorAll('.form-control, .form-select');
        formControls.forEach(control => {
          // Ensure minimum touch target size
          if (control.offsetHeight < 44) {
            control.style.minHeight = 'var(--input-height)';
          }

          // iOS date input fixes
          if (this.device.isIOS && (control.type === 'date' || control.type === 'time' || control.type === 'datetime-local')) {
            control.style.minHeight = 'var(--input-height)';
            control.style.paddingRight = '0.75rem';
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
     */
    enhanceTables: function () {
      const tables = document.querySelectorAll('.table-responsive');
      
      tables.forEach(table => {
        // Ensure touch scrolling works well
        table.style.webkitOverflowScrolling = 'touch';
        
        // Add faded edge indicators for scrollable tables on mobile
        if (this.device.isMobile && !table.querySelector('.table-scroll-hint')) {
          const tableWidth = table.scrollWidth;
          const containerWidth = table.clientWidth;
          
          if (tableWidth > containerWidth) {
            // Add scroll hint indicator
            const scrollHint = document.createElement('div');
            scrollHint.className = 'table-scroll-hint';
            scrollHint.innerHTML = '<small class="text-muted"><i class="ti ti-arrows-horizontal me-1"></i>swipe to see more</small>';
            scrollHint.style.textAlign = 'center';
            scrollHint.style.fontSize = '0.7rem';
            scrollHint.style.marginTop = '0.25rem';
            scrollHint.style.opacity = '0.7';
            
            table.parentNode.insertBefore(scrollHint, table.nextSibling);
            
            // Hide hint when user has scrolled
            table.addEventListener('scroll', function() {
              if (this.scrollLeft > 20) {
                scrollHint.style.opacity = '0';
                setTimeout(() => {
                  scrollHint.style.display = 'none';
                }, 300);
              }
            });
          }
        }
      });
    },

    /**
     * Enhance navigation elements for touch devices
     */
    enhanceNavigation: function () {
      // Make tabs scrollable on mobile
      const tabContainers = document.querySelectorAll('.nav-tabs, .nav-pills');
      
      tabContainers.forEach(container => {
        // Check prerequisites first
        const tabs = container.querySelectorAll('.nav-link');
        const isOnMobile = window.innerWidth < 768;
        const hasMultipleTabs = tabs.length > 1;
        const hasOverflow = container.scrollWidth > container.clientWidth;
        
        // Only show on mobile with multiple tabs that actually overflow
        if (isOnMobile && hasMultipleTabs && hasOverflow) {
          // Apply scrolling styles
          container.classList.add('scrollable-tabs');
          container.style.overflowX = 'auto';
          container.style.flexWrap = 'nowrap';
          container.style.webkitOverflowScrolling = 'touch';
          
          // Add scroll indicator if not present
          if (!container.nextElementSibling || !container.nextElementSibling.classList.contains('tabs-scroll-hint')) {
            const scrollHint = document.createElement('div');
            scrollHint.className = 'tabs-scroll-hint';
            scrollHint.innerHTML = '<small class="text-muted"><i class="ti ti-arrows-horizontal me-1"></i>swipe</small>';
            scrollHint.style.textAlign = 'center';
            scrollHint.style.fontSize = '0.7rem';
            scrollHint.style.marginTop = '0.25rem';
            scrollHint.style.opacity = '0.7';
            
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
          if (item.classList.contains('menu-item-has-children')) {
            const toggle = item.querySelector('.menu-toggle');
            if (toggle) {
              toggle.style.minHeight = 'var(--touch-target-size)';
            }
          }
          
          // Make all menu links more touch-friendly
          const link = item.querySelector('.menu-link');
          if (link) {
            link.style.minHeight = 'var(--touch-target-size)';
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
     */
    showNetworkStatus: function (isOnline) {
      const statusDiv = document.createElement('div');
      statusDiv.className = 'network-status-indicator';
      statusDiv.style.position = 'fixed';
      statusDiv.style.bottom = '20px';
      statusDiv.style.left = '50%';
      statusDiv.style.transform = 'translateX(-50%)';
      statusDiv.style.padding = '0.75rem 1rem';
      statusDiv.style.borderRadius = 'var(--border-radius)';
      statusDiv.style.color = 'white';
      statusDiv.style.fontWeight = 'bold';
      statusDiv.style.zIndex = '9999';
      statusDiv.style.opacity = '0';
      statusDiv.style.transition = 'opacity 0.3s ease';
      statusDiv.style.boxShadow = '0 0.25rem 0.75rem rgba(0, 0, 0, 0.15)';
      
      if (isOnline) {
        statusDiv.style.backgroundColor = '#28a745'; // Success green
        statusDiv.innerHTML = '<i class="ti ti-wifi me-2"></i> Connected';
      } else {
        statusDiv.style.backgroundColor = '#dc3545'; // Danger red
        statusDiv.innerHTML = '<i class="ti ti-wifi-off me-2"></i> Disconnected';
      }
      
      document.body.appendChild(statusDiv);
      
      // Animate in
      setTimeout(() => {
        statusDiv.style.opacity = '1';
      }, 10);
      
      // Hide after delay
      setTimeout(() => {
        statusDiv.style.opacity = '0';
        
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
                  node.classList && (
                    node.classList.contains('modal') ||
                    node.classList.contains('form-control') ||
                    node.classList.contains('btn') ||
                    node.classList.contains('nav-tabs') ||
                    node.classList.contains('table-responsive')
                  )
                ) {
                  shouldEnhance = true;
                  break;
                }
                
                // Check if added node contains elements we care about
                if (
                  node.querySelector && (
                    node.querySelector('.modal') ||
                    node.querySelector('.form-control') ||
                    node.querySelector('.btn') ||
                    node.querySelector('.nav-tabs') ||
                    node.querySelector('.table-responsive')
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

  // Initialize when DOM is ready
  document.addEventListener('DOMContentLoaded', function () {
    ResponsiveSystem.init();
  });

  // Make available globally
  window.ResponsiveSystem = ResponsiveSystem;
})();