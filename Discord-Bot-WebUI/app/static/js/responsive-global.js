/**
 * ECS Soccer League Global Responsive Helper
 * 
 * This utility enhances the responsive behavior across the entire application
 * by applying device-specific optimizations and fixes common mobile issues.
 */

(function() {
  'use strict';

  // Main responsive handler
  const ResponsiveGlobal = {
    // Device detection results
    device: {
      isMobile: false,
      isTablet: false,
      isDesktop: false,
      isIOS: false,
      isAndroid: false,
      hasTouch: false,
      hasMouse: false
    },

    // Initialize all responsive features
    init: function() {
      this.detectDevice();
      this.applyDeviceClasses();
      this.fixViewportHeight();
      this.applyGlobalFixes();
      this.enhanceModals();
      this.enhanceInputs();
      this.enhanceButtons();
      this.improveNavigation();
      this.setupScrolling();
      this.monitorNetworkStatus();
      this.attachGlobalEventListeners();
      this.setupMutationObserver();
    },

    // Detect device capabilities
    detectDevice: function() {
      // Check for touch capability
      this.device.hasTouch = ('ontouchstart' in window) || 
                            (navigator.maxTouchPoints > 0) || 
                            (navigator.msMaxTouchPoints > 0);
      
      // Check for mouse capability
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
      
      // Log device info for debugging
      // console.log('Device detection:', this.device);
    },

    // Add device-specific classes to the body
    applyDeviceClasses: function() {
      const body = document.body;
      
      // Clear existing classes
      body.classList.remove(
        'mobile-device', 'tablet-device', 'desktop-device',
        'ios-device', 'android-device', 'touch-device', 'mouse-device'
      );
      
      // Add device type
      if (this.device.isMobile) body.classList.add('mobile-device');
      if (this.device.isTablet) body.classList.add('tablet-device');
      if (this.device.isDesktop) body.classList.add('desktop-device');
      
      // Add OS type
      if (this.device.isIOS) body.classList.add('ios-device');
      if (this.device.isAndroid) body.classList.add('android-device');
      
      // Add input type
      if (this.device.hasTouch) body.classList.add('touch-device');
      if (this.device.hasMouse) body.classList.add('mouse-device');
    },

    // Fix iOS 100vh issue
    fixViewportHeight: function() {
      const setVh = () => {
        const vh = window.innerHeight * 0.01;
        document.documentElement.style.setProperty('--vh', `${vh}px`);
      };
      
      setVh();
      window.addEventListener('resize', setVh);
      window.addEventListener('orientationchange', setVh);
      
      // Extra fix for iOS
      if (this.device.isIOS) {
        // Fix for iOS keyboard causing viewport issues
        const inputs = document.querySelectorAll('input, textarea, select');
        inputs.forEach(input => {
          input.addEventListener('focus', () => {
            document.documentElement.classList.add('input-focused');
          });
          
          input.addEventListener('blur', () => {
            document.documentElement.classList.remove('input-focused');
          });
        });
      }
    },

    // Apply global fixes for all devices
    applyGlobalFixes: function() {
      // Don't force user-scalable=no anymore to prevent accidental refreshes
      // We'll use other methods to prevent refresh on small scrolls
      
      // Fix tap delay on mobile browsers
      if (this.device.hasTouch) {
        document.addEventListener('touchstart', function() {}, {passive: true});
      }
      
      // Fix for Bootstrap transitions
      const transitionEndEvents = ['webkitTransitionEnd', 'transitionend', 'otransitionend', 'oTransitionEnd'];
      transitionEndEvents.forEach(event => {
        document.body.addEventListener(event, () => {
          this.checkOverlayCleanup();
        });
      });
    },

    // Enhance modal behavior globally
    enhanceModals: function() {
      const modals = document.querySelectorAll('.modal');
      
      modals.forEach(modal => {
        // Ensure proper focus management
        modal.addEventListener('shown.bs.modal', () => {
          // Focus first focusable element
          const focusable = modal.querySelector('input:not([type="hidden"]), button.btn-close, button.close, [tabindex]:not([tabindex="-1"])');
          if (focusable) {
            setTimeout(() => focusable.focus(), 100);
          }
          
          // iOS keyboard fixes
          if (this.device.isIOS) {
            const modalBody = modal.querySelector('.modal-body');
            if (modalBody) {
              modalBody.style.maxHeight = `calc(100vh - 200px)`;
              modalBody.style.overflowY = 'auto';
              modalBody.style.webkitOverflowScrolling = 'touch';
            }
          }
          
          // Fix for modal content scroll
          if (this.device.isMobile) {
            modal.querySelector('.modal-content').style.maxHeight = `calc(100vh - 3.5rem)`;
          }
        });
        
        // Clean up stray modal backdrops on close
        modal.addEventListener('hidden.bs.modal', () => {
          this.checkOverlayCleanup();
        });
      });
    },

    // Enhance inputs for all device types
    enhanceInputs: function() {
      // Make all form inputs large enough on mobile
      if (this.device.isMobile || this.device.isTablet) {
        const inputs = document.querySelectorAll('.form-control, .form-select');
        inputs.forEach(input => {
          input.classList.add('input-enhanced');
          
          // Fix iOS specific issues
          if (this.device.isIOS) {
            // iOS date inputs fix
            if (input.type === 'date' || input.type === 'time' || input.type === 'datetime-local') {
              input.style.paddingRight = '0.75rem';
              input.style.minHeight = 'var(--input-height)';
            }
          }
        });
      }
      
      // Enhance Select2 dropdowns if present
      if (typeof $.fn.select2 !== 'undefined') {
        try {
          // Re-initialize any Select2 instances to apply responsive fixes
          setTimeout(() => {
            $('.select2-container').each(function() {
              const selectElement = $(this).siblings('select');
              if (selectElement.length) {
                const config = {
                  theme: 'bootstrap-5',
                  width: '100%',
                  dropdownParent: $(selectElement).closest('.modal').length ? 
                    $(selectElement).closest('.modal') : $('body')
                };
                
                if (selectElement.is('[multiple]')) {
                  config.placeholder = selectElement.data('placeholder') || 'Select multiple options';
                } else {
                  config.placeholder = selectElement.data('placeholder') || 'Select an option';
                }
                
                selectElement.select2(config);
              }
            });
          }, 500);
        } catch (e) {
          // console.warn('Error enhancing Select2:', e);
        }
      }
    },

    // Enhance button behavior
    enhanceButtons: function() {
      const buttons = document.querySelectorAll('button, .btn, [class*="btn-"], .nav-link');
      
      buttons.forEach(button => {
        // Ensure no transform effects on touch
        if (this.device.hasTouch) {
          button.addEventListener('touchstart', function(e) {
            this.classList.add('touch-active');
          }, {passive: true});
          
          button.addEventListener('touchend', function(e) {
            this.classList.remove('touch-active');
          }, {passive: true});
        }
        
        // Ensure minimum size for touch targets
        if (this.device.isMobile || this.device.isTablet) {
          if (button.offsetHeight < 44 && !button.classList.contains('btn-close')) {
            button.style.minHeight = 'var(--touch-target-size)';
          }
        }
      });
    },

    // Improve navigation elements
    improveNavigation: function() {
      // Fix tabs on mobile
      const tabContainers = document.querySelectorAll('.nav-tabs, .nav-pills');
      
      tabContainers.forEach(container => {
        // Only show on mobile (< 768px) and only if multiple tabs exist
        if (window.innerWidth < 768 && container.scrollWidth > container.clientWidth) {
          const tabs = container.querySelectorAll('.nav-link');
          if (tabs.length > 1) {
            container.classList.add('scrollable-tabs');
            container.style.overflowX = 'auto';
            container.style.flexWrap = 'nowrap';
            container.style.webkitOverflowScrolling = 'touch';
            container.style.msOverflowStyle = 'none';
            container.style.scrollbarWidth = 'none';
            
            // Add visual scroll indicator if not already present
            if (!container.nextElementSibling || !container.nextElementSibling.classList.contains('tabs-scroll-hint')) {
              const scrollHint = document.createElement('div');
              scrollHint.className = 'tabs-scroll-hint';
              scrollHint.innerHTML = '<small class="text-muted"><i class="ti ti-arrows-horizontal me-1"></i>swipe</small>';
              scrollHint.style.textAlign = 'center';
              scrollHint.style.fontSize = '0.7rem';
              scrollHint.style.marginTop = '0.25rem';
              scrollHint.style.marginBottom = '0.5rem';
              scrollHint.style.opacity = '0.7';
              
              container.parentNode.insertBefore(scrollHint, container.nextSibling);
            }
          }
        } else {
          // Remove any existing swipe hints on desktop or single tabs
          const existingHint = container.nextElementSibling;
          if (existingHint && existingHint.classList.contains('tabs-scroll-hint')) {
            existingHint.remove();
          }
        }
      });
      
      // Enhance sidebar navigation
      const layoutMenu = document.querySelector('.layout-menu');
      if (layoutMenu && (this.device.isMobile || this.device.isTablet)) {
        const menuItems = layoutMenu.querySelectorAll('.menu-item');
        
        menuItems.forEach(item => {
          // Make submenus more touch-friendly
          if (item.classList.contains('menu-item-has-children')) {
            const toggle = item.querySelector('.menu-toggle');
            if (toggle) {
              toggle.style.minHeight = 'var(--touch-target-size)';
            }
          }
          
          // Make menu links more touch-friendly
          const link = item.querySelector('.menu-link');
          if (link) {
            link.style.minHeight = 'var(--touch-target-size)';
          }
        });
      }
    },

    // Setup scroll improvements
    setupScrolling: function() {
      // Improve browser scroll physics on iOS
      if (this.device.isIOS) {
        document.body.style.webkitOverflowScrolling = 'touch';
      }
      
      // Add smooth scrolling to anchor links
      document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        if (anchor.getAttribute('href').length > 1) { // Skip empty anchors
          anchor.addEventListener('click', function(e) {
            const targetId = this.getAttribute('href');
            if (targetId === '#' || !targetId) return;
            
            const targetElement = document.querySelector(targetId);
            if (targetElement) {
              e.preventDefault();
              
              targetElement.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
              });
            }
          });
        }
      });
    },

    // Monitor and display network status
    monitorNetworkStatus: function() {
      // Network status monitoring
      window.addEventListener('online', () => {
        this.showNetworkStatus(true);
      });
      
      window.addEventListener('offline', () => {
        this.showNetworkStatus(false);
      });
    },

    // Show network status toast
    showNetworkStatus: function(isOnline) {
      const statusDiv = document.createElement('div');
      statusDiv.className = 'network-status-indicator fixed-bottom m-3';
      statusDiv.style.position = 'fixed';
      statusDiv.style.left = '50%';
      statusDiv.style.transform = 'translateX(-50%)';
      statusDiv.style.zIndex = '9999';
      statusDiv.style.borderRadius = 'var(--border-radius)';
      statusDiv.style.boxShadow = '0 0.25rem 1rem rgba(0, 0, 0, 0.15)';
      statusDiv.style.padding = '0.75rem 1.25rem';
      statusDiv.style.display = 'flex';
      statusDiv.style.alignItems = 'center';
      statusDiv.style.justifyContent = 'center';
      statusDiv.style.opacity = '0';
      statusDiv.style.transition = 'opacity 0.3s ease';
      statusDiv.style.pointerEvents = 'none';
      
      if (isOnline) {
        statusDiv.style.backgroundColor = '#198754'; // Success green
        statusDiv.innerHTML = '<i class="ti ti-wifi me-2"></i> Connected';
      } else {
        statusDiv.style.backgroundColor = '#dc3545'; // Danger red
        statusDiv.innerHTML = '<i class="ti ti-wifi-off me-2"></i> Disconnected';
      }
      
      statusDiv.style.color = 'white';
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

    // Attach global event listeners
    attachGlobalEventListeners: function() {
      // Handle orientation changes
      window.addEventListener('orientationchange', () => {
        // Fix view after orientation change
        setTimeout(() => {
          this.fixViewportHeight();
          this.improveNavigation();
          
          // Dispatch custom event for other components
          const event = new CustomEvent('app:orientationchange');
          document.dispatchEvent(event);
        }, 200);
      });
      
      // Handle resize events - debounced
      let resizeTimer;
      window.addEventListener('resize', () => {
        clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => {
          this.detectDevice();
          this.applyDeviceClasses();
          this.fixViewportHeight();
          this.improveNavigation();
          
          // Dispatch custom event for other components
          const event = new CustomEvent('app:resize');
          document.dispatchEvent(event);
        }, 250);
      });
      
      // Fix any overlay/backdrop issues
      document.addEventListener('click', (e) => {
        setTimeout(() => {
          this.checkOverlayCleanup();
        }, 300);
      });
    },

    // Clean up any stray modal backdrops or overlays
    checkOverlayCleanup: function() {
      const openModals = document.querySelectorAll('.modal.show');
      const modalBackdrops = document.querySelectorAll('.modal-backdrop');
      
      // If there are no open modals but we have backdrops, clean them up
      if (openModals.length === 0 && modalBackdrops.length > 0) {
        modalBackdrops.forEach(backdrop => {
          if (backdrop.parentNode) {
            backdrop.parentNode.removeChild(backdrop);
          }
        });
        
        // Fix body classes
        document.body.classList.remove('modal-open');
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
      }
    },

    // Monitor DOM changes to enhance new elements
    setupMutationObserver: function() {
      // Set up an observer to watch for dynamically added elements
      const observer = new MutationObserver((mutations) => {
        let shouldEnhance = false;
        
        mutations.forEach(mutation => {
          if (mutation.addedNodes.length) {
            shouldEnhance = true;
          }
        });
        
        if (shouldEnhance) {
          this.enhanceNewElements();
        }
      });
      
      // Start observing the document body for changes
      observer.observe(document.body, {
        childList: true,
        subtree: true
      });
    },

    // Enhance dynamically added elements
    enhanceNewElements: function() {
      this.enhanceInputs();
      this.enhanceButtons();
      this.improveNavigation();
      this.enhanceModals();
    }
  };
  
  // Initialize when DOM is ready
  document.addEventListener('DOMContentLoaded', function() {
    ResponsiveGlobal.init();
  });
  
  // Make available globally for other scripts
  window.ResponsiveGlobal = ResponsiveGlobal;
})();