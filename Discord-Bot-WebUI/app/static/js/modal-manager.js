'use strict';

/**
 * Modal Manager - Centralized Bootstrap Modal Management
 *
 * Best Practice 2025: Single source of truth for all modal operations
 *
 * USAGE:
 * ------
 * 1. Declarative (no JavaScript needed):
 *    <button data-bs-toggle="modal" data-bs-target="#myModal">Show Modal</button>
 *
 * 2. Programmatic (simple one-liner):
 *    window.ModalManager.show('myModal');
 *
 * 3. With options:
 *    window.ModalManager.show('myModal', { backdrop: 'static', keyboard: false });
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
 * - Falls back to .modal class for backward compatibility
 * - Uses data-action="show-modal|hide-modal|toggle-modal" for triggers
 *
 * @author ECS Discord Bot Team
 * @since 2025-12-17
 */

/**
 * Centralized Bootstrap Modal Manager
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
    static DEBUG = true;

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

        if (typeof window.bootstrap === 'undefined' || typeof window.bootstrap.Modal === 'undefined') {
            console.error('[window.ModalManager] Bootstrap not loaded. Cannot initialize modals.');
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
     * Uses data-modal attribute first, falls back to .modal class
     * @private
     * @param {Element} context - Context element to search within
     */
    static discoverModals(context = document) {
        // Query by data attribute first, then fall back to class
        const modalElements = context.querySelectorAll('[data-modal], .modal');

        modalElements.forEach(modalEl => {
            if (modalEl.id) {
                // Skip if already cached
                if (this.modalInstances.has(modalEl.id)) {
                    return;
                }

                try {
                    // Check if modal already has a Bootstrap instance
                    let instance = window.bootstrap.Modal.getInstance(modalEl);

                    if (!instance) {
                        // Create new instance if it doesn't exist
                        instance = new window.bootstrap.Modal(modalEl);
                    }

                    this.modalInstances.set(modalEl.id, instance);
                    this.log(`Cached modal: ${modalEl.id}`);
                } catch (error) {
                    console.error(`[window.ModalManager] Failed to initialize modal ${modalEl.id}:`, error);
                }
            } else {
                console.warn('[window.ModalManager] Found modal without ID. Modals should have unique IDs:', modalEl);
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
     * @param {Object} options - Bootstrap modal options (backdrop, keyboard, focus)
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
                console.error(`[window.ModalManager] Modal element not found: ${modalId}`);
                return false;
            }

            try {
                // Check if Bootstrap already initialized it
                modal = window.bootstrap.Modal.getInstance(modalElement);

                if (!modal) {
                    // Create new instance with options
                    modal = new window.bootstrap.Modal(modalElement, options);
                }

                // Cache for future use
                this.modalInstances.set(modalId, modal);
                this.log(`Created and cached new modal: ${modalId}`);
            } catch (error) {
                console.error(`[window.ModalManager] Failed to initialize modal ${modalId}:`, error);
                return false;
            }
        }

        // Show the modal
        try {
            modal.show();
            return true;
        } catch (error) {
            console.error(`[window.ModalManager] Failed to show modal ${modalId}:`, error);
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

            // Try to find it in DOM and get Bootstrap instance
            const modalElement = document.getElementById(modalId);
            if (modalElement) {
                const instance = window.bootstrap.Modal.getInstance(modalElement);
                if (instance) {
                    try {
                        instance.hide();
                        return true;
                    } catch (error) {
                        console.error(`[window.ModalManager] Failed to hide modal ${modalId}:`, error);
                        return false;
                    }
                }
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
     * @returns {window.bootstrap.Modal|null} - The Bootstrap modal instance or null
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
 * @returns {window.bootstrap.Modal|null} Modal instance or null
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

    console.log('[window.ModalManager] Event delegation handlers registered');
}

// Backward compatibility - keep window.ModalManager for legacy code
window.ModalManager = ModalManager;
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
