/**
 * ============================================================================
 * MODERN COMPONENTS CONTROLLER - ATHLETIC PRECISION
 * ============================================================================
 *
 * Unified JavaScript controller for all modern components
 * - Event delegation architecture
 * - Data-attribute based hooks
 * - No direct element binding
 * - Modular initialization
 * - Performance optimized
 *
 * Components handled:
 * - Modals
 * - Toasts
 * - Tooltips
 * - Dropdowns
 * - Tables (sorting, pagination)
 * - Forms (validation)
 *
 * ============================================================================
 */
// ES Module
'use strict';

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';

/**
 * ============================================================================
 * MODAL CONTROLLER
 * ROOT CAUSE FIX: Added initialization guard
 * ============================================================================
 */
export const ModalController = {
    activeModals: new Set(),
    _initialized: false,

    init() {
      // Only register listeners once
      if (this._initialized) return;
      this._initialized = true;

      // Helper to safely get element from event target
      const getElement = (target) => target instanceof Element ? target : null;

      // EventDelegation handlers are registered at module scope below

      // Close on backdrop click
      document.addEventListener('click', (e) => {
        const el = getElement(e.target);
        if (!el) return;
        if (el.classList.contains('c-modal-modern__backdrop')) {
          const openModal = Array.from(this.activeModals).pop();
          if (openModal) this.close(openModal);
        }
      });

      // Close on Escape key
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.activeModals.size > 0) {
          const topModal = Array.from(this.activeModals).pop();
          this.close(topModal);
        }
      });
    },

    open(modalId) {
      const modal = document.getElementById(modalId);
      const backdrop = document.querySelector(`[data-modal-backdrop="${modalId}"]`);

      if (!modal) return;

      // Add to active stack
      this.activeModals.add(modalId);

      // Show backdrop
      if (backdrop) {
        backdrop.classList.add('is-open');
      }

      // Show modal
      modal.classList.add('is-open');
      modal.setAttribute('aria-hidden', 'false');

      // Focus trap
      this.trapFocus(modal);

      // Emit custom event
      modal.dispatchEvent(new CustomEvent('modal:opened', { detail: { id: modalId } }));
    },

    close(modalId) {
      const modal = document.getElementById(modalId);
      const backdrop = document.querySelector(`[data-modal-backdrop="${modalId}"]`);

      if (!modal) return;

      // Add closing state for animation
      modal.classList.add('is-closing');

      setTimeout(() => {
        modal.classList.remove('is-open', 'is-closing');
        modal.setAttribute('aria-hidden', 'true');

        if (backdrop) {
          backdrop.classList.remove('is-open');
        }

        // Remove from active stack
        this.activeModals.delete(modalId);

        // Emit custom event
        modal.dispatchEvent(new CustomEvent('modal:closed', { detail: { id: modalId } }));
      }, 300);
    },

    trapFocus(modal) {
      const focusableElements = modal.querySelectorAll(
        'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
      );
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];

      const handleTabKey = (e) => {
        if (e.key !== 'Tab') return;

        if (e.shiftKey) {
          if (document.activeElement === firstElement) {
            lastElement.focus();
            e.preventDefault();
          }
        } else {
          if (document.activeElement === lastElement) {
            firstElement.focus();
            e.preventDefault();
          }
        }
      };

      modal.addEventListener('keydown', handleTabKey);
      firstElement?.focus();
    }
  };

/**
 * ============================================================================
 * TOAST CONTROLLER
 * ROOT CAUSE FIX: Added initialization guard
 * ============================================================================
 */
export const ToastController = {
    container: null,
    toasts: new Map(),
    idCounter: 0,
    _initialized: false,

    init() {
      // Only initialize once
      if (this._initialized) return;
      this._initialized = true;

      // Create toast container if doesn't exist
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.className = 'c-toast-modern__container';
        document.body.appendChild(this.container);
      }

      // EventDelegation handler is registered at module scope below
    },

    show(options = {}) {
      const {
        type = 'info',
        title,
        message,
        duration = 5000,
        dismissible = true,
        actions = []
      } = options;

      const toastId = `toast-${++this.idCounter}`;

      const toast = document.createElement('div');
      toast.className = `c-toast-modern c-toast-modern--${type}`;
      toast.id = toastId;
      toast.setAttribute('role', 'alert');
      toast.setAttribute('aria-live', 'polite');

      // Icon mapping
      const icons = {
        success: '✓',
        error: '×',
        warning: '⚠',
        info: 'ℹ'
      };

      toast.innerHTML = `
        <div class="c-toast-modern__icon">${icons[type] || icons.info}</div>
        <div class="c-toast-modern__content">
          ${title ? `<h4 class="c-toast-modern__title">${title}</h4>` : ''}
          ${message ? `<p class="c-toast-modern__message">${message}</p>` : ''}
          ${actions.length > 0 ? `
            <div class="c-toast-modern__actions">
              ${actions.map(action => `
                <button class="c-toast-modern__action" data-action="toast-action" data-callback="${action.callback}">
                  ${action.label}
                </button>
              `).join('')}
            </div>
          ` : ''}
        </div>
        ${dismissible ? `
          <button class="c-toast-modern__dismiss" data-action="dismiss-toast" data-toast-id="${toastId}" aria-label="Close">×</button>
        ` : ''}
        ${duration > 0 ? `
          <div class="c-toast-modern__progress">
            <div class="c-toast-modern__progress-bar" data-duration="${duration}"></div>
          </div>
        ` : ''}
      `;

      this.container.appendChild(toast);

      // Trigger animation
      requestAnimationFrame(() => {
        toast.classList.add('is-visible');
      });

      // Auto-dismiss
      if (duration > 0) {
        setTimeout(() => {
          this.dismiss(toastId);
        }, duration);
      }

      this.toasts.set(toastId, toast);
      return toastId;
    },

    dismiss(toastId) {
      const toast = this.toasts.get(toastId);
      if (!toast) return;

      toast.classList.add('is-dismissing');
      toast.classList.remove('is-visible');

      setTimeout(() => {
        toast.remove();
        this.toasts.delete(toastId);
      }, 300);
    }
  };

/**
 * ============================================================================
 * TOOLTIP CONTROLLER
 * ============================================================================
 */
export const TooltipController = {
    activeTooltip: null,
    tooltips: new Map(),
    _initialized: false,

    init() {
      // FIXED: Added guard to prevent duplicate event listener registration
      if (this._initialized) {
        return;
      }
      this._initialized = true;

      // Helper to safely get element from event target
      const getElement = (target) => target instanceof Element ? target : null;

      // Find all elements with data-tooltip
      document.addEventListener('mouseenter', (e) => {
        const el = getElement(e.target);
        if (!el) return;
        const trigger = el.closest('[data-tooltip]');
        if (trigger) {
          this.show(trigger);
        }
      }, true);

      document.addEventListener('mouseleave', (e) => {
        const el = getElement(e.target);
        if (!el) return;
        const trigger = el.closest('[data-tooltip]');
        if (trigger) {
          this.hide();
        }
      }, true);

      // Keyboard support
      document.addEventListener('focus', (e) => {
        const el = getElement(e.target);
        if (!el) return;
        const trigger = el.closest('[data-tooltip]');
        if (trigger) {
          this.show(trigger);
        }
      }, true);

      document.addEventListener('blur', (e) => {
        const el = getElement(e.target);
        if (!el) return;
        const trigger = el.closest('[data-tooltip]');
        if (trigger) {
          this.hide();
        }
      }, true);
    },

    show(trigger) {
      const content = trigger.dataset.tooltip;
      const position = trigger.dataset.tooltipPosition || 'top';
      const variant = trigger.dataset.tooltipVariant || '';

      if (!content) return;

      // Create tooltip
      const tooltip = document.createElement('div');
      tooltip.className = `c-tooltip-modern c-tooltip-modern--${position} ${variant ? `c-tooltip-modern--${variant}` : ''}`;
      tooltip.setAttribute('role', 'tooltip');
      tooltip.innerHTML = `
        ${content}
        <div class="c-tooltip-modern__arrow"></div>
      `;

      // Position tooltip
      trigger.appendChild(tooltip);

      // Show with animation
      requestAnimationFrame(() => {
        tooltip.classList.add('is-visible');
      });

      this.activeTooltip = tooltip;
    },

    hide() {
      if (this.activeTooltip) {
        this.activeTooltip.classList.remove('is-visible');
        setTimeout(() => {
          this.activeTooltip?.remove();
          this.activeTooltip = null;
        }, 200);
      }
    }
  };

/**
 * ============================================================================
 * DROPDOWN CONTROLLER
 * ============================================================================
 */
export const DropdownController = {
    activeDropdown: null,
    _initialized: false,

    init() {
      // FIXED: Added guard to prevent duplicate event listener registration
      if (this._initialized) {
        return;
      }
      this._initialized = true;

      // EventDelegation handler is registered at module scope below

      // Close if clicking outside
      document.addEventListener('click', (e) => {
        if (!e.target.closest('.c-dropdown-modern') && this.activeDropdown) {
          this.close(this.activeDropdown);
        }
      });

      // Keyboard navigation
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.activeDropdown) {
          this.close(this.activeDropdown);
        }
      });
    },

    toggle(dropdownId) {
      const dropdown = document.getElementById(dropdownId);
      if (!dropdown) return;

      if (dropdown.classList.contains('is-open')) {
        this.close(dropdownId);
      } else {
        // Close any open dropdown
        if (this.activeDropdown) {
          this.close(this.activeDropdown);
        }
        this.open(dropdownId);
      }
    },

    open(dropdownId) {
      const dropdown = document.getElementById(dropdownId);
      if (!dropdown) return;

      dropdown.classList.add('is-open');
      this.activeDropdown = dropdownId;

      // Emit event
      dropdown.dispatchEvent(new CustomEvent('dropdown:opened', { detail: { id: dropdownId } }));
    },

    close(dropdownId) {
      const dropdown = document.getElementById(dropdownId);
      if (!dropdown) return;

      dropdown.classList.remove('is-open');
      if (this.activeDropdown === dropdownId) {
        this.activeDropdown = null;
      }

      // Emit event
      dropdown.dispatchEvent(new CustomEvent('dropdown:closed', { detail: { id: dropdownId } }));
    }
  };

/**
 * ============================================================================
 * TABLE CONTROLLER
 * ROOT CAUSE FIX: Added initialization guard
 * ============================================================================
 */
export const TableController = {
    _initialized: false,

    init() {
      // Only register listeners once
      if (this._initialized) return;
      this._initialized = true;

      // Helper to safely get element from event target
      const getElement = (target) => target instanceof Element ? target : null;

      // Single delegated click listener for sorting and pagination
      document.addEventListener('click', (e) => {
        const el = getElement(e.target);
        if (!el) return;

        // Sortable columns
        const header = el.closest('.c-table-modern__header--sortable');
        if (header) {
          this.sort(header);
          return;
        }

        // Pagination
        const paginationBtn = el.closest('.c-table-modern__pagination-button');
        if (paginationBtn && !paginationBtn.disabled) {
          const page = parseInt(paginationBtn.dataset.page);
          const tableId = paginationBtn.closest('[data-table-id]')?.dataset.tableId;
          if (tableId) {
            this.paginate(tableId, page);
          }
        }
      });
    },

    sort(header) {
      const table = header.closest('.c-table-modern');
      const column = header.dataset.sortColumn;
      const currentDirection = header.dataset.sortDirection || 'none';

      // Determine new direction
      let newDirection = 'asc';
      if (currentDirection === 'asc') newDirection = 'desc';
      if (currentDirection === 'desc') newDirection = 'none';

      // Remove sorting from other headers
      table.querySelectorAll('.c-table-modern__header--sortable').forEach(h => {
        h.classList.remove('c-table-modern__header--sorted-asc', 'c-table-modern__header--sorted-desc');
        h.dataset.sortDirection = 'none';
      });

      // Apply new sorting
      if (newDirection !== 'none') {
        header.classList.add(`c-table-modern__header--sorted-${newDirection}`);
        header.dataset.sortDirection = newDirection;
      }

      // Emit event for external handling
      table.dispatchEvent(new CustomEvent('table:sort', {
        detail: { column, direction: newDirection }
      }));
    },

    paginate(tableId, page) {
      const table = document.querySelector(`[data-table-id="${tableId}"]`);
      if (!table) return;

      // Emit event for external handling
      table.dispatchEvent(new CustomEvent('table:paginate', {
        detail: { page }
      }));
    }
  };

/**
 * ============================================================================
 * FORM VALIDATION CONTROLLER
 * ROOT CAUSE FIX: Added initialization guard
 * ============================================================================
 */
export const FormController = {
    _initialized: false,

    init() {
      // Only register listeners once
      if (this._initialized) return;
      this._initialized = true;

      // Helper to safely get element from event target
      const getElement = (target) => target instanceof Element ? target : null;

      // Real-time validation via focusout delegation
      document.addEventListener('focusout', (e) => {
        const el = getElement(e.target);
        if (!el) return;
        const input = el.closest('.c-form-modern__input');
        if (input) {
          this.validateField(input);
        }
      }, true);

      // Form submission
      document.addEventListener('submit', (e) => {
        const el = getElement(e.target);
        if (!el) return;
        const form = el.closest('form[data-validate]');
        if (form) {
          if (!this.validateForm(form)) {
            e.preventDefault();
          }
        }
      });
    },

    validateField(input) {
      const isValid = input.checkValidity();

      if (isValid) {
        input.classList.remove('is-invalid');
        input.classList.add('is-valid');
        this.clearError(input);
      } else {
        input.classList.remove('is-valid');
        input.classList.add('is-invalid');
        this.showError(input, input.validationMessage);
      }

      return isValid;
    },

    validateForm(form) {
      const inputs = form.querySelectorAll('.c-form-modern__input');
      let isValid = true;

      inputs.forEach(input => {
        if (!this.validateField(input)) {
          isValid = false;
        }
      });

      return isValid;
    },

    showError(input, message) {
      let feedback = input.parentElement.querySelector('.c-form-modern__feedback--invalid');

      if (!feedback) {
        feedback = document.createElement('div');
        feedback.className = 'c-form-modern__feedback c-form-modern__feedback--invalid';
        input.parentElement.appendChild(feedback);
      }

      feedback.textContent = message;
    },

    clearError(input) {
      const feedback = input.parentElement.querySelector('.c-form-modern__feedback--invalid');
      if (feedback) {
        feedback.remove();
      }
    }
  };

/**
 * ============================================================================
 * INITIALIZATION
 * ============================================================================
 */
export function init() {
    // NOTE: ModalController is DISABLED to prevent conflicts with ModalManager
    // ModalManager (modal-manager.js) handles all Bootstrap modals (.modal class)
    // ModalController was designed for .c-modal-modern class which is not used in templates
    // Keeping the controller code for reference but not initializing it
    // ModalController.init();
    ToastController.init();
    TooltipController.init();
    DropdownController.init();
    TableController.init();
    FormController.init();

    console.log('Modern components initialized');
  }

  // Expose API for external use
  window.ModernComponents = {
    Modal: ModalController,
    Toast: ToastController,
    Tooltip: TooltipController,
    Dropdown: DropdownController,
    Table: TableController,
    Form: FormController
  };

  // Register with InitSystem if available
  if (true && InitSystem.register) {
    InitSystem.register('components-modern', init, {
      priority: 70,
      description: 'Modern UI components (toast, tooltip, dropdown, table, form)',
      reinitializable: true
    });
  } else {
    // Fallback: Initialize on DOM ready
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', init);
    } else {
      init();
    }
  }

  // ============================================================================
  // EVENT DELEGATION - Registered at module scope
  // ============================================================================
  // MUST use EventDelegation to avoid TDZ errors in bundled code.
  // Handlers registered when IIFE executes, delegating to controller instances

  // Toast dismiss action
  EventDelegation.register('dismiss-toast', (element, e) => {
    const toastId = element.dataset.toastId;
    if (toastId && window.ModernComponents?.Toast) {
      window.ModernComponents.Toast.dismiss(toastId);
    }
  }, { preventDefault: true });

  // Dropdown trigger action
  EventDelegation.register('dropdown-trigger', (element, e) => {
    const dropdownId = element.dataset.dropdownTrigger;
    if (dropdownId && window.ModernComponents?.Dropdown) {
      window.ModernComponents.Dropdown.toggle(dropdownId);
    }
  }, { preventDefault: true });

// Backward compatibility
window.ModalController = ModalController;

// Backward compatibility
window.ToastController = ToastController;

// Backward compatibility
window.TooltipController = TooltipController;

// Backward compatibility
window.DropdownController = DropdownController;

// Backward compatibility
window.TableController = TableController;

// Backward compatibility
window.FormController = FormController;

// Backward compatibility
window.init = init;
