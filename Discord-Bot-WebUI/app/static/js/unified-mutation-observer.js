/**
 * ============================================================================
 * UNIFIED MUTATION OBSERVER MANAGER
 * ============================================================================
 *
 * ROOT CAUSE FIX: Consolidates ALL body-level MutationObservers into ONE
 *
 * PROBLEM:
 * Multiple MutationObservers all watching document.body with childList+subtree
 * causes cascade effects where each observer's DOM changes trigger all others,
 * leading to 89%+ CPU usage in MutationCallback.
 *
 * SOLUTION:
 * Single MutationObserver with:
 * - Debounced mutation processing (prevents cascade)
 * - Handler registry (each subsystem registers interest)
 * - Batch processing (groups mutations before callbacks)
 * - Skip flag (prevents re-triggering during callback execution)
 *
 * USAGE:
 * UnifiedMutationObserver.register('my-handler', {
 *   onAddedNodes: (nodes) => { ... },
 *   onRemovedNodes: (nodes) => { ... },
 *   filter: (node) => node.hasAttribute('data-my-attr')
 * });
 *
 * ============================================================================
 */
// ES Module
'use strict';

// Singleton state
let _initialized = false;
let _observer = null;
let _isProcessing = false;
let _debounceTimer = null;
let _pendingMutations = [];

const DEBOUNCE_MS = 16; // ~1 frame at 60fps

// Handler registry
const _handlers = new Map();

const UnifiedMutationObserver = {
    /**
     * Register a handler for DOM mutations
     *
     * @param {string} id - Unique identifier for this handler
     * @param {Object} config - Handler configuration
     * @param {Function} [config.onAddedNodes] - Called with array of added nodes
     * @param {Function} [config.onRemovedNodes] - Called with array of removed nodes
     * @param {Function} [config.filter] - Filter function, receives node, returns boolean
     * @param {number} [config.priority] - Lower numbers run first (default: 100)
     */
    register: function(id, config) {
        if (_handlers.has(id)) {
            console.warn(`[UnifiedMutationObserver] Handler "${id}" already registered, replacing`);
        }

        _handlers.set(id, {
            onAddedNodes: config.onAddedNodes || null,
            onRemovedNodes: config.onRemovedNodes || null,
            filter: config.filter || (() => true),
            priority: config.priority || 100
        });

        // Ensure observer is running
        this.init();
    },

    /**
     * Unregister a handler
     * @param {string} id - Handler identifier
     */
    unregister: function(id) {
        _handlers.delete(id);
    },

    /**
     * Temporarily skip mutation processing
     * Use when making DOM changes that shouldn't trigger handlers
     *
     * @param {Function} callback - Function to execute while skipping
     * @returns {*} Return value of callback
     */
    skipDuring: function(callback) {
        const wasProcessing = _isProcessing;
        _isProcessing = true;
        try {
            return callback();
        } finally {
            _isProcessing = wasProcessing;
        }
    },

    /**
     * Initialize the unified observer
     * Called automatically when first handler is registered
     */
    init: function() {
        if (_initialized) return;
        _initialized = true;

        const self = this;
        _observer = new MutationObserver((mutations) => {
            // Skip if we're already processing (prevents cascade)
            if (_isProcessing) return;

            // Accumulate mutations for debounced processing
            _pendingMutations.push(...mutations);

            // Debounce processing
            if (_debounceTimer) {
                clearTimeout(_debounceTimer);
            }

            _debounceTimer = setTimeout(() => {
                self._processMutations();
            }, DEBOUNCE_MS);
        });

        // Start observing with minimal config that covers all use cases
        _observer.observe(document.body, {
            childList: true,
            subtree: true
        });

        // UnifiedMutationObserver initialized
    },

    /**
     * Process accumulated mutations
     * @private
     */
    _processMutations: function() {
        if (_pendingMutations.length === 0) return;

        _isProcessing = true;

        try {
            // Collect all added and removed nodes
            const addedNodes = [];
            const removedNodes = [];

            _pendingMutations.forEach(mutation => {
                mutation.addedNodes.forEach(node => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        addedNodes.push(node);
                    }
                });
                mutation.removedNodes.forEach(node => {
                    if (node.nodeType === Node.ELEMENT_NODE) {
                        removedNodes.push(node);
                    }
                });
            });

            // Clear pending mutations
            _pendingMutations = [];

            // Nothing to process
            if (addedNodes.length === 0 && removedNodes.length === 0) {
                return;
            }

            // Sort handlers by priority
            const sortedHandlers = Array.from(_handlers.entries())
                .sort((a, b) => a[1].priority - b[1].priority);

            // Process each handler
            sortedHandlers.forEach(([id, handler]) => {
                try {
                    // Process added nodes
                    if (handler.onAddedNodes && addedNodes.length > 0) {
                        const filtered = addedNodes.filter(handler.filter);
                        if (filtered.length > 0) {
                            handler.onAddedNodes(filtered);
                        }
                    }

                    // Process removed nodes
                    if (handler.onRemovedNodes && removedNodes.length > 0) {
                        const filtered = removedNodes.filter(handler.filter);
                        if (filtered.length > 0) {
                            handler.onRemovedNodes(filtered);
                        }
                    }
                } catch (e) {
                    console.error(`[UnifiedMutationObserver] Error in handler "${id}":`, e);
                }
            });

        } finally {
            _isProcessing = false;
        }
    },

    /**
     * Disconnect the observer (for cleanup/testing)
     */
    disconnect: function() {
        if (_observer) {
            _observer.disconnect();
            _observer = null;
        }
        if (_debounceTimer) {
            clearTimeout(_debounceTimer);
            _debounceTimer = null;
        }
        _handlers.clear();
        _pendingMutations = [];
        _initialized = false;
        _isProcessing = false;
    },

    /**
     * Get debugging info
     */
    getDebugInfo: function() {
        return {
            initialized: _initialized,
            isProcessing: _isProcessing,
            pendingMutations: _pendingMutations.length,
            handlers: Array.from(_handlers.keys())
        };
    }
};

// Expose globally
window.UnifiedMutationObserver = UnifiedMutationObserver;
