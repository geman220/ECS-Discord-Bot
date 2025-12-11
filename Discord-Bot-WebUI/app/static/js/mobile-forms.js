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
      document.querySelectorAll('.modal').forEach(modal => {
        if (this.isMobile()) {
          // Convert large modals to full-screen on mobile
          const modalDialog = modal.querySelector('.modal-dialog');
          if (modalDialog) {
            // If modal-lg, make it responsive
            if (modalDialog.classList.contains('modal-lg')) {
              modalDialog.classList.add('mobile-optimized-modal');
            }

            // Adjust modal content max-height
            const modalContent = modal.querySelector('.modal-content');
            if (modalContent) {
              modalContent.style.maxHeight = 'calc(100vh - 32px)';
              modalContent.style.overflowY = 'auto';
            }
          }
        }
      });
    },

    /**
     * Optimize input groups for touch (match reporting events)
     */
    optimizeInputGroups: function () {
      document.querySelectorAll('.input-group').forEach(group => {
        if (this.isMobile()) {
          // Make select dropdowns full-width on mobile
          const selects = group.querySelectorAll('select');
          selects.forEach(select => {
            select.style.minWidth = '0';
            select.style.width = 'auto';
            select.style.flex = '1';
          });

          // Make minute inputs larger on mobile
          const inputs = group.querySelectorAll('input[type="number"], input[placeholder*="Min"]');
          inputs.forEach(input => {
            input.style.maxWidth = 'none';
            input.style.width = '80px';
            input.style.minWidth = '80px';
            input.style.fontSize = '16px'; // Prevent iOS zoom
          });

          // Make remove buttons larger for touch
          const removeButtons = group.querySelectorAll('.btn-close, button[onclick*="remove"]');
          removeButtons.forEach(btn => {
            btn.style.minWidth = '44px';
            btn.style.minHeight = '44px';
            btn.style.fontSize = '20px';
          });
        }
      });
    },

    /**
     * Add swipe-to-delete for input groups
     */
    setupSwipeToDelete: function () {
      if (!window.Hammer || !this.isMobile()) return;

      document.querySelectorAll('.input-group[id*="event-"], .event-entry').forEach(entry => {
        const hammer = new Hammer(entry);
        hammer.get('swipe').set({ direction: Hammer.DIRECTION_LEFT, threshold: 50 });

        let deleteIndicator = entry.querySelector('.swipe-delete-indicator');
        if (!deleteIndicator) {
          deleteIndicator = document.createElement('div');
          deleteIndicator.className = 'swipe-delete-indicator';
          deleteIndicator.innerHTML = '<i class="ti ti-trash"></i> Swipe to delete';
          deleteIndicator.style.cssText = `
            position: absolute;
            right: 0;
            top: 0;
            bottom: 0;
            background: var(--bs-danger);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 0 20px;
            transform: translateX(100%);
            transition: transform 0.3s ease;
            z-index: 1;
            gap: 8px;
          `;
          entry.style.position = 'relative';
          entry.style.overflow = 'hidden';
          entry.appendChild(deleteIndicator);
        }

        hammer.on('swipeleft', () => {
          // Show delete indicator
          deleteIndicator.style.transform = 'translateX(0)';
          entry.style.transform = 'translateX(-100px)';

          if (window.Haptics) window.Haptics.warning();

          // Auto-hide after 3 seconds or on tap
          const hideTimeout = setTimeout(() => {
            deleteIndicator.style.transform = 'translateX(100%)';
            entry.style.transform = 'translateX(0)';
          }, 3000);

          // Tap to confirm delete
          deleteIndicator.onclick = () => {
            clearTimeout(hideTimeout);

            if (window.Haptics) window.Haptics.delete();

            // Find and click the remove button
            const removeBtn = entry.querySelector('.btn-close, button[onclick*="remove"]');
            if (removeBtn) {
              removeBtn.click();
            }
          };
        });

        hammer.on('swiperight', () => {
          // Hide delete indicator
          deleteIndicator.style.transform = 'translateX(100%)';
          entry.style.transform = 'translateX(0)';
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
      document.querySelectorAll('.modal-body .row, .form-section').forEach(section => {
        const inputGroups = section.querySelectorAll('.input-group');

        if (inputGroups.length > 3) {
          // Create collapsible header
          const header = document.createElement('button');
          header.type = 'button';
          header.className = 'btn btn-link w-100 text-start mobile-collapse-toggle';
          header.innerHTML = `
            <span class="fw-bold">${section.dataset.sectionTitle || 'Show/Hide Section'}</span>
            <i class="ti ti-chevron-down float-end"></i>
          `;
          header.style.cssText = `
            padding: 12px;
            margin-bottom: 8px;
            border: 1px solid var(--bs-border-color);
            border-radius: 8px;
          `;

          const content = document.createElement('div');
          content.className = 'mobile-collapse-content';
          content.style.maxHeight = '1000px';
          content.style.overflow = 'hidden';
          content.style.transition = 'max-height 0.3s ease';

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
              content.style.maxHeight = '0';
              icon.classList.remove('ti-chevron-down');
              icon.classList.add('ti-chevron-right');
            } else {
              content.style.maxHeight = '1000px';
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
        jQuery('.dataTable, table.table').each(function () {
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
     */
    optimizeTextareas: function () {
      document.querySelectorAll('textarea').forEach(textarea => {
        if (this.isMobile()) {
          // Increase minimum height
          textarea.style.minHeight = '120px';

          // Auto-expand on focus
          textarea.addEventListener('focus', () => {
            textarea.style.minHeight = '200px';
          });

          // Character count if needed
          const maxLength = textarea.getAttribute('maxlength');
          if (maxLength) {
            let counter = textarea.parentElement.querySelector('.char-counter');
            if (!counter) {
              counter = document.createElement('div');
              counter.className = 'char-counter text-muted small';
              counter.style.cssText = 'text-align: right; margin-top: 4px;';
              textarea.parentElement.appendChild(counter);
            }

            const updateCounter = () => {
              const remaining = maxLength - textarea.value.length;
              counter.textContent = `${remaining} characters remaining`;
              counter.style.color = remaining < 20 ? 'var(--bs-danger)' : '';
            };

            textarea.addEventListener('input', updateCounter);
            updateCounter();
          }
        }
      });
    },

    /**
     * Add floating labels for better mobile UX
     */
    convertToFloatingLabels: function () {
      if (!this.isMobile()) return;

      document.querySelectorAll('.form-group:not(.form-floating)').forEach(group => {
        const label = group.querySelector('label');
        const input = group.querySelector('input, select, textarea');

        if (label && input && !input.closest('.input-group')) {
          // Convert to floating label
          group.classList.add('form-floating');
          group.appendChild(label); // Move label after input
        }
      });
    },

    /**
     * Setup form validation with mobile feedback
     */
    setupMobileValidation: function () {
      document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', (e) => {
          const invalidFields = form.querySelectorAll(':invalid');

          if (invalidFields.length > 0) {
            e.preventDefault();

            // Show first error
            const firstInvalid = invalidFields[0];
            firstInvalid.scrollIntoView({ behavior: 'smooth', block: 'center' });
            firstInvalid.focus();

            // Visual feedback
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
        });

        // Real-time validation feedback
        form.querySelectorAll('input, select, textarea').forEach(field => {
          field.addEventListener('blur', () => {
            if (field.validity.valid) {
              field.classList.remove('is-invalid');
              field.classList.add('is-valid');
            } else if (field.value) {
              field.classList.remove('is-valid');
              field.classList.add('is-invalid');
              if (window.Haptics) window.Haptics.light();
            }
          });
        });
      });
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

          .mobile-optimized-modal .modal-content {
            border-radius: 16px 16px 0 0;
          }

          /* Input group stacking */
          .input-group {
            flex-wrap: wrap;
            gap: 8px;
          }

          .input-group > * {
            flex: 1 1 auto;
            min-width: 0;
          }

          .input-group .btn-close,
          .input-group button[onclick*="remove"] {
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
          .modal-body .row.g-2 {
            row-gap: 16px !important;
          }

          .modal-body .col-md-6,
          .modal-body .col-lg-6 {
            width: 100%;
          }

          /* Sticky submit button spacing */
          .modal-footer {
            padding-bottom: 0 !important;
          }

          /* Larger touch targets in modals */
          .modal .btn {
            min-height: 48px;
            font-size: 16px;
            padding: 12px 24px;
          }

          .modal .form-control,
          .modal .form-select {
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
        .input-group,
        .event-entry {
          transition: transform 0.3s ease;
        }
      `;
      document.head.appendChild(style);
    },

    /**
     * Initialize all mobile form enhancements
     */
    init: function () {
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

      // Re-run on modal shown
      document.addEventListener('shown.bs.modal', () => {
        setTimeout(() => {
          this.optimizeInputGroups();
          this.setupSwipeToDelete();
          this.addQuickActions();
        }, 100);
      });

      // Re-run on window resize
      let resizeTimeout;
      window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
          if (this.isMobile()) {
            this.optimizeInputGroups();
          }
        }, 250);
      });

      console.log('MobileForms: Initialized successfully');
    }
  };

  // Auto-initialize
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => MobileForms.init());
  } else {
    MobileForms.init();
  }

  // Expose globally
  window.MobileForms = MobileForms;

})(window);
