/**
 * ============================================================================
 * PROGRESSIVE DISCLOSURE COMPONENT
 * ============================================================================
 *
 * Reusable component for showing/hiding content on demand.
 * Follows mobile UX best practices - show critical info first, reveal details on tap.
 *
 * Features:
 * - Accordion mode (only one open at a time)
 * - Keyboard navigation (Enter/Space to toggle, arrows for accordion)
 * - ARIA attributes for accessibility
 * - Smooth CSS-driven animations
 * - Memory of open/closed state (optional)
 * - Event delegation for dynamic content
 *
 * Data Attributes:
 * - data-disclosure: Container element
 * - data-disclosure-trigger: Clickable toggle button
 * - data-disclosure-content: Content to show/hide
 * - data-disclosure-group: Group name for accordion behavior
 * - data-disclosure-remember: Persist open/closed state in localStorage
 *
 * @version 1.0.0
 * @created 2025-12-29
 *
 * Usage:
 *   <div class="c-disclosure" data-disclosure data-disclosure-group="faq">
 *     <button class="c-disclosure__trigger" data-disclosure-trigger>
 *       Question text
 *       <i class="c-disclosure__icon ti ti-chevron-down"></i>
 *     </button>
 *     <div class="c-disclosure__content" data-disclosure-content>
 *       <div class="c-disclosure__content-inner">
 *         Answer text...
 *       </div>
 *     </div>
 *   </div>
 *
 * ============================================================================
 */

(function(window, document) {
  'use strict';

  const ProgressiveDisclosure = {
    // ========================================================================
    // CONFIGURATION
    // ========================================================================

    SELECTORS: {
      DISCLOSURE: '[data-disclosure]',
      TRIGGER: '[data-disclosure-trigger]',
      CONTENT: '[data-disclosure-content]',
      ACCORDION: '[data-accordion]'
    },

    CLASSES: {
      EXPANDED: 'is-expanded',
      COLLAPSED: 'is-collapsed',
      ANIMATING: 'is-animating'
    },

    STORAGE_PREFIX: 'disclosure_',

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initialize all disclosure components in context
     * @param {Element} context - Root element to search within
     */
    init(context = document) {
      const disclosures = context.querySelectorAll(this.SELECTORS.DISCLOSURE);

      if (disclosures.length === 0) {
        return;
      }

      disclosures.forEach(disclosure => this.initDisclosure(disclosure));

      // Set up global event delegation for dynamic content
      this.setupEventDelegation(context);
    },

    /**
     * Initialize a single disclosure component
     * @param {Element} disclosure - Disclosure container element
     */
    initDisclosure(disclosure) {
      // Skip if already initialized
      if (disclosure.dataset.disclosureInitialized === 'true') {
        return;
      }

      const trigger = disclosure.querySelector(this.SELECTORS.TRIGGER);
      const content = disclosure.querySelector(this.SELECTORS.CONTENT);

      if (!trigger || !content) {
        console.warn('ProgressiveDisclosure: Missing trigger or content element', disclosure);
        return;
      }

      // Generate unique ID if not present
      const id = disclosure.id || `disclosure-${this.generateId()}`;
      disclosure.id = id;

      // Set up ARIA attributes
      const contentId = `${id}-content`;
      content.id = contentId;
      trigger.setAttribute('aria-expanded', 'false');
      trigger.setAttribute('aria-controls', contentId);
      content.setAttribute('aria-hidden', 'true');

      // Restore saved state if remember is enabled
      if (disclosure.dataset.disclosureRemember !== undefined) {
        this.restoreState(disclosure);
      }

      // Mark as initialized
      disclosure.dataset.disclosureInitialized = 'true';
    },

    /**
     * Set up event delegation for click and keyboard events
     * @param {Element} context - Root element
     */
    setupEventDelegation(context) {
      // Avoid multiple event listeners
      if (context._disclosureDelegation) {
        return;
      }
      context._disclosureDelegation = true;

      // Click handler
      context.addEventListener('click', (e) => {
        const trigger = e.target.closest(this.SELECTORS.TRIGGER);
        if (!trigger) return;

        e.preventDefault();
        const disclosure = trigger.closest(this.SELECTORS.DISCLOSURE);
        if (disclosure) {
          this.toggle(disclosure);
        }
      });

      // Keyboard handler
      context.addEventListener('keydown', (e) => {
        const trigger = e.target.closest(this.SELECTORS.TRIGGER);
        if (!trigger) return;

        const disclosure = trigger.closest(this.SELECTORS.DISCLOSURE);
        if (!disclosure) return;

        switch (e.key) {
          case 'Enter':
          case ' ':
            e.preventDefault();
            this.toggle(disclosure);
            break;

          case 'ArrowDown':
            e.preventDefault();
            this.focusNextDisclosure(disclosure);
            break;

          case 'ArrowUp':
            e.preventDefault();
            this.focusPrevDisclosure(disclosure);
            break;

          case 'Home':
            e.preventDefault();
            this.focusFirstDisclosure(disclosure);
            break;

          case 'End':
            e.preventDefault();
            this.focusLastDisclosure(disclosure);
            break;
        }
      });
    },

    // ========================================================================
    // STATE MANAGEMENT
    // ========================================================================

    /**
     * Toggle disclosure open/closed state
     * @param {Element} disclosure - Disclosure container
     */
    toggle(disclosure) {
      const isExpanded = disclosure.classList.contains(this.CLASSES.EXPANDED);

      if (isExpanded) {
        this.collapse(disclosure);
      } else {
        this.expand(disclosure);
      }
    },

    /**
     * Expand a disclosure
     * @param {Element} disclosure - Disclosure container
     */
    expand(disclosure) {
      const trigger = disclosure.querySelector(this.SELECTORS.TRIGGER);
      const content = disclosure.querySelector(this.SELECTORS.CONTENT);
      const group = disclosure.dataset.disclosureGroup;

      // If part of accordion group, collapse others first
      if (group) {
        this.collapseGroup(group, disclosure);
      }

      // Update classes
      disclosure.classList.remove(this.CLASSES.COLLAPSED);
      disclosure.classList.add(this.CLASSES.EXPANDED);

      // Update ARIA
      trigger?.setAttribute('aria-expanded', 'true');
      content?.setAttribute('aria-hidden', 'false');

      // Save state if remember is enabled
      if (disclosure.dataset.disclosureRemember !== undefined) {
        this.saveState(disclosure, true);
      }

      // Dispatch custom event
      disclosure.dispatchEvent(new CustomEvent('disclosure:expanded', {
        bubbles: true,
        detail: { disclosure }
      }));

      // Log for debugging
      if (window.InitSystemDebug) {
        window.InitSystemDebug.log('progressive-disclosure', `Expanded: ${disclosure.id}`);
      }
    },

    /**
     * Collapse a disclosure
     * @param {Element} disclosure - Disclosure container
     */
    collapse(disclosure) {
      const trigger = disclosure.querySelector(this.SELECTORS.TRIGGER);
      const content = disclosure.querySelector(this.SELECTORS.CONTENT);

      // Update classes
      disclosure.classList.remove(this.CLASSES.EXPANDED);
      disclosure.classList.add(this.CLASSES.COLLAPSED);

      // Update ARIA
      trigger?.setAttribute('aria-expanded', 'false');
      content?.setAttribute('aria-hidden', 'true');

      // Save state if remember is enabled
      if (disclosure.dataset.disclosureRemember !== undefined) {
        this.saveState(disclosure, false);
      }

      // Dispatch custom event
      disclosure.dispatchEvent(new CustomEvent('disclosure:collapsed', {
        bubbles: true,
        detail: { disclosure }
      }));
    },

    /**
     * Collapse all disclosures in a group except the specified one
     * @param {string} group - Group name
     * @param {Element} except - Disclosure to keep open
     */
    collapseGroup(group, except = null) {
      const groupDisclosures = document.querySelectorAll(
        `${this.SELECTORS.DISCLOSURE}[data-disclosure-group="${group}"]`
      );

      groupDisclosures.forEach(disclosure => {
        if (disclosure !== except && disclosure.classList.contains(this.CLASSES.EXPANDED)) {
          this.collapse(disclosure);
        }
      });
    },

    /**
     * Expand all disclosures (or in a group)
     * @param {string} group - Optional group name
     */
    expandAll(group = null) {
      const selector = group
        ? `${this.SELECTORS.DISCLOSURE}[data-disclosure-group="${group}"]`
        : this.SELECTORS.DISCLOSURE;

      document.querySelectorAll(selector).forEach(disclosure => {
        if (!disclosure.classList.contains(this.CLASSES.EXPANDED)) {
          this.expand(disclosure);
        }
      });
    },

    /**
     * Collapse all disclosures (or in a group)
     * @param {string} group - Optional group name
     */
    collapseAll(group = null) {
      const selector = group
        ? `${this.SELECTORS.DISCLOSURE}[data-disclosure-group="${group}"]`
        : this.SELECTORS.DISCLOSURE;

      document.querySelectorAll(selector).forEach(disclosure => {
        if (disclosure.classList.contains(this.CLASSES.EXPANDED)) {
          this.collapse(disclosure);
        }
      });
    },

    // ========================================================================
    // STATE PERSISTENCE
    // ========================================================================

    /**
     * Save disclosure state to localStorage
     * @param {Element} disclosure - Disclosure container
     * @param {boolean} isExpanded - Current state
     */
    saveState(disclosure, isExpanded) {
      const key = this.STORAGE_PREFIX + disclosure.id;
      try {
        localStorage.setItem(key, isExpanded ? '1' : '0');
      } catch (e) {
        // localStorage not available or full
      }
    },

    /**
     * Restore disclosure state from localStorage
     * @param {Element} disclosure - Disclosure container
     */
    restoreState(disclosure) {
      const key = this.STORAGE_PREFIX + disclosure.id;
      try {
        const saved = localStorage.getItem(key);
        if (saved === '1') {
          this.expand(disclosure);
        }
      } catch (e) {
        // localStorage not available
      }
    },

    // ========================================================================
    // KEYBOARD NAVIGATION
    // ========================================================================

    /**
     * Get all disclosures in the same group or parent container
     * @param {Element} disclosure - Current disclosure
     * @returns {Element[]} Array of disclosure elements
     */
    getSiblingDisclosures(disclosure) {
      const group = disclosure.dataset.disclosureGroup;
      if (group) {
        return Array.from(document.querySelectorAll(
          `${this.SELECTORS.DISCLOSURE}[data-disclosure-group="${group}"]`
        ));
      }

      // Fall back to parent container
      const parent = disclosure.parentElement;
      return Array.from(parent.querySelectorAll(this.SELECTORS.DISCLOSURE));
    },

    /**
     * Focus the next disclosure's trigger
     * @param {Element} disclosure - Current disclosure
     */
    focusNextDisclosure(disclosure) {
      const siblings = this.getSiblingDisclosures(disclosure);
      const index = siblings.indexOf(disclosure);
      const next = siblings[index + 1] || siblings[0];
      next?.querySelector(this.SELECTORS.TRIGGER)?.focus();
    },

    /**
     * Focus the previous disclosure's trigger
     * @param {Element} disclosure - Current disclosure
     */
    focusPrevDisclosure(disclosure) {
      const siblings = this.getSiblingDisclosures(disclosure);
      const index = siblings.indexOf(disclosure);
      const prev = siblings[index - 1] || siblings[siblings.length - 1];
      prev?.querySelector(this.SELECTORS.TRIGGER)?.focus();
    },

    /**
     * Focus the first disclosure's trigger
     * @param {Element} disclosure - Current disclosure
     */
    focusFirstDisclosure(disclosure) {
      const siblings = this.getSiblingDisclosures(disclosure);
      siblings[0]?.querySelector(this.SELECTORS.TRIGGER)?.focus();
    },

    /**
     * Focus the last disclosure's trigger
     * @param {Element} disclosure - Current disclosure
     */
    focusLastDisclosure(disclosure) {
      const siblings = this.getSiblingDisclosures(disclosure);
      siblings[siblings.length - 1]?.querySelector(this.SELECTORS.TRIGGER)?.focus();
    },

    // ========================================================================
    // UTILITIES
    // ========================================================================

    /**
     * Generate a unique ID
     * @returns {string} Unique ID
     */
    generateId() {
      return Math.random().toString(36).substr(2, 9);
    },

    /**
     * Check if a disclosure is expanded
     * @param {Element} disclosure - Disclosure container
     * @returns {boolean} True if expanded
     */
    isExpanded(disclosure) {
      return disclosure.classList.contains(this.CLASSES.EXPANDED);
    },

    /**
     * Programmatically open a disclosure by ID
     * @param {string} id - Disclosure element ID
     */
    open(id) {
      const disclosure = document.getElementById(id);
      if (disclosure) {
        this.expand(disclosure);
      }
    },

    /**
     * Programmatically close a disclosure by ID
     * @param {string} id - Disclosure element ID
     */
    close(id) {
      const disclosure = document.getElementById(id);
      if (disclosure) {
        this.collapse(disclosure);
      }
    }
  };

  // ==========================================================================
  // INITSYSTEM REGISTRATION
  // ==========================================================================

  // Expose globally for programmatic access (MUST be before any callbacks or registrations)
  window.ProgressiveDisclosure = ProgressiveDisclosure;

  // MUST use window.InitSystem and window.ProgressiveDisclosure to avoid TDZ errors in bundled code
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('progressive-disclosure', function(context) {
      window.ProgressiveDisclosure.init(context);
    }, {
      priority: 70,
      description: 'Progressive disclosure / accordion component',
      reinitializable: true
    });
  } else {
    // Fallback: Initialize on DOMContentLoaded
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => window.ProgressiveDisclosure.init());
    } else {
      window.ProgressiveDisclosure.init();
    }
  }

})(window, document);
