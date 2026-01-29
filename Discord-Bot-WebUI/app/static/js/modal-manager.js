'use strict';

/**
 * Modal Manager - Centralized Flowbite Modal Management
 *
 * Best Practice 2025: Single source of truth for all modal operations
 *
 * USAGE:
 * ------
 * 1. Declarative (no JavaScript needed):
 *    <button data-modal-target="myModal" data-modal-toggle="myModal">Show Modal</button>
 *
 * 2. Programmatic (simple one-liner):
 *    window.ModalManager.show('myModal');
 *
 * 3. With options:
 *    window.ModalManager.show('myModal', { backdrop: 'static', closable: true });
 *
 * 4. Event delegation (preferred):
 *    <button data-action="show-modal" data-modal-id="myModal">Show</button>
 *
 * FEATURES:
 * ---------
 * - Instance caching (prevents duplicate modal initializations)
 * - Safe initialization (handles timing issues)
 * - Auto-discovery of all modals on page
 * - Event delegation support via data-action attributes
 * - Memory cleanup
 * - window.InitSystem registration (priority 20)
 *
 * SELECTOR CONVENTION:
 * --------------------
 * - Uses data-modal attribute for modal identification
 * - Falls back to .modal class for backward compatibility (Flowbite modals use hidden/flex classes)
 * - Uses data-action="show-modal|hide-modal|toggle-modal" for triggers
 *
 * @author ECS Discord Bot Team
 * @since 2025-12-17
 * @updated 2026-01-09 - Migrated to Flowbite from Bootstrap
 */

/**
 * Centralized Flowbite Modal Manager
 */
export class ModalManager {
    /**
     * Modal instance cache - prevents duplicate initializations
     * @private
     */
    static modalInstances = new Map();

    /**
     * Debug mode - set to true for debugging, false in production
     * @private
     */
    static DEBUG = false;

    /**
     * Track initialization state
     * @private
     */
    static _initialized = false;

    /**
     * Track if unified observer is registered
     * @private
     */
    static _unifiedObserverRegistered = false;

    /**
     * Initialize the Modal Manager
     * - Auto-discovers all modals on the page
     * - Sets up event delegation for data-action triggers
     * - Called automatically via window.InitSystem or DOMContentLoaded
     *
     * @param {Element} context - Optional context element (defaults to document)
     */
    static init(context = document) {
        // For full document init, only run once
        if (context === document && this._initialized) {
            return;
        }

        // Check for Flowbite Modal (window.Modal) - set by vendor-globals.js
        if (typeof window.Modal === 'undefined') {
            console.error('[window.ModalManager] Flowbite not loaded. Cannot initialize modals.');
            return;
        }

        this.log('Initializing Modal Manager...');

        // Discover and cache all modals in context
        this.discoverModals(context);

        // Set up event delegation (only once for document)
        if (context === document) {
            this.setupEventDelegation();
            this.setupMutationObserver();
            this._initialized = true;
        }

        this.log(`Initialized with ${this.modalInstances.size} modals`);
    }

    /**
     * Discover all modals in context and cache their instances
     * Uses data-modal attribute first, falls back to Flowbite modal patterns
     * Also pre-initializes modals referenced by data-modal-hide to prevent Flowbite warnings
     * @private
     * @param {Element} context - Context element to search within
     */
    static discoverModals(context = document) {
        // First, find all modal IDs referenced by data-modal-hide buttons
        // This ensures we initialize modals BEFORE Flowbite tries to attach hide handlers
        const hideButtons = context.querySelectorAll('[data-modal-hide]');
        const referencedModalIds = new Set();
        hideButtons.forEach(btn => {
            const modalId = btn.getAttribute('data-modal-hide');
            if (modalId) referencedModalIds.add(modalId);
        });

        // Query by data attribute first, then fall back to common modal selectors
        // Flowbite modals typically use 'hidden fixed inset-0' pattern
        const modalElements = context.querySelectorAll('[data-modal], .modal, [id*="Modal"]');

        // Also include any modals referenced by hide buttons that might not match the selector
        referencedModalIds.forEach(id => {
            const el = document.getElementById(id);
            if (el && !Array.from(modalElements).includes(el)) {
                // Will be processed in the main loop below
            }
        });

        // Process all discovered modals
        const allModalElements = new Set(modalElements);
        referencedModalIds.forEach(id => {
            const el = document.getElementById(id);
            if (el) allModalElements.add(el);
        });

        allModalElements.forEach(modalEl => {
            if (modalEl.id) {
                // Skip if already cached
                if (this.modalInstances.has(modalEl.id)) {
                    return;
                }

                // Skip elements that don't look like proper modal structures
                // Flowbite modals should have 'fixed' positioning and contain a modal dialog
                const isProperModal = modalEl.classList.contains('fixed') ||
                                       modalEl.classList.contains('modal') ||
                                       modalEl.classList.contains('hidden') ||
                                       modalEl.hasAttribute('data-modal') ||
                                       modalEl.hasAttribute('aria-hidden') ||
                                       modalEl.hasAttribute('tabindex') ||
                                       modalEl.querySelector('[role="dialog"]') ||
                                       referencedModalIds.has(modalEl.id);

                if (!isProperModal) {
                    this.log(`Skipping non-modal element: ${modalEl.id}`);
                    return;
                }

                try {
                    // Check if modal already has a Flowbite instance stored
                    let instance = modalEl._flowbiteModal;

                    if (!instance) {
                        // Create new Flowbite Modal instance
                        instance = new window.Modal(modalEl, {
                            backdrop: 'dynamic',
                            closable: true
                        });
                        modalEl._flowbiteModal = instance;
                    }

                    this.modalInstances.set(modalEl.id, instance);
                    this.log(`Cached modal: ${modalEl.id}`);
                } catch (error) {
                    // Silently skip elements that fail to initialize as modals
                    this.log(`Skipped element ${modalEl.id}: not a valid modal structure`);
                }
            } else {
                this.log('Found modal-like element without ID, skipping');
            }
        });
    }

    /**
     * Set up event delegation for data-action triggers
     * Note: window.EventDelegation handlers are registered at module scope below
     * @private
     */
    static setupEventDelegation() {
        // window.EventDelegation handlers are registered at module scope for proper timing
        this.log('Event delegation handlers are registered at module scope');
    }

    /**
     * Parse modal options from data attributes
     * @param {Element} element - Element to parse options from
     * @returns {Object|null} Options object or null
     */
    static parseOptionsFromElement(element) {
        const options = {};

        if (element.dataset.backdrop !== undefined) {
            options.backdrop = element.dataset.backdrop === 'false' ? false : element.dataset.backdrop;
        }

        if (element.dataset.keyboard !== undefined) {
            options.keyboard = element.dataset.keyboard === 'true';
        }

        if (element.dataset.focus !== undefined) {
            options.focus = element.dataset.focus === 'true';
        }

        return Object.keys(options).length > 0 ? options : null;
    }

    /**
     * Set up MutationObserver to clean up modal instances when removed from DOM
     * REFACTORED: Uses UnifiedMutationObserver to prevent cascade effects
     * @private
     */
    static setupMutationObserver() {
        // Only register once
        if (this._unifiedObserverRegistered) return;
        this._unifiedObserverRegistered = true;

        const self = this;

        // Use unified observer if available
        if (window.UnifiedMutationObserver) {
            window.UnifiedMutationObserver.register('modal-manager', {
                onRemovedNodes: function(nodes) {
                    nodes.forEach(node => {
                        // Check if removed node is a modal
                        const isModal = (node.classList?.contains('modal') || node.hasAttribute?.('data-modal'));
                        if (isModal && node.id) {
                            self.cleanup(node.id);
                        }
                    });
                },
                filter: function(node) {
                    // Only process modal elements
                    return node.classList?.contains('modal') || node.hasAttribute?.('data-modal');
                },
                priority: 200 // Run late - cleanup happens after other processing
            });
        }
    }

    /**
     * Show a modal by ID
     * @param {string} modalId - The ID of the modal to show (without # prefix)
     * @param {Object} options - Flowbite modal options (backdrop, closable)
     * @returns {boolean} - True if modal was shown successfully, false otherwise
     */
    static show(modalId, options = null) {
        if (!modalId) {
            console.error('[window.ModalManager] show() requires a modal ID');
            return false;
        }

        this.log(`Showing modal: ${modalId}`);

        // Get or create modal instance
        let modal = this.modalInstances.get(modalId);

        if (!modal) {
            // Modal not in cache - try to find and initialize it
            const modalElement = document.getElementById(modalId);

            if (!modalElement) {
                // Silently return false for missing modals - this is common on multi-page apps
                this.log(`Modal element not found: ${modalId}`);
                return false;
            }

            // Verify this looks like a proper modal structure before initializing
            const isProperModal = modalElement.classList.contains('fixed') ||
                                   modalElement.classList.contains('modal') ||
                                   modalElement.hasAttribute('data-modal') ||
                                   modalElement.hasAttribute('aria-hidden');

            if (!isProperModal) {
                this.log(`Element ${modalId} doesn't appear to be a modal structure`);
                return false;
            }

            try {
                // Check if Flowbite already initialized it
                modal = modalElement._flowbiteModal;

                if (!modal) {
                    // Create new Flowbite Modal instance with options
                    const modalOptions = options || { backdrop: 'dynamic', closable: true };
                    modal = new window.Modal(modalElement, modalOptions);
                    modalElement._flowbiteModal = modal;
                }

                // Cache for future use
                this.modalInstances.set(modalId, modal);
                this.log(`Created and cached new modal: ${modalId}`);
            } catch (error) {
                this.log(`Failed to initialize modal ${modalId}: ${error.message}`);
                return false;
            }
        }

        // Show the modal
        try {
            modal.show();
            return true;
        } catch (error) {
            this.log(`Failed to show modal ${modalId}: ${error.message}`);
            return false;
        }
    }

    /**
     * Hide a modal by ID
     * @param {string} modalId - The ID of the modal to hide (without # prefix)
     * @returns {boolean} - True if modal was hidden successfully, false otherwise
     */
    static hide(modalId) {
        if (!modalId) {
            console.error('[window.ModalManager] hide() requires a modal ID');
            return false;
        }

        this.log(`Hiding modal: ${modalId}`);

        const modal = this.modalInstances.get(modalId);

        if (!modal) {
            console.warn(`[window.ModalManager] Modal not found in cache: ${modalId}`);

            // Try to find it in DOM and get Flowbite instance
            const modalElement = document.getElementById(modalId);
            if (modalElement) {
                const instance = modalElement._flowbiteModal;
                if (instance) {
                    try {
                        instance.hide();
                        return true;
                    } catch (error) {
                        console.error(`[window.ModalManager] Failed to hide modal ${modalId}:`, error);
                        return false;
                    }
                }
                // Fallback: manually hide using Flowbite pattern
                modalElement.classList.add('hidden');
                modalElement.classList.remove('flex');
                modalElement.setAttribute('aria-hidden', 'true');
                document.body.classList.remove('overflow-hidden');
                return true;
            }

            return false;
        }

        try {
            modal.hide();
            return true;
        } catch (error) {
            console.error(`[window.ModalManager] Failed to hide modal ${modalId}:`, error);
            return false;
        }
    }

    /**
     * Toggle a modal (show if hidden, hide if shown)
     * @param {string} modalId - The ID of the modal to toggle
     * @returns {boolean} - True if toggle was successful, false otherwise
     */
    static toggle(modalId) {
        if (!modalId) {
            console.error('[window.ModalManager] toggle() requires a modal ID');
            return false;
        }

        const modal = this.modalInstances.get(modalId);

        if (!modal) {
            // Modal not in cache - just show it
            return this.show(modalId);
        }

        try {
            modal.toggle();
            return true;
        } catch (error) {
            console.error(`[window.ModalManager] Failed to toggle modal ${modalId}:`, error);
            return false;
        }
    }

    /**
     * Get a modal instance by ID
     * @param {string} modalId - The ID of the modal
     * @returns {Modal|null} - The Flowbite modal instance or null
     */
    static getInstance(modalId) {
        return this.modalInstances.get(modalId) || null;
    }

    /**
     * Clean up a modal instance from cache
     * @param {string} modalId - The ID of the modal to clean up
     */
    static cleanup(modalId) {
        if (this.modalInstances.has(modalId)) {
            this.log(`Cleaning up modal: ${modalId}`);

            try {
                const modal = this.modalInstances.get(modalId);
                modal.dispose();
            } catch (error) {
                console.warn(`[window.ModalManager] Error disposing modal ${modalId}:`, error);
            }

            this.modalInstances.delete(modalId);
        }
    }

    /**
     * Clean up all modal instances
     */
    static cleanupAll() {
        this.log('Cleaning up all modals...');

        this.modalInstances.forEach((modal, modalId) => {
            try {
                modal.dispose();
            } catch (error) {
                console.warn(`[window.ModalManager] Error disposing modal ${modalId}:`, error);
            }
        });

        this.modalInstances.clear();
        this.log('All modals cleaned up');
    }

    /**
     * Reinitialize - useful after dynamic content loading (HTMX, Turbo, AJAX)
     * @param {Element} context - Optional context element (defaults to document)
     */
    static reinit(context = document) {
        this.log('Reinitializing Modal Manager...');
        this.discoverModals(context);
    }

    /**
     * Populate modal form fields with data
     * Uses data-field attributes to map data to form elements
     *
     * @param {string} modalId - The ID of the modal
     * @param {Object} data - Key-value pairs to populate (keys match data-field values)
     * @returns {boolean} - True if population was successful
     *
     * @example
     * // HTML: <input type="text" name="name" data-field="name">
     * window.ModalManager.populate('editPlayerModal', { name: 'John Doe', id: 123 });
     */
    static populate(modalId, data) {
        if (!modalId || !data) {
            console.error('[window.ModalManager] populate() requires modalId and data');
            return false;
        }

        const modalElement = document.getElementById(modalId);
        if (!modalElement) {
            console.warn(`[window.ModalManager] Modal not found: ${modalId}`);
            return false;
        }

        this.log(`Populating modal ${modalId} with data:`, data);

        // Find all elements with data-field attribute
        const fields = modalElement.querySelectorAll('[data-field]');

        fields.forEach(field => {
            const fieldName = field.dataset.field;
            const value = data[fieldName];

            if (value !== undefined) {
                if (field.tagName === 'INPUT' || field.tagName === 'TEXTAREA') {
                    if (field.type === 'checkbox') {
                        field.checked = Boolean(value);
                    } else if (field.type === 'radio') {
                        field.checked = field.value === String(value);
                    } else {
                        field.value = value;
                    }
                } else if (field.tagName === 'SELECT') {
                    field.value = value;
                    // Trigger change event for Select2 or other enhanced selects
                    field.dispatchEvent(new Event('change', { bubbles: true }));
                } else {
                    // For spans, divs, etc. - set text content
                    field.textContent = value;
                }
            }
        });

        return true;
    }

    /**
     * Show modal and populate with data in one call
     *
     * @param {string} modalId - The ID of the modal
     * @param {Object} data - Data to populate
     * @param {Object} options - Modal options
     * @returns {boolean} - True if successful
     *
     * @example
     * window.ModalManager.showWithData('editPlayerModal', { id: 1, name: 'John' });
     */
    static showWithData(modalId, data, options = null) {
        const populated = this.populate(modalId, data);
        if (!populated) {
            return false;
        }
        return this.show(modalId, options);
    }

    /**
     * Reset all form fields in a modal
     *
     * @param {string} modalId - The ID of the modal
     * @returns {boolean} - True if reset was successful
     */
    static reset(modalId) {
        if (!modalId) {
            console.error('[window.ModalManager] reset() requires a modal ID');
            return false;
        }

        const modalElement = document.getElementById(modalId);
        if (!modalElement) {
            console.warn(`[window.ModalManager] Modal not found: ${modalId}`);
            return false;
        }

        // Find and reset all forms in the modal
        const forms = modalElement.querySelectorAll('form');
        forms.forEach(form => form.reset());

        // Clear non-form display elements with data-field
        const displayFields = modalElement.querySelectorAll('[data-field]:not(input):not(select):not(textarea)');
        displayFields.forEach(field => {
            field.textContent = '';
        });

        this.log(`Reset modal: ${modalId}`);
        return true;
    }

    /**
     * Set the action URL for a modal's form
     * Useful for edit modals where the URL includes an ID
     *
     * @param {string} modalId - The ID of the modal
     * @param {string} action - The new action URL
     * @returns {boolean} - True if successful
     *
     * @example
     * window.ModalManager.setFormAction('editPlayerModal', '/api/players/123/update');
     */
    static setFormAction(modalId, action) {
        if (!modalId || !action) {
            console.error('[window.ModalManager] setFormAction() requires modalId and action');
            return false;
        }

        const modalElement = document.getElementById(modalId);
        if (!modalElement) {
            console.warn(`[window.ModalManager] Modal not found: ${modalId}`);
            return false;
        }

        const form = modalElement.querySelector('form');
        if (!form) {
            console.warn(`[window.ModalManager] No form found in modal: ${modalId}`);
            return false;
        }

        form.action = action;
        this.log(`Set form action for ${modalId}: ${action}`);
        return true;
    }

    /**
     * Register a callback for when a modal is shown
     *
     * @param {string} modalId - The ID of the modal
     * @param {Function} callback - Function to call when modal is shown
     */
    static onShow(modalId, callback) {
        const modalElement = document.getElementById(modalId);
        if (!modalElement) {
            console.warn(`[window.ModalManager] Modal not found: ${modalId}`);
            return;
        }

        // Use Flowbite's show event
        modalElement.addEventListener('show.fb.modal', callback);
    }

    /**
     * Register a callback for when a modal is hidden
     *
     * @param {string} modalId - The ID of the modal
     * @param {Function} callback - Function to call when modal is hidden
     */
    static onHide(modalId, callback) {
        const modalElement = document.getElementById(modalId);
        if (!modalElement) {
            console.warn(`[window.ModalManager] Modal not found: ${modalId}`);
            return;
        }

        // Use Flowbite's hide event
        modalElement.addEventListener('hide.fb.modal', callback);
    }

    /**
     * Enable debug logging
     */
    static enableDebug() {
        this.DEBUG = true;
        console.log('[window.ModalManager] Debug mode enabled');
    }

    /**
     * Disable debug logging
     */
    static disableDebug() {
        this.DEBUG = false;
    }

    /**
     * Debug logging helper
     * @private
     * @param {...any} args - Arguments to log
     */
    static log(...args) {
        if (this.DEBUG) {
            console.log('[window.ModalManager]', ...args);
        }
    }
}

/**
 * Deprecated helper function - use window.ModalManager.getInstance() instead
 * @deprecated
 * @param {string} modalId - Modal ID
 * @returns {Modal|null} Modal instance or null
 */
export function safeGetModal(modalId) {
    console.warn('[Deprecated] safeGetModal() is deprecated. Use window.ModalManager.getInstance() instead.');
    return window.ModalManager.getInstance(modalId);
}

/**
 * Deprecated helper function - use window.ModalManager.show() instead
 * @deprecated
 * @param {string} modalId - Modal ID
 * @returns {boolean} Success status
 */
export function safeShowModal(modalId) {
    console.warn('[Deprecated] safeShowModal() is deprecated. Use window.ModalManager.show() instead.');
    return window.ModalManager.show(modalId);
}

/**
 * Register modal event handlers with window.EventDelegation
 * @private
 */
function registerModalManagerEventHandlers() {
    // Safety check - MUST use window.EventDelegation to avoid TDZ errors in bundled code
    // In Vite/Rollup bundles, bare `window.EventDelegation` reference can throw ReferenceError
    // if the variable is hoisted but not yet initialized (Temporal Dead Zone)
    if (typeof window.EventDelegation === 'undefined' || typeof window.EventDelegation.register !== 'function') {
        console.warn('[window.ModalManager] window.EventDelegation not available, handlers not registered');
        return;
    }

    // Prevent double registration
    if (window._modalManagerHandlersRegistered) {
        return;
    }
    window._modalManagerHandlersRegistered = true;

    // Show modal
    window.EventDelegation.register('show-modal', (element, e) => {
        const modalId = element.dataset.modalId;
        if (modalId) {
            const options = window.ModalManager.parseOptionsFromElement(element);
            window.ModalManager.show(modalId, options);
        } else {
            console.error('[window.ModalManager] data-action="show-modal" requires data-modal-id attribute');
        }
    }, { preventDefault: true });

    // Hide modal
    window.EventDelegation.register('hide-modal', (element, e) => {
        const modalId = element.dataset.modalId;
        if (modalId) {
            window.ModalManager.hide(modalId);
        } else {
            // Try to find the closest modal and close it
            const closestModal = element.closest('[data-modal], .modal');
            if (closestModal && closestModal.id) {
                window.ModalManager.hide(closestModal.id);
            }
        }
    }, { preventDefault: true });

    // Close modal (alias for hide) - handles all modal types
    window.EventDelegation.register('close-modal', (element, e) => {
        const modalId = element.dataset.modalId;
        if (modalId) {
            window.ModalManager.hide(modalId);
        } else {
            // Support Bootstrap .modal, custom [data-modal], and .c-modal-modern
            const closestModal = element.closest('[data-modal], .modal, .c-modal-modern');
            if (closestModal && closestModal.id) {
                window.ModalManager.hide(closestModal.id);
            }
        }
    }, { preventDefault: true });

    // Toggle modal
    window.EventDelegation.register('toggle-modal', (element, e) => {
        const modalId = element.dataset.modalId;
        if (modalId) {
            window.ModalManager.toggle(modalId);
        } else {
            console.error('[window.ModalManager] data-action="toggle-modal" requires data-modal-id attribute');
        }
    }, { preventDefault: true });

    // ModalManager event delegation handlers registered
}

// Backward compatibility - keep window.ModalManager for legacy code
// Check if a stub was set up (for early calls before this module loads)
if (window.ModalManager && window.ModalManager._isStub && window.ModalManager._pendingCalls) {
    // Replay any queued calls
    const pendingCalls = window.ModalManager._pendingCalls;
    window.ModalManager = ModalManager;

    // Process queued show() calls after a microtask to ensure init completes
    queueMicrotask(() => {
        pendingCalls.forEach(({ method, args }) => {
            if (typeof ModalManager[method] === 'function') {
                ModalManager[method](...args);
            }
        });
        if (pendingCalls.length > 0) {
            ModalManager.log(`Replayed ${pendingCalls.length} queued modal calls`);
        }
    });
} else {
    window.ModalManager = ModalManager;
}

window.safeGetModal = safeGetModal;
window.safeShowModal = safeShowModal;

// Register with window.InitSystem if available
if (typeof window.InitSystem !== 'undefined') {
    window.InitSystem.register('window.ModalManager', function(context) {
        window.ModalManager.init(context);
    }, {
        priority: 20 // After responsive (10) and admin-base (15), before page-specific components
    });
}

// Fallback
// window.InitSystem handles initialization

// Try to register event handlers immediately (works in Vite bundle)
// MUST use window.EventDelegation to avoid TDZ errors
if (typeof window.EventDelegation !== 'undefined') {
    registerModalManagerEventHandlers();
} else {
    // Fallback: Wait for DOMContentLoaded (for individual script loading)
    document.addEventListener('DOMContentLoaded', registerModalManagerEventHandlers);
}

// CRITICAL: Pre-initialize modals BEFORE Flowbite's auto-init runs
// This prevents "Instance with ID does not exist" warnings from Flowbite
// when it encounters data-modal-hide buttons without prior initialization
// We use 'capture: true' to run before other DOMContentLoaded handlers
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        if (typeof window.Modal !== 'undefined') {
            ModalManager.discoverModals();
        }
    }, { capture: true });
} else {
    // DOM already loaded, initialize immediately
    if (typeof window.Modal !== 'undefined') {
        ModalManager.discoverModals();
    }
}
