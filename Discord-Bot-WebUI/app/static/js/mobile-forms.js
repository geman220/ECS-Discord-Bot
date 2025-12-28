/**
 * Mobile Forms Enhancement
 *
 * Optimizes forms, modals, and input groups for mobile devices.
 * Handles match reporting, RSVP management, and other complex forms.
 *
 * Features:
 * - Dynamic modal sizing based on device
 * - Input group optimization for touch
 * - Swipe-to-delete for repeated entries
 * - Form field collapsing/expanding
 * - Better select dropdown handling
 *
 * REFACTORED: All inline style manipulations replaced with CSS classes
 * REFACTORED: All styling class selectors replaced with stable behavioral hooks
 */

(function (window) {
  'use strict';

  const MobileForms = {
    /**
     * Check if device is mobile
     */
    isMobile: function () {
      return window.innerWidth < 768;
    },

    /**
     * Optimize modal sizes for mobile
     */
    optimizeModals: function () {
      document.querySelectorAll('[data-modal]').forEach(modal => {
        if (this.isMobile()) {
          // Convert large modals to full-screen on mobile
          const modalDialog = modal.querySelector('[data-modal-dialog]');
          if (modalDialog) {
            // If modal-lg, make it responsive
            if (modalDialog.classList.contains('modal-lg')) {
              modalDialog.classList.add('mobile-optimized-modal');
            }

            // Adjust modal content max-height with CSS class
            const modalContent = modal.querySelector('[data-modal-content]');
            if (modalContent) {
              modalContent.classList.add('mobile-modal-content');
            }
          }
        }
      });
    },

    /**
     * Optimize input groups for touch (match reporting events)
     */
    optimizeInputGroups: function () {
      document.querySelectorAll('[data-input-group]').forEach(group => {
        if (this.isMobile()) {
          // Make select dropdowns full-width on mobile
          const selects = group.querySelectorAll('select');
          selects.forEach(select => {
            select.classList.add('mobile-input-select');
          });

          // Make minute inputs larger on mobile
          const inputs = group.querySelectorAll('input[type="number"], input[placeholder*="Min"]');
          inputs.forEach(input => {
            input.classList.add('mobile-input-number');
          });

          // Make remove buttons larger for touch
          const removeButtons = group.querySelectorAll('[data-remove-btn], button[onclick*="remove"]');
          removeButtons.forEach(btn => {
            btn.classList.add('mobile-remove-btn');
          });
        }
      });
    },

    /**
     * Add swipe-to-delete for input groups
     * FIXED: Added guard to prevent duplicate Hammer listener registration
     */
    setupSwipeToDelete: function () {
      if (!window.Hammer || !this.isMobile()) return;

      document.querySelectorAll('[data-input-group][id*="event-"], [data-event-entry]').forEach(entry => {
        // Skip if already enhanced to prevent duplicate Hammer listeners
        if (entry.hasAttribute('data-swipe-enhanced')) return;
        entry.setAttribute('data-swipe-enhanced', 'true');

        const hammer = new Hammer(entry);
        hammer.get('swipe').set({ direction: Hammer.DIRECTION_LEFT, threshold: 50 });

        let deleteIndicator = entry.querySelector('.swipe-delete-indicator');
        if (!deleteIndicator) {
          deleteIndicator = document.createElement('div');
          deleteIndicator.className = 'swipe-delete-indicator';
          deleteIndicator.innerHTML = '<i class="ti ti-trash"></i> Swipe to delete';

          // Apply CSS classes instead of inline styles
          entry.classList.add('swipe-container');
          entry.appendChild(deleteIndicator);
        }

        hammer.on('swipeleft', () => {
          // Show delete indicator
          deleteIndicator.classList.add('swipe-visible');
          entry.classList.add('swipe-active');

          if (window.Haptics) window.Haptics.warning();

          // Auto-hide after 3 seconds or on tap
          const hideTimeout = setTimeout(() => {
            deleteIndicator.classList.remove('swipe-visible');
            entry.classList.remove('swipe-active');
          }, 3000);

          // Tap to confirm delete
          deleteIndicator.onclick = () => {
            clearTimeout(hideTimeout);

            if (window.Haptics) window.Haptics.delete();

            // Find and click the remove button
            const removeBtn = entry.querySelector('[data-remove-btn], button[onclick*="remove"]');
            if (removeBtn) {
              removeBtn.click();
            }
          };
        });

        hammer.on('swiperight', () => {
          // Hide delete indicator
          deleteIndicator.classList.remove('swipe-visible');
          entry.classList.remove('swipe-active');
        });
      });
    },

    /**
     * Optimize select2 dropdowns for mobile
     */
    optimizeSelect2: function () {
      if (!this.isMobile()) return;

      // Configure Select2 for mobile
      if (window.jQuery && jQuery.fn.select2) {
        jQuery('select.select2').each(function () {
          const $select = jQuery(this);

          // Reconfigure with mobile options
          if ($select.hasClass('select2-hidden-accessible')) {
            $select.select2('destroy');
          }

          $select.select2({
            width: '100%',
            dropdownAutoWidth: true,
            dropdownCssClass: 'mobile-select2-dropdown',
            containerCssClass: 'mobile-select2-container',
            minimumResultsForSearch: 10 // Show search only for long lists
          });
        });
      }
    },

    /**
     * Make form sections collapsible on mobile
     */
    makeCollapsible: function () {
      if (!this.isMobile()) return;

      // Find form sections with multiple input groups
      document.querySelectorAll('[data-modal-body] .row, [data-form-section]').forEach(section => {
        const inputGroups = section.querySelectorAll('[data-input-group]');

        if (inputGroups.length > 3) {
          // Create collapsible header
          const header = document.createElement('button');
          header.type = 'button';
          header.className = 'btn btn-link w-100 text-start mobile-collapse-toggle';
          header.innerHTML = `
            <span class="fw-bold">${section.dataset.sectionTitle || 'Show/Hide Section'}</span>
            <i class="ti ti-chevron-down float-end"></i>
          `;

          const content = document.createElement('div');
          content.className = 'mobile-collapse-content mobile-collapse-expanded';

          // Move input groups to content
          while (inputGroups.length > 0) {
            content.appendChild(inputGroups[0]);
          }

          section.insertBefore(header, section.firstChild);
          section.appendChild(content);

          // Toggle handler
          let isCollapsed = false;
          header.onclick = () => {
            isCollapsed = !isCollapsed;
            const icon = header.querySelector('i');

            if (isCollapsed) {
              content.classList.remove('mobile-collapse-expanded');
              content.classList.add('mobile-collapse-collapsed');
              icon.classList.remove('ti-chevron-down');
              icon.classList.add('ti-chevron-right');
            } else {
              content.classList.remove('mobile-collapse-collapsed');
              content.classList.add('mobile-collapse-expanded');
              icon.classList.remove('ti-chevron-right');
              icon.classList.add('ti-chevron-down');
            }

            if (window.Haptics) window.Haptics.light();
          };
        }
      });
    },

    /**
     * Optimize DataTables for mobile
     */
    optimizeDataTables: function () {
      if (!this.isMobile()) return;

      if (window.jQuery && jQuery.fn.DataTable) {
        jQuery('[data-table], .js-data-table').each(function () {
          const $table = jQuery(this);

          // Check if already initialized
          if (jQuery.fn.DataTable.isDataTable($table)) {
            const dt = $table.DataTable();

            // Update responsive settings
            dt.settings()[0].responsive = true;

            // Hide specific columns on mobile
            dt.columns([0, -1]).visible(true); // Keep first and last columns (name and actions)

            // Adjust page length
            dt.page.len(10).draw();
          } else {
            // Initialize with mobile settings
            $table.DataTable({
              responsive: true,
              pageLength: 10,
              dom: '<"top"f>rt<"bottom"ip><"clear">',
              language: {
                search: 'Filter:',
                lengthMenu: 'Show _MENU_',
                info: 'Page _PAGE_ of _PAGES_',
                infoEmpty: 'No entries',
                infoFiltered: ''
              }
            });
          }
        });
      }
    },

    /**
     * Add quick action buttons for mobile
     */
    addQuickActions: function () {
      // DISABLED: This function was creating duplicate submit buttons with inline styles
      // Mobile modal buttons are now styled purely via CSS in mobile-modals.css
      // This provides single source of truth and eliminates duplicate green submit button
      // If haptic feedback is needed, it should be added to existing submit button click handlers
      return;
    },

    /**
     * Improve textarea handling on mobile
     * ROOT CAUSE FIX: Uses event delegation for focus/input events
     */
    _textareaListenersRegistered: false,
    optimizeTextareas: function () {
      if (!this.isMobile()) return;

      // Set up document-level delegation ONCE
      if (!this._textareaListenersRegistered) {
        this._textareaListenersRegistered = true;

        // Single delegated focusin listener for ALL textareas
        document.addEventListener('focusin', function(e) {
          if (e.target.tagName === 'TEXTAREA') {
            e.target.classList.add('mobile-textarea-expanded');
          }
        }, true);

        // Single delegated input listener for ALL textareas with maxlength
        document.addEventListener('input', function(e) {
          if (e.target.tagName !== 'TEXTAREA') return;
          const textarea = e.target;
          const maxLength = textarea.getAttribute('maxlength');
          if (!maxLength) return;

          // Find or create counter
          let counter = textarea.parentElement?.querySelector('.char-counter');
          if (!counter) return; // Counter will be created in the CSS class setup below

          const remaining = parseInt(maxLength) - textarea.value.length;
          counter.textContent = `${remaining} characters remaining`;

          if (remaining < 20) {
            counter.classList.add('char-counter-warning');
          } else {
            counter.classList.remove('char-counter-warning');
          }
        }, true);
      }

      // Apply CSS classes and create counters for textareas (one-time, idempotent)
      document.querySelectorAll('textarea').forEach(textarea => {
        // Add CSS class for minimum height (idempotent)
        textarea.classList.add('mobile-textarea');

        // Create character counter if needed
        const maxLength = textarea.getAttribute('maxlength');
        if (maxLength && textarea.parentElement) {
          let counter = textarea.parentElement.querySelector('.char-counter');
          if (!counter) {
            counter = document.createElement('div');
            counter.className = 'char-counter text-muted small';
            const remaining = parseInt(maxLength) - textarea.value.length;
            counter.textContent = `${remaining} characters remaining`;
            textarea.parentElement.appendChild(counter);
          }
        }
      });
    },

    /**
     * Add floating labels for better mobile UX
     */
    convertToFloatingLabels: function () {
      if (!this.isMobile()) return;

      document.querySelectorAll('[data-form-group]:not(.form-floating)').forEach(group => {
        const label = group.querySelector('label');
        const input = group.querySelector('input, select, textarea');

        if (label && input && !input.closest('[data-input-group]')) {
          // Convert to floating label
          group.classList.add('form-floating');
          group.appendChild(label); // Move label after input
        }
      });
    },

    /**
     * Setup form validation with mobile feedback
     * ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
     */
    _validationListenersRegistered: false,
    setupMobileValidation: function () {
      // Only register once - event delegation handles all forms
      if (this._validationListenersRegistered) return;
      this._validationListenersRegistered = true;

      // Single delegated submit listener for ALL forms
      document.addEventListener('submit', function(e) {
        const form = e.target;
        if (form.tagName !== 'FORM') return;

        const invalidFields = form.querySelectorAll(':invalid');

        if (invalidFields.length > 0) {
          e.preventDefault();

          // Show first error
          const firstInvalid = invalidFields[0];
          firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
          firstInvalid.focus();

          // Visual feedback with CSS class
          firstInvalid.classList.add('shake-invalid');
          setTimeout(() => firstInvalid.classList.remove('shake-invalid'), 500);

          // Haptic feedback
          if (window.Haptics) window.Haptics.validationError();

          // Show toast
          if (window.Swal) {
            Swal.fire({
              toast: true,
              position: 'top',
              icon: 'error',
              title: 'Please fill out all required fields',
              showConfirmButton: false,
              timer: 3000
            });
          }
        }
      }, true); // Use capture phase to catch before native validation

      // Single delegated focusout listener for ALL form fields (real-time validation)
      document.addEventListener('focusout', function(e) {
        const field = e.target;
        // Only handle form fields
        if (field.tagName !== 'INPUT' && field.tagName !== 'SELECT' && field.tagName !== 'TEXTAREA') return;

        // Check if field is inside a form
        const form = field.closest('form');
        if (!form) return;

        if (field.validity.valid) {
          field.classList.remove('is-invalid');
          field.classList.add('is-valid');
        } else if (field.value) {
          field.classList.remove('is-valid');
          field.classList.add('is-invalid');
          if (window.Haptics) window.Haptics.light();
        }
      }, true);
    },

    /**
     * Add CSS for mobile form enhancements
     */
    addMobileFormStyles: function () {
      if (document.getElementById('mobile-form-styles')) return;

      const style = document.createElement('style');
      style.id = 'mobile-form-styles';
      style.textContent = `
        /* Mobile modal optimization */
        @media (max-width: 767.98px) {
          .mobile-optimized-modal {
            max-width: 100%;
            margin: 0;
          }

          .mobile-optimized-modal [data-modal-content] {
            border-radius: 16px 16px 0 0;
          }

          /* Input group stacking */
          [data-input-group] {
            flex-wrap: wrap;
            gap: 8px;
          }

          [data-input-group] > * {
            flex: 1 1 auto;
            min-width: 0;
          }

          [data-input-group] [data-remove-btn],
          [data-input-group] button[onclick*="remove"] {
            flex: 0 0 44px;
            min-width: 44px !important;
            min-height: 44px !important;
            padding: 0;
            display: flex;
            align-items: center;
            justify-content: center;
          }

          /* Select2 mobile */
          .mobile-select2-dropdown {
            font-size: 16px !important;
          }

          .mobile-select2-container .select2-selection {
            min-height: 44px;
            padding: 8px 12px;
          }

          /* Shake animation for validation */
          @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-10px); }
            75% { transform: translateX(10px); }
          }

          .shake-invalid {
            animation: shake 0.3s ease-in-out;
            border-color: var(--bs-danger) !important;
          }

          /* Mobile form row stacking */
          [data-modal-body] .row.g-2 {
            row-gap: 16px !important;
          }

          [data-modal-body] .col-md-6,
          [data-modal-body] .col-lg-6 {
            width: 100%;
          }

          /* Sticky submit button spacing */
          [data-modal-footer] {
            padding-bottom: 0 !important;
          }

          /* Larger touch targets in modals */
          [data-modal] .btn {
            min-height: 48px;
            font-size: 16px;
            padding: 12px 24px;
          }

          [data-modal] .form-control,
          [data-modal] .form-select {
            min-height: 44px;
            font-size: 16px;
          }
        }

        /* Swipe delete indicator */
        .swipe-delete-indicator {
          font-size: 14px;
          font-weight: 600;
          cursor: pointer;
        }

        /* Entry transition for swipe */
        [data-input-group],
        [data-event-entry] {
          transition: transform 0.3s ease;
        }
      `;
      document.head.appendChild(style);
    },

    /**
     * Initialize all mobile form enhancements
     * ROOT CAUSE FIX: Added module-level init guard
     */
    _initialized: false,
    init: function () {
      // Only initialize once
      if (this._initialized) {
        console.log('[MobileForms] Already initialized, skipping');
        return;
      }
      this._initialized = true;

      // Add styles first
      this.addMobileFormStyles();

      // Run optimizations
      this.optimizeModals();
      this.optimizeInputGroups();
      this.optimizeSelect2();
      this.optimizeDataTables();
      this.optimizeTextareas();
      this.setupMobileValidation();

      if (this.isMobile()) {
        this.setupSwipeToDelete();
        this.addQuickActions();
        // this.makeCollapsible(); // Optional: enable if needed
        // this.convertToFloatingLabels(); // Optional: enable if needed
      }

      // Re-run on modal shown (only register listener once)
      // FIXED: Added guard to prevent duplicate global event listener registration
      if (!this._modalListenerRegistered) {
        this._modalListenerRegistered = true;
        document.addEventListener('shown.bs.modal', () => {
          setTimeout(() => {
            this.optimizeInputGroups();
            this.setupSwipeToDelete();
            this.addQuickActions();
          }, 100);
        });
      }

      // Re-run on window resize (only register listener once)
      // FIXED: Added guard to prevent duplicate global event listener registration
      if (!this._resizeListenerRegistered) {
        this._resizeListenerRegistered = true;
        let resizeTimeout;
        window.addEventListener('resize', () => {
          clearTimeout(resizeTimeout);
          resizeTimeout = setTimeout(() => {
            if (this.isMobile()) {
              this.optimizeInputGroups();
            }
          }, 250);
        });
      }

      console.log('MobileForms: Initialized successfully (refactored with CSS classes and stable selectors)');
    }
  };

  // Expose globally
  window.MobileForms = MobileForms;

  // Register with InitSystem if available
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('mobile-forms', function() {
      MobileForms.init();
    }, {
      priority: 60,
      description: 'Mobile form optimizations (input groups, swipe, quick actions)',
      reinitializable: true
    });
  } else {
    // Fallback: Auto-initialize
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => MobileForms.init());
    } else {
      MobileForms.init();
    }
  }

})(window);
