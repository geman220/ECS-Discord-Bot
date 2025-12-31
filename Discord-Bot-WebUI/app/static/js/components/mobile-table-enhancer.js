/**
 * ============================================================================
 * MOBILE TABLE ENHANCER
 * ============================================================================
 *
 * Automatically enhances HTML tables for mobile responsiveness.
 * Adds data-label attributes from headers, enables card transformation,
 * and supports progressive disclosure for complex data.
 *
 * Features:
 * - Auto-detects table headers and adds data-label to cells
 * - Identifies primary/secondary columns for mobile prioritization
 * - Supports expandable rows for hiding non-critical data
 * - Works with dynamically loaded tables
 * - No changes needed to existing HTML - pure enhancement
 *
 * Data Attributes (optional, for customization):
 * - data-mobile-table: Enable mobile enhancement (auto-detected on .table)
 * - data-mobile-primary="1,2": Column indices to always show (0-based)
 * - data-mobile-expand: Enable row expansion on mobile
 * - data-mobile-card: Force card layout on mobile
 * - data-mobile-priority="high|medium|low": Column priority
 *
 * CSS Classes Applied:
 * - .c-table--mobile-enhanced: Table has been processed
 * - .c-table__row--expandable: Row can expand for more details
 * - .c-table__row--expanded: Row is currently expanded
 * - .c-table__cell--primary: Primary data cell (always visible)
 * - .c-table__cell--secondary: Secondary data cell (shown on expand)
 *
 * @version 1.0.0
 * @created 2025-12-29
 *
 * ============================================================================
 */

(function(window, document) {
  'use strict';

  const MobileTableEnhancer = {
    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    SELECTORS: {
      // Only enhance tables that explicitly opt-in with data-mobile-table attribute
      // This prevents conflicts with existing table styles
      TABLE: '[data-mobile-table]',
      TABLE_RESPONSIVE: '.table-responsive',
      HEADER: 'thead th, thead td',
      BODY_ROW: 'tbody tr',
      BODY_CELL: 'tbody td'
    },

    CLASSES: {
      ENHANCED: 'c-table--mobile-enhanced',
      ROW_EXPANDABLE: 'c-table__row--expandable',
      ROW_EXPANDED: 'c-table__row--expanded',
      CELL_PRIMARY: 'c-table__cell--primary',
      CELL_SECONDARY: 'c-table__cell--secondary',
      CELL_ACTIONS: 'c-table__cell--actions',
      EXPAND_TRIGGER: 'c-table__expand-trigger',
      MOBILE_DETAIL: 'c-table__mobile-detail',
      DETAIL_ROW: 'c-table__detail-row'
    },

    // Default number of columns to show on mobile before collapsing
    DEFAULT_VISIBLE_COLUMNS: 3,

    // Breakpoint for mobile view (matches CSS)
    MOBILE_BREAKPOINT: 768,

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initialize table enhancement for all tables in context
     * @param {Element} context - Root element to search within
     */
    init(context = document) {
      const tables = context.querySelectorAll(this.SELECTORS.TABLE);

      if (tables.length === 0) {
        return;
      }

      tables.forEach(table => this.enhanceTable(table));

      // Set up resize observer for responsive behavior
      this.setupResizeObserver();

      // Set up click delegation for expandable rows
      this.setupEventDelegation(context);
    },

    /**
     * Enhance a single table for mobile
     * @param {Element} table - Table element
     */
    enhanceTable(table) {
      // Skip if already enhanced
      if (table.classList.contains(this.CLASSES.ENHANCED)) {
        return;
      }

      // Get headers
      const headers = this.extractHeaders(table);
      if (headers.length === 0) {
        return;
      }

      // Add data-label attributes to all body cells
      this.addDataLabels(table, headers);

      // Determine which columns are primary/secondary
      this.classifyColumns(table, headers);

      // Add expand triggers if table has many columns
      if (headers.length > this.DEFAULT_VISIBLE_COLUMNS) {
        this.addExpandTriggers(table);
      }

      // Mark as enhanced
      table.classList.add(this.CLASSES.ENHANCED);

      // Dispatch enhancement event
      table.dispatchEvent(new CustomEvent('table:enhanced', {
        bubbles: true,
        detail: { table, headers }
      }));

      // Log for debugging
      if (window.InitSystemDebug) {
        window.InitSystemDebug.log('mobile-table-enhancer',
          `Enhanced table with ${headers.length} columns`);
      }
    },

    // ========================================================================
    // HEADER EXTRACTION
    // ========================================================================

    /**
     * Extract header labels from table
     * @param {Element} table - Table element
     * @returns {Array} Array of header objects {text, index, element, priority}
     */
    extractHeaders(table) {
      const headerCells = table.querySelectorAll(this.SELECTORS.HEADER);
      const headers = [];

      headerCells.forEach((cell, index) => {
        // Get header text, stripping any icons or extra elements
        let text = cell.textContent.trim();

        // If cell has data-label attribute, use that
        if (cell.dataset.label) {
          text = cell.dataset.label;
        }

        // Determine priority based on data attribute or heuristics
        let priority = cell.dataset.mobilePriority || this.inferPriority(text, index);

        headers.push({
          text: text,
          index: index,
          element: cell,
          priority: priority,
          visible: priority === 'high'
        });
      });

      return headers;
    },

    /**
     * Infer column priority based on header text
     * @param {string} text - Header text
     * @param {number} index - Column index
     * @returns {string} Priority level (high, medium, low)
     */
    inferPriority(text, index) {
      const textLower = text.toLowerCase();

      // High priority - always show
      const highPriorityTerms = [
        'name', 'title', 'user', 'player', 'team', 'status',
        'date', 'time', 'action', 'actions', ''
      ];

      // Low priority - hide on mobile
      const lowPriorityTerms = [
        'id', 'uuid', 'created', 'updated', 'modified',
        'last', 'details', 'description', 'notes'
      ];

      // First column is usually primary identifier
      if (index === 0) return 'high';

      // Last column is usually actions
      if (textLower === 'actions' || textLower === '' || textLower === 'action') {
        return 'high';
      }

      // Check high priority terms
      if (highPriorityTerms.some(term => textLower.includes(term))) {
        return 'high';
      }

      // Check low priority terms
      if (lowPriorityTerms.some(term => textLower.includes(term))) {
        return 'low';
      }

      // Default to medium
      return 'medium';
    },

    // ========================================================================
    // DATA LABEL APPLICATION
    // ========================================================================

    /**
     * Add data-label attributes to all body cells
     * @param {Element} table - Table element
     * @param {Array} headers - Header array from extractHeaders
     */
    addDataLabels(table, headers) {
      const rows = table.querySelectorAll(this.SELECTORS.BODY_ROW);

      rows.forEach(row => {
        const cells = row.querySelectorAll('td');

        cells.forEach((cell, index) => {
          // Skip if already has data-label
          if (cell.dataset.label) return;

          // Get corresponding header
          const header = headers[index];
          if (header && header.text) {
            cell.dataset.label = header.text;
          }
        });
      });
    },

    /**
     * Classify columns as primary or secondary
     * @param {Element} table - Table element
     * @param {Array} headers - Header array
     */
    classifyColumns(table, headers) {
      // Check for explicit primary columns setting
      const primaryIndices = table.dataset.mobilePrimary
        ? table.dataset.mobilePrimary.split(',').map(n => parseInt(n.trim(), 10))
        : null;

      const rows = table.querySelectorAll(this.SELECTORS.BODY_ROW);

      rows.forEach(row => {
        const cells = row.querySelectorAll('td');

        cells.forEach((cell, index) => {
          const header = headers[index];
          const isPrimary = primaryIndices
            ? primaryIndices.includes(index)
            : (header && header.priority === 'high');

          if (isPrimary) {
            cell.classList.add(this.CLASSES.CELL_PRIMARY);
          } else {
            cell.classList.add(this.CLASSES.CELL_SECONDARY);
          }

          // Mark actions column
          if (header && header.text.toLowerCase() === 'actions') {
            cell.classList.add(this.CLASSES.CELL_ACTIONS);
          }
        });
      });
    },

    // ========================================================================
    // EXPANDABLE ROWS
    // ========================================================================

    /**
     * Add expand triggers to rows with many columns
     * @param {Element} table - Table element
     */
    addExpandTriggers(table) {
      // Only add if data-mobile-expand is set or auto-detected
      if (table.dataset.mobileExpand === 'false') {
        return;
      }

      const rows = table.querySelectorAll(this.SELECTORS.BODY_ROW);

      rows.forEach(row => {
        // Skip if already has expand trigger
        if (row.querySelector(`.${this.CLASSES.EXPAND_TRIGGER}`)) {
          return;
        }

        // Add expandable class
        row.classList.add(this.CLASSES.ROW_EXPANDABLE);

        // Create expand trigger (inserted via CSS ::after pseudo-element)
        // The actual click handling is done via event delegation
        row.setAttribute('tabindex', '0');
        row.setAttribute('role', 'button');
        row.setAttribute('aria-expanded', 'false');
      });
    },

    /**
     * Toggle row expansion
     * @param {Element} row - Table row element
     */
    toggleRow(row) {
      const isExpanded = row.classList.contains(this.CLASSES.ROW_EXPANDED);

      if (isExpanded) {
        this.collapseRow(row);
      } else {
        this.expandRow(row);
      }
    },

    /**
     * Expand a row to show all data
     * @param {Element} row - Table row element
     */
    expandRow(row) {
      row.classList.add(this.CLASSES.ROW_EXPANDED);
      row.setAttribute('aria-expanded', 'true');

      // Show secondary cells
      row.querySelectorAll(`.${this.CLASSES.CELL_SECONDARY}`).forEach(cell => {
        cell.style.display = '';
      });

      row.dispatchEvent(new CustomEvent('row:expanded', {
        bubbles: true,
        detail: { row }
      }));
    },

    /**
     * Collapse a row to hide secondary data
     * @param {Element} row - Table row element
     */
    collapseRow(row) {
      row.classList.remove(this.CLASSES.ROW_EXPANDED);
      row.setAttribute('aria-expanded', 'false');

      row.dispatchEvent(new CustomEvent('row:collapsed', {
        bubbles: true,
        detail: { row }
      }));
    },

    // ========================================================================
    // EVENT HANDLING
    // ========================================================================

    /**
     * Set up event delegation for row expansion
     * @param {Element} context - Root element
     */
    setupEventDelegation(context) {
      if (context._mobileTableDelegation) {
        return;
      }
      context._mobileTableDelegation = true;

      // Click handler for expandable rows (mobile only)
      context.addEventListener('click', (e) => {
        // Only on mobile
        if (window.innerWidth >= this.MOBILE_BREAKPOINT) {
          return;
        }

        const row = e.target.closest(`.${this.CLASSES.ROW_EXPANDABLE}`);
        if (!row) return;

        // Don't expand if clicking on interactive elements
        if (e.target.closest('a, button, input, select, .btn, .dropdown')) {
          return;
        }

        e.preventDefault();
        this.toggleRow(row);
      });

      // Keyboard handler
      context.addEventListener('keydown', (e) => {
        if (window.innerWidth >= this.MOBILE_BREAKPOINT) {
          return;
        }

        const row = e.target.closest(`.${this.CLASSES.ROW_EXPANDABLE}`);
        if (!row) return;

        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          this.toggleRow(row);
        }
      });
    },

    /**
     * Set up resize observer to handle responsive changes
     */
    setupResizeObserver() {
      if (this._resizeObserverSetup) {
        return;
      }
      this._resizeObserverSetup = true;

      // Simple resize handler
      let resizeTimeout;
      window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
          this.handleResize();
        }, 150);
      });
    },

    /**
     * Handle window resize - update table states
     */
    handleResize() {
      const isMobile = window.innerWidth < this.MOBILE_BREAKPOINT;
      const tables = document.querySelectorAll(`.${this.CLASSES.ENHANCED}`);

      tables.forEach(table => {
        // Collapse all expanded rows when switching to desktop
        if (!isMobile) {
          table.querySelectorAll(`.${this.CLASSES.ROW_EXPANDED}`).forEach(row => {
            this.collapseRow(row);
          });
        }
      });
    },

    // ========================================================================
    // PUBLIC API
    // ========================================================================

    /**
     * Manually enhance a specific table
     * @param {Element|string} tableOrSelector - Table element or selector
     */
    enhance(tableOrSelector) {
      const table = typeof tableOrSelector === 'string'
        ? document.querySelector(tableOrSelector)
        : tableOrSelector;

      if (table) {
        this.enhanceTable(table);
      }
    },

    /**
     * Re-process a table (e.g., after dynamic content update)
     * @param {Element|string} tableOrSelector - Table element or selector
     */
    refresh(tableOrSelector) {
      const table = typeof tableOrSelector === 'string'
        ? document.querySelector(tableOrSelector)
        : tableOrSelector;

      if (table) {
        // Remove enhanced class to allow re-processing
        table.classList.remove(this.CLASSES.ENHANCED);
        this.enhanceTable(table);
      }
    },

    /**
     * Check if currently in mobile view
     * @returns {boolean} True if mobile viewport
     */
    isMobileView() {
      return window.innerWidth < this.MOBILE_BREAKPOINT;
    }
  };

  // ==========================================================================
  // INITSYSTEM REGISTRATION
  // ==========================================================================

  // Expose globally for programmatic access (MUST be before any callbacks or registrations)
  window.MobileTableEnhancer = MobileTableEnhancer;

  // MUST use window.InitSystem and window.MobileTableEnhancer to avoid TDZ errors in bundled code
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('mobile-table-enhancer', function(context) {
      window.MobileTableEnhancer.init(context);
    }, {
      priority: 65, // Run before most UI components
      description: 'Enhances tables for mobile card transformation',
      reinitializable: true
    });
  } else {
    // Fallback: Initialize on DOMContentLoaded
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => window.MobileTableEnhancer.init());
    } else {
      window.MobileTableEnhancer.init();
    }
  }

})(window, document);
