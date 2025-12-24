/**
 * Responsive Tables JS
 * 
 * Adds data-label attributes to table cells and handles responsive behavior
 * Automatically transforms all tables with .mobile-card-table class
 */

(function() {
  'use strict';
  
  const ResponsiveTables = {
    /**
     * Initialize responsive tables functionality
     */
    init: function() {
      // Initialize tables when DOM is ready
      this.processAllTables();
      this.setupScrollTracking();
      this.setupDataTables();
      this.setupMutationObserver();
    },
    
    /**
     * Process all tables (prioritize .mobile-card-table, then all .table-responsive tables)
     */
    processAllTables: function() {
      // First process tables with explicit mobile-card-table class
      const mobileCardTables = document.querySelectorAll('table.mobile-card-table');
      mobileCardTables.forEach(table => {
        this.processTable(table);
      });

      // Then process all tables within .table-responsive containers
      const responsiveTables = document.querySelectorAll('[data-table-responsive] table');
      responsiveTables.forEach(table => {
        // Skip if already processed or if it's within a horizontal-mobile table
        if (!table.classList.contains('mobile-card-processed') &&
            !table.closest('[data-table-horizontal-mobile]')) {
          this.processTable(table);
        }
      });

      // Process any standalone .table elements not in .table-responsive (fallback)
      const standaloneTables = document.querySelectorAll('table.table:not(.mobile-card-processed)');
      standaloneTables.forEach(table => {
        // Only process if not already in a .table-responsive container
        if (!table.closest('[data-table-responsive]') &&
            !table.closest('[data-table-horizontal-mobile]') &&
            window.innerWidth < 992) {
          this.processTable(table);
        }
      });
    },
    
    /**
     * Process a single table by adding data-label attributes
     * @param {HTMLElement} table - The table element to process
     */
    processTable: function(table) {
      // Skip if table has already been processed
      if (table.classList.contains('mobile-card-processed')) {
        return;
      }
      
      // Get header text values
      const headerCells = table.querySelectorAll('thead th');
      const headerTexts = Array.from(headerCells).map(th => th.textContent.trim());
      
      // Add data-label attributes to all body cells
      const rows = table.querySelectorAll('tbody tr');
      rows.forEach(row => {
        const cells = row.querySelectorAll('td');
        cells.forEach((cell, index) => {
          // Only add data-label if we have a corresponding header and no existing data-label
          if (index < headerTexts.length && !cell.hasAttribute('data-label')) {
            cell.setAttribute('data-label', headerTexts[index]);
          }
          
          // Special handling for cells containing only action buttons
          if (this.isCellWithOnlyActions(cell)) {
            cell.classList.add('table-actions');
          }
          
          // Special handling for cells with avatars
          if (this.isCellWithAvatar(cell)) {
            cell.classList.add('avatar-cell');
          }
          
          // Make sure empty cells still show their labels
          if (!cell.textContent.trim() && !cell.querySelector('*')) {
            const placeholder = document.createElement('span');
            placeholder.classList.add('empty-cell-placeholder');
            placeholder.innerText = "—";
            cell.appendChild(placeholder);
          }
        });
      });
      
      // Mark table as processed
      table.classList.add('mobile-card-processed');
    },
    
    /**
     * Check if a cell contains only action buttons
     * @param {HTMLElement} cell - The table cell to check
     * @return {boolean} True if cell contains only action buttons
     */
    isCellWithOnlyActions: function(cell) {
      // Get direct children
      const children = Array.from(cell.children);
      
      // If no children, not an action cell
      if (children.length === 0) {
        return false;
      }
      
      // Check if all children are buttons or links with button classes
      return children.every(child => {
        return (
          child.tagName === 'BUTTON' ||
          child.tagName === 'A' && child.classList.contains('btn') ||
          child.hasAttribute('data-dropdown') ||
          child.hasAttribute('data-btn-group')
        );
      });
    },
    
    /**
     * Check if a cell contains an avatar
     * @param {HTMLElement} cell - The table cell to check
     * @return {boolean} True if cell contains an avatar
     */
    isCellWithAvatar: function(cell) {
      return (
        cell.querySelector('[data-avatar]') !== null ||
        cell.querySelector('img[data-rounded-circle]') !== null ||
        cell.querySelector('img[data-avatar]') !== null
      );
    },
    
    /**
     * Track scrolling on table-responsive-scroll elements
     */
    setupScrollTracking: function() {
      const scrollTables = document.querySelectorAll('[data-table-responsive-scroll]');

      scrollTables.forEach(tableWrapper => {
        tableWrapper.addEventListener('scroll', function() {
          if (this.scrollLeft > 10) {
            this.classList.add('is-scrolled');
          } else {
            this.classList.remove('is-scrolled');
          }
        });
      });
    },
    
    /**
     * Setup DataTables compatibility
     */
    setupDataTables: function() {
      // Only proceed if DataTables is available
      if (typeof $.fn.dataTable !== 'undefined') {
        // Default DataTables setup for mobile
        $.extend(true, $.fn.dataTable.defaults, {
          responsive: true,
          drawCallback: function() {
            // Ensure mobile card processing on DataTables
            if (this.hasClass('mobile-card-table')) {
              ResponsiveTables.processTable(this[0]);
            }
          }
        });
        
        // Process any existing DataTables
        $('.dataTable.mobile-card-table').each(function() {
          ResponsiveTables.processTable(this);
        });
      }
    },
    
    /**
     * Setup MutationObserver to detect and process newly added tables
     */
    setupMutationObserver: function() {
      // Create observer instance
      const observer = new MutationObserver((mutations) => {
        let shouldProcess = false;
        
        mutations.forEach(mutation => {
          // Check for added nodes
          if (mutation.addedNodes && mutation.addedNodes.length) {
            for (let i = 0; i < mutation.addedNodes.length; i++) {
              const node = mutation.addedNodes[i];
              
              // Check if node is an element
              if (node.nodeType === 1) {
                // Check if it's a table with our class
                if (node.matches && node.matches('table.mobile-card-table')) {
                  shouldProcess = true;
                  break;
                }
                
                // Check if it contains tables with our class
                if (node.querySelectorAll && node.querySelectorAll('table.mobile-card-table').length) {
                  shouldProcess = true;
                  break;
                }
              }
            }
          }
        });
        
        // Process tables if needed
        if (shouldProcess) {
          this.processAllTables();
        }
      });
      
      // Start observing document body
      observer.observe(document.body, {
        childList: true,
        subtree: true
      });
    }
  };
  
  // Make available globally
  window.ResponsiveTables = ResponsiveTables;

  // Register with InitSystem if available
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('responsive-tables', function() {
      ResponsiveTables.init();
    }, {
      priority: 60,
      description: 'Responsive table system (card view on mobile, data-labels)',
      reinitializable: true
    });
  } else {
    // Fallback: Initialize when document is ready
    document.addEventListener('DOMContentLoaded', function() {
      ResponsiveTables.init();
    });
  }
})();
