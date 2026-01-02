/**
 * Mobile Gestures - Touch Interaction Handler
 *
 * Provides comprehensive gesture support using Hammer.js for mobile interactions.
 * Handles swipe, long-press, double-tap, pinch-to-zoom, and pull-to-refresh.
 *
 * Dependencies: Hammer.js (already loaded in helpers.js)
 * Usage: Automatically initializes on DOMContentLoaded
 *
 * @version 1.0.1
 * @updated 2025-12-26 - Code review for window.EventDelegation (no changes needed - uses Hammer.js)
 */
// ES Module
'use strict';

import { InitSystem } from './init-system.js';

let _initialized = false;

/**
   * Mobile Gestures Controller
   */
export const MobileGestures = {
    /**
     * Check if device supports touch
     * @returns {boolean}
     */
    isTouchDevice: function () {
      return ('ontouchstart' in window) ||
        (navigator.maxTouchPoints > 0) ||
        (navigator.msMaxTouchPoints > 0);
    },

    /**
     * Check if Hammer.js is loaded
     * @returns {boolean}
     */
    isHammerLoaded: function () {
      return typeof window.Hammer !== 'undefined';
    },

    /**
     * Swipe to dismiss modal (swipe down on bottom sheets)
     */
    setupModalSwipeDismiss: function () {
      if (!this.isHammerLoaded()) return;

      document.querySelectorAll('.modal.modal-bottom-sheet').forEach(modal => {
        const modalDialog = modal.querySelector('.modal-dialog');
        if (!modalDialog) return;

        const hammer = new window.Hammer(modalDialog);
        hammer.get('swipe').set({ direction: window.Hammer.DIRECTION_DOWN, threshold: 50 });

        hammer.on('swipedown', (ev) => {
          // Only dismiss if swiping from near the top (drag handle area)
          if (ev.center.y < 100) {
            const bootstrapModal = window.bootstrap.Modal.getInstance(modal);
            if (bootstrapModal) {
              if (window.Haptics) window.Haptics.modalClose();
              bootstrapModal.hide();
            }
          }
        });

        // Visual feedback during pan (drag)
        hammer.get('pan').set({ direction: window.Hammer.DIRECTION_DOWN, threshold: 0 });
        let startY = 0;

        hammer.on('panstart', (ev) => {
          startY = ev.center.y;
          // REFACTORED: Using utility classes for transitions
          modalDialog.classList.add('transition-none');
        });

        hammer.on('panmove', (ev) => {
          if (ev.center.y > startY && ev.center.y < 100) {
            const deltaY = ev.center.y - startY;
            if (deltaY > 0 && deltaY < 200) {
              // Note: Dynamic transform value, kept as inline style
              modalDialog.style.transform = `translateY(${deltaY}px)`;
            }
          }
        });

        hammer.on('panend', (ev) => {
          // REFACTORED: Using utility classes for transitions
          modalDialog.classList.remove('transition-none');
          modalDialog.classList.add('transition-transform');
          const deltaY = ev.center.y - startY;

          if (deltaY > 100) {
            // Threshold reached, dismiss modal
            const bootstrapModal = window.bootstrap.Modal.getInstance(modal);
            if (bootstrapModal) {
              if (window.Haptics) window.Haptics.modalClose();
              bootstrapModal.hide();
            }
          } else {
            // Snap back - REFACTORED: Using utility classes
            modalDialog.classList.add('translate-y-0');
            modalDialog.style.transform = '';
          }
        });
      });
    },

    /**
     * Swipe to open/close sidebar
     */
    setupSidebarSwipe: function () {
      if (!this.isHammerLoaded()) return;

      const sidebar = document.getElementById('layout-menu');
      if (!sidebar) return;

      const body = document.body;
      const hammer = new window.Hammer(body);

      // Swipe right from left edge to open
      hammer.on('swiperight', (ev) => {
        if (ev.center.x < 50 && window.innerWidth < 992) {
          // Near left edge
          if (!sidebar.classList.contains('layout-menu-expanded')) {
            sidebar.classList.add('layout-menu-expanded');
            body.classList.add('layout-menu-expanded');
            if (window.Haptics) window.Haptics.menuOpen();
          }
        }
      });

      // Swipe left to close sidebar
      hammer.on('swipeleft', (ev) => {
        if (sidebar.classList.contains('layout-menu-expanded')) {
          sidebar.classList.remove('layout-menu-expanded');
          body.classList.remove('layout-menu-expanded');
          if (window.Haptics) window.Haptics.menuClose();
        }
      });
    },

    /**
     * Pull-to-refresh on tables and lists
     */
    setupPullToRefresh: function () {
      if (!this.isHammerLoaded()) return;

      document.querySelectorAll('[data-pull-refresh="true"], .table-responsive').forEach(container => {
        const hammer = new window.Hammer(container);
        hammer.get('pan').set({ direction: window.Hammer.DIRECTION_DOWN, threshold: 10 });

        let startY = 0;
        let isPulling = false;
        let refreshThreshold = 80;

        // Create refresh indicator - REFACTORED: Using utility classes
        let refreshIndicator = container.querySelector('.pull-refresh-indicator');
        if (!refreshIndicator) {
          refreshIndicator = document.createElement('div');
          refreshIndicator.className = 'pull-refresh-indicator position-absolute left-50 translate-middle-x d-flex align-items-center justify-content-center text-white opacity-0 z-index-1000';
          refreshIndicator.innerHTML = '<i class="ti ti-refresh"></i>';
          // Note: top, width, height, background, borderRadius, transition use specific values, kept as inline styles
          refreshIndicator.style.top = '-50px';
          refreshIndicator.style.width = '40px';
          refreshIndicator.style.height = '40px';
          refreshIndicator.style.background = 'var(--bs-primary)';
          refreshIndicator.style.borderRadius = '50%';
          refreshIndicator.style.transition = 'opacity 0.3s, top 0.3s';
          container.classList.add('position-relative');
          container.insertBefore(refreshIndicator, container.firstChild);
        }

        hammer.on('panstart', (ev) => {
          // Only allow pull-to-refresh at scroll position 0
          if (container.scrollTop === 0 || container === window) {
            startY = ev.center.y;
            isPulling = true;
          }
        });

        hammer.on('panmove', (ev) => {
          if (!isPulling) return;

          const deltaY = ev.center.y - startY;
          if (deltaY > 0 && deltaY < refreshThreshold * 1.5) {
            // Show indicator - Note: Dynamic opacity and top values, kept as inline styles
            refreshIndicator.style.opacity = Math.min(deltaY / refreshThreshold, 1);
            refreshIndicator.style.top = `${-50 + deltaY}px`;

            // Rotate icon - Note: Dynamic rotation value, kept as inline style
            const icon = refreshIndicator.querySelector('i');
            if (icon) {
              icon.style.transform = `rotate(${deltaY * 3}deg)`;
            }
          }
        });

        hammer.on('panend', (ev) => {
          if (!isPulling) return;

          const deltaY = ev.center.y - startY;

          if (deltaY > refreshThreshold) {
            // Trigger refresh
            if (window.Haptics) window.Haptics.refresh();

            refreshIndicator.style.top = '10px';
            const icon = refreshIndicator.querySelector('i');
            if (icon) {
              icon.classList.add('ti-spin');
            }

            // Dispatch custom event for refresh
            const refreshEvent = new CustomEvent('mobile:pullrefresh', {
              detail: { container: container }
            });
            container.dispatchEvent(refreshEvent);

            // Auto-hide after 2 seconds (or listen for custom event)
            setTimeout(() => {
              // REFACTORED: Using utility classes for opacity
              refreshIndicator.classList.add('opacity-0');
              refreshIndicator.style.top = '-50px';
              if (icon) icon.classList.remove('ti-spin');
            }, 2000);
          } else {
            // Snap back - REFACTORED: Using utility classes for opacity
            refreshIndicator.classList.add('opacity-0');
            refreshIndicator.style.top = '-50px';
          }

          isPulling = false;
        });
      });
    },

    /**
     * Long-press for context menus
     */
    setupLongPress: function () {
      if (!this.isHammerLoaded()) return;

      document.querySelectorAll('[data-long-press="true"], .card, .list-group-item').forEach(element => {
        const hammer = new window.Hammer(element);
        hammer.get('press').set({ time: 500 }); // 500ms for long press

        hammer.on('press', (ev) => {
          if (window.Haptics) window.Haptics.longPress();

          // Dispatch custom event
          const longPressEvent = new CustomEvent('mobile:longpress', {
            detail: { element: element, event: ev }
          });
          element.dispatchEvent(longPressEvent);

          // Visual feedback
          element.classList.add('long-press-active');
          setTimeout(() => {
            element.classList.remove('long-press-active');
          }, 200);
        });
      });
    },

    /**
     * Double-tap to zoom (images, player cards)
     */
    setupDoubleTap: function () {
      if (!this.isHammerLoaded()) return;

      document.querySelectorAll('[data-double-tap="zoom"], .player-card img, .avatar-lg').forEach(element => {
        const hammer = new window.Hammer(element);
        hammer.get('tap').set({ taps: 2, threshold: 10, posThreshold: 50 });

        let isZoomed = false;

        hammer.on('tap', (ev) => {
          if (ev.tapCount === 2) {
            if (window.Haptics) window.Haptics.doubleTap();

            if (!isZoomed) {
              // Zoom in - REFACTORED: Using utility classes
              element.classList.add('transition-transform', 'z-index-1000');
              // Note: Dynamic scale value, kept as inline style
              element.style.transform = 'scale(2)';
              isZoomed = true;
            } else {
              // Zoom out - REFACTORED: Using utility classes
              element.classList.remove('z-index-1000');
              element.classList.add('scale-1');
              element.style.transform = '';
              isZoomed = false;
            }

            // Reset after 3 seconds - REFACTORED: Using utility classes
            setTimeout(() => {
              if (isZoomed) {
                element.classList.remove('z-index-1000');
                element.classList.add('scale-1');
                element.style.transform = '';
                isZoomed = false;
              }
            }, 3000);
          }
        });
      });
    },

    /**
     * Swipe actions on table/list rows (edit, delete, archive)
     */
    setupSwipeActions: function () {
      if (!this.isHammerLoaded()) return;

      document.querySelectorAll('[data-swipe-actions="true"]').forEach(row => {
        if (row.closest('thead')) return; // Skip header rows

        const hammer = new window.Hammer(row);
        hammer.get('swipe').set({ threshold: 50, velocity: 0.3 });

        let actionsRevealed = false;

        // Create action buttons container if not exists - REFACTORED: Using utility classes
        let actionsContainer = row.querySelector('.swipe-actions');
        if (!actionsContainer) {
          actionsContainer = document.createElement('div');
          actionsContainer.className = 'swipe-actions position-absolute right-0 top-0 bottom-0 d-flex align-items-center gap-2 translate-x-100 transition-transform';
          // Note: padding, background use specific values, kept as inline styles
          actionsContainer.style.padding = '0 16px';
          actionsContainer.style.background = 'var(--bs-danger)';

          // Add default actions (can be customized with data attributes)
          const deleteBtn = document.createElement('button');
          deleteBtn.className = 'btn btn-sm btn-light';
          deleteBtn.innerHTML = '<i class="ti ti-trash"></i>';
          deleteBtn.onclick = () => {
            if (window.Haptics) window.Haptics.delete();
            const deleteEvent = new CustomEvent('mobile:swipedelete', { detail: { row } });
            row.dispatchEvent(deleteEvent);
          };
          actionsContainer.appendChild(deleteBtn);

          row.classList.add('position-relative', 'overflow-hidden');
          row.appendChild(actionsContainer);
        }

        hammer.on('swipeleft', () => {
          if (!actionsRevealed) {
            // REFACTORED: Using utility classes
            actionsContainer.classList.remove('translate-x-100');
            actionsContainer.classList.add('translate-x-0');
            // Note: Dynamic translate value, kept as inline style
            row.style.transform = 'translateX(-100px)';
            actionsRevealed = true;
            if (window.Haptics) window.Haptics.swipe();
          }
        });

        hammer.on('swiperight', () => {
          if (actionsRevealed) {
            // REFACTORED: Using utility classes
            actionsContainer.classList.remove('translate-x-0');
            actionsContainer.classList.add('translate-x-100');
            row.classList.add('translate-x-0');
            row.style.transform = '';
            actionsRevealed = false;
            if (window.Haptics) window.Haptics.swipe();
          }
        });

        // Close on tap outside (keep this - non-action click listener)
        // REFACTORED: Using utility classes
        document.addEventListener('click', (e) => {
          if (actionsRevealed && !row.contains(e.target)) {
            actionsContainer.classList.remove('translate-x-0');
            actionsContainer.classList.add('translate-x-100');
            row.classList.add('translate-x-0');
            row.style.transform = '';
            actionsRevealed = false;
          }
        });
      });
    },

    /**
     * Pinch to zoom (images, charts)
     */
    setupPinchZoom: function () {
      if (!this.isHammerLoaded()) return;

      document.querySelectorAll('[data-pinch-zoom="true"], .chart-container, img.zoomable').forEach(element => {
        const hammer = new window.Hammer(element);
        hammer.get('pinch').set({ enable: true });

        let lastScale = 1;

        hammer.on('pinchstart', () => {
          // REFACTORED: Using utility classes
          element.classList.add('transition-none');
        });

        hammer.on('pinchmove', (ev) => {
          const scale = Math.max(1, Math.min(lastScale * ev.scale, 4)); // 1x to 4x
          // Note: Dynamic scale value, kept as inline style
          element.style.transform = `scale(${scale})`;
        });

        hammer.on('pinchend', (ev) => {
          // REFACTORED: Using utility classes
          element.classList.remove('transition-none');
          element.classList.add('transition-transform');
          lastScale = Math.max(1, Math.min(lastScale * ev.scale, 4));

          // Reset to 1x after 3 seconds if zoomed - REFACTORED: Using utility classes
          if (lastScale > 1) {
            setTimeout(() => {
              element.classList.add('scale-1');
              element.style.transform = '';
              lastScale = 1;
            }, 3000);
          }
        });
      });
    },

    /**
     * Swipe navigation between tabs/pages
     */
    setupSwipeNavigation: function () {
      if (!this.isHammerLoaded()) return;

      document.querySelectorAll('[data-swipe-nav="true"], .nav-tabs').forEach(nav => {
        const hammer = new window.Hammer(nav);
        hammer.get('swipe').set({ threshold: 30 });

        const tabs = Array.from(nav.querySelectorAll('.nav-link'));
        if (tabs.length === 0) return;

        hammer.on('swipeleft', () => {
          const activeTab = tabs.find(tab => tab.classList.contains('active'));
          const activeIndex = tabs.indexOf(activeTab);
          if (activeIndex < tabs.length - 1) {
            tabs[activeIndex + 1].click();
            if (window.Haptics) window.Haptics.swipe();
          }
        });

        hammer.on('swiperight', () => {
          const activeTab = tabs.find(tab => tab.classList.contains('active'));
          const activeIndex = tabs.indexOf(activeTab);
          if (activeIndex > 0) {
            tabs[activeIndex - 1].click();
            if (window.Haptics) window.Haptics.swipe();
          }
        });
      });
    },

    /**
     * Scroll Detection - Prevent Accidental Clicks During Scroll
     *
     * On mobile, users often accidentally trigger clicks when trying to scroll.
     * This tracks scroll state and prevents click events during active scrolling.
     */
    setupScrollClickPrevention: function () {
      let isScrolling = false;
      let scrollTimeout = null;
      const SCROLL_TIMEOUT = 150; // ms to wait after scroll stops

      // Track touch move (scrolling)
      document.addEventListener('touchmove', () => {
        isScrolling = true;
        clearTimeout(scrollTimeout);
        scrollTimeout = setTimeout(() => {
          isScrolling = false;
        }, SCROLL_TIMEOUT);
      }, { passive: true });

      // Reset on touch start
      document.addEventListener('touchstart', () => {
        // Don't immediately reset - wait a tiny bit
        // This helps with quick taps after scrolling
      }, { passive: true });

      // Prevent click events during scroll momentum
      document.addEventListener('click', (e) => {
        if (isScrolling) {
          // Only prevent on interactive elements that aren't form controls
          const target = e.target;
          const isFormControl = target.matches('input, select, textarea, [contenteditable]');
          const isLink = target.closest('a, button, [role="button"], .btn, .nav-link, .list-group-item');

          if (isLink && !isFormControl) {
            e.preventDefault();
            e.stopPropagation();
            console.debug('[MobileGestures] Prevented accidental click during scroll');
          }
        }
      }, { capture: true });

      console.debug('[MobileGestures] Scroll click prevention initialized');
    },

    /**
     * Initialize all gesture handlers
     */
    init: function () {
      if (_initialized) return;

      if (!this.isTouchDevice()) {
        console.log('MobileGestures: Not a touch device, skipping initialization');
        return;
      }

      _initialized = true;

      // Always setup scroll click prevention (doesn't need Hammer.js)
      this.setupScrollClickPrevention();

      if (!this.isHammerLoaded()) {
        console.warn('MobileGestures: Hammer.js not loaded, gesture support disabled');
        return;
      }

      // Setup all gesture handlers
      this.setupModalSwipeDismiss();
      this.setupSidebarSwipe();
      this.setupPullToRefresh();
      this.setupLongPress();
      this.setupDoubleTap();
      this.setupSwipeActions();
      this.setupPinchZoom();
      this.setupSwipeNavigation();

      // Add CSS for visual feedback
      this.addGestureStyles();

      console.log('MobileGestures: Initialized successfully');
    },

    /**
     * Add CSS for gesture visual feedback
     */
    addGestureStyles: function () {
      if (document.getElementById('mobile-gesture-styles')) return;

      const style = document.createElement('style');
      style.id = 'mobile-gesture-styles';
      style.textContent = `
        .long-press-active {
          animation: long-press-pulse 0.2s ease;
        }

        @keyframes long-press-pulse {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(0.95); }
        }

        .swipe-actions button {
          touch-action: manipulation;
        }

        .pull-refresh-indicator .ti-spin {
          animation: spin 1s linear infinite;
        }

        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }

        /* Smooth transitions for swipe actions */
        [data-swipe-actions="true"],
        .table-responsive tr {
          transition: transform 0.3s ease;
        }
      `;
      document.head.appendChild(style);
    }
  };

  // Expose globally (MUST be before any callbacks or registrations)
  window.MobileGestures = MobileGestures;

  // Register with window.InitSystem
  if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('mobile-gestures', () => MobileGestures.init(), {
      priority: 40,
      reinitializable: false,
      description: 'Mobile gesture handlers'
    });
  }

  // Fallback
// window.InitSystem handles initialization

