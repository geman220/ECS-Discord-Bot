/**
 * Modal Manager - Centralized Bootstrap Modal Management
 * ========================================================
 *
 * Best Practice 2025: Single source of truth for all modal operations
 *
 * USAGE:
 * ------
 * 1. Declarative (no JavaScript needed):
 *    <button data-bs-toggle="modal" data-bs-target="#myModal">Show Modal</button>
 *
 * 2. Programmatic (simple one-liner):
 *    ModalManager.show('myModal');
 *
 * 3. With options:
 *    ModalManager.show('myModal', { backdrop: 'static', keyboard: false });
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
 * - InitSystem registration (priority 20)
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

class ModalManager {
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
     * Initialize the Modal Manager
     * - Auto-discovers all modals on the page
     * - Sets up event delegation for data-action triggers
     * - Called automatically via InitSystem or DOMContentLoaded
     *
     * @param {Element} context - Optional context element (defaults to document)
     */
    static init(context = document) {
        // For full document init, only run once
        if (context === document && this._initialized) {
            return;
        }

        if (typeof bootstrap === 'undefined' || typeof bootstrap.Modal === 'undefined') {
            console.error('[ModalManager] Bootstrap not loaded. Cannot initialize modals.');
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
                    let instance = bootstrap.Modal.getInstance(modalEl);

                    if (!instance) {
                        // Create new instance if it doesn't exist
                        instance = new bootstrap.Modal(modalEl);
                    }

                    this.modalInstances.set(modalEl.id, instance);
                    this.log(`Cached modal: ${modalEl.id}`);
                } catch (error) {
                    console.error(`[ModalManager] Failed to initialize modal ${modalEl.id}:`, error);
                }
            } else {
                console.warn('[ModalManager] Found modal without ID. Modals should have unique IDs:', modalEl);
            }
        });
    }

    /**
     * Set up event delegation for data-action triggers
     * Supports: show-modal, hide-modal, toggle-modal, close-modal
     * Uses EventDelegation system if available
     * @private
     */
    static setupEventDelegation() {
        // Use EventDelegation if available
        if (window.EventDelegation && typeof window.EventDelegation.register === 'function') {
            // Show modal
            window.EventDelegation.register('show-modal', (element, e) => {
                const modalId = element.dataset.modalId;
                if (modalId) {
                    const options = this.parseOptionsFromElement(element);
                    this.show(modalId, options);
                } else {
                    console.error('[ModalManager] data-action="show-modal" requires data-modal-id attribute');
                }
            }, { preventDefault: true });

            // Hide modal
            window.EventDelegation.register('hide-modal', (element, e) => {
                const modalId = element.dataset.modalId;
                if (modalId) {
                    this.hide(modalId);
                } else {
                    // Try to find the closest modal and close it
                    const closestModal = element.closest('[data-modal], .modal');
                    if (closestModal && closestModal.id) {
                        this.hide(closestModal.id);
                    }
                }
            }, { preventDefault: true });

            // Close modal (alias for hide) - handles all modal types
            window.EventDelegation.register('close-modal', (element, e) => {
                const modalId = element.dataset.modalId;
                if (modalId) {
                    this.hide(modalId);
                } else {
                    // Support Bootstrap .modal, custom [data-modal], and .c-modal-modern
                    const closestModal = element.closest('[data-modal], .modal, .c-modal-modern');
                    if (closestModal && closestModal.id) {
                        this.hide(closestModal.id);
                    }
                }
            }, { preventDefault: true });

            // Toggle modal
            window.EventDelegation.register('toggle-modal', (element, e) => {
                const modalId = element.dataset.modalId;
                if (modalId) {
                    this.toggle(modalId);
                } else {
                    console.error('[ModalManager] data-action="toggle-modal" requires data-modal-id attribute');
                }
            }, { preventDefault: true });

            this.log('Event delegation registered via EventDelegation system');
        } else {
            // Fallback: Use standard event delegation
            document.addEventListener('click', (e) => {
                const actionElement = e.target.closest('[data-action]');
                if (!actionElement) return;

                const action = actionElement.dataset.action;
                const modalId = actionElement.dataset.modalId;

                switch (action) {
                    case 'show-modal':
                        if (modalId) {
                            e.preventDefault();
                            const options = this.parseOptionsFromElement(actionElement);
                            this.show(modalId, options);
                        } else {
                            console.error('[ModalManager] data-action="show-modal" requires data-modal-id attribute');
                        }
                        break;

                    case 'hide-modal':
                    case 'close-modal':
                        e.preventDefault();
                        if (modalId) {
                            this.hide(modalId);
                        } else {
                            // Try to find the closest modal and close it
                            const closestModal = actionElement.closest('[data-modal], .modal');
                            if (closestModal && closestModal.id) {
                                this.hide(closestModal.id);
                            }
                        }
                        break;

                    case 'toggle-modal':
                        if (modalId) {
                            e.preventDefault();
                            this.toggle(modalId);
                        } else {
                            console.error('[ModalManager] data-action="toggle-modal" requires data-modal-id attribute');
                        }
                        break;
                }
            });

            this.log('Event delegation registered via fallback click handler');
        }
    }

    /**
     * Parse modal options from data attributes
     * @private
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
     * @private
     */
    static setupMutationObserver() {
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.removedNodes.forEach((node) => {
                    if (node.nodeType === 1) {
                        // Check if removed node is a modal
                        const isModal = (node.classList?.contains('modal') || node.hasAttribute?.('data-modal'));
                        if (isModal && node.id) {
                            this.cleanup(node.id);
                        }
                    }
                });
            });
        });

        observer.observe(document.body, { childList: true, subtree: true });
    }

    /**
     * Show a modal by ID
     * @param {string} modalId - The ID of the modal to show (without # prefix)
     * @param {Object} options - Bootstrap modal options (backdrop, keyboard, focus)
     * @returns {boolean} - True if modal was shown successfully, false otherwise
     */
    static show(modalId, options = null) {
        if (!modalId) {
            console.error('[ModalManager] show() requires a modal ID');
            return false;
        }

        this.log(`Showing modal: ${modalId}`);

        // Get or create modal instance
        let modal = this.modalInstances.get(modalId);

        if (!modal) {
            // Modal not in cache - try to find and initialize it
            const modalElement = document.getElementById(modalId);

            if (!modalElement) {
                console.error(`[ModalManager] Modal element not found: ${modalId}`);
                return false;
            }

            try {
                // Check if Bootstrap already initialized it
                modal = bootstrap.Modal.getInstance(modalElement);

                if (!modal) {
                    // Create new instance with options
                    modal = new bootstrap.Modal(modalElement, options);
                }

                // Cache for future use
                this.modalInstances.set(modalId, modal);
                this.log(`Created and cached new modal: ${modalId}`);
            } catch (error) {
                console.error(`[ModalManager] Failed to initialize modal ${modalId}:`, error);
                return false;
            }
        }

        // Show the modal
        try {
            modal.show();
            return true;
        } catch (error) {
            console.error(`[ModalManager] Failed to show modal ${modalId}:`, error);
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
            console.error('[ModalManager] hide() requires a modal ID');
            return false;
        }

        this.log(`Hiding modal: ${modalId}`);

        const modal = this.modalInstances.get(modalId);

        if (!modal) {
            console.warn(`[ModalManager] Modal not found in cache: ${modalId}`);

            // Try to find it in DOM and get Bootstrap instance
            const modalElement = document.getElementById(modalId);
            if (modalElement) {
                const instance = bootstrap.Modal.getInstance(modalElement);
                if (instance) {
                    try {
                        instance.hide();
                        return true;
                    } catch (error) {
                        console.error(`[ModalManager] Failed to hide modal ${modalId}:`, error);
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
            console.error(`[ModalManager] Failed to hide modal ${modalId}:`, error);
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
            console.error('[ModalManager] toggle() requires a modal ID');
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
            console.error(`[ModalManager] Failed to toggle modal ${modalId}:`, error);
            return false;
        }
    }

    /**
     * Get a modal instance by ID
     * @param {string} modalId - The ID of the modal
     * @returns {bootstrap.Modal|null} - The Bootstrap modal instance or null
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
                console.warn(`[ModalManager] Error disposing modal ${modalId}:`, error);
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
                console.warn(`[ModalManager] Error disposing modal ${modalId}:`, error);
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
        console.log('[ModalManager] Debug mode enabled');
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
     */
    static log(...args) {
        if (this.DEBUG) {
            console.log('[ModalManager]', ...args);
        }
    }
}

// Register with InitSystem if available
if (typeof window.InitSystem !== 'undefined') {
    window.InitSystem.register('ModalManager', function(context) {
        ModalManager.init(context);
    }, {
        priority: 20 // After responsive (10) and admin-base (15), before page-specific components
    });
} else {
    // Fallback to DOMContentLoaded
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => ModalManager.init());
    } else {
        ModalManager.init();
    }
}

// Make ModalManager globally available
window.ModalManager = ModalManager;

// Backward compatibility: Maintain the old helper functions
window.safeGetModal = function(modalId) {
    console.warn('[Deprecated] safeGetModal() is deprecated. Use ModalManager.getInstance() instead.');
    return ModalManager.getInstance(modalId);
};

window.safeShowModal = function(modalId) {
    console.warn('[Deprecated] safeShowModal() is deprecated. Use ModalManager.show() instead.');
    return ModalManager.show(modalId);
};
