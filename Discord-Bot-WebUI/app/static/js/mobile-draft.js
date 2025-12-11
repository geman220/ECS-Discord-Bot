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
 */

(function (window) {
  'use strict';

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
     */
    setupTapToSelect: function () {
      if (!this.isMobile()) return;

      document.querySelectorAll('.player-card, .available-player').forEach(card => {
        // Remove drag attributes on mobile
        card.removeAttribute('draggable');
        card.style.cursor = 'pointer';

        // Add touch-friendly selection
        card.addEventListener('click', (e) => {
          // Prevent if clicking a button inside
          if (e.target.closest('button, a')) return;

          const playerId = card.dataset.playerId || card.id;

          // Toggle selection
          if (card.classList.contains('mobile-selected')) {
            card.classList.remove('mobile-selected');
            this.selectedPlayer = null;

            if (window.Haptics) window.Haptics.deselection();
          } else {
            // Deselect other cards
            document.querySelectorAll('.mobile-selected').forEach(c => {
              c.classList.remove('mobile-selected');
            });

            // Select this card
            card.classList.add('mobile-selected');
            this.selectedPlayer = playerId;

            if (window.Haptics) window.Haptics.selection();

            // Show quick draft panel
            this.showQuickDraftPanel(card);
          }
        });

        // Long-press for player details
        if (window.Hammer) {
          const hammer = new Hammer(card);
          hammer.get('press').set({ time: 500 });

          hammer.on('press', () => {
            if (window.Haptics) window.Haptics.longPress();

            // Find and click view profile button
            const viewBtn = card.querySelector('[data-action="view-profile"], .view-profile, button[onclick*="profile"]');
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
     */
    showQuickDraftPanel: function (card) {
      // Remove existing panel
      const existing = document.querySelector('.mobile-quick-draft-panel');
      if (existing) existing.remove();

      // Create quick draft panel
      const panel = document.createElement('div');
      panel.className = 'mobile-quick-draft-panel';
      panel.style.cssText = `
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: var(--bs-body-bg);
        border-top: 2px solid var(--bs-primary);
        box-shadow: 0 -4px 12px rgba(0,0,0,0.2);
        padding: 16px;
        z-index: 1060;
        transform: translateY(100%);
        transition: transform 0.3s ease;
      `;

      // Get player info from card
      const playerName = card.querySelector('.player-name, .card-title, h6')?.textContent || 'Player';
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
          <button class="btn btn-sm btn-light" onclick="this.closest('.mobile-quick-draft-panel').remove()">
            <i class="ti ti-x"></i>
          </button>
        </div>
        <div class="d-grid gap-2">
          <button class="btn btn-success btn-lg" onclick="MobileDraft.quickDraft('${playerId}', 'default')">
            <i class="ti ti-check"></i> Quick Draft
          </button>
          <button class="btn btn-outline-primary" onclick="MobileDraft.showTeamSelector('${playerId}')">
            <i class="ti ti-users"></i> Select Team
          </button>
        </div>
      `;

      document.body.appendChild(panel);

      // Animate in
      setTimeout(() => {
        panel.style.transform = 'translateY(0)';
      }, 10);

      if (window.Haptics) window.Haptics.light();
    },

    /**
     * Quick draft to default team
     */
    quickDraft: function (playerId, teamId) {
      // Find draft button and click it
      const draftBtn = document.querySelector(`[data-player-id="${playerId}"] .draft-btn, button[onclick*="draft"][onclick*="${playerId}"]`);
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
      // Find and click team selection modal trigger
      const selectBtn = document.querySelector(`[data-player-id="${playerId}"] [data-bs-toggle="modal"]`);
      if (selectBtn) {
        selectBtn.click();
      }

      // Close quick draft panel
      const panel = document.querySelector('.mobile-quick-draft-panel');
      if (panel) panel.remove();
    },

    /**
     * Optimize pitch view for mobile
     */
    optimizePitchView: function () {
      if (!this.isMobile()) return;

      const pitch = document.querySelector('.pitch-container, .pitch-view, #pitch');
      if (!pitch) return;

      // Make pitch scrollable horizontally on mobile
      pitch.style.overflowX = 'auto';
      pitch.style.webkitOverflowScrolling = 'touch';

      // Increase player marker sizes on mobile
      pitch.querySelectorAll('.position-player, .player-marker').forEach(marker => {
        marker.style.minWidth = '44px';
        marker.style.minHeight = '44px';
        marker.style.fontSize = '14px';
      });

      // Make position zones larger on mobile
      pitch.querySelectorAll('.position-zone, .zone').forEach(zone => {
        zone.style.minHeight = '60px';
        zone.style.fontSize = '12px';
      });

      // Add pinch-to-zoom if Hammer.js is available
      if (window.Hammer) {
        const hammer = new Hammer(pitch);
        hammer.get('pinch').set({ enable: true });

        let lastScale = 1;

        hammer.on('pinchstart', () => {
          pitch.style.transition = 'none';
        });

        hammer.on('pinchmove', (ev) => {
          const scale = Math.max(1, Math.min(lastScale * ev.scale, 3));
          pitch.style.transform = `scale(${scale})`;
          pitch.style.transformOrigin = 'center center';
        });

        hammer.on('pinchend', (ev) => {
          pitch.style.transition = 'transform 0.3s ease';
          lastScale = Math.max(1, Math.min(lastScale * ev.scale, 3));

          // Reset after 5 seconds
          if (lastScale > 1.2) {
            setTimeout(() => {
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

      const hammer = new Hammer(teamsContainer);
      hammer.get('swipe').set({ direction: Hammer.DIRECTION_HORIZONTAL });

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
     */
    optimizeRemoveButtons: function () {
      if (!this.isMobile()) return;

      document.querySelectorAll('.remove-player, button[onclick*="remove"]').forEach(btn => {
        // Make buttons larger
        btn.style.minWidth = '44px';
        btn.style.minHeight = '44px';
        btn.style.padding = '12px';

        // Add haptic feedback
        btn.addEventListener('click', () => {
          if (window.Haptics) window.Haptics.delete();
        });

        // Add confirmation for touch
        const originalOnclick = btn.onclick;
        btn.onclick = (e) => {
          if (this.isMobile()) {
            if (window.Swal) {
              Swal.fire({
                title: 'Remove Player?',
                text: 'Are you sure you want to remove this player from the team?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, remove',
                cancelButtonText: 'Cancel',
                confirmButtonColor: '#dc3545'
              }).then((result) => {
                if (result.isConfirmed) {
                  if (originalOnclick) originalOnclick.call(btn, e);
                  if (window.Haptics) window.Haptics.delete();
                }
              });
            } else {
              if (confirm('Remove this player?')) {
                if (originalOnclick) originalOnclick.call(btn, e);
                if (window.Haptics) window.Haptics.delete();
              }
            }
            return false;
          } else {
            if (originalOnclick) return originalOnclick.call(btn, e);
          }
        };
      });
    },

    /**
     * Optimize search and filters for mobile
     */
    optimizeFilters: function () {
      if (!this.isMobile()) return;

      const searchInput = document.querySelector('input[type="search"], input[placeholder*="Search"]');
      if (searchInput) {
        searchInput.style.fontSize = '16px'; // Prevent iOS zoom
        searchInput.style.minHeight = '44px';
      }

      const filterSelects = document.querySelectorAll('select.filter, select[name*="filter"]');
      filterSelects.forEach(select => {
        select.style.fontSize = '16px';
        select.style.minHeight = '44px';
      });

      // Make filter controls sticky on mobile
      const filterContainer = document.querySelector('.filters, .search-filters, .draft-controls');
      if (filterContainer) {
        filterContainer.style.position = 'sticky';
        filterContainer.style.top = '60px'; // Below navbar
        filterContainer.style.zIndex = '100';
        filterContainer.style.background = 'var(--bs-body-bg)';
        filterContainer.style.paddingBottom = '12px';
        filterContainer.style.marginBottom = '12px';
        filterContainer.style.borderBottom = '1px solid var(--bs-border-color)';
      }
    },

    /**
     * Add mobile-specific CSS
     */
    addMobileDraftStyles: function () {
      if (document.getElementById('mobile-draft-styles')) return;

      const style = document.createElement('style');
      style.id = 'mobile-draft-styles';
      style.textContent = `
        /* Mobile draft optimizations */
        @media (max-width: 767.98px) {
          /* Selected player indicator */
          .mobile-selected {
            border: 3px solid var(--bs-primary) !important;
            box-shadow: 0 0 0 4px rgba(13, 110, 253, 0.2) !important;
            transform: scale(1.02);
          }

          /* Player cards */
          .player-card,
          .available-player {
            min-height: 80px;
            margin-bottom: 12px;
          }

          .player-card img,
          .available-player img {
            width: 60px;
            height: 60px;
          }

          /* Draft buttons */
          .draft-btn,
          button[onclick*="draft"] {
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
          }

          @keyframes slideUp {
            from { transform: translateY(100%); }
            to { transform: translateY(0); }
          }

          /* Remove buttons */
          .remove-player,
          button[onclick*="remove"] {
            min-width: 44px !important;
            min-height: 44px !important;
          }

          /* Filter controls */
          .filters,
          .search-filters,
          .draft-controls {
            flex-wrap: wrap;
            gap: 8px;
          }

          .filters > *,
          .search-filters > *,
          .draft-controls > * {
            flex: 1 1 100%;
          }

          /* Hide drag handles on mobile */
          .drag-handle,
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
      const observer = new MutationObserver((mutations) => {
        let shouldUpdate = false;

        mutations.forEach(mutation => {
          mutation.addedNodes.forEach(node => {
            if (node.nodeType === 1 &&
                (node.classList?.contains('player-card') ||
                 node.classList?.contains('available-player') ||
                 node.querySelector?.('.player-card, .available-player'))) {
              shouldUpdate = true;
            }
          });
        });

        if (shouldUpdate) {
          setTimeout(() => {
            this.setupTapToSelect();
            this.optimizeRemoveButtons();
          }, 100);
        }
      });

      observer.observe(document.body, {
        childList: true,
        subtree: true
      });

      console.log('MobileDraft: Initialized successfully');
    }
  };

  // Auto-initialize on draft pages
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      // Only init if on draft page
      if (document.querySelector('.player-card, .draft-container, [id*="draft"]')) {
        MobileDraft.init();
      }
    });
  } else {
    if (document.querySelector('.player-card, .draft-container, [id*="draft"]')) {
      MobileDraft.init();
    }
  }

  // Expose globally
  window.MobileDraft = MobileDraft;

})(window);
