'use strict';

/**
 * Event Delegation Core
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
 */

/**
 * Centralized event delegation system
 */
export const EventDelegation = {
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
     * @param {string} action - Action name to unregister
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
     * @param {string} action - Action name
     * @returns {boolean} True if registered
     */
    isRegistered(action) {
        return this.handlers.has(action);
    },

    /**
     * Get all registered action names
     * @returns {Array<string>} Array of action names
     */
    getRegisteredActions() {
        return Array.from(this.handlers.keys());
    },

    /**
     * Get all actions that were registered multiple times (duplicates)
     * @returns {Array<string>} Array of duplicate action names
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
     * @param {Event} e - Click event
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
     * @param {Event} e - Change event
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
     * @param {Event} e - Input event
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
     * @param {Event} e - Submit event
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
     * @param {Event} e - Keydown event
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
     * @param {string} action - Action name
     * @param {Error} error - Error object
     * @param {Element} element - Element that triggered the action
     */
    handleError(action, error, element) {
        console.error(`[EventDelegation] Action "${action}" failed:`, error);
        if (typeof window.showNotification === 'function') {
            window.showNotification('Error', `Action failed: ${action}`, 'error');
        }
    },

    /**
     * Enable debug mode
     */
    enableDebug() {
        this.debug = true;
        console.log('[EventDelegation] Debug mode enabled');
    },

    /**
     * Disable debug mode
     */
    disableDebug() {
        this.debug = false;
        console.log('[EventDelegation] Debug mode disabled');
    },

    /**
     * Get statistics
     * @returns {Object} Statistics object
     */
    getStats() {
        return {
            ...this.stats,
            registeredActions: this.handlers.size
        };
    },

    /**
     * Reset statistics
     */
    resetStats() {
        this.stats.eventsProcessed = 0;
        this.stats.errorsEncountered = 0;
    }
};

// Backward compatibility - keep window.EventDelegation for legacy code
window.EventDelegation = EventDelegation;

// NOTE: Initialization is now controlled by main-entry.js
// DO NOT auto-init here - handlers must register first
