/**
 * ============================================================================
 * EVENT DELEGATION CORE
 * ============================================================================
 *
 * Centralized Event Delegation System - Core Module
 *
 * Handles all interactive events for dynamic content across the application.
 * Uses event delegation to ensure event handlers work for elements added after
 * page load (via AJAX, HTMX, innerHTML, appendChild, etc.)
 *
 * @version 2.0.0 (Modular refactor)
 * @author ECS Development Team
 *
 * USAGE:
 *
 * 1. In HTML, use data-action attributes:
 *    <button data-action="delete-match" data-match-id="123">Delete</button>
 *
 * 2. Register handler in JavaScript:
 *    import { EventDelegation } from './event-delegation/core.js';
 *    EventDelegation.register('delete-match', function(element, event) {
 *        const matchId = element.dataset.matchId;
 *        // Handle delete
 *    });
 *
 * ============================================================================
 */

const EventDelegation = {
    // Handler registry - maps action names to handler functions
    handlers: new Map(),

    // Debug mode - set to true for verbose logging
    debug: false,

    // Track duplicates for debugging
    duplicates: new Set(),

    // Statistics for monitoring
    stats: {
        handlersRegistered: 0,
        eventsProcessed: 0,
        errorsEncountered: 0
    },

    /**
     * Register an action handler
     *
     * @param {string} action - Action name (from data-action attribute)
     * @param {Function} handler - Handler function(element, event)
     * @param {Object} options - Optional configuration
     *   @param {boolean} options.preventDefault - Auto preventDefault (default: false)
     *   @param {boolean} options.stopPropagation - Auto stopPropagation (default: false)
     */
    register(action, handler, options = {}) {
        if (typeof handler !== 'function') {
            console.error(`[EventDelegation] Handler for action "${action}" must be a function`);
            return;
        }

        // Duplicate detection - warn if handler already exists
        if (this.handlers.has(action)) {
            console.warn(`[EventDelegation] WARNING: Handler for action "${action}" is being overwritten! This may cause unexpected behavior. Consider using unique action names.`);
            this.duplicates.add(action);
        }

        // Wrap handler with options
        const wrappedHandler = (element, event) => {
            if (options.preventDefault) event.preventDefault();
            if (options.stopPropagation) event.stopPropagation();
            return handler(element, event);
        };

        this.handlers.set(action, wrappedHandler);
        this.stats.handlersRegistered++;

        if (this.debug) {
            console.log(`[EventDelegation] Registered handler: ${action}`);
        }
    },

    /**
     * Unregister an action handler
     */
    unregister(action) {
        if (this.handlers.has(action)) {
            this.handlers.delete(action);
            this.stats.handlersRegistered--;
            if (this.debug) {
                console.log(`[EventDelegation] Unregistered handler: ${action}`);
            }
        }
    },

    /**
     * Check if an action is registered
     */
    isRegistered(action) {
        return this.handlers.has(action);
    },

    /**
     * Get all registered action names
     */
    getRegisteredActions() {
        return Array.from(this.handlers.keys());
    },

    /**
     * Get all actions that were registered multiple times (duplicates)
     */
    getDuplicates() {
        return Array.from(this.duplicates);
    },

    /**
     * Initialize event delegation system
     */
    init() {
        // Click events (most common)
        document.addEventListener('click', this.handleClick.bind(this), false);

        // Change events (for form inputs)
        document.addEventListener('change', this.handleChange.bind(this), false);

        // Input events (for real-time validation/search)
        document.addEventListener('input', this.handleInput.bind(this), false);

        // Submit events (for forms)
        document.addEventListener('submit', this.handleSubmit.bind(this), false);

        // Keydown events (for keyboard shortcuts)
        document.addEventListener('keydown', this.handleKeydown.bind(this), false);

        console.log('[EventDelegation] System initialized');
        console.log(`[EventDelegation] Registered ${this.stats.handlersRegistered} handlers`);
    },

    /**
     * Handle click events
     */
    handleClick(e) {
        const actionElement = e.target.closest('[data-action]');
        if (!actionElement) return;

        const action = actionElement.dataset.action;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;

            if (this.debug) {
                console.log(`[EventDelegation] Handling click action: ${action}`, {
                    element: actionElement,
                    data: actionElement.dataset
                });
            }

            try {
                handler(actionElement, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
                this.handleError(action, error, actionElement);
            }
        } else {
            if (this.debug) {
                console.warn(`[EventDelegation] No handler registered for action: ${action}`);
            }
        }
    },

    /**
     * Handle change events
     */
    handleChange(e) {
        const target = e.target.closest('[data-on-change]');
        if (!target) return;

        const action = target.dataset.onChange;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;
            try {
                handler(target, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
            }
        }
    },

    /**
     * Handle input events
     */
    handleInput(e) {
        const target = e.target.closest('[data-on-input]');
        if (!target) return;

        const action = target.dataset.onInput;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;
            try {
                handler(target, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
            }
        }
    },

    /**
     * Handle submit events
     */
    handleSubmit(e) {
        const form = e.target.closest('[data-on-submit]');
        if (!form) return;

        const action = form.dataset.onSubmit;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;
            try {
                handler(form, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
            }
        }
    },

    /**
     * Handle keydown events
     */
    handleKeydown(e) {
        const target = e.target.closest('[data-on-keydown]');
        if (!target) return;

        const action = target.dataset.onKeydown;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;
            try {
                handler(target, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
            }
        }
    },

    /**
     * Handle errors in action handlers
     */
    handleError(action, error, element) {
        console.error(`[EventDelegation] Action "${action}" failed:`, error);
        if (typeof showNotification === 'function') {
            showNotification('Error', `Action failed: ${action}`, 'error');
        }
    },

    enableDebug() {
        this.debug = true;
        console.log('[EventDelegation] Debug mode enabled');
    },

    disableDebug() {
        this.debug = false;
        console.log('[EventDelegation] Debug mode disabled');
    },

    getStats() {
        return {
            ...this.stats,
            registeredActions: this.handlers.size
        };
    },

    resetStats() {
        this.stats.eventsProcessed = 0;
        this.stats.errorsEncountered = 0;
    }
};

// Export to window for global access and backward compatibility
window.EventDelegation = EventDelegation;

// Initialize the system when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => EventDelegation.init());
} else {
    EventDelegation.init();
}
