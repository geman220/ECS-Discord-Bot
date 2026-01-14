/**
 * Mobile Draft System Enhancement
 *
 * Optimizes the draft system for touch interactions on mobile devices.
 * Provides alternatives to drag-and-drop and improves touch target sizing.
 *
 * Features:
 * - Tap-to-select instead of drag-and-drop
 * - Long-press for player details
 * - Swipe navigation between teams
 * - Larger touch targets for player cards
 * - Mobile-optimized pitch view
 * - Quick draft mode for mobile
 *
 * REFACTORED: All inline style manipulations replaced with CSS classes
 * See /app/static/css/utilities/draft-system-utils.css for utility classes
 */
// ES Module
'use strict';

import { EventDelegation } from './event-delegation/core.js';
const MobileDraft = {
    selectedPlayer: null,
    selectedTeam: null,

    /**
     * Check if device is mobile
     */
    isMobile: function () {
      return window.innerWidth < 768;
    },

    /**
     * Replace drag-and-drop with tap-to-select on mobile
     * ROOT CAUSE FIX: Uses event delegation for click handling
     */
    _tapToSelectRegistered: false,
    setupTapToSelect: function () {
      if (!this.isMobile()) return;

      const self = this;

      // One-time setup: delegated click handler
      if (!this._tapToSelectRegistered) {
        this._tapToSelectRegistered = true;

        document.addEventListener('click', function(e) {
          // Guard: ensure e.target is an Element with closest method
          if (!e.target || typeof e.target.closest !== 'function') return;

          const card = e.target.closest('[data-component="player-card"], [data-component="player-item"]');
          if (!card) return;

          // Prevent if clicking a button inside
          if (e.target.closest('button, a')) return;

          const playerId = card.dataset.playerId || card.id;

          // Toggle selection
          if (card.classList.contains('mobile-selected')) {
            card.classList.remove('mobile-selected');
            self.selectedPlayer = null;

            if (window.Haptics) window.Haptics.deselection();
          } else {
            // Deselect other cards
            document.querySelectorAll('.mobile-selected').forEach(c => {
              c.classList.remove('mobile-selected');
            });

            // Select this card
            card.classList.add('mobile-selected');
            self.selectedPlayer = playerId;

            if (window.Haptics) window.Haptics.selection();

            // Show quick draft panel
            self.showQuickDraftPanel(card);
          }
        });
      }

      // Apply CSS classes to existing cards (idempotent)
      document.querySelectorAll('[data-component="player-card"], [data-component="player-item"]').forEach(card => {
        card.removeAttribute('draggable');
        card.classList.add('cursor-pointer');

        // Long-press for player details (Hammer needs per-element setup)
        if (window.Hammer && !card._hammerInitialized) {
          card._hammerInitialized = true;
          const hammer = new window.Hammer(card);
          hammer.get('press').set({ time: 500 });

          hammer.on('press', () => {
            if (window.Haptics) window.Haptics.longPress();

            // Find and click view profile button
            const viewBtn = card.querySelector('[data-action="view-profile"]');
            if (viewBtn) {
              viewBtn.click();
            } else {
              // Show player info modal
              const playerId = card.dataset.playerId;
              if (playerId && window.showPlayerInfo) {
                window.showPlayerInfo(playerId);
              }
            }
          });
        }
      });
    },

    /**
     * Show quick draft panel when player is selected
     * REFACTORED: Replaced style.zIndex with z-index-1060 utility class
     */
    showQuickDraftPanel: function (card) {
      // Remove existing panel
      const existing = document.querySelector('.mobile-quick-draft-panel');
      if (existing) existing.remove();

      // Create quick draft panel
      const panel = document.createElement('div');
      // REFACTORED: Added z-index-1060 class instead of inline style.zIndex
      panel.className = 'mobile-quick-draft-panel position-fixed bottom-0 start-0 end-0 bg-body border-top border-primary border-2 p-3 translate-y-full transition-transform z-index-1060';

      // Get player info from card
      const playerName = card.querySelector('[data-component="player-name"], .fw-semibold, h6')?.textContent || 'Player';
      const playerId = card.dataset.playerId;

      panel.innerHTML = `
        <div class="d-flex align-items-center justify-content-between mb-3">
          <div class="d-flex align-items-center gap-2">
            <img src="${card.querySelector('img')?.src || ''}"
                 class="rounded-circle"
                 width="40" height="40"
                 onerror="this.src='/static/assets/img/default-avatar.png'">
            <div>
              <div class="fw-bold">${playerName}</div>
              <div class="small text-muted">Select team to draft</div>
            </div>
          </div>
          <button class="text-gray-900 bg-gray-100 hover:bg-gray-200 focus:ring-4 focus:ring-gray-100 font-medium rounded-lg text-xs px-3 py-1.5 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600" data-action="close-quick-draft-panel" aria-label="Close"><i class="ti ti-x"></i></button>
        </div>
        <div class="d-grid gap-2">
          <button class="text-white bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-base px-6 py-3" data-action="quick-draft" data-player-id="${playerId}" data-team="default">
            <i class="ti ti-check"></i> Quick Draft
          </button>
          <button class="text-ecs-green bg-transparent border border-ecs-green hover:bg-ecs-green hover:text-white focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-5 py-2.5" data-action="show-team-selector" data-player-id="${playerId}">
            <i class="ti ti-users"></i> Select Team
          </button>
        </div>
      `;

      document.body.appendChild(panel);

      // Animate in
      setTimeout(() => {
        panel.classList.remove('translate-y-full');
      }, 10);

      if (window.Haptics) window.Haptics.light();
    },

    /**
     * Quick draft to default team
     */
    quickDraft: function (playerId, teamId) {
      // Find draft button and click it
      const draftBtn = document.querySelector(`[data-player-id="${playerId}"] [data-action="draft-player"]`);
      if (draftBtn) {
        draftBtn.click();

        if (window.Haptics) window.Haptics.drafted();

        // Close panel
        const panel = document.querySelector('.mobile-quick-draft-panel');
        if (panel) panel.remove();
      }
    },

    /**
     * Show team selector modal
     */
    showTeamSelector: function (playerId) {
      // Find and click team selection modal trigger (Flowbite pattern)
      const selectBtn = document.querySelector(`[data-player-id="${playerId}"] [data-modal-toggle]`);
      if (selectBtn) {
        selectBtn.click();
      }

      // Close quick draft panel
      const panel = document.querySelector('.mobile-quick-draft-panel');
      if (panel) panel.remove();
    },

    /**
     * Optimize pitch view for mobile
     * REFACTORED: Replaced style.webkitOverflowScrolling with webkit-overflow-scrolling-touch class
     * NOTE: Lines 217-218 and 228 kept dynamic for real-time pinch-to-zoom gesture tracking
     */
    optimizePitchView: function () {
      if (!this.isMobile()) return;

      const pitch = document.querySelector('.pitch-container, .pitch-view, #pitch');
      if (!pitch) return;

      // Make pitch scrollable horizontally on mobile
      // REFACTORED: Added webkit-overflow-scrolling-touch class instead of inline style
      pitch.classList.add('overflow-x-auto', 'webkit-overflow-scrolling-touch');

      // Increase player marker sizes on mobile
      pitch.querySelectorAll('.position-player, .player-marker').forEach(marker => {
        marker.classList.add('mobile-touch-target', 'fs-6');
      });

      // Make position zones larger on mobile
      pitch.querySelectorAll('.position-zone, .zone').forEach(zone => {
        zone.classList.add('mobile-zone-enhanced', 'fs-7');
      });

      // Add pinch-to-zoom if Hammer.js is available
      if (window.Hammer) {
        const hammer = new window.Hammer(pitch);
        hammer.get('pinch').set({ enable: true });

        let lastScale = 1;

        hammer.on('pinchstart', () => {
          pitch.classList.remove('transition-transform');
        });

        hammer.on('pinchmove', (ev) => {
          const scale = Math.max(1, Math.min(lastScale * ev.scale, 3));
          // KEEP DYNAMIC: Real-time pinch gesture tracking requires inline styles
          // These cannot be replaced with classes as they change continuously during gesture
          pitch.style.transform = `scale(${scale})`;
          pitch.style.transformOrigin = 'center center';
        });

        hammer.on('pinchend', (ev) => {
          pitch.classList.add('transition-transform');
          lastScale = Math.max(1, Math.min(lastScale * ev.scale, 3));

          // Reset after 5 seconds
          if (lastScale > 1.2) {
            setTimeout(() => {
              // KEEP DYNAMIC: Resetting transform after zoom timeout
              pitch.style.transform = 'scale(1)';
              lastScale = 1;
            }, 5000);
          }
        });
      }
    },

    /**
     * Swipe navigation between teams
     */
    setupTeamSwipe: function () {
      if (!this.isMobile() || !window.Hammer) return;

      const teamsContainer = document.querySelector('.teams-container, .accordion');
      if (!teamsContainer) return;

      const hammer = new window.Hammer(teamsContainer);
      hammer.get('swipe').set({ direction: window.Hammer.DIRECTION_HORIZONTAL });

      const teams = Array.from(teamsContainer.querySelectorAll('.accordion-item, .team-card'));

      hammer.on('swipeleft', () => {
        // Go to next team
        const activeIndex = teams.findIndex(team =>
          team.querySelector('.accordion-collapse.show') || team.classList.contains('active')
        );

        if (activeIndex < teams.length - 1) {
          const nextTeam = teams[activeIndex + 1];
          const btn = nextTeam.querySelector('.accordion-button, .team-toggle');
          if (btn) btn.click();

          if (window.Haptics) window.Haptics.swipe();
        }
      });

      hammer.on('swiperight', () => {
        // Go to previous team
        const activeIndex = teams.findIndex(team =>
          team.querySelector('.accordion-collapse.show') || team.classList.contains('active')
        );

        if (activeIndex > 0) {
          const prevTeam = teams[activeIndex - 1];
          const btn = prevTeam.querySelector('.accordion-button, .team-toggle');
          if (btn) btn.click();

          if (window.Haptics) window.Haptics.swipe();
        }
      });
    },

    /**
     * Optimize player remove buttons for touch
     * ROOT CAUSE FIX: Uses event delegation for haptic feedback
     */
    _removeButtonsRegistered: false,
    optimizeRemoveButtons: function () {
      if (!this.isMobile()) return;

      const self = this;

      // One-time setup: delegated click handler for haptic feedback
      if (!this._removeButtonsRegistered) {
        this._removeButtonsRegistered = true;

        document.addEventListener('click', function(e) {
          // Guard: ensure e.target is an Element with closest method
          if (!e.target || typeof e.target.closest !== 'function') return;

          const btn = e.target.closest('[data-action="remove-player"]');
          if (!btn) return;

          // Haptic feedback
          if (window.Haptics) window.Haptics.delete();

          // Mobile confirmation
          if (self.isMobile() && window.Swal && !btn._confirmationHandled) {
            e.preventDefault();
            e.stopPropagation();

            window.Swal.fire({
              title: 'Remove Player?',
              text: 'Are you sure you want to remove this player from the team?',
              icon: 'warning',
              showCancelButton: true,
              confirmButtonText: 'Yes, remove',
              cancelButtonText: 'Cancel',
              confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
            }).then((result) => {
              if (result.isConfirmed) {
                btn._confirmationHandled = true;
                btn.click(); // Re-trigger with confirmation flag
                btn._confirmationHandled = false;
                if (window.Haptics) window.Haptics.delete();
              }
            });
          }
        }, true); // Capture phase to intercept before default handlers
      }

      // Apply CSS classes to existing buttons (idempotent)
      document.querySelectorAll('[data-action="remove-player"]').forEach(btn => {
        btn.classList.add('mobile-touch-target', 'p-3');
      });
    },

    /**
     * Optimize search and filters for mobile
     * REFACTORED: Replaced inline style.top and style.zIndex with sticky-filter-mobile class
     */
    optimizeFilters: function () {
      if (!this.isMobile()) return;

      const searchInput = document.querySelector('[data-component="player-search"], input#playerSearch');
      if (searchInput) {
        searchInput.classList.add('mobile-input-no-zoom', 'mobile-touch-target');
      }

      const filterSelects = document.querySelectorAll('[data-component="filter-select"], select[data-filter]');
      filterSelects.forEach(select => {
        select.classList.add('mobile-input-no-zoom', 'mobile-touch-target');
      });

      // Make filter controls sticky on mobile
      // REFACTORED: Replaced style.top and style.zIndex with sticky-filter-mobile utility class
      const filterContainer = document.querySelector('[data-component="draft-controls"], [data-component="filters"]');
      if (filterContainer) {
        filterContainer.classList.add('sticky-filter-mobile', 'bg-body', 'pb-3', 'mb-3', 'border-bottom');
      }
    },

    /**
     * Add mobile-specific CSS
     * NOTE: This method injects CSS for backwards compatibility and mobile-specific styling
     * that doesn't fit into the main utility class system
     */
    addMobileDraftStyles: function () {
      if (document.getElementById('mobile-draft-styles')) return;

      const style = document.createElement('style');
      style.id = 'mobile-draft-styles';
      style.textContent = `
        /* Mobile draft optimizations */
        @media (max-width: 767.98px) {
          /* Utility classes for mobile interactions */
          .cursor-pointer { cursor: pointer; }
          .translate-y-full { transform: translateY(100%); }
          .transition-transform { transition: transform 0.3s ease; }
          .overflow-x-auto { overflow-x: auto; }

          .mobile-touch-target {
            min-width: 44px;
            min-height: 44px;
          }

          .mobile-zone-enhanced {
            min-height: 60px;
          }

          .mobile-input-no-zoom {
            font-size: 16px; /* Prevent iOS zoom on focus */
          }

          /* Selected player indicator */
          .mobile-selected {
            border: 3px solid var(--bs-primary) !important;
            box-shadow: 0 0 0 4px rgba(13, 110, 253, 0.2) !important;
            transform: scale(1.02);
          }

          /* Player cards */
          [data-component="player-card"],
          [data-component="player-item"] {
            min-height: 80px;
            margin-bottom: 12px;
          }

          [data-component="player-card"] img,
          [data-component="player-item"] img {
            width: 60px;
            height: 60px;
          }

          /* Draft buttons */
          [data-action="draft-player"],
          button[data-action*="draft"] {
            min-height: 48px;
            font-size: 16px;
            padding: 12px 20px;
          }

          /* Team accordion */
          .accordion-button {
            min-height: 56px;
            font-size: 16px;
            padding: 16px;
          }

          /* Position zones on pitch */
          .position-zone,
          .zone {
            min-height: 60px;
            padding: 8px;
          }

          /* Player markers on pitch */
          .position-player,
          .player-marker {
            min-width: 44px;
            min-height: 44px;
            font-size: 14px;
          }

          /* Quick draft panel animation */
          .mobile-quick-draft-panel {
            animation: slideUp 0.3s ease;
            box-shadow: 0 -4px 12px rgba(0,0,0,0.2);
          }

          @keyframes slideUp {
            from { transform: translateY(100%); }
            to { transform: translateY(0); }
          }

          /* Remove buttons */
          [data-action="remove-player"],
          button[data-action*="remove"] {
            min-width: 44px !important;
            min-height: 44px !important;
          }

          /* Filter controls */
          [data-component="filters"],
          [data-component="draft-controls"] {
            flex-wrap: wrap;
            gap: 8px;
          }

          [data-component="filters"] > *,
          [data-component="draft-controls"] > * {
            flex: 1 1 100%;
          }

          /* Hide drag handles on mobile */
          [data-component="drag-handle"],
          [draggable="true"]::before {
            display: none;
          }

          /* Stack pitch and teams vertically */
          .draft-layout {
            flex-direction: column;
          }

          /* Full-width teams on mobile */
          .teams-section {
            width: 100%;
            max-width: 100%;
          }
        }

        /* Pitch container scroll hint */
        .pitch-container::after {
          content: 'Swipe to view full pitch';
          position: absolute;
          bottom: 8px;
          right: 8px;
          background: rgba(0,0,0,0.7);
          color: white;
          padding: 4px 8px;
          border-radius: 4px;
          font-size: 12px;
          pointer-events: none;
          opacity: 0;
          transition: opacity 0.3s;
        }

        .pitch-container:hover::after {
          opacity: 1;
        }
      `;
      document.head.appendChild(style);
    },

    /**
     * Initialize mobile draft enhancements
     */
    init: function () {
      if (!this.isMobile()) {
        console.log('MobileDraft: Not mobile, skipping initialization');
        return;
      }

      // Add styles
      this.addMobileDraftStyles();

      // Setup all enhancements
      this.setupTapToSelect();
      this.optimizePitchView();
      this.setupTeamSwipe();
      this.optimizeRemoveButtons();
      this.optimizeFilters();

      // Re-run when new players are added to DOM
      // REFACTORED: Uses UnifiedMutationObserver to prevent cascade effects
      if (window.UnifiedMutationObserver) {
        const self = this;
        window.UnifiedMutationObserver.register('mobile-draft', {
          onAddedNodes: function(nodes) {
            let shouldUpdate = false;

            nodes.forEach(node => {
              if (node.getAttribute?.('data-component') === 'player-card' ||
                  node.getAttribute?.('data-component') === 'player-item' ||
                  node.querySelector?.('[data-component="player-card"], [data-component="player-item"]')) {
                shouldUpdate = true;
              }
            });

            if (shouldUpdate) {
              self.setupTapToSelect();
              self.optimizeRemoveButtons();
            }
          },
          filter: function(node) {
            return node.getAttribute?.('data-component') === 'player-card' ||
                   node.getAttribute?.('data-component') === 'player-item' ||
                   node.querySelector?.('[data-component="player-card"], [data-component="player-item"]');
          },
          priority: 110 // Run after responsive-system
        });
      }

      console.log('MobileDraft: Initialized successfully');
    }
  };

import { InitSystem } from './init-system.js';

let _mobileInitialized = false;

function initMobileDraft() {
    if (_mobileInitialized) return;

    // Only init if on draft page
    if (!document.querySelector('[data-component="player-card"], [data-component="draft-container"]')) {
        return;
    }

    _mobileInitialized = true;
    window.MobileDraft.init();
}

window.InitSystem.register('mobile-draft', initMobileDraft, {
    priority: 30,
    reinitializable: false,
    description: 'Mobile draft system enhancements'
});

// Fallback
// window.InitSystem handles initialization

  // Expose globally
  window.MobileDraft = MobileDraft;

  // ========================================================================
  // EVENT DELEGATION REGISTRATIONS
  // ========================================================================
  // MUST use window.EventDelegation to avoid TDZ errors in bundled code

  if (true) {
    window.EventDelegation.register('close-quick-draft-panel', function(element) {
      const panel = element.closest('.mobile-quick-draft-panel');
      if (panel) panel.remove();
    }, { preventDefault: true });

    window.EventDelegation.register('quick-draft', function(element) {
      const playerId = element.dataset.playerId;
      const team = element.dataset.team || 'default';
      if (playerId && window.MobileDraft) {
        window.MobileDraft.quickDraft(playerId, team);
      }
    }, { preventDefault: true });

    window.EventDelegation.register('show-team-selector', function(element) {
      const playerId = element.dataset.playerId;
      if (playerId && window.MobileDraft) {
        window.MobileDraft.showTeamSelector(playerId);
      }
    }, { preventDefault: true });
  }

