'use strict';

/**
 * ECS Soccer League Design System Helper
 *
 * This script helps enforce consistent application of the design system
 * across all templates by:
 * 1. Converting Bootstrap classes to design system classes
 * 2. Adding responsive behaviors to components
 * 3. Providing helper functions for common UI patterns
 */

import { InitSystem } from './init-system.js';

// Main design system helper
export const ECSDesignSystem = {
  // Module-level initialization guard - prevents multiple init calls
  _initialized: false,

  // Initialize the design system
  init: function() {
    // Prevent multiple initialization - ROOT CAUSE FIX
    if (this._initialized) {
      console.log('[ECSDesignSystem] Already initialized, skipping');
      return;
    }
    this._initialized = true;

    // Add the design system stylesheet to the page
    this.ensureStylesheetLoaded();

    // Apply consistent styling to standard components
    this.enhanceButtons();
    this.enhanceCards();
    this.enhanceForms();
    this.enhanceModals();
    this.enhanceTables();
    this.enhanceNavs();

    // Set up responsive behaviors
    this.setupResponsive();

    // Set up dark mode
    this.setupDarkMode();

    // Add any custom behaviors
    this.setupCustomBehaviors();
  },

  // Ensure the ECS CSS architecture is loaded
  ensureStylesheetLoaded: function() {
    // DISABLED: These CSS files don't exist in the project
    // Commenting out to prevent 404 errors
    /*
    // Load core CSS if not already present
    if (!document.getElementById('ecs-core-stylesheet')) {
      const coreLink = document.createElement('link');
      coreLink.id = 'ecs-core-stylesheet';
      coreLink.rel = 'stylesheet';
      coreLink.href = '/static/css/ecs-core.css';
      document.head.appendChild(coreLink);
    }

    // Load components CSS if not already present
    if (!document.getElementById('ecs-components-stylesheet')) {
      const componentsLink = document.createElement('link');
      componentsLink.id = 'ecs-components-stylesheet';
      componentsLink.rel = 'stylesheet';
      componentsLink.href = '/static/css/ecs-components.css';
      document.head.appendChild(componentsLink);
    }

    // Load utilities CSS if not already present
    if (!document.getElementById('ecs-utilities-stylesheet')) {
      const utilitiesLink = document.createElement('link');
      utilitiesLink.id = 'ecs-utilities-stylesheet';
      utilitiesLink.rel = 'stylesheet';
      utilitiesLink.href = '/static/css/ecs-utilities.css';
      document.head.appendChild(utilitiesLink);
    }
    */
  },

  // Add consistent styling to buttons
  enhanceButtons: function() {
    // Map Bootstrap button classes to design system classes
    const btnClassMap = {
      'btn-primary': 'ecs-btn ecs-btn-primary',
      'btn-secondary': 'ecs-btn ecs-btn-secondary',
      'btn-success': 'ecs-btn ecs-btn-success',
      'btn-info': 'ecs-btn ecs-btn-info',
      'btn-warning': 'ecs-btn ecs-btn-warning',
      'btn-danger': 'ecs-btn ecs-btn-danger',
      'btn-dark': 'ecs-btn ecs-btn-dark',
      'btn-outline-primary': 'ecs-btn ecs-btn-outline-primary',
      'btn-outline-secondary': 'ecs-btn ecs-btn-outline-secondary',
      'btn-sm': 'ecs-btn-sm',
      'btn-lg': 'ecs-btn-lg'
    };

    // Selectors to exclude from button enhancement (BEM components with their own styling)
    const excludeSelectors = [
      '.c-admin-nav',         // Admin navigation component
      '.c-mobile-nav',        // Mobile navigation component
      '.c-modal',             // BEM modal components
      '.c-btn-modern',        // BEM button components
      '.c-form-modern',       // BEM form components
      '.c-settings-tabs',     // Settings tabs component
      '.c-messages-inbox',    // Messages inbox component
      '.c-tabs',              // BEM tabs component
      '.c-schedule',          // Team schedule accordion
      '.c-schedule-controls', // Schedule expand/collapse controls
      '[data-no-enhance]'     // Explicit opt-out attribute
    ];
    const excludeSelector = excludeSelectors.join(', ');

    // Apply design system classes to buttons
    document.querySelectorAll('button, [type="button"], [type="submit"], [role="button"]').forEach(button => {
      // Skip buttons inside excluded components
      if (button.closest(excludeSelector)) {
        return;
      }

      // Skip BEM component buttons that have their own styling
      if (button.classList.contains('c-tabs__item') ||
          button.classList.contains('c-btn') ||
          button.classList.contains('c-nav__item') ||
          button.classList.contains('c-schedule-controls__btn')) {
        return;
      }

      if (!button.classList.contains('ecs-btn')) {
        button.classList.add('ecs-btn');

        // Add appropriate design system classes
        for (const [bootstrapClass, ecsClass] of Object.entries(btnClassMap)) {
          if (button.classList.contains(bootstrapClass)) {
            // Add our classes
            ecsClass.split(' ').forEach(cls => {
              if (!button.classList.contains(cls)) {
                button.classList.add(cls);
              }
            });
          }
        }

        // Add icon wrapper if button has an icon
        if (button.querySelector('[data-icon], [class*="icon-"], [class*="ti-"], [class*="feather-"]')) {
          button.classList.add('ecs-btn-icon');
        }
      }
    });
  },

  // Add consistent styling to cards
  enhanceCards: function() {
    // Map Bootstrap card classes to design system classes
    const cardClassMap = {
      'card': 'ecs-card',
      'card-header': 'ecs-card-header',
      'card-body': 'ecs-card-body',
      'card-footer': 'ecs-card-footer',
      'card-title': 'ecs-card-title',
      'card-subtitle': 'ecs-card-subtitle'
    };

    // Header color mappings
    const headerColorMap = {
      'bg-primary': 'ecs-card-header-primary',
      'bg-secondary': 'ecs-card-header-secondary',
      'bg-success': 'ecs-card-header-success',
      'bg-info': 'ecs-card-header-info',
      'bg-warning': 'ecs-card-header-warning',
      'bg-danger': 'ecs-card-header-danger',
      'bg-dark': 'ecs-card-header-dark'
    };

    // Apply design system classes to cards
    document.querySelectorAll('[data-component="card"], [data-role*="card"]').forEach(card => {
      if (!card.classList.contains('ecs-card')) {
        card.classList.add('ecs-card');

        // Process card components
        Object.entries(cardClassMap).forEach(([bootstrapClass, ecsClass]) => {
          card.querySelectorAll(`[data-card-part="${bootstrapClass.replace('card-', '')}"]`).forEach(element => {
            if (!element.classList.contains(ecsClass)) {
              element.classList.add(ecsClass);
            }
          });
        });

        // Process card header colors
        const cardHeader = card.querySelector('[data-card-part="header"]');
        if (cardHeader) {
          Object.entries(headerColorMap).forEach(([bootstrapClass, ecsClass]) => {
            if (cardHeader.classList.contains(bootstrapClass) && !cardHeader.classList.contains(ecsClass)) {
              cardHeader.classList.add(ecsClass);
            }
          });
        }
      }
    });
  },

  // Add consistent styling to forms
  enhanceForms: function() {
    // Map Bootstrap form classes to design system classes
    const formClassMap = {
      'form-control': 'ecs-form-control',
      'form-select': 'ecs-form-select',
      'form-check': 'ecs-form-check',
      'form-check-input': 'ecs-form-check-input',
      'form-label': 'ecs-form-label',
      'form-text': 'ecs-form-text',
      'form-floating': 'ecs-form-floating'
    };

    // Apply design system classes to form elements
    Object.entries(formClassMap).forEach(([bootstrapClass, ecsClass]) => {
      document.querySelectorAll(`[data-form-element], [data-input-type]`).forEach(element => {
        if (!element.classList.contains(ecsClass)) {
          element.classList.add(ecsClass);
        }
      });
    });

    // Handle validation states
    document.querySelectorAll('[data-validation-state="valid"], [data-validation-state="invalid"]').forEach(field => {
      if (field.getAttribute('data-validation-state') === 'valid') {
        field.classList.add('ecs-is-valid');
      } else if (field.getAttribute('data-validation-state') === 'invalid') {
        field.classList.add('ecs-is-invalid');
      }
    });
  },

  // Add consistent styling to modals
  enhanceModals: function() {
    // Skip BEM modals - they have their own styling
    const bemModalSelector = '.c-modal';

    // Map Bootstrap modal classes to design system classes
    const modalClassMap = {
      'modal': 'ecs-modal',
      'modal-dialog': 'ecs-modal-dialog',
      'modal-content': 'ecs-modal-content',
      'modal-header': 'ecs-modal-header',
      'modal-body': 'ecs-modal-body',
      'modal-footer': 'ecs-modal-footer',
      'modal-title': 'ecs-modal-title',
      'btn-close': 'ecs-modal-close',
      'modal-dialog-centered': 'ecs-modal-dialog-centered',
      'modal-dialog-scrollable': 'ecs-modal-dialog-scrollable',
      'modal-sm': 'ecs-modal-sm',
      'modal-lg': 'ecs-modal-lg',
      'modal-xl': 'ecs-modal-xl'
    };

    // Apply design system classes to modals (skip BEM modals)
    Object.entries(modalClassMap).forEach(([bootstrapClass, ecsClass]) => {
      document.querySelectorAll(`[data-component="${bootstrapClass}"], [data-modal-part]`).forEach(element => {
        // Skip if this is a BEM modal
        if (element.closest(bemModalSelector)) return;
        if (!element.classList.contains(ecsClass)) {
          element.classList.add(ecsClass);
        }
      });
    });

    // Apply consistent behavior to all modals (skip BEM modals)
    // FIXED: Added guard to prevent duplicate event listener registration
    document.querySelectorAll('[data-component="modal"], [role="dialog"]').forEach(modal => {
      // Skip BEM modals - they use their own system
      if (modal.classList.contains('c-modal')) return;

      // Skip if already enhanced to prevent duplicate event listeners
      if (modal.hasAttribute('data-ecs-modal-enhanced')) return;
      modal.setAttribute('data-ecs-modal-enhanced', 'true');

      // Handle modal opening - apply design system styles
      modal.addEventListener('show.bs.modal', function() {
        // Enhance any form elements inside the modal
        this.querySelectorAll('[data-form-element], [data-input-type]').forEach(input => {
          if (input.classList.contains('form-control')) {
            input.classList.add('ecs-form-control');
          } else if (input.classList.contains('form-select')) {
            input.classList.add('ecs-form-select');
          }
        });

        // Enhance buttons inside the modal
        this.querySelectorAll('button, [type="button"], [type="submit"], [role="button"]').forEach(button => {
          if (!button.classList.contains('ecs-btn')) {
            button.classList.add('ecs-btn');
          }
        });
      });
    });
  },

  // Add consistent styling to tables
  enhanceTables: function() {
    // Map Bootstrap table classes to design system classes
    const tableClassMap = {
      'table': 'ecs-table',
      'table-hover': 'ecs-table-hover',
      'table-striped': 'ecs-table-striped',
      'table-sm': 'ecs-table-sm'
    };

    // Apply design system classes to tables
    Object.entries(tableClassMap).forEach(([bootstrapClass, ecsClass]) => {
      document.querySelectorAll('[data-component="table"], [role="table"]').forEach(element => {
        if (!element.classList.contains(ecsClass)) {
          element.classList.add(ecsClass);
        }
      });
    });
  },

  // Add consistent styling to navs and tabs
  enhanceNavs: function() {
    // Map Bootstrap nav classes to design system classes
    const navClassMap = {
      'nav': 'ecs-nav',
      'nav-link': 'ecs-nav-link',
      'nav-tabs': 'ecs-nav-tabs',
      'nav-pills': 'ecs-nav-pills',
      'active': 'ecs-active'
    };

    // Apply design system classes to navs
    Object.entries(navClassMap).forEach(([bootstrapClass, ecsClass]) => {
      document.querySelectorAll('[data-component="nav"], [role="navigation"] > [role="tablist"]').forEach(element => {
        if (!element.classList.contains(ecsClass)) {
          element.classList.add(ecsClass);
        }
      });
    });

    // Ensure tab content has proper design system styling
    document.querySelectorAll('[data-component="tab-content"], [role="tabpanel"]').forEach(element => {
      if (element.hasAttribute('data-component')) {
        element.classList.add('ecs-tab-content');
      } else if (element.hasAttribute('role')) {
        element.classList.add('ecs-tab-pane');
      }
    });
  },

  // Set up responsive behaviors
  setupResponsive: function() {
    // Adjust elements based on screen size
    const adjustForScreenSize = () => {
      const isMobile = window.innerWidth < 768;

      // Adjust buttons on mobile
      if (isMobile) {
        document.querySelectorAll('button, [type="button"], [type="submit"], [role="button"]').forEach(button => {
          // Make sure mobile buttons have adequate touch targets
          if (!button.classList.contains('btn-sm') && !button.classList.contains('ecs-btn-sm')) {
            button.classList.add('touch-target');
          }
        });

        // Make sure form controls have adequate size on mobile
        // Exclude checkboxes and radio buttons (they don't trigger iOS zoom)
        document.querySelectorAll('[data-form-element]:not([type="checkbox"]):not([type="radio"]), [data-input-type]:not([type="checkbox"]):not([type="radio"])').forEach(input => {
          if (!input.classList.contains('ios-input')) {
            input.classList.add('ios-input');
          }
        });
      }
    };

    // Adjust on page load and resize
    adjustForScreenSize();
    window.addEventListener('resize', adjustForScreenSize);
  },

  // Set up dark mode
  setupDarkMode: function() {
    // Watch for changes to BOTH data-style and data-bs-theme attributes on the html element
    const htmlElement = document.documentElement;

    // Create an observer to monitor changes to theme attributes
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.type === 'attributes' &&
            (mutation.attributeName === 'data-style' || mutation.attributeName === 'data-bs-theme')) {
          const isDarkStyle = htmlElement.getAttribute('data-style') === 'dark';
          const isDarkBsTheme = htmlElement.getAttribute('data-bs-theme') === 'dark';
          const isDark = isDarkStyle || isDarkBsTheme;
          this.applyDarkModeToContent(isDark);
        }
      });
    });

    // Start observing the html element for changes to theme attributes
    observer.observe(htmlElement, { attributes: true });

    // Initial application based on current state
    const isDarkStyle = htmlElement.getAttribute('data-style') === 'dark';
    const isDarkBsTheme = htmlElement.getAttribute('data-bs-theme') === 'dark';
    const isDark = isDarkStyle || isDarkBsTheme;
    this.applyDarkModeToContent(isDark);

    // Add dark mode toggle functionality if it doesn't exist
    if (!document.querySelector('.dark-mode-toggle')) {
      this.addDarkModeToggle();
    }
  },

  // Apply dark mode to content areas
  // UPDATED: Minimal intervention - let Bootstrap CSS variables handle dark mode
  // Templates now use var(--bs-*) variables which automatically adapt
  applyDarkModeToContent: function(isDark) {
    // Only add/remove marker class for CSS targeting - no inline styles
    // This allows CSS-based dark mode to work without JavaScript conflicts
    if (isDark) {
      document.body.classList.add('dark-mode-body');
    } else {
      document.body.classList.remove('dark-mode-body');

      // Clean up any legacy dark-mode-applied classes from previous state
      document.querySelectorAll('.dark-mode-applied').forEach(element => {
        element.classList.remove('dark-mode-applied');
      });
    }
  },

  // Add dark mode toggle if it doesn't exist
  addDarkModeToggle: function() {
    // DISABLED: Don't add the toggle at all since there's already one in the navbar.html
    return;
  },

  // Set up custom behaviors for the design system
  setupCustomBehaviors: function() {
    // Add ripple effect to buttons for better feedback
    this.addRippleEffect();

    // Improve keyboard navigation
    this.improveKeyboardNavigation();

    // Add support for custom transitions
    this.setupTransitions();
  },

  // Add ripple effect to buttons using EVENT DELEGATION - ROOT CAUSE FIX
  // Uses ONE document-level listener instead of per-button listeners
  // This automatically works for dynamically added buttons
  _rippleListenerAttached: false,
  addRippleEffect: function() {
    // Only attach the delegated listener once
    if (this._rippleListenerAttached) return;
    this._rippleListenerAttached = true;

    // Single delegated click handler for ALL buttons
    document.addEventListener('click', function(e) {
      // Find the button that was clicked (could be the target or an ancestor)
      const button = e.target.closest('button, [type="button"], [type="submit"], [role="button"]');
      if (!button) return;

      // Skip modal buttons and other exclusions
      if (button.getAttribute('data-bs-toggle') === 'modal' ||
          button.classList.contains('edit-match-btn') ||
          button.closest('[data-bs-toggle="modal"]') ||
          button.hasAttribute('data-no-ripple')) {
        return;
      }

      // Create and position the ripple
      const ripple = document.createElement('span');
      ripple.classList.add('waves-ripple');

      const rect = button.getBoundingClientRect();
      const size = Math.max(rect.width, rect.height);

      // Set custom properties for ripple positioning
      ripple.style.setProperty('--ripple-size', `${size}px`);
      ripple.style.setProperty('--ripple-left', `${e.clientX - rect.left - size / 2}px`);
      ripple.style.setProperty('--ripple-top', `${e.clientY - rect.top - size / 2}px`);

      // Add transform-none class to prevent button scaling
      ripple.classList.add('transform-none');

      button.appendChild(ripple);

      // Trigger animation by adding active class
      setTimeout(() => {
        ripple.classList.add('waves-ripple-active');
      }, 10);

      // Remove ripple after animation
      setTimeout(() => {
        if (ripple.parentNode) {
          ripple.parentNode.removeChild(ripple);
        }
      }, 600);
    }, false);
  },

  // Improve keyboard navigation using EVENT DELEGATION - ROOT CAUSE FIX
  // Uses document-level listeners instead of per-element listeners
  _keyboardNavListenerAttached: false,
  improveKeyboardNavigation: function() {
    // Only attach delegated listeners once
    if (this._keyboardNavListenerAttached) return;
    this._keyboardNavListenerAttached = true;

    // Single delegated focus handler
    document.addEventListener('focusin', function(e) {
      const element = e.target.closest('a, button, input, select, textarea, [tabindex]');
      if (element) {
        element.classList.add('ecs-focus');
      }
    }, true);

    // Single delegated blur handler
    document.addEventListener('focusout', function(e) {
      const element = e.target.closest('a, button, input, select, textarea, [tabindex]');
      if (element) {
        element.classList.remove('ecs-focus');
      }
    }, true);
  },

  // Set up custom transitions
  // FIXED: Added guard to prevent duplicate transition setup
  setupTransitions: function() {
    // Add slide-in animation for elements with data-ecs-animate="slide-in"
    document.querySelectorAll('[data-ecs-animate="slide-in"]').forEach(element => {
      // Skip if already processed
      if (element.hasAttribute('data-transition-enhanced')) return;
      element.setAttribute('data-transition-enhanced', 'true');

      // Add initial state classes (opacity 0, translate down 20px)
      element.classList.add('opacity-0', 'translate-y-20px', 'transition-smooth');

      // Trigger animation after a short delay
      setTimeout(() => {
        // Add final state classes (opacity 1, translate to normal position)
        element.classList.remove('opacity-0', 'translate-y-20px');
        element.classList.add('opacity-100', 'translate-y-0');
      }, 100);
    });
  }
};

// Register with InitSystem
InitSystem.register('design-system', function() {
  ECSDesignSystem.init();
}, {
  priority: 90,
  description: 'ECS Design System (theme, colors, focus states)',
  reinitializable: false
});

// Fallback
// InitSystem handles initialization

// Backward compatibility
window.ECSDesignSystem = ECSDesignSystem;
