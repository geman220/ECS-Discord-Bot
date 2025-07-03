/**
 * ECS Soccer League Design System Helper
 * 
 * This script helps enforce consistent application of the design system
 * across all templates by:
 * 1. Converting Bootstrap classes to design system classes
 * 2. Adding responsive behaviors to components
 * 3. Providing helper functions for common UI patterns
 */

(function() {
  'use strict';
  
  // Main design system helper
  const ECSDesignSystem = {
    // Initialize the design system
    init: function() {
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
      
      // Apply design system classes to buttons
      document.querySelectorAll('.btn').forEach(button => {
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
          if (button.querySelector('i, .feather, .ti, svg')) {
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
      document.querySelectorAll('.card').forEach(card => {
        if (!card.classList.contains('ecs-card')) {
          card.classList.add('ecs-card');
          
          // Process card components
          Object.entries(cardClassMap).forEach(([bootstrapClass, ecsClass]) => {
            card.querySelectorAll(`.${bootstrapClass}`).forEach(element => {
              if (!element.classList.contains(ecsClass)) {
                element.classList.add(ecsClass);
              }
            });
          });
          
          // Process card header colors
          const cardHeader = card.querySelector('.card-header, .ecs-card-header');
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
        document.querySelectorAll(`.${bootstrapClass}`).forEach(element => {
          if (!element.classList.contains(ecsClass)) {
            element.classList.add(ecsClass);
          }
        });
      });
      
      // Handle validation states
      document.querySelectorAll('.is-valid, .is-invalid').forEach(field => {
        if (field.classList.contains('is-valid')) {
          field.classList.add('ecs-is-valid');
        } else if (field.classList.contains('is-invalid')) {
          field.classList.add('ecs-is-invalid');
        }
      });
    },
    
    // Add consistent styling to modals
    enhanceModals: function() {
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
      
      // Apply design system classes to modals
      Object.entries(modalClassMap).forEach(([bootstrapClass, ecsClass]) => {
        document.querySelectorAll(`.${bootstrapClass}`).forEach(element => {
          if (!element.classList.contains(ecsClass)) {
            element.classList.add(ecsClass);
          }
        });
      });
      
      // Apply consistent behavior to all modals
      document.querySelectorAll('.modal, .ecs-modal').forEach(modal => {
        const modalId = modal.id;
        
        // Handle modal opening - apply design system styles
        modal.addEventListener('show.bs.modal', function() {
          // Enhance any form elements inside the modal
          this.querySelectorAll('input, select, textarea').forEach(input => {
            if (input.classList.contains('form-control')) {
              input.classList.add('ecs-form-control');
            } else if (input.classList.contains('form-select')) {
              input.classList.add('ecs-form-select');
            }
          });
          
          // Enhance buttons inside the modal
          this.querySelectorAll('.btn').forEach(button => {
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
        document.querySelectorAll(`.${bootstrapClass}`).forEach(element => {
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
        document.querySelectorAll(`.${bootstrapClass}`).forEach(element => {
          if (!element.classList.contains(ecsClass)) {
            element.classList.add(ecsClass);
          }
        });
      });
      
      // Ensure tab content has proper design system styling
      document.querySelectorAll('.tab-content, .tab-pane').forEach(element => {
        if (element.classList.contains('tab-content')) {
          element.classList.add('ecs-tab-content');
        } else if (element.classList.contains('tab-pane')) {
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
          document.querySelectorAll('.ecs-btn, .btn').forEach(button => {
            // Make sure mobile buttons have adequate touch targets
            if (!button.classList.contains('btn-sm') && !button.classList.contains('ecs-btn-sm')) {
              button.style.minHeight = '44px';
            }
          });
          
          // Make sure form controls have adequate size on mobile
          document.querySelectorAll('input, select, textarea').forEach(input => {
            if (!input.style.fontSize || input.style.fontSize < '16px') {
              input.style.fontSize = '16px';
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
      // Watch for changes to the data-style attribute on the html element
      const htmlElement = document.documentElement;
      
      // Create an observer to monitor changes to the data-style attribute
      const observer = new MutationObserver((mutations) => {
        mutations.forEach((mutation) => {
          if (mutation.type === 'attributes' && mutation.attributeName === 'data-style') {
            const isDark = htmlElement.getAttribute('data-style') === 'dark';
            this.applyDarkModeToContent(isDark);
          }
        });
      });
      
      // Start observing the html element for changes to the data-style attribute
      observer.observe(htmlElement, { attributes: true });
      
      // Initial application based on current state
      const isDark = htmlElement.getAttribute('data-style') === 'dark';
      this.applyDarkModeToContent(isDark);
      
      // Add dark mode toggle functionality if it doesn't exist
      if (!document.querySelector('.dark-mode-toggle')) {
        this.addDarkModeToggle();
      }
    },
    
    // Apply dark mode to content areas
    applyDarkModeToContent: function(isDark) {
      // Target the main content areas that may not be automatically styled
      const contentAreas = [
        '.container-xxl',
        '.container-fluid',
        '.content-wrapper',
        '.card',
        '.modal-content',
        '.layout-page', // Add layout page container
        '.container-p-y', // Add main content container
        '.container-fluid'
      ];
      
      contentAreas.forEach(selector => {
        const elements = document.querySelectorAll(selector);
        elements.forEach(element => {
          // Add a marker class to track dark mode application
          if (isDark) {
            element.classList.add('dark-mode-applied');
            
            // Apply dark mode styles directly
            element.style.backgroundColor = element.classList.contains('card') ? 
              'var(--ecs-neutral-100)' : 
              (selector === '.content-wrapper' || selector === '.layout-page' || selector === '.container-fluid' || selector === '.container-p-y') ? 
                'var(--ecs-background)' : '';
            
            element.style.color = 'var(--ecs-neutral-30)';
            
            // Add border color adjustments for dark mode
            if (element.style.borderColor) {
              element.style.borderColor = 'var(--ecs-neutral-70)';
            }
          } else {
            element.classList.remove('dark-mode-applied');
            
            // Reset styles when switching back to light mode
            element.style.backgroundColor = '';
            element.style.color = '';
            element.style.borderColor = '';
          }
        });
      });
      
      // Apply dark mode to the body element to ensure full coverage
      if (isDark) {
        document.body.classList.add('dark-mode-body');
        document.body.style.backgroundColor = 'var(--ecs-background)';
        document.body.style.color = 'var(--ecs-neutral-30)';
        
        // Fix card backgrounds
        document.querySelectorAll('.card:not(.bg-primary):not(.bg-secondary):not(.bg-success):not(.bg-info):not(.bg-warning):not(.bg-danger)').forEach(card => {
          card.style.backgroundColor = 'var(--ecs-neutral-100)';
          card.style.color = 'var(--ecs-neutral-10)';
        });
        
        // Target the specific content container
        const mainContent = document.querySelector('.container-fluid.flex-grow-1.container-p-y');
        if (mainContent) {
          mainContent.style.backgroundColor = 'var(--ecs-background)';
          mainContent.style.color = 'var(--ecs-neutral-30)';
        }
        
        // Fix text colors for better contrast
        document.querySelectorAll('.text-body, p, h1, h2, h3, h4, h5, h6, .navbar-text, .nav-link, tbody, td, th, tr').forEach(element => {
          if (!element.classList.contains('text-white') && 
              !element.classList.contains('text-primary') && 
              !element.classList.contains('text-success') && 
              !element.classList.contains('text-info') && 
              !element.classList.contains('text-warning') && 
              !element.classList.contains('text-danger')) {
            element.style.color = 'var(--ecs-neutral-30)';
          }
        });
        
        // Fix table styling in dark mode
        document.querySelectorAll('table.table').forEach(table => {
          table.style.color = 'var(--ecs-neutral-30)';
          table.querySelectorAll('th, td').forEach(cell => {
            cell.style.borderColor = 'var(--ecs-neutral-70)';
          });
        });
        
      } else {
        document.body.classList.remove('dark-mode-body');
        document.body.style.backgroundColor = '';
        document.body.style.color = '';
        
        // Reset card backgrounds
        document.querySelectorAll('.card').forEach(card => {
          if (card.style.backgroundColor === 'var(--ecs-neutral-100)') {
            card.style.backgroundColor = '';
          }
          if (card.style.color === 'var(--ecs-neutral-10)') {
            card.style.color = '';
          }
        });
        
        // Reset the main content container
        const mainContent = document.querySelector('.container-fluid.flex-grow-1.container-p-y');
        if (mainContent) {
          mainContent.style.backgroundColor = '';
          mainContent.style.color = '';
        }
        
        // Reset text colors
        document.querySelectorAll('[style*="color: var(--ecs-neutral-30)"]').forEach(element => {
          element.style.color = '';
        });
        
        // Reset table styling
        document.querySelectorAll('table.table').forEach(table => {
          table.style.color = '';
          table.querySelectorAll('th, td').forEach(cell => {
            cell.style.borderColor = '';
          });
        });
      }
    },
    
    // Add dark mode toggle if it doesn't exist
    addDarkModeToggle: function() {
      // DISABLED: Don't add the toggle at all since there's already one in the navbar.html
      return;
      
      /* 
      // The following code is kept for reference only but is completely commented out
      // to prevent JavaScript syntax errors
      
      const existingToggle = document.querySelector('.style-switcher-toggle');
      if (existingToggle) {
        return; // Don't duplicate if it already exists
      }
      
      const navbar = document.querySelector('.navbar-nav');
      if (navbar) {
        const toggleItem = document.createElement('li');
        toggleItem.className = 'nav-item dark-mode-toggle';
        
        // Check current theme and adjust icon accordingly
        const currentTheme = document.documentElement.getAttribute('data-style') || 'light';
        const icon = currentTheme === 'dark' ? 'ti ti-sun' : 'ti ti-moon-stars';
        
        toggleItem.innerHTML = `
          <a class="nav-link style-switcher-toggle" href="javascript:void(0);" title="Toggle Dark Mode">
            <i class="${icon}"></i>
          </a>
        `;
        navbar.prepend(toggleItem);
        
        // Add click event to toggle dark mode
        toggleItem.querySelector('a').addEventListener('click', () => {
          const html = document.documentElement;
          const currentStyle = html.getAttribute('data-style') || 'light';
          const newStyle = currentStyle === 'dark' ? 'light' : 'dark';
          
          // Update icon
          const iconElement = toggleItem.querySelector('i');
          if (iconElement) {
            iconElement.className = newStyle === 'dark' ? 'ti ti-sun' : 'ti ti-moon-stars';
          }
          
          // Set theme
          html.setAttribute('data-style', newStyle);
          
          // Persist selection
          localStorage.setItem('template-style', newStyle);
          
          // Apply dark mode immediately to ensure all content areas are updated
          this.applyDarkModeToContent(newStyle === 'dark');
          
          // Make an AJAX request to store theme preference server-side
          fetch('/set-theme', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').getAttribute('content')
            },
            body: JSON.stringify({ theme: newStyle })
          }).catch(error => // console.error('Error saving theme preference:', error));
        });
      }
      */
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
    
    // Add ripple effect to buttons - Modified to prevent button scaling issues
    addRippleEffect: function() {
      // Only apply ripple effect to non-modal buttons to prevent conflicts
      document.querySelectorAll('.ecs-btn:not([data-bs-toggle="modal"]), .btn:not([data-bs-toggle="modal"]):not(.edit-match-btn)').forEach(button => {
        button.addEventListener('click', function(e) {
          // Skip if this is a modal button
          if (this.getAttribute('data-bs-toggle') === 'modal' || 
              this.classList.contains('edit-match-btn') ||
              this.closest('[data-bs-toggle="modal"]')) {
            return;
          }
          
          const ripple = document.createElement('span');
          ripple.classList.add('ripple-effect');
          
          const rect = this.getBoundingClientRect();
          const size = Math.max(rect.width, rect.height);
          
          ripple.style.width = ripple.style.height = `${size}px`;
          ripple.style.left = `${e.clientX - rect.left - size / 2}px`;
          ripple.style.top = `${e.clientY - rect.top - size / 2}px`;
          
          // Set transform to none to prevent button scaling
          ripple.style.transform = 'none';
          
          this.appendChild(ripple);
          
          setTimeout(() => {
            if (ripple.parentNode) {
              ripple.parentNode.removeChild(ripple);
            }
          }, 600);
        });
      });
      
      // console.log('Ripple effect added with scaling fix');
    },
    
    // Improve keyboard navigation for better accessibility
    improveKeyboardNavigation: function() {
      // Add focus styles to interactive elements
      document.querySelectorAll('a, button, input, select, textarea, [tabindex]').forEach(element => {
        element.addEventListener('focus', function() {
          this.classList.add('ecs-focus');
        });
        
        element.addEventListener('blur', function() {
          this.classList.remove('ecs-focus');
        });
      });
    },
    
    // Set up custom transitions
    setupTransitions: function() {
      // Add slide-in animation for elements with data-ecs-animate="slide-in"
      document.querySelectorAll('[data-ecs-animate="slide-in"]').forEach(element => {
        element.style.opacity = '0';
        element.style.transform = 'translateY(20px)';
        element.style.transition = 'opacity 0.3s ease-out, transform 0.3s ease-out';
        
        // Trigger animation after a short delay
        setTimeout(() => {
          element.style.opacity = '1';
          element.style.transform = 'translateY(0)';
        }, 100);
      });
    }
  };
  
  // Initialize on DOM ready
  document.addEventListener('DOMContentLoaded', function() {
    ECSDesignSystem.init();
  });
  
  // Make available globally
  window.ECSDesignSystem = ECSDesignSystem;
})();