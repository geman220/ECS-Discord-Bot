/**
 * ECS Soccer League Mobile & Responsive Helper
 * 
 * This utility file helps ensure consistent responsive behavior across the app.
 */

(function() {
  'use strict';
  
  // Main helper object
  const ResponsiveHelper = {
    // Initialize responsive features
    init: function() {
      this.fixIOSViewportHeight();
      this.setupTouchFriendlyControls();
      this.setupPullToRefresh();
      this.setupAddToHomeScreen();
      this.attachEventListeners();
      this.improveModalExperience();
      this.setupTabsScrolling();
    },
    
    // Fix iOS 100vh issue
    fixIOSViewportHeight: function() {
      const setVh = () => {
        let vh = window.innerHeight * 0.01;
        document.documentElement.style.setProperty('--vh', `${vh}px`);
      };
      
      setVh();
      window.addEventListener('resize', setVh);
      window.addEventListener('orientationchange', setVh);
    },
    
    // Make controls more touch-friendly
    setupTouchFriendlyControls: function() {
      if ('ontouchstart' in window) {
        // Only apply opacity effect on mobile (no transform scaling)
        const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
        
        if (isMobile) {
          // Simple opacity feedback on mobile without scaling
          const touchElements = document.querySelectorAll('button, .btn, a.nav-link, .card');
          touchElements.forEach(el => {
            el.addEventListener('touchstart', function() {
              this.style.opacity = '0.9';
            }, {passive: true});
            
            el.addEventListener('touchend', function() {
              this.style.opacity = '1';
            }, {passive: true});
          });
        }
        
        // Make form elements bigger on mobile
        if (window.innerWidth < 768) {
          const formControls = document.querySelectorAll('.form-control, .form-select');
          formControls.forEach(el => {
            el.classList.add('form-control-lg');
          });
        }
      }
    },
    
    // Setup pull-to-refresh functionality
    setupPullToRefresh: function() {
      if ('ontouchstart' in window) {
        let startY, startTopScroll;
        let refreshIndicator = null;
        
        document.addEventListener('touchstart', function(e) {
          startY = e.touches[0].pageY;
          startTopScroll = window.scrollY;
        }, {passive: true});
        
        document.addEventListener('touchmove', function(e) {
          // Only trigger when at top of page
          if (window.scrollY === 0 && e.touches[0].pageY - startY > 60) {
            if (!refreshIndicator) {
              refreshIndicator = document.createElement('div');
              refreshIndicator.className = 'refresh-indicator';
              refreshIndicator.innerHTML = `
                <div class="d-flex align-items-center justify-content-center p-2 bg-primary text-white">
                  <i class="ti ti-refresh me-2"></i>
                  <span>Pull down to refresh</span>
                </div>
              `;
              refreshIndicator.style.position = 'fixed';
              refreshIndicator.style.top = '0';
              refreshIndicator.style.left = '0';
              refreshIndicator.style.right = '0';
              refreshIndicator.style.zIndex = '9999';
              refreshIndicator.style.transform = 'translateY(-100%)';
              refreshIndicator.style.transition = 'transform 0.2s ease-out';
              document.body.appendChild(refreshIndicator);
            }
            
            // Calculate and set the pull distance
            const pullDistance = Math.min(e.touches[0].pageY - startY, 100);
            const percentage = pullDistance / 100;
            refreshIndicator.style.transform = `translateY(${-100 + (percentage * 100)}%)`;
          }
        }, {passive: true});
        
        document.addEventListener('touchend', function(e) {
          if (refreshIndicator) {
            // If pulled far enough, refresh the page
            if (window.scrollY === 0 && e.changedTouches[0].pageY - startY > 100) {
              refreshIndicator.innerHTML = `
                <div class="d-flex align-items-center justify-content-center p-2 bg-primary text-white">
                  <i class="ti ti-refresh ti-spin me-2"></i>
                  <span>Refreshing...</span>
                </div>
              `;
              refreshIndicator.style.transform = 'translateY(0)';
              
              // Refresh after animation
              setTimeout(() => {
                window.location.reload();
              }, 500);
            } else {
              // Reset and remove indicator
              refreshIndicator.style.transform = 'translateY(-100%)';
              setTimeout(() => {
                if (refreshIndicator.parentNode) {
                  document.body.removeChild(refreshIndicator);
                }
                refreshIndicator = null;
              }, 200);
            }
          }
        }, {passive: true});
      }
    },
    
    // Setup "Add to Home Screen" prompt
    setupAddToHomeScreen: function() {
      // Only proceed if we can install PWAs and user hasn't dismissed or installed
      if ('BeforeInstallPromptEvent' in window && !localStorage.getItem('pwaInstalled') && !localStorage.getItem('pwaDismissed')) {
        let deferredPrompt;
        
        window.addEventListener('beforeinstallprompt', (e) => {
          // Prevent default browser prompt
          e.preventDefault();
          
          // Store the event for later use
          deferredPrompt = e;
          
          // Create our custom prompt
          this.showAddToHomeScreen(deferredPrompt);
        });
        
        // Check if PWA was installed
        window.addEventListener('appinstalled', () => {
          localStorage.setItem('pwaInstalled', 'true');
          
          // Hide any install prompts
          const installPrompt = document.querySelector('.pwa-install-prompt');
          if (installPrompt) {
            installPrompt.remove();
          }
          
          console.log('PWA installed successfully');
        });
      }
    },
    
    // Show custom "Add to Home Screen" prompt
    showAddToHomeScreen: function(deferredPrompt) {
      // Create the prompt element if it doesn't exist
      if (!document.querySelector('.pwa-install-prompt')) {
        const prompt = document.createElement('div');
        prompt.className = 'pwa-install-prompt';
        prompt.innerHTML = `
          <div class="card shadow fixed-bottom m-2">
            <div class="card-body p-3">
              <div class="d-flex justify-content-between align-items-center">
                <div>
                  <h5 class="mb-1">Add to Home Screen</h5>
                  <p class="mb-0 small">Install this app for quick access</p>
                </div>
                <div>
                  <button class="btn btn-primary btn-sm me-2 install-button">Install</button>
                  <button class="btn btn-outline-secondary btn-sm dismiss-button">Later</button>
                </div>
              </div>
            </div>
          </div>
        `;
        document.body.appendChild(prompt);
        
        // Handle install button
        prompt.querySelector('.install-button').addEventListener('click', async () => {
          if (deferredPrompt) {
            deferredPrompt.prompt();
            const { outcome } = await deferredPrompt.userChoice;
            
            if (outcome === 'accepted') {
              localStorage.setItem('pwaInstalled', 'true');
            } else {
              localStorage.setItem('pwaDismissed', 'true');
            }
            
            deferredPrompt = null;
            prompt.remove();
          }
        });
        
        // Handle dismiss button
        prompt.querySelector('.dismiss-button').addEventListener('click', () => {
          localStorage.setItem('pwaDismissed', new Date().toISOString());
          prompt.remove();
        });
      }
    },
    
    // Attach global event listeners
    attachEventListeners: function() {
      // Fix for 300ms tap delay on mobile browsers
      if ('ontouchstart' in window) {
        document.addEventListener('touchstart', function() {}, {passive: true});
      }
      
      // Handle orientation changes
      window.addEventListener('orientationchange', () => {
        // Refresh components that need reflow after orientation change
        setTimeout(() => {
          this.setupTabsScrolling();
          
          // Notify custom components about the orientation change
          const event = new CustomEvent('app:orientationchange');
          document.dispatchEvent(event);
        }, 200);
      });
      
      // Listen for network status changes
      window.addEventListener('online', () => {
        this.showNetworkStatus(true);
      });
      
      window.addEventListener('offline', () => {
        this.showNetworkStatus(false);
      });
    },
    
    // Show network status notification
    showNetworkStatus: function(isOnline) {
      const statusDiv = document.createElement('div');
      statusDiv.className = 'network-status-indicator';
      statusDiv.style.position = 'fixed';
      statusDiv.style.bottom = '20px';
      statusDiv.style.left = '50%';
      statusDiv.style.transform = 'translateX(-50%)';
      statusDiv.style.padding = '10px 20px';
      statusDiv.style.borderRadius = '20px';
      statusDiv.style.color = 'white';
      statusDiv.style.fontSize = '14px';
      statusDiv.style.fontWeight = 'bold';
      statusDiv.style.zIndex = '9999';
      statusDiv.style.opacity = '0';
      statusDiv.style.transition = 'opacity 0.3s ease-in-out';
      
      if (isOnline) {
        statusDiv.style.backgroundColor = '#28a745';
        statusDiv.innerHTML = '<i class="ti ti-wifi me-1"></i> Back online';
      } else {
        statusDiv.style.backgroundColor = '#dc3545';
        statusDiv.innerHTML = '<i class="ti ti-wifi-off me-1"></i> You are offline';
      }
      
      document.body.appendChild(statusDiv);
      
      // Show the notification
      setTimeout(() => {
        statusDiv.style.opacity = '1';
      }, 100);
      
      // Hide after a delay
      setTimeout(() => {
        statusDiv.style.opacity = '0';
        
        setTimeout(() => {
          if (statusDiv.parentNode) {
            document.body.removeChild(statusDiv);
          }
        }, 300);
      }, 3000);
    },
    
    // Improve modal experience on mobile
    improveModalExperience: function() {
      const modals = document.querySelectorAll('.modal');
      
      modals.forEach(modal => {
        modal.addEventListener('shown.bs.modal', function() {
          // Focus the first form element or close button
          const firstInput = modal.querySelector('input, textarea, select, button.close, button.btn-close');
          if (firstInput) {
            setTimeout(() => firstInput.focus(), 100);
          }
          
          // Fix issues with iOS keyboard and scrolling
          if (/iPad|iPhone|iPod/.test(navigator.userAgent)) {
            modal.querySelector('.modal-body').style.maxHeight = 'calc(100vh - 200px)';
            modal.querySelector('.modal-body').style.overflowY = 'auto';
            modal.querySelector('.modal-body').style.webkitOverflowScrolling = 'touch';
          }
        });
      });
    },
    
    // Make tabs scrollable on smaller screens
    setupTabsScrolling: function() {
      const tabNavs = document.querySelectorAll('.nav-pills, .nav-tabs');
      
      tabNavs.forEach(tabNav => {
        // Only apply to tabs that need horizontal scrolling
        if (tabNav.scrollWidth > tabNav.clientWidth) {
          tabNav.classList.add('flex-nowrap', 'overflow-auto');
          
          // Enable smooth scrolling with touch
          tabNav.style.webkitOverflowScrolling = 'touch';
          
          // Add visual indicators for scroll
          const scrollableIndicator = document.createElement('div');
          scrollableIndicator.className = 'tabs-scroll-indicator';
          scrollableIndicator.innerHTML = '<i class="ti ti-chevron-right"></i>';
          scrollableIndicator.style.position = 'absolute';
          scrollableIndicator.style.right = '0';
          scrollableIndicator.style.top = '50%';
          scrollableIndicator.style.transform = 'translateY(-50%)';
          scrollableIndicator.style.backgroundColor = 'rgba(255, 255, 255, 0.7)';
          scrollableIndicator.style.borderRadius = '50%';
          scrollableIndicator.style.width = '20px';
          scrollableIndicator.style.height = '20px';
          scrollableIndicator.style.display = 'flex';
          scrollableIndicator.style.alignItems = 'center';
          scrollableIndicator.style.justifyContent = 'center';
          scrollableIndicator.style.pointerEvents = 'none';
          
          // Only add if not already there
          if (!tabNav.querySelector('.tabs-scroll-indicator')) {
            const tabNavParent = tabNav.parentElement;
            tabNavParent.style.position = 'relative';
            tabNavParent.appendChild(scrollableIndicator);
            
            // Show/hide indicator based on scroll position
            tabNav.addEventListener('scroll', function() {
              const isScrolledToEnd = this.scrollLeft + this.clientWidth >= this.scrollWidth - 5;
              
              if (isScrolledToEnd) {
                scrollableIndicator.style.opacity = '0';
              } else {
                scrollableIndicator.style.opacity = '1';
              }
            });
            
            // Trigger initial check
            tabNav.dispatchEvent(new Event('scroll'));
          }
        }
      });
    }
  };
  
  // Initialize on DOM ready
  document.addEventListener('DOMContentLoaded', function() {
    ResponsiveHelper.init();
  });
  
  // Make available globally
  window.ResponsiveHelper = ResponsiveHelper;
})();