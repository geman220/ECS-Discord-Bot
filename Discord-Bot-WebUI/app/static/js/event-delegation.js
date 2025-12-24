/**
 * Centralized Event Delegation System
 *
 * Handles all interactive events for dynamic content across the application.
 * Uses event delegation to ensure event handlers work for elements added after page load
 * (via AJAX, HTMX, innerHTML, appendChild, etc.)
 *
 * @version 1.0.0
 * @author ECS Development Team
 * @date 2025-12-16
 *
 * USAGE:
 *
 * 1. In HTML, use data-action attributes:
 *    <button data-action="delete-match" data-match-id="123">Delete</button>
 *
 * 2. Register handler in JavaScript:
 *    EventDelegation.register('delete-match', function(element, event) {
 *        const matchId = element.dataset.matchId;
 *        // Handle delete
 *    });
 *
 * 3. Initialize (already done in this file):
 *    EventDelegation.init();
 */

const EventDelegation = {
    // Handler registry - maps action names to handler functions
    handlers: new Map(),

    // Debug mode - set to true for verbose logging
    debug: false,

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
     *
     * @example
     * EventDelegation.register('delete-item', function(element, e) {
     *     const itemId = element.dataset.itemId;
     *     deleteItem(itemId);
     * });
     */
    register(action, handler, options = {}) {
        if (typeof handler !== 'function') {
            console.error(`[EventDelegation] Handler for action "${action}" must be a function`);
            return;
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
     *
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
     *
     * @param {string} action - Action name to check
     * @returns {boolean}
     */
    isRegistered(action) {
        return this.handlers.has(action);
    },

    /**
     * Get all registered action names
     *
     * @returns {string[]} Array of action names
     */
    getRegisteredActions() {
        return Array.from(this.handlers.keys());
    },

    /**
     * Initialize event delegation system
     * Sets up global event listeners on document
     */
    init() {
        // Click events (most common)
        // NOTE: Using bubble phase (false) to allow other handlers to also process events
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
     * Delegates to registered action handlers based on data-action attribute
     *
     * @param {Event} e - Click event
     */
    handleClick(e) {
        // Find element with data-action (check target and parents)
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
     * Handle change events (for form inputs with data-on-change)
     *
     * @param {Event} e - Change event
     */
    handleChange(e) {
        const target = e.target.closest('[data-on-change]');
        if (!target) return;

        const action = target.dataset.onChange;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;

            if (this.debug) {
                console.log(`[EventDelegation] Handling change action: ${action}`, {
                    element: target,
                    value: target.value
                });
            }

            try {
                handler(target, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
                this.handleError(action, error, target);
            }
        }
    },

    /**
     * Handle input events (for real-time validation/search with data-on-input)
     *
     * @param {Event} e - Input event
     */
    handleInput(e) {
        const target = e.target.closest('[data-on-input]');
        if (!target) return;

        const action = target.dataset.onInput;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;

            if (this.debug) {
                console.log(`[EventDelegation] Handling input action: ${action}`, {
                    element: target,
                    value: target.value
                });
            }

            try {
                handler(target, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
                this.handleError(action, error, target);
            }
        }
    },

    /**
     * Handle submit events (for forms with data-on-submit)
     *
     * @param {Event} e - Submit event
     */
    handleSubmit(e) {
        const form = e.target.closest('[data-on-submit]');
        if (!form) return;

        const action = form.dataset.onSubmit;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;

            if (this.debug) {
                console.log(`[EventDelegation] Handling submit action: ${action}`, {
                    form: form,
                    data: new FormData(form)
                });
            }

            try {
                handler(form, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
                this.handleError(action, error, form);
            }
        }
    },

    /**
     * Handle keydown events (for keyboard shortcuts with data-on-keydown)
     *
     * @param {Event} e - Keydown event
     */
    handleKeydown(e) {
        const target = e.target.closest('[data-on-keydown]');
        if (!target) return;

        const action = target.dataset.onKeydown;
        const handler = this.handlers.get(action);

        if (handler) {
            this.stats.eventsProcessed++;

            if (this.debug) {
                console.log(`[EventDelegation] Handling keydown action: ${action}`, {
                    element: target,
                    key: e.key,
                    code: e.code
                });
            }

            try {
                handler(target, e);
            } catch (error) {
                this.stats.errorsEncountered++;
                console.error(`[EventDelegation] Error in handler "${action}":`, error);
                this.handleError(action, error, target);
            }
        }
    },

    /**
     * Handle errors in action handlers
     * Can be overridden to customize error handling
     *
     * @param {string} action - Action name that errored
     * @param {Error} error - The error object
     * @param {HTMLElement} element - The element that triggered the action
     */
    handleError(action, error, element) {
        // Default error handling - can be customized
        console.error(`[EventDelegation] Action "${action}" failed:`, error);

        // Optionally show user-facing error message
        if (typeof showNotification === 'function') {
            showNotification('Error', `Action failed: ${action}`, 'error');
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
     * Get system statistics
     *
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

// Initialize the system when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
        EventDelegation.init();
    });
} else {
    // DOM already loaded
    EventDelegation.init();
}

// ============================================================================
// MATCH MANAGEMENT ACTIONS
// ============================================================================

/**
 * Show Task Info Action
 * Displays detailed information about a scheduled task
 */
EventDelegation.register('show-task-info', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;
    const taskType = element.dataset.taskType;
    const taskDataStr = element.dataset.taskData;

    if (!taskId || !taskType) {
        console.error('[show-task-info] Missing required data attributes');
        return;
    }

    let taskData;
    try {
        taskData = taskDataStr ? JSON.parse(taskDataStr) : {};
    } catch (err) {
        console.error('[show-task-info] Failed to parse task data:', err);
        taskData = {};
    }

    if (typeof showTaskInfo === 'function') {
        showTaskInfo(taskId, taskType, taskData);
    } else {
        console.error('[show-task-info] Function not found');
    }
});

/**
 * Revoke Task Action
 * Cancels a scheduled task (thread creation, reporting, etc.)
 */
EventDelegation.register('revoke-task', function(element, e) {
    e.preventDefault();

    const taskId = element.dataset.taskId;
    const matchId = element.dataset.matchId;
    const taskType = element.dataset.taskType;

    if (!taskId || !matchId || !taskType) {
        console.error('[revoke-task] Missing required data attributes');
        return;
    }

    if (typeof revokeTask === 'function') {
        revokeTask(taskId, matchId, taskType);
    } else {
        console.error('[revoke-task] Function not found');
    }
});

/**
 * Reschedule Task Action
 * Re-schedules a task to run at a different time
 */
EventDelegation.register('reschedule-task', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const taskType = element.dataset.taskType;

    if (!matchId || !taskType) {
        console.error('[reschedule-task] Missing required data attributes');
        return;
    }

    if (typeof rescheduleTask === 'function') {
        rescheduleTask(matchId, taskType);
    } else {
        console.error('[reschedule-task] Function not found');
    }
});

/**
 * Refresh Tasks Action
 * Manually refreshes task status for all matches
 */
EventDelegation.register('refresh-tasks', function(element, e) {
    e.preventDefault();

    if (typeof loadAllTaskDetails === 'function') {
        loadAllTaskDetails();
    } else if (typeof refreshStatuses === 'function') {
        refreshStatuses();
    } else {
        console.error('[refresh-tasks] No refresh function found');
    }
});

/**
 * Toggle Historical Matches Action
 * Shows/hides historical matches section
 */
EventDelegation.register('toggle-historical', function(element, e) {
    e.preventDefault();

    const targetId = element.dataset.target;
    if (!targetId) {
        console.error('[toggle-historical] Missing target ID');
        return;
    }

    const target = document.querySelector(targetId);
    if (target && window.bootstrap) {
        const collapse = bootstrap.Collapse.getOrCreateInstance(target);
        collapse.toggle();
    }
});

/**
 * Schedule Match Action
 * Schedules all tasks for a match (thread + reporting)
 */
EventDelegation.register('schedule-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[schedule-match] Missing match ID');
        return;
    }

    if (typeof scheduleMatch === 'function') {
        scheduleMatch(matchId);
    } else {
        console.error('[schedule-match] Function not found');
    }
});

/**
 * Verify Match Action
 * Opens match verification modal/page
 */
EventDelegation.register('verify-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[verify-match] Missing match ID');
        return;
    }

    // Navigate to verification page or open modal
    if (typeof verifyMatch === 'function') {
        verifyMatch(matchId);
    } else {
        // Fallback: navigate to verification page
        const verifyUrl = element.dataset.verifyUrl || `/admin/match_verification/${matchId}`;
        window.location.href = verifyUrl;
    }
});

/**
 * Edit Match Action
 * Opens match editing modal/page
 */
EventDelegation.register('edit-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[edit-match] Missing match ID');
        return;
    }

    if (typeof editMatch === 'function') {
        editMatch(matchId);
    } else {
        console.error('[edit-match] Function not found');
    }
});

// ============================================================================
// DRAFT SYSTEM ACTIONS
// ============================================================================

/**
 * Draft Player Action
 * Shows modal to select team and draft player
 */
EventDelegation.register('draft-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;

    if (!playerId || !playerName) {
        console.error('[draft-player] Missing required data attributes');
        return;
    }

    // Call global function
    if (typeof confirmDraftPlayer === 'function') {
        confirmDraftPlayer(playerId, playerName);
    } else if (window.draftSystemInstance && typeof window.draftSystemInstance.showDraftModal === 'function') {
        window.draftSystemInstance.showDraftModal(playerId, playerName);
    } else {
        console.error('[draft-player] No draft function available');
    }
});

/**
 * Remove Player Action
 * Removes player from team and returns to available pool
 */
EventDelegation.register('remove-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const teamId = element.dataset.teamId;
    const playerName = element.dataset.playerName;
    const teamName = element.dataset.teamName;

    if (!playerId || !teamId) {
        console.error('[remove-player] Missing required data attributes');
        return;
    }

    // Call global function
    if (typeof confirmRemovePlayer === 'function') {
        confirmRemovePlayer(playerId, teamId, playerName, teamName);
    } else {
        console.error('[remove-player] Function not found');
    }
});

/**
 * View Player Profile Action
 * Opens modal with player details
 */
EventDelegation.register('view-player-profile', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[view-player-profile] Missing player ID');
        return;
    }

    // Check for instance method first, then global
    if (window.draftSystemInstance && typeof window.draftSystemInstance.openPlayerModal === 'function') {
        window.draftSystemInstance.openPlayerModal(playerId);
    } else if (typeof openPlayerModal === 'function') {
        openPlayerModal(playerId);
    } else {
        console.error('[view-player-profile] No modal function available');
    }
});

/**
 * Search Players Action (triggered by input event)
 * Filters available players by name
 */
EventDelegation.register('search-players', function(element, e) {
    const searchTerm = element.value.toLowerCase().trim();

    if (window.draftSystemInstance && typeof window.draftSystemInstance.handleSearch === 'function') {
        window.draftSystemInstance.handleSearch(e);
    } else {
        // Fallback: basic search implementation
        const playerCards = document.querySelectorAll('[data-component="player-card"]');
        playerCards.forEach(card => {
            const playerName = (card.dataset.playerName || '').toLowerCase();
            const shouldShow = !searchTerm || playerName.includes(searchTerm);
            card.closest('[data-component="player-column"]')?.classList.toggle('d-none', !shouldShow);
        });
    }
});

/**
 * Filter Players by Position (triggered by change event)
 */
EventDelegation.register('filter-position', function(element, e) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handleFilter === 'function') {
        window.draftSystemInstance.handleFilter(e);
    } else {
        const position = element.value.toLowerCase();
        const playerCards = document.querySelectorAll('[data-component="player-card"]');
        playerCards.forEach(card => {
            const playerPosition = (card.dataset.position || '').toLowerCase();
            const shouldShow = !position || playerPosition === position;
            card.closest('[data-component="player-column"]')?.classList.toggle('d-none', !shouldShow);
        });
    }
});

/**
 * Sort Players (triggered by change event)
 */
EventDelegation.register('sort-players', function(element, e) {
    if (window.draftSystemInstance && typeof window.draftSystemInstance.handleSort === 'function') {
        window.draftSystemInstance.handleSort(e);
    } else {
        console.warn('[sort-players] Sort function not available');
    }
});

// ============================================================================
// MATCH REPORTING ACTIONS
// ============================================================================

/**
 * Edit Match Report Action
 * Opens modal to edit/create match report
 */
EventDelegation.register('edit-match-report', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (!matchId) {
        console.error('[edit-match-report] Missing match ID');
        return;
    }

    // Call the global function that handles the edit button click
    if (typeof handleEditButtonClick === 'function') {
        handleEditButtonClick(matchId);
    } else {
        console.error('[edit-match-report] handleEditButtonClick function not found');
    }
});

/**
 * Add Goal Action
 * Adds goal scorer to match report
 */
EventDelegation.register('add-goal', function(element, e) {
    e.preventDefault();

    // Extract matchId from onclick attribute or data attribute
    let matchId = element.dataset.matchId;
    if (!matchId) {
        const onclickAttr = element.getAttribute('onclick');
        if (onclickAttr) {
            const match = onclickAttr.match(/'([^']+)'/);
            if (match) matchId = match[1];
        }
    }

    if (!matchId) {
        console.error('[add-goal] Missing match ID');
        return;
    }

    const containerId = `goalScorersContainer-${matchId}`;

    if (typeof window.addEvent === 'function') {
        window.addEvent(matchId, containerId);
    } else {
        console.error('[add-goal] addEvent function not found');
    }
});

/**
 * Add Assist Action
 * Adds assist provider to match report
 */
EventDelegation.register('add-assist', function(element, e) {
    e.preventDefault();

    // Extract matchId from onclick attribute or data attribute
    let matchId = element.dataset.matchId;
    if (!matchId) {
        const onclickAttr = element.getAttribute('onclick');
        if (onclickAttr) {
            const match = onclickAttr.match(/'([^']+)'/);
            if (match) matchId = match[1];
        }
    }

    if (!matchId) {
        console.error('[add-assist] Missing match ID');
        return;
    }

    const containerId = `assistProvidersContainer-${matchId}`;

    if (typeof window.addEvent === 'function') {
        window.addEvent(matchId, containerId);
    } else {
        console.error('[add-assist] addEvent function not found');
    }
});

/**
 * Add Yellow Card Action
 * Adds yellow card to match report
 */
EventDelegation.register('add-yellow-card', function(element, e) {
    e.preventDefault();

    // Extract matchId from onclick attribute or data attribute
    let matchId = element.dataset.matchId;
    if (!matchId) {
        const onclickAttr = element.getAttribute('onclick');
        if (onclickAttr) {
            const match = onclickAttr.match(/'([^']+)'/);
            if (match) matchId = match[1];
        }
    }

    if (!matchId) {
        console.error('[add-yellow-card] Missing match ID');
        return;
    }

    const containerId = `yellowCardsContainer-${matchId}`;

    if (typeof window.addEvent === 'function') {
        window.addEvent(matchId, containerId);
    } else {
        console.error('[add-yellow-card] addEvent function not found');
    }
});

/**
 * Add Red Card Action
 * Adds red card to match report
 */
EventDelegation.register('add-red-card', function(element, e) {
    e.preventDefault();

    // Extract matchId from onclick attribute or data attribute
    let matchId = element.dataset.matchId;
    if (!matchId) {
        const onclickAttr = element.getAttribute('onclick');
        if (onclickAttr) {
            const match = onclickAttr.match(/'([^']+)'/);
            if (match) matchId = match[1];
        }
    }

    if (!matchId) {
        console.error('[add-red-card] Missing match ID');
        return;
    }

    const containerId = `redCardsContainer-${matchId}`;

    if (typeof window.addEvent === 'function') {
        window.addEvent(matchId, containerId);
    } else {
        console.error('[add-red-card] addEvent function not found');
    }
});

/**
 * Remove Event Action (Generic)
 * Removes any event entry (goal, assist, card) from match report
 */
EventDelegation.register('remove-event', function(element, e) {
    e.preventDefault();

    if (typeof window.removeEvent === 'function') {
        window.removeEvent(element);
    } else {
        console.error('[remove-event] removeEvent function not found');
    }
});

/**
 * Remove Own Goal Action
 * Removes own goal from match report
 */
EventDelegation.register('remove-own-goal', function(element, e) {
    e.preventDefault();

    if (typeof window.removeEvent === 'function') {
        window.removeEvent(element);
    } else {
        console.error('[remove-own-goal] removeEvent function not found');
    }
});

// ============================================================================
// RSVP ACTIONS
// ============================================================================

/**
 * RSVP Yes Action
 * Player confirms attendance (admin can set for players)
 */
EventDelegation.register('rsvp-yes', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const playerId = element.dataset.playerId;

    if (!matchId) {
        console.error('[rsvp-yes] Missing match ID');
        return;
    }

    // Admin update mode (has playerId) vs player self-RSVP
    if (playerId) {
        // Admin updating player RSVP
        if (typeof updatePlayerRSVP === 'function') {
            updatePlayerRSVP(playerId, matchId, 'yes');
        } else {
            // Fallback: trigger the update-rsvp-btn logic
            const response = 'yes';
            updateRSVPStatus(playerId, matchId, response);
        }
    } else {
        // Player self-RSVP
        if (typeof submitRSVP === 'function') {
            submitRSVP(matchId, 'yes');
        } else {
            console.error('[rsvp-yes] submitRSVP function not found');
        }
    }
});

/**
 * RSVP No Action
 * Player confirms they cannot attend
 */
EventDelegation.register('rsvp-no', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const playerId = element.dataset.playerId;

    if (!matchId) {
        console.error('[rsvp-no] Missing match ID');
        return;
    }

    if (playerId) {
        if (typeof updatePlayerRSVP === 'function') {
            updatePlayerRSVP(playerId, matchId, 'no');
        } else {
            updateRSVPStatus(playerId, matchId, 'no');
        }
    } else {
        if (typeof submitRSVP === 'function') {
            submitRSVP(matchId, 'no');
        } else {
            console.error('[rsvp-no] submitRSVP function not found');
        }
    }
});

/**
 * RSVP Maybe Action
 * Player is unsure about attendance
 */
EventDelegation.register('rsvp-maybe', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const playerId = element.dataset.playerId;

    if (!matchId) {
        console.error('[rsvp-maybe] Missing match ID');
        return;
    }

    if (playerId) {
        if (typeof updatePlayerRSVP === 'function') {
            updatePlayerRSVP(playerId, matchId, 'maybe');
        } else {
            updateRSVPStatus(playerId, matchId, 'maybe');
        }
    } else {
        if (typeof submitRSVP === 'function') {
            submitRSVP(matchId, 'maybe');
        } else {
            console.error('[rsvp-maybe] submitRSVP function not found');
        }
    }
});

/**
 * Withdraw RSVP Action
 * Player cancels their RSVP
 */
EventDelegation.register('rsvp-withdraw', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const playerId = element.dataset.playerId;

    if (!matchId) {
        console.error('[rsvp-withdraw] Missing match ID');
        return;
    }

    if (playerId) {
        // Admin clearing player RSVP
        if (typeof updatePlayerRSVP === 'function') {
            updatePlayerRSVP(playerId, matchId, 'no_response');
        } else {
            updateRSVPStatus(playerId, matchId, 'no_response');
        }
    } else {
        // Player withdrawing own RSVP
        if (typeof withdrawRSVP === 'function') {
            withdrawRSVP(matchId);
        } else {
            console.error('[rsvp-withdraw] withdrawRSVP function not found');
        }
    }
});

/**
 * Send SMS Action
 * Opens modal to send SMS to player
 */
EventDelegation.register('rsvp-request-sms', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;
    const phone = element.dataset.phone;

    if (!playerId) {
        console.error('[rsvp-request-sms] Missing player ID');
        return;
    }

    // Use jQuery if available (legacy code uses it)
    if (window.jQuery) {
        const $ = window.jQuery;

        try {
            // Populate modal fields
            $('#smsPlayerName').text(playerName || 'Player');
            $('#smsPlayerId').val(playerId);
            $('#smsPlayerPhone').val(phone || '');

            // Format phone number for display
            if (phone && typeof formatPhoneNumber === 'function') {
                $('#smsPlayerPhoneDisplay').text(formatPhoneNumber(phone));
            } else {
                $('#smsPlayerPhoneDisplay').text(phone || '');
            }

            $('#smsMessage').val('');
            $('#smsCharCount').text('0');

            // Show modal
            const smsModal = document.querySelector('[data-modal="send-sms"]');
            if (smsModal) {
                ModalManager.showByElement(smsModal);
            }
        } catch (err) {
            console.error('[rsvp-request-sms] Error opening modal:', err);
        }
    } else {
        // Vanilla JS fallback
        const smsModal = document.querySelector('[data-modal="send-sms"]');
        if (smsModal && window.bootstrap) {
            // Set values directly
            const playerNameEl = document.getElementById('smsPlayerName');
            const playerIdEl = document.getElementById('smsPlayerId');
            const playerPhoneEl = document.getElementById('smsPlayerPhone');
            const messageEl = document.getElementById('smsMessage');
            const charCountEl = document.getElementById('smsCharCount');

            if (playerNameEl) playerNameEl.textContent = playerName || 'Player';
            if (playerIdEl) playerIdEl.value = playerId;
            if (playerPhoneEl) playerPhoneEl.value = phone || '';
            if (messageEl) messageEl.value = '';
            if (charCountEl) charCountEl.textContent = '0';

            ModalManager.showByElement(smsModal);
        }
    }
});

/**
 * Send Discord DM Action
 * Opens modal to send Discord direct message
 */
EventDelegation.register('rsvp-request-discord-dm', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;
    const discordId = element.dataset.discordId;

    if (!playerId) {
        console.error('[rsvp-request-discord-dm] Missing player ID');
        return;
    }

    // Use jQuery if available (legacy code uses it)
    if (window.jQuery) {
        const $ = window.jQuery;

        try {
            $('#discordPlayerName').text(playerName || 'Player');
            $('#discordPlayerId').val(playerId);
            $('#discordId').val(discordId || '');
            $('#discordMessage').val('');
            $('#discordCharCount').text('0');

            const discordModal = document.querySelector('[data-modal="send-discord-dm"]');
            if (discordModal) {
                ModalManager.showByElement(discordModal);
            }
        } catch (err) {
            console.error('[rsvp-request-discord-dm] Error opening modal:', err);
        }
    } else {
        // Vanilla JS fallback
        const discordModal = document.querySelector('[data-modal="send-discord-dm"]');
        if (discordModal && window.bootstrap) {
            const playerNameEl = document.getElementById('discordPlayerName');
            const playerIdEl = document.getElementById('discordPlayerId');
            const discordIdEl = document.getElementById('discordId');
            const messageEl = document.getElementById('discordMessage');
            const charCountEl = document.getElementById('discordCharCount');

            if (playerNameEl) playerNameEl.textContent = playerName || 'Player';
            if (playerIdEl) playerIdEl.value = playerId;
            if (discordIdEl) discordIdEl.value = discordId || '';
            if (messageEl) messageEl.value = '';
            if (charCountEl) charCountEl.textContent = '0';

            ModalManager.showByElement(discordModal);
        }
    }
});

/**
 * Update RSVP Status Action (Admin)
 * Admin manually updates player RSVP status
 * This is the main handler that triggers the update via AJAX
 */
EventDelegation.register('rsvp-update-status', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const matchId = element.dataset.matchId;
    const response = element.dataset.response;

    if (!playerId || !matchId || !response) {
        console.error('[rsvp-update-status] Missing required data attributes');
        return;
    }

    updateRSVPStatus(playerId, matchId, response);
});

/**
 * Helper function to update RSVP status via AJAX
 * This replaces the inline logic from the jQuery handler
 */
function updateRSVPStatus(playerId, matchId, response) {
    // Use SweetAlert2 for confirmation
    if (typeof Swal === 'undefined') {
        console.error('[updateRSVPStatus] SweetAlert2 not available');
        return;
    }

    Swal.fire({
        title: 'Update RSVP Status?',
        text: 'Are you sure you want to update this player\'s RSVP status?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, update it',
        cancelButtonText: 'Cancel',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
        customClass: {
            confirmButton: 'swal-btn-confirm',
            cancelButton: 'swal-btn-cancel'
        },
        buttonsStyling: false
    }).then((result) => {
        if (result.isConfirmed) {
            const formData = new FormData();

            // Get CSRF token
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value || '';

            formData.append('csrf_token', csrfToken);
            formData.append('player_id', playerId);
            formData.append('match_id', matchId);
            formData.append('response', response);

            // Show loading state
            Swal.fire({
                title: 'Updating...',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                }
            });

            // Make the AJAX request
            fetch('/admin/update_rsvp', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(function(response) {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(function(data) {
                if (data.success) {
                    Swal.fire({
                        title: 'Success!',
                        text: 'RSVP updated successfully.',
                        icon: 'success',
                        timer: 1500,
                        showConfirmButton: false
                    }).then(() => {
                        window.location.reload();
                    });
                } else {
                    Swal.fire({
                        title: 'Error',
                        text: data.message || 'Error updating RSVP.',
                        icon: 'error'
                    });
                }
            })
            .catch(function(error) {
                console.error('[updateRSVPStatus] Error:', error);
                Swal.fire({
                    title: 'Error',
                    text: 'An error occurred while updating RSVP. Please try again.',
                    icon: 'error'
                });
            });
        }
    });
}

// ============================================================================
// CALENDAR SUBSCRIPTION ACTIONS
// ============================================================================

/**
 * Copy Subscription URL Action
 * Copies the calendar subscription URL to clipboard
 */
EventDelegation.register('copy-subscription-url', async function(element, e) {
    e.preventDefault();

    const urlInput = document.getElementById('subscriptionUrl');
    if (!urlInput || !urlInput.value) {
        showCalendarToast('warning', 'No subscription URL available');
        return;
    }

    try {
        await navigator.clipboard.writeText(urlInput.value);
        showCalendarToast('success', 'URL copied to clipboard');

        // Visual feedback
        const originalHtml = element.innerHTML;
        element.innerHTML = '<i class="ti ti-check me-1"></i>Copied!';
        setTimeout(() => {
            element.innerHTML = originalHtml;
        }, 2000);
    } catch (error) {
        // Fallback for older browsers
        urlInput.select();
        document.execCommand('copy');
        showCalendarToast('success', 'URL copied to clipboard');
    }
});

/**
 * Regenerate Subscription Token Action
 * Regenerates the calendar subscription URL/token
 */
EventDelegation.register('regenerate-subscription-token', async function(element, e) {
    e.preventDefault();

    if (!confirm('Are you sure you want to regenerate your subscription URL?\n\nYour existing calendar subscriptions will stop working and you will need to re-subscribe with the new URL.')) {
        return;
    }

    setCalendarLoading(true);

    try {
        const response = await fetch('/api/calendar/subscription/regenerate', {
            method: 'POST',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json'
            }
        });

        if (!response.ok) {
            throw new Error('Failed to regenerate token');
        }

        const data = await response.json();

        // Update the calendar subscription state if CalendarSubscription module is available
        if (typeof CalendarSubscription !== 'undefined' && CalendarSubscription.loadSubscription) {
            await CalendarSubscription.loadSubscription();
        }

        showCalendarToast('success', 'Subscription URL regenerated successfully');

    } catch (error) {
        console.error('[regenerate-subscription-token] Error:', error);
        showCalendarToast('error', 'Failed to regenerate subscription URL');
    } finally {
        setCalendarLoading(false);
    }
});

/**
 * Subscribe via Webcal Action
 * Opens subscription in iOS/macOS Calendar app via webcal:// protocol
 */
EventDelegation.register('subscribe-webcal', function(element, e) {
    e.preventDefault();

    const webcalUrl = element.dataset.webcalUrl;

    if (webcalUrl) {
        window.location.href = webcalUrl;
    } else {
        showCalendarToast('warning', 'Subscription URL not available');
    }
});

/**
 * Subscribe via Google Calendar Action
 * Opens Google Calendar subscription page in new tab
 */
EventDelegation.register('subscribe-google', function(element, e) {
    e.preventDefault();

    const feedUrl = element.dataset.feedUrl;

    if (!feedUrl) {
        showCalendarToast('warning', 'Subscription URL not available');
        return;
    }

    // Google Calendar subscription URL
    const googleUrl = 'https://calendar.google.com/calendar/r?cid=' + encodeURIComponent(feedUrl);
    window.open(googleUrl, '_blank');
});

/**
 * Update Calendar Preferences Action
 * Updates subscription preferences (which events to include)
 * Triggered by change events on preference checkboxes
 */
EventDelegation.register('update-calendar-preferences', async function(element, e) {
    const preferences = {
        include_team_matches: document.getElementById('subIncludeMatches')?.checked ?? true,
        include_league_events: document.getElementById('subIncludeLeagueEvents')?.checked ?? true,
        include_ref_assignments: document.getElementById('subIncludeRefAssignments')?.checked ?? true
    };

    try {
        const response = await fetch('/api/calendar/subscription/preferences', {
            method: 'PUT',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(preferences)
        });

        if (!response.ok) {
            throw new Error('Failed to update preferences');
        }

        await response.json();
        showCalendarToast('success', 'Preferences updated');

    } catch (error) {
        console.error('[update-calendar-preferences] Error:', error);
        showCalendarToast('error', 'Failed to update preferences');

        // Revert checkbox state
        element.checked = !element.checked;
    }
});

/**
 * Helper: Show calendar-specific toast notification
 * Uses existing toast system if available
 */
function showCalendarToast(type, message) {
    // Use existing toast system if available
    if (typeof window.showToast === 'function') {
        window.showToast(type, message);
        return;
    }

    // Fallback to Toastify
    if (typeof Toastify !== 'undefined') {
        // Use ECSTheme colors with gradient variations for toast backgrounds
        const successColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#198754';
        const successLight = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success-light') : '#198754';
        const dangerColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545';
        const dangerLight = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger-light') : '#dc3545';
        const warningColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffc107';
        const warningLight = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning-light') : '#ffc107';
        const infoColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info') : '#0dcaf0';
        const infoLight = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info-light') : '#0dcaf0';
        const bgColors = {
            success: `linear-gradient(to right, ${successColor}, ${successLight})`,
            error: `linear-gradient(to right, ${dangerColor}, ${dangerLight})`,
            warning: `linear-gradient(to right, ${warningColor}, ${warningLight})`,
            info: `linear-gradient(to right, ${infoColor}, ${infoLight})`
        };

        Toastify({
            text: message,
            duration: 3000,
            gravity: 'top',
            position: 'right',
            style: { background: bgColors[type] || bgColors.info }
        }).showToast();
        return;
    }

    // Final fallback
    console.log(`[${type}] ${message}`);
}

/**
 * Helper: Set loading state for calendar subscription
 */
function setCalendarLoading(loading) {
    const loadingIndicator = document.getElementById('subscriptionLoading');
    const content = document.getElementById('subscriptionContent');

    if (loadingIndicator) {
        loadingIndicator.classList.toggle('is-hidden', !loading);
    }
    if (content) {
        content.classList.toggle('is-hidden', loading);
    }
}

// ============================================================================
// PROFILE VERIFICATION ACTIONS
// ============================================================================

/**
 * Toggle Section Reviewed Checkbox Action
 * Handles when user checks/unchecks a profile section as reviewed
 * Updates progress indicator and confirm button state
 */
EventDelegation.register('verify-section-reviewed', function(element, e) {
    // This handler is triggered by the change event via data-on-change
    // The ProfileVerification module will handle the actual logic
    if (window.ProfileVerification && typeof window.ProfileVerification.handleCheckboxChange === 'function') {
        window.ProfileVerification.handleCheckboxChange(element);
    } else {
        console.error('[verify-section-reviewed] ProfileVerification not available');
    }
});

/**
 * Verify Profile Action
 * Navigates to the profile verification page where users review sections.
 * Used on the main profile page to start the verification flow.
 * The /verify route auto-detects mobile vs desktop and redirects appropriately.
 */
EventDelegation.register('verify-profile', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[verify-profile] Missing player ID');
        return;
    }

    // Get verify URL from data element or construct it
    // The /verify GET route handles mobile vs desktop detection
    const verifyDataEl = document.querySelector('[data-profile-verify]');
    const verifyUrl = verifyDataEl?.dataset.verifyUrl || `/players/profile/${playerId}/verify`;

    // Navigate to verification page
    window.location.href = verifyUrl;
});

/**
 * Verify Profile Submit Action (Form-based)
 * Submits the profile verification form
 * Validates that all sections have been reviewed before allowing submission
 */
EventDelegation.register('verify-profile-submit', function(element, e) {
    // Check if all sections are reviewed before allowing submission
    if (window.ProfileVerification && typeof window.ProfileVerification.areAllSectionsReviewed === 'function') {
        const allReviewed = window.ProfileVerification.areAllSectionsReviewed();

        if (!allReviewed) {
            e.preventDefault();

            const uncheckedSections = window.ProfileVerification.getUncheckedSections();

            // Haptic feedback for error
            if (window.Haptics) {
                window.Haptics.error();
            }

            // Show warning
            window.ProfileVerification.showIncompleteWarning(uncheckedSections);
        } else {
            // All reviewed - allow form submission with success feedback
            if (window.Haptics) {
                window.Haptics.success();
            }
            // Form will submit naturally
        }
    } else {
        // ProfileVerification not available - allow submission (backward compatibility)
        console.warn('[verify-profile-submit] ProfileVerification not available, allowing submission');
    }
});

// ============================================================================
// DISCORD MANAGEMENT ACTIONS
// ============================================================================

/**
 * Change Per Page Action (triggered by change event)
 * Updates the number of items displayed per page
 */
EventDelegation.register('change-per-page', function(element, e) {
    const perPage = element.value;
    const url = new URL(window.location);
    url.searchParams.set('per_page', perPage);
    url.searchParams.set('page', '1'); // Reset to first page
    window.location.href = url.toString();
});

/**
 * Refresh All Discord Status Action
 * Refreshes Discord status for all players
 */
EventDelegation.register('refresh-all-discord-status', function(element, e) {
    e.preventDefault();

    const btn = element;

    if (typeof Swal === 'undefined') {
        console.error('[refresh-all-discord-status] SweetAlert2 not available');
        return;
    }

    Swal.fire({
        title: 'Refresh All Discord Status',
        text: 'This will refresh Discord status for all players. This may take a moment. Continue?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, refresh all',
        cancelButtonText: 'Cancel',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28c76f',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#ea5455'
    }).then((result) => {
        if (result.isConfirmed) {
            // Show loading state
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i>Refreshing...';
            btn.disabled = true;

            // Get CSRF token
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            // Refresh all Discord status
            fetch('/admin/refresh_all_discord_status', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            }).then(response => response.json())
            .then(data => {
                if (data.success) {
                    Swal.fire({
                        icon: 'success',
                        title: 'Status Updated',
                        text: `Refreshed Discord status for ${data.success_count} players`,
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => {
                        location.reload();
                    });
                } else {
                    throw new Error(data.message || 'Failed to refresh status');
                }
            }).catch(error => {
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Failed to refresh status: ' + error.message,
                    confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#ea5455'
                });
            }).finally(() => {
                btn.innerHTML = originalText;
                btn.disabled = false;
            });
        }
    });
});

/**
 * Refresh Unknown Discord Status Action
 * Checks Discord status for all players with unknown status
 */
EventDelegation.register('refresh-unknown-discord-status', function(element, e) {
    e.preventDefault();

    const btn = element;

    if (typeof Swal === 'undefined') {
        console.error('[refresh-unknown-discord-status] SweetAlert2 not available');
        return;
    }

    Swal.fire({
        title: 'Check Unknown Discord Status',
        text: 'This will check Discord status for all players with unknown status. Continue?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, check unknown',
        cancelButtonText: 'Cancel',
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffab00',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#ea5455'
    }).then((result) => {
        if (result.isConfirmed) {
            // Show loading state
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i>Checking...';
            btn.disabled = true;

            // Get CSRF token
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            // Check unknown Discord status
            fetch('/admin/refresh_unknown_discord_status', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            }).then(response => response.json())
            .then(data => {
                if (data.success) {
                    Swal.fire({
                        icon: 'success',
                        title: 'Status Checked',
                        text: `Checked Discord status for ${data.success_count} players with unknown status`,
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => {
                        location.reload();
                    });
                } else {
                    throw new Error(data.message || 'Failed to check unknown status');
                }
            }).catch(error => {
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Failed to check unknown status: ' + error.message,
                    confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#ea5455'
                });
            }).finally(() => {
                btn.innerHTML = originalText;
                btn.disabled = false;
            });
        }
    });
});

/**
 * Refresh Player Status Action
 * Refreshes Discord status for individual player
 */
EventDelegation.register('refresh-player-status', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;

    if (!playerId) {
        console.error('[refresh-player-status] Missing player ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i><span>Checking...</span>';
    element.disabled = true;

    // Get CSRF token
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/teams/player/${playerId}/refresh-discord-status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    }).then(response => response.json())
    .then(data => {
        if (data.success) {
            // Show success message and reload
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    icon: 'success',
                    title: 'Status Updated',
                    text: `Discord status refreshed for ${playerName}`,
                    timer: 2000,
                    showConfirmButton: false
                }).then(() => {
                    location.reload();
                });
            } else {
                location.reload();
            }
        } else {
            throw new Error(data.message || 'Failed to refresh status');
        }
    }).catch(error => {
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to refresh status: ' + error.message,
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#ea5455'
            });
        } else {
            console.error('[refresh-player-status] Error:', error);
        }
    }).finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

/**
 * Send Discord DM Action
 * Opens modal to send Discord direct message
 */
EventDelegation.register('send-discord-dm', function(element, e) {
    e.preventDefault();

    const discordId = element.dataset.discordId;
    const playerName = element.dataset.playerName;

    if (!discordId) {
        console.error('[send-discord-dm] Missing Discord ID');
        return;
    }

    const dmDiscordIdInput = document.getElementById('dmDiscordId');
    const modalTitle = document.querySelector('#discordDMModal .modal-title');
    const dmMessageTextarea = document.getElementById('dmMessage');

    if (dmDiscordIdInput) dmDiscordIdInput.value = discordId;
    if (modalTitle) modalTitle.textContent = `Send Discord DM to ${playerName}`;

    // Set default message
    const defaultMessage = `Hi ${playerName}! 👋

We noticed you haven't joined our ECS FC Discord server yet.

Join us to:
• Get match updates and announcements
• Connect with your teammates
• Participate in league discussions

Join here: https://discord.gg/weareecs

See you there!
- ECS FC Admin Team`;

    if (dmMessageTextarea) dmMessageTextarea.value = defaultMessage;

    // Show modal
    const modalElement = document.getElementById('discordDMModal');
    if (modalElement) {
        ModalManager.show('discordDMModal');
    }
});

/**
 * Submit Discord DM Action
 * Sends the Discord direct message
 */
EventDelegation.register('submit-discord-dm', function(element, e) {
    e.preventDefault();

    const discordId = document.getElementById('dmDiscordId')?.value;
    const message = document.getElementById('dmMessage')?.value;

    if (!message || !message.trim()) {
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                icon: 'warning',
                title: 'Message Required',
                text: 'Please enter a message before sending',
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('warning') : '#ffab00'
            });
        }
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i>Sending...';
    element.disabled = true;

    // Get CSRF token
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin/send_discord_dm', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            discord_id: discordId,
            message: message
        })
    }).then(response => response.json())
    .then(data => {
        if (data.success) {
            const modalElement = document.getElementById('discordDMModal');
            if (modalElement && window.bootstrap) {
                const modalInstance = bootstrap.Modal.getInstance(modalElement);
                if (modalInstance) modalInstance.hide();
            }

            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    icon: 'success',
                    title: 'Message Sent',
                    text: 'Discord message sent successfully!',
                    timer: 2000,
                    showConfirmButton: false
                });
            }
        } else {
            throw new Error(data.message || 'Failed to send message');
        }
    }).catch(error => {
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to send Discord message: ' + error.message,
                confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#ea5455'
            });
        } else {
            console.error('[submit-discord-dm] Error:', error);
        }
    }).finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

// ============================================================================
// REFEREE MANAGEMENT ACTIONS
// ============================================================================

/**
 * Assign Referee Action
 * Assigns a referee to a match via form submission
 */
EventDelegation.register('assign-referee', function(element, e) {
    e.preventDefault();

    const matchId = document.getElementById('matchId')?.value;
    const refId = document.getElementById('refSelect')?.value;

    if (!matchId || !refId) {
        console.error('[assign-referee] Missing match ID or referee ID');
        return;
    }

    // Call global function if exists
    if (typeof assignReferee === 'function') {
        assignReferee(e);
    } else {
        console.error('[assign-referee] assignReferee function not found');
    }
});

/**
 * Remove Referee Action
 * Removes a referee from a match
 */
EventDelegation.register('remove-referee', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId || document.getElementById('matchId')?.value;

    if (!matchId) {
        console.error('[remove-referee] Missing match ID');
        return;
    }

    // Call global function if exists
    if (typeof removeReferee === 'function') {
        removeReferee();
    } else {
        console.error('[remove-referee] removeReferee function not found');
    }
});

/**
 * Refresh Calendar Action
 * Reloads calendar events and available referees list
 */
EventDelegation.register('refresh-calendar', function(element, e) {
    e.preventDefault();

    // Check for calendar-specific refresh function
    if (typeof loadCalendarEvents === 'function' && typeof fetchAvailableReferees === 'function') {
        loadCalendarEvents();
        // Get calendar instance if available
        if (window.calendarInstance) {
            fetchAvailableReferees(window.calendarInstance.getDate());
        } else {
            fetchAvailableReferees(new Date());
        }
    } else if (typeof window.refreshCalendar === 'function') {
        window.refreshCalendar();
    } else {
        console.error('[refresh-calendar] No refresh function available');
    }
});

/**
 * View Referee Profile Action
 * Opens modal or page with referee details
 */
EventDelegation.register('view-referee-profile', function(element, e) {
    e.preventDefault();

    const refereeId = element.dataset.refereeId;

    if (!refereeId) {
        console.error('[view-referee-profile] Missing referee ID');
        return;
    }

    if (typeof viewRefereeProfile === 'function') {
        viewRefereeProfile(refereeId);
    } else {
        // Fallback: navigate to referee profile page
        const profileUrl = element.dataset.profileUrl || `/admin/referee/${refereeId}`;
        window.location.href = profileUrl;
    }
});

/**
 * Update Referee Status Action
 * Updates referee availability status
 */
EventDelegation.register('update-referee-status', function(element, e) {
    e.preventDefault();

    const refereeId = element.dataset.refereeId;
    const status = element.dataset.status;

    if (!refereeId || !status) {
        console.error('[update-referee-status] Missing referee ID or status');
        return;
    }

    if (typeof updateRefereeStatus === 'function') {
        updateRefereeStatus(refereeId, status);
    } else {
        console.error('[update-referee-status] updateRefereeStatus function not found');
    }
});

// ============================================================================
// SUBSTITUTE POOL MANAGEMENT ACTIONS
// ============================================================================

/**
 * Approve Pool Player Action
 * Adds a pending player to the active substitute pool
 */
EventDelegation.register('approve-pool-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[approve-pool-player] Missing required data attributes');
        return;
    }

    if (typeof approvePlayer === 'function') {
        approvePlayer(playerId, league);
    } else {
        console.error('[approve-pool-player] approvePlayer function not found');
    }
});

/**
 * Remove Pool Player Action
 * Removes a player from the active substitute pool
 */
EventDelegation.register('remove-pool-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[remove-pool-player] Missing required data attributes');
        return;
    }

    if (typeof removePlayer === 'function') {
        removePlayer(playerId, league);
    } else {
        console.error('[remove-pool-player] removePlayer function not found');
    }
});

/**
 * Edit Pool Preferences Action
 * Opens modal to edit player's substitute pool preferences
 */
EventDelegation.register('edit-pool-preferences', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[edit-pool-preferences] Missing required data attributes');
        return;
    }

    if (typeof openEditPreferencesModal === 'function') {
        openEditPreferencesModal(playerId, league);
    } else {
        console.error('[edit-pool-preferences] openEditPreferencesModal function not found');
    }
});

/**
 * View Pool Player Details Action
 * Opens modal with detailed player information
 */
EventDelegation.register('view-pool-player-details', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[view-pool-player-details] Missing player ID');
        return;
    }

    if (typeof openPlayerDetailsModal === 'function') {
        openPlayerDetailsModal(playerId);
    } else {
        console.error('[view-pool-player-details] openPlayerDetailsModal function not found');
    }
});

/**
 * Add Player to League Action
 * Adds a player to a specific league's substitute pool (from search results)
 */
EventDelegation.register('add-player-to-league', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const league = element.dataset.league;

    if (!playerId || !league) {
        console.error('[add-player-to-league] Missing required data attributes');
        return;
    }

    if (typeof approvePlayer === 'function') {
        approvePlayer(playerId, league);
    } else {
        console.error('[add-player-to-league] approvePlayer function not found');
    }
});

/**
 * Toggle Pool View Action
 * Switches between grid and list view for substitute pool
 */
EventDelegation.register('toggle-pool-view', function(element, e) {
    e.preventDefault();

    const view = element.dataset.view;
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!view || !league || !section) {
        console.error('[toggle-pool-view] Missing required data attributes');
        return;
    }

    // Update button states
    const siblings = element.parentElement.querySelectorAll('.view-toggle');
    siblings.forEach(btn => btn.classList.remove('active'));
    element.classList.add('active');

    // Show/hide views
    const listView = document.getElementById(`${section}-list-${league}`);
    const gridView = document.getElementById(`${section}-grid-${league}`);

    if (view === 'list') {
        if (listView) listView.classList.remove('u-hidden');
        if (gridView) gridView.classList.add('u-hidden');
    } else {
        if (listView) listView.classList.add('u-hidden');
        if (gridView) gridView.classList.remove('u-hidden');
    }
});

/**
 * Filter Pool Action (triggered by input event)
 * Filters player cards by search text
 */
EventDelegation.register('filter-pool', function(element, e) {
    const filterText = element.value.toLowerCase().trim();
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!league || !section) {
        console.error('[filter-pool] Missing required data attributes');
        return;
    }

    if (typeof filterPlayerCards === 'function') {
        filterPlayerCards(league, section, filterText);
    } else {
        // Fallback implementation
        const cards = document.querySelectorAll(
            `.player-card[data-league="${league}"][data-status="${section}"], ` +
            `.player-list-item[data-league="${league}"][data-status="${section}"]`
        );

        cards.forEach(card => {
            const searchText = (card.dataset.searchText || '').toLowerCase();
            const shouldShow = !filterText || searchText.includes(filterText);
            card.classList.toggle('u-hidden', !shouldShow);
        });
    }
});

/**
 * Manage League Pool Action
 * Opens modal for league-specific pool management
 */
EventDelegation.register('manage-league-pool', function(element, e) {
    e.preventDefault();

    const league = element.dataset.league;

    if (!league) {
        console.error('[manage-league-pool] Missing league identifier');
        return;
    }

    if (typeof openLeagueManagementModal === 'function') {
        openLeagueManagementModal(league);
    } else {
        console.error('[manage-league-pool] openLeagueManagementModal function not found');
    }
});

/**
 * Save Pool Preferences Action
 * Saves edited preferences for a substitute pool player
 */
EventDelegation.register('save-pool-preferences', function(element, e) {
    e.preventDefault();

    if (typeof savePreferences === 'function') {
        savePreferences();
    } else {
        console.error('[save-pool-preferences] savePreferences function not found');
    }
});

/**
 * Pagination Click Handler for Pool Pages
 * Handles page navigation for substitute pool pagination
 */
EventDelegation.register('pool-pagination', function(element, e) {
    e.preventDefault();

    const page = parseInt(element.dataset.page);
    const league = element.dataset.league;
    const section = element.dataset.section;

    if (!page || !league || !section) {
        console.error('[pool-pagination] Missing required data attributes');
        return;
    }

    const key = `${league}-${section}`;

    if (typeof paginationState !== 'undefined' && paginationState[key]) {
        if (page !== paginationState[key].currentPage) {
            paginationState[key].currentPage = page;
            if (typeof updatePagination === 'function') {
                updatePagination(league, section);
            }
        }
    }
});

/**
 * Add to Pool Action (Admin Panel variant)
 * Adds a player to substitute pool (admin panel version)
 */
EventDelegation.register('add-to-pool', async function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;

    if (!playerId) {
        console.error('[add-to-pool] Missing player ID');
        return;
    }

    // Check if addToPool function exists (from substitute_pool_detail.html)
    if (typeof addToPool === 'function') {
        addToPool(playerId);
    } else {
        console.error('[add-to-pool] addToPool function not found');
    }
});

/**
 * Reject Player Action (Admin Panel)
 * Rejects a player from being added to substitute pool
 */
EventDelegation.register('reject-player', async function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;

    if (!playerId) {
        console.error('[reject-player] Missing player ID');
        return;
    }

    // Check if rejectPlayer function exists (from substitute_pool_detail.html)
    if (typeof rejectPlayer === 'function') {
        rejectPlayer(playerId, playerName);
    } else {
        console.error('[reject-player] rejectPlayer function not found');
    }
});

/**
 * Remove Player Action (Admin Panel variant)
 * Removes player from pool (maps to remove-pool-player for compatibility)
 */
EventDelegation.register('remove-player', async function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;

    if (!playerId) {
        console.error('[remove-player] Missing player ID');
        return;
    }

    // Check if removeFromPool function exists (from substitute_pool_detail.html)
    if (typeof removeFromPool === 'function') {
        removeFromPool(playerId, playerName);
    } else {
        console.error('[remove-player] removeFromPool function not found');
    }
});

/**
 * Load Stats Action (Admin Panel)
 * Opens statistics modal for substitute pool
 */
EventDelegation.register('load-stats', async function(element, e) {
    e.preventDefault();

    if (typeof loadStatistics === 'function') {
        loadStatistics();
    } else {
        console.error('[load-stats] loadStatistics function not found');
    }
});

/**
 * Add Player Action (Admin Panel)
 * Opens modal to add player to substitute pool
 */
EventDelegation.register('add-player', function(element, e) {
    e.preventDefault();

    if (typeof showAddPlayerModal === 'function') {
        showAddPlayerModal();
    } else {
        console.error('[add-player] showAddPlayerModal function not found');
    }
});

// ============================================================================
// ONBOARDING WIZARD ACTIONS
// ============================================================================

/**
 * Create Profile Action
 * User clicks "Create Profile" button on intro screen
 * Advances carousel to first step and sets form action
 */
EventDelegation.register('onboarding-create-profile', function(element, e) {
    e.preventDefault();

    const formActionInput = document.getElementById('form_action');
    if (formActionInput) formActionInput.value = 'create_profile';

    // Get bootstrap carousel instance and advance to next slide
    const carouselElement = document.getElementById('modalCarouselControls');
    if (carouselElement && window.bootstrap) {
        const bootstrapCarousel = bootstrap.Carousel.getInstance(carouselElement) ||
                                 new bootstrap.Carousel(carouselElement);
        bootstrapCarousel.next();
    }
});

/**
 * Skip Profile Action
 * User clicks "Skip for now" button on intro screen
 * Submits form with skip_profile action
 */
EventDelegation.register('onboarding-skip-profile', function(element, e) {
    e.preventDefault();

    const formActionInput = document.getElementById('form_action');
    const modalElement = document.getElementById('onboardingSlideModal');
    const form = modalElement ? modalElement.querySelector('form.needs-validation') : null;

    if (formActionInput) formActionInput.value = 'skip_profile';
    if (form) form.submit();
});

/**
 * Next/Save Button Action
 * Handles "Next" button clicks (validation + navigation) and "Save and Finish" on final step
 * Validates current step before advancing, or submits form on final step
 */
EventDelegation.register('onboarding-next', function(element, e) {
    e.preventDefault();
    e.stopPropagation();

    if (!window.OnboardingWizard) {
        console.error('[onboarding-next] OnboardingWizard not initialized');
        return;
    }

    const { form, formActionInput, croppedImageHiddenInput, carouselElement, bootstrapCarousel, totalSteps } =
        window.OnboardingWizard.getFormElements();

    const step = window.OnboardingWizard.getCurrentStep();

    // Final step - save and finish
    if (step === totalSteps) {
        if (formActionInput) formActionInput.value = 'update_profile';

        // Final check for any cropping
        if (window.cropper) {
            try {
                const canvas = window.cropper.getCroppedCanvas();
                if (canvas) {
                    croppedImageHiddenInput.value = canvas.toDataURL('image/png');
                }
            } catch (err) {
                console.error('[onboarding-next] Error getting cropped image:', err);
            }
        }

        // Validate form
        if (form && form.checkValidity()) {
            form.submit();
        } else {
            form.classList.add('was-validated');

            // Find first invalid input and focus it
            const firstInvalid = form.querySelector(':invalid');
            if (firstInvalid) {
                firstInvalid.focus();
                firstInvalid.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }
        }
    } else {
        // Validate current step's required fields before moving to next
        const activeItem = carouselElement ? carouselElement.querySelector('.carousel-item.active') : null;
        const requiredFields = activeItem ? activeItem.querySelectorAll('input[required], select[required], textarea[required]') : [];
        let isValid = true;

        // Check if all required fields in current step are filled
        requiredFields.forEach(field => {
            // Skip hidden fields or fields that are part of hidden sections
            if (field.offsetParent === null) return;

            if (!field.checkValidity()) {
                isValid = false;
                field.classList.add('is-invalid');

                // Add validation feedback if it doesn't exist
                if (!field.nextElementSibling || !field.nextElementSibling.classList.contains('invalid-feedback')) {
                    const feedback = document.createElement('div');
                    feedback.className = 'invalid-feedback';
                    feedback.textContent = field.validationMessage || 'This field is required.';
                    field.parentNode.insertBefore(feedback, field.nextSibling);
                }
            } else {
                field.classList.remove('is-invalid');
            }
        });

        if (isValid) {
            // Clear form action and manually move to next step
            if (formActionInput) formActionInput.value = '';
            if (bootstrapCarousel) {
                bootstrapCarousel.next();
            }
        } else {
            // Focus first invalid field
            const firstInvalid = activeItem ? activeItem.querySelector('.is-invalid') : null;
            if (firstInvalid) {
                firstInvalid.focus();
                firstInvalid.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center'
                });
            }
        }
    }
});

/**
 * Previous Button Action
 * Navigates to previous step in onboarding carousel
 */
EventDelegation.register('onboarding-previous', function(element, e) {
    e.preventDefault();

    const carouselElement = document.getElementById('modalCarouselControls');
    if (carouselElement && window.bootstrap) {
        const bootstrapCarousel = bootstrap.Carousel.getInstance(carouselElement);
        if (bootstrapCarousel) bootstrapCarousel.prev();
    }
});

/**
 * Toggle SMS Notifications Section
 * Shows/hides SMS opt-in section with animation when checkbox changes
 * Triggered by data-on-change attribute on SMS toggle checkbox
 */
EventDelegation.register('onboarding-toggle-sms', function(element, e) {
    // Element is the checkbox that was changed
    if (window.OnboardingWizard && typeof window.OnboardingWizard.handleSmsToggle === 'function') {
        window.OnboardingWizard.handleSmsToggle(element);
    } else {
        console.error('[onboarding-toggle-sms] SMS toggle handler not available');
    }
});

// ============================================================================
// SECURITY DASHBOARD ACTIONS
// ============================================================================

/**
 * Refresh Security Stats Action
 * Refreshes all security dashboard data (stats, events, logs)
 */
EventDelegation.register('refresh-stats', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.refreshAll === 'function') {
        await window.securityDashboard.refreshAll();
    } else {
        console.error('[refresh-stats] SecurityDashboard instance not available');
    }
});

/**
 * Refresh Security Events Action
 * Reloads recent security events list
 */
EventDelegation.register('refresh-events', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.loadSecurityEvents === 'function') {
        await window.securityDashboard.loadSecurityEvents();
    } else {
        console.error('[refresh-events] SecurityDashboard instance not available');
    }
});

/**
 * Refresh Security Logs Action
 * Reloads security logs display
 */
EventDelegation.register('refresh-logs', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.loadSecurityLogs === 'function') {
        await window.securityDashboard.loadSecurityLogs();
    } else {
        console.error('[refresh-logs] SecurityDashboard instance not available');
    }
});

/**
 * Unban IP Action
 * Removes an IP address from the blacklist
 */
EventDelegation.register('unban-ip', async function(element, e) {
    e.preventDefault();

    const ip = element.dataset.ip;

    if (!ip) {
        console.error('[unban-ip] Missing IP address');
        return;
    }

    if (window.securityDashboard && typeof window.securityDashboard.unbanIP === 'function') {
        await window.securityDashboard.unbanIP(ip, element);
    } else {
        console.error('[unban-ip] SecurityDashboard instance not available');
    }
});

/**
 * Quick Ban IP Action
 * Quickly bans an IP from the security events list
 */
EventDelegation.register('ban-ip-quick', async function(element, e) {
    e.preventDefault();

    const ip = element.dataset.ip;
    const reason = element.dataset.reason || 'Security event';

    if (!ip) {
        console.error('[ban-ip-quick] Missing IP address');
        return;
    }

    if (window.securityDashboard && typeof window.securityDashboard.quickBanIP === 'function') {
        await window.securityDashboard.quickBanIP(ip, reason);
    } else {
        console.error('[ban-ip-quick] SecurityDashboard instance not available');
    }
});

/**
 * Ban IP Confirm Action
 * Confirms and submits the ban IP form from the modal
 */
EventDelegation.register('ban-ip-confirm', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.banIP === 'function') {
        await window.securityDashboard.banIP();
    } else {
        console.error('[ban-ip-confirm] SecurityDashboard instance not available');
    }
});

/**
 * Clear All Bans Action
 * Removes all IP addresses from the blacklist
 */
EventDelegation.register('clear-all-bans', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.clearAllBans === 'function') {
        await window.securityDashboard.clearAllBans();
    } else if (typeof clearAllBans === 'function') {
        // Admin panel version
        await clearAllBans();
    } else {
        console.error('[clear-all-bans] No clearAllBans function available');
    }
});

/**
 * Show Ban IP Modal Action (Admin Panel)
 * Opens the modal to manually ban an IP address
 */
EventDelegation.register('show-ban-ip-modal', function(element, e) {
    e.preventDefault();

    if (typeof showBanIpModal === 'function') {
        showBanIpModal();
    } else if (window.bootstrap) {
        // Fallback: directly show the modal
        const modalElement = document.getElementById('banIpModal');
        if (modalElement) {
            ModalManager.show('banIpModal');
        }
    } else {
        console.error('[show-ban-ip-modal] No showBanIpModal function available');
    }
});

/**
 * Ban IP Action (Admin Panel)
 * Submits the ban IP form from the admin panel modal
 */
EventDelegation.register('ban-ip', async function(element, e) {
    e.preventDefault();

    if (typeof banIp === 'function') {
        await banIp();
    } else if (window.securityDashboard && typeof window.securityDashboard.banIP === 'function') {
        await window.securityDashboard.banIP();
    } else {
        console.error('[ban-ip] No banIp function available');
    }
});

// ============================================================================
// AUTO SCHEDULE WIZARD ACTIONS
// ============================================================================

/**
 * Start Season Wizard Action
 * Opens the season builder wizard modal
 */
EventDelegation.register('start-season-wizard', function(element, e) {
    e.preventDefault();

    if (typeof startSeasonWizard === 'function') {
        startSeasonWizard();
    } else {
        console.error('[start-season-wizard] startSeasonWizard function not found');
    }
});

/**
 * Show Existing Seasons Action
 * Displays the list of existing seasons
 */
EventDelegation.register('show-existing-seasons', function(element, e) {
    e.preventDefault();

    if (typeof showExistingSeasons === 'function') {
        showExistingSeasons();
    } else {
        console.error('[show-existing-seasons] showExistingSeasons function not found');
    }
});

/**
 * Show Main View Action
 * Returns to main season builder view
 */
EventDelegation.register('show-main-view', function(element, e) {
    e.preventDefault();

    if (typeof showMainView === 'function') {
        showMainView();
    } else {
        console.error('[show-main-view] showMainView function not found');
    }
});

/**
 * Next Step Action (Wizard Navigation)
 * Advances to the next step in the wizard
 */
EventDelegation.register('next-step', function(element, e) {
    e.preventDefault();

    if (typeof nextStep === 'function') {
        nextStep();
    } else {
        console.error('[next-step] nextStep function not found');
    }
});

/**
 * Previous Step Action (Wizard Navigation)
 * Goes back to the previous step in the wizard
 */
EventDelegation.register('previous-step', function(element, e) {
    e.preventDefault();

    if (typeof previousStep === 'function') {
        previousStep();
    } else {
        console.error('[previous-step] previousStep function not found');
    }
});

/**
 * Create Season Action
 * Submits the wizard and creates the season
 */
EventDelegation.register('create-season', function(element, e) {
    e.preventDefault();

    if (typeof createSeason === 'function') {
        createSeason();
    } else {
        console.error('[create-season] createSeason function not found');
    }
});

/**
 * Update Season Structure Action
 * Updates season breakdown based on total weeks selection
 */
EventDelegation.register('update-season-structure', function(element, e) {
    if (typeof updateSeasonStructure === 'function') {
        updateSeasonStructure();
    } else {
        console.error('[update-season-structure] updateSeasonStructure function not found');
    }
});

/**
 * Apply Wizard Template Action
 * Applies a configuration template (standard, classic-practice, custom)
 */
EventDelegation.register('apply-wizard-template', function(element, e) {
    e.preventDefault();

    const templateType = element.dataset.templateType;

    if (!templateType) {
        console.error('[apply-wizard-template] Missing template type');
        return;
    }

    if (typeof applyWizardTemplate === 'function') {
        applyWizardTemplate(templateType);
    } else {
        console.error('[apply-wizard-template] applyWizardTemplate function not found');
    }
});

/**
 * Add Wizard Field Action
 * Adds a new field configuration row in the wizard
 */
EventDelegation.register('add-wizard-field', function(element, e) {
    e.preventDefault();

    if (typeof addWizardField === 'function') {
        addWizardField();
    } else {
        console.error('[add-wizard-field] addWizardField function not found');
    }
});

/**
 * Remove Wizard Field Action
 * Removes a field configuration row from the wizard
 */
EventDelegation.register('remove-wizard-field', function(element, e) {
    e.preventDefault();

    if (typeof removeWizardField === 'function') {
        removeWizardField(element);
    } else {
        console.error('[remove-wizard-field] removeWizardField function not found');
    }
});

/**
 * Set Active Season Action
 * Sets a season as the current active season
 */
EventDelegation.register('set-active-season', function(element, e) {
    e.preventDefault();

    const seasonId = element.dataset.seasonId;
    const seasonType = element.dataset.seasonType;

    if (!seasonId || !seasonType) {
        console.error('[set-active-season] Missing season ID or type');
        return;
    }

    if (typeof setActiveSeason === 'function') {
        setActiveSeason(seasonId, seasonType);
    } else {
        console.error('[set-active-season] setActiveSeason function not found');
    }
});

/**
 * Confirm Delete Season Action
 * Shows confirmation dialog before deleting a season
 */
EventDelegation.register('confirm-delete-season', function(element, e) {
    e.preventDefault();

    const seasonId = element.dataset.seasonId;
    const seasonName = element.dataset.seasonName;

    if (!seasonId || !seasonName) {
        console.error('[confirm-delete-season] Missing season ID or name');
        return;
    }

    if (typeof confirmDeleteSeason === 'function') {
        confirmDeleteSeason(seasonId, seasonName);
    } else {
        console.error('[confirm-delete-season] confirmDeleteSeason function not found');
    }
});

/**
 * Recreate Discord Resources Action
 * Recreates Discord channels and roles for a season
 */
EventDelegation.register('recreate-discord-resources', function(element, e) {
    e.preventDefault();

    const seasonId = element.dataset.seasonId;
    const seasonName = element.dataset.seasonName;

    if (!seasonId || !seasonName) {
        console.error('[recreate-discord-resources] Missing season ID or name');
        return;
    }

    if (typeof recreateDiscordResources === 'function') {
        recreateDiscordResources(seasonId, seasonName);
    } else {
        console.error('[recreate-discord-resources] recreateDiscordResources function not found');
    }
});

/**
 * Toggle Settings Action (Schedule Preview)
 * Toggles visibility of schedule settings panel
 */
EventDelegation.register('toggle-settings', function(element, e) {
    e.preventDefault();

    if (typeof toggleScheduleSettings === 'function') {
        toggleScheduleSettings();
    } else {
        console.error('[toggle-settings] toggleScheduleSettings function not found');
    }
});

/**
 * Delete Schedule Action (Schedule Preview)
 * Deletes the generated schedule
 */
EventDelegation.register('delete-schedule', function(element, e) {
    e.preventDefault();

    if (typeof deleteSchedule === 'function') {
        deleteSchedule();
    } else {
        console.error('[delete-schedule] deleteSchedule function not found');
    }
});

/**
 * Commit Schedule Action (Schedule Preview)
 * Commits the schedule and creates matches
 */
EventDelegation.register('commit-schedule', function(element, e) {
    e.preventDefault();

    if (typeof commitSchedule === 'function') {
        commitSchedule();
    } else {
        console.error('[commit-schedule] commitSchedule function not found');
    }
});

/**
 * Select for Swap Action (Schedule Preview)
 * Selects a match for team swapping
 */
EventDelegation.register('select-for-swap', function(element, e) {
    e.preventDefault();

    const matchId = parseInt(element.dataset.matchId);
    const matchDesc = element.dataset.matchDesc;

    if (!matchId || !matchDesc) {
        console.error('[select-for-swap] Missing match ID or description');
        return;
    }

    if (typeof selectForSwap === 'function') {
        selectForSwap(matchId, matchDesc);
    } else {
        console.error('[select-for-swap] selectForSwap function not found');
    }
});

/**
 * Execute Swap Action (Schedule Preview)
 * Executes the team swap
 */
EventDelegation.register('execute-swap', function(element, e) {
    e.preventDefault();

    if (typeof executeSwap === 'function') {
        executeSwap();
    } else {
        console.error('[execute-swap] executeSwap function not found');
    }
});

/**
 * Remove from Swap Action (Schedule Preview)
 * Removes a match from swap selection
 */
EventDelegation.register('remove-from-swap', function(element, e) {
    e.preventDefault();

    const swapIndex = parseInt(element.dataset.swapIndex);

    if (swapIndex === undefined || swapIndex === null) {
        console.error('[remove-from-swap] Missing swap index');
        return;
    }

    if (typeof removeFromSwap === 'function') {
        removeFromSwap(swapIndex);
    } else {
        console.error('[remove-from-swap] removeFromSwap function not found');
    }
});

/**
 * Remove Field Action (Config Page)
 * Removes a field from the configuration
 */
EventDelegation.register('remove-field', function(element, e) {
    e.preventDefault();

    if (typeof removeField === 'function') {
        removeField(element);
    } else {
        console.error('[remove-field] removeField function not found');
    }
});

/**
 * Add Field Action (Config Page)
 * Adds a new field to the configuration
 */
EventDelegation.register('add-field', function(element, e) {
    e.preventDefault();

    if (typeof addField === 'function') {
        addField();
    } else {
        console.error('[add-field] addField function not found');
    }
});

/**
 * Apply Template Action (Config Page)
 * Applies a configuration template
 */
EventDelegation.register('apply-template', function(element, e) {
    e.preventDefault();

    const template = element.dataset.template;

    if (!template) {
        console.error('[apply-template] Missing template type');
        return;
    }

    if (typeof applyTemplate === 'function') {
        applyTemplate(template);
    } else {
        console.error('[apply-template] applyTemplate function not found');
    }
});

/**
 * Add Week Config Action (Config Page)
 * Adds a new week configuration
 */
EventDelegation.register('add-week-config', function(element, e) {
    e.preventDefault();

    if (typeof addWeekConfig === 'function') {
        addWeekConfig();
    } else {
        console.error('[add-week-config] addWeekConfig function not found');
    }
});

/**
 * Generate Default Weeks Action (Config Page)
 * Auto-generates default week configuration
 */
EventDelegation.register('generate-default-weeks', function(element, e) {
    e.preventDefault();

    if (typeof generateDefaultWeeks === 'function') {
        generateDefaultWeeks();
    } else {
        console.error('[generate-default-weeks] generateDefaultWeeks function not found');
    }
});

/**
 * Clear Weeks Action (Config Page)
 * Clears all week configurations
 */
EventDelegation.register('clear-weeks', function(element, e) {
    e.preventDefault();

    if (typeof clearWeeks === 'function') {
        clearWeeks();
    } else {
        console.error('[clear-weeks] clearWeeks function not found');
    }
});

/**
 * Update Week Card Action (Config Page)
 * Updates week type when dropdown changes
 */
EventDelegation.register('update-week-card', function(element, e) {
    if (typeof updateWeekCard === 'function') {
        updateWeekCard(element);
    } else {
        console.error('[update-week-card] updateWeekCard function not found');
    }
});

/**
 * Remove Week Card Action (Config Page)
 * Removes a week configuration
 */
EventDelegation.register('remove-week-card', function(element, e) {
    e.preventDefault();

    if (typeof removeWeekCard === 'function') {
        removeWeekCard(element);
    } else {
        console.error('[remove-week-card] removeWeekCard function not found');
    }
});

/**
 * Close Toast Action
 * Closes/removes a toast notification
 */
EventDelegation.register('close-toast', function(element, e) {
    e.preventDefault();

    // Remove the toast (parent element)
    if (element.parentElement) {
        element.parentElement.remove();
    }
});

// ============================================================================
// PASS STUDIO ACTIONS
// ============================================================================

/**
 * Platform Toggle Action
 * Switches between Apple and Google wallet preview
 */
EventDelegation.register('toggle-platform', function(element, e) {
    e.preventDefault();

    const platform = element.dataset.platform;

    if (!platform) {
        console.error('[toggle-platform] Missing platform attribute');
        return;
    }

    if (window.PassStudio && typeof window.PassStudio.setPreviewPlatform === 'function') {
        window.PassStudio.setPreviewPlatform(platform);
    } else {
        console.error('[toggle-platform] PassStudio.setPreviewPlatform not available');
    }
});

/**
 * Update Pass Style Action
 * Changes pass layout style (generic, storeCard, eventTicket)
 * Triggered by change event on radio buttons
 */
EventDelegation.register('update-pass-style', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updatePassStylePreview === 'function') {
        window.PassStudio.updatePassStylePreview();
    } else {
        console.error('[update-pass-style] PassStudio.updatePassStylePreview not available');
    }
});

/**
 * Apply Color Preset Action
 * Applies predefined color schemes to the pass
 */
EventDelegation.register('apply-color-preset', function(element, e) {
    e.preventDefault();

    const bg = element.dataset.bg;
    const fg = element.dataset.fg;
    const label = element.dataset.label;

    if (!bg || !fg || !label) {
        console.error('[apply-color-preset] Missing color data attributes');
        return;
    }

    // Set color inputs
    const bgColorInput = document.getElementById('background_color');
    const fgColorInput = document.getElementById('foreground_color');
    const labelColorInput = document.getElementById('label_color');

    if (bgColorInput) bgColorInput.value = bg;
    if (fgColorInput) fgColorInput.value = fg;
    if (labelColorInput) labelColorInput.value = label;

    // Set text inputs
    const bgColorText = document.getElementById('background_color_text');
    const fgColorText = document.getElementById('foreground_color_text');
    const labelColorText = document.getElementById('label_color_text');

    if (bgColorText) bgColorText.value = bg;
    if (fgColorText) fgColorText.value = fg;
    if (labelColorText) labelColorText.value = label;

    // Update preview
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }

    // Mark unsaved
    if (window.PassStudio && typeof window.PassStudio.markUnsaved === 'function') {
        window.PassStudio.markUnsaved();
    }
});

/**
 * Sync Color Input Action
 * Syncs color picker with text input and vice versa
 */
EventDelegation.register('sync-color-input', function(element, e) {
    const targetId = element.dataset.target;
    if (!targetId) return;

    const target = document.getElementById(targetId);
    if (!target) return;

    // Sync the values
    if (element.type === 'color') {
        // Color picker changed - update text input
        const textInput = document.getElementById(targetId + '_text');
        if (textInput) textInput.value = element.value;
    } else {
        // Text input changed - update color picker
        target.value = element.value;
    }

    // Update preview
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }
});

/**
 * Update Preview Field Action
 * Updates specific field in preview (e.g., logo text)
 */
EventDelegation.register('update-preview-field', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }
});

/**
 * Toggle Logo Visibility Action
 * Shows/hides logo in preview
 */
EventDelegation.register('toggle-logo-visibility', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.toggleLogoVisibility === 'function') {
        window.PassStudio.toggleLogoVisibility();
    }
});

/**
 * Open Asset Cropper Action
 * Opens modal to upload/crop pass assets
 */
EventDelegation.register('open-asset-cropper', function(element, e) {
    e.preventDefault();

    const assetType = element.dataset.assetType;

    if (!assetType) {
        console.error('[open-asset-cropper] Missing asset type');
        return;
    }

    if (window.PassStudio && typeof window.PassStudio.openAssetCropper === 'function') {
        window.PassStudio.openAssetCropper(assetType);
    } else {
        console.error('[open-asset-cropper] PassStudio.openAssetCropper not available');
    }
});

/**
 * Update Google Preview Action
 * Updates Google Wallet preview with URL changes
 */
EventDelegation.register('update-google-preview', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updateGooglePreview === 'function') {
        window.PassStudio.updateGooglePreview();
    }
});

/**
 * Update Barcode Preview Action
 * Shows/hides barcode in preview
 */
EventDelegation.register('update-barcode-preview', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updateBarcodePreview === 'function') {
        window.PassStudio.updateBarcodePreview();
    }
});

/**
 * Save Appearance Action
 * Saves appearance settings to server
 */
EventDelegation.register('save-appearance', function(element, e) {
    e.preventDefault();

    if (window.PassStudio && typeof window.PassStudio.saveAppearance === 'function') {
        window.PassStudio.saveAppearance();
    } else {
        console.error('[save-appearance] PassStudio.saveAppearance not available');
    }
});

/**
 * Initialize Defaults Action
 * Loads default field configuration for pass
 */
EventDelegation.register('initialize-defaults', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.initializeDefaults === 'function') {
        window.FieldsManager.initializeDefaults();
    } else {
        console.error('[initialize-defaults] FieldsManager.initializeDefaults not available');
    }
});

/**
 * Add Field Action
 * Opens modal to add new pass field
 */
EventDelegation.register('add-field', function(element, e) {
    e.preventDefault();

    const fieldType = element.dataset.fieldType;

    if (!fieldType) {
        console.error('[add-field] Missing field type');
        return;
    }

    if (window.FieldsManager && typeof window.FieldsManager.openAddFieldModal === 'function') {
        window.FieldsManager.openAddFieldModal(fieldType);
    } else {
        console.error('[add-field] FieldsManager.openAddFieldModal not available');
    }
});

/**
 * Create Field Action
 * Creates new field from modal data
 */
EventDelegation.register('create-field', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.createField === 'function') {
        window.FieldsManager.createField();
    } else {
        console.error('[create-field] FieldsManager.createField not available');
    }
});

/**
 * Save Fields Action
 * Saves all field configurations to server
 */
EventDelegation.register('save-fields', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.saveFields === 'function') {
        window.FieldsManager.saveFields();
    } else {
        console.error('[save-fields] FieldsManager.saveFields not available');
    }
});

/**
 * Reset Fields Action
 * Resets fields to last saved state
 */
EventDelegation.register('reset-fields', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.resetFields === 'function') {
        window.FieldsManager.resetFields();
    } else {
        console.error('[reset-fields] FieldsManager.resetFields not available');
    }
});

/**
 * Insert Variable Action
 * Inserts template variable at cursor position
 */
EventDelegation.register('insert-variable', function(element, e) {
    e.preventDefault();

    const variableName = element.dataset.variableName;

    if (!variableName) {
        console.error('[insert-variable] Missing variable name');
        return;
    }

    if (window.FieldsManager && typeof window.FieldsManager.insertVariableInAdd === 'function') {
        window.FieldsManager.insertVariableInAdd(variableName);
    } else {
        console.error('[insert-variable] FieldsManager.insertVariableInAdd not available');
    }
});

// ============================================================================
// USER APPROVAL MANAGEMENT ACTIONS
// ============================================================================

/**
 * Refresh Approval Stats Action
 * Manually refreshes user approval statistics display
 */
EventDelegation.register('refresh-approval-stats', function(element, e) {
    e.preventDefault();

    if (typeof window.refreshStats === 'function') {
        window.refreshStats();
    } else {
        console.error('[refresh-approval-stats] refreshStats function not found');
    }
});

/**
 * Show Player Details Action
 * Opens modal showing detailed player information
 */
EventDelegation.register('show-player-details', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;

    if (!userId) {
        console.error('[show-player-details] Missing user ID');
        return;
    }

    if (typeof window.showPlayerDetails === 'function') {
        window.showPlayerDetails(parseInt(userId));
    } else {
        console.error('[show-player-details] showPlayerDetails function not found');
    }
});

/**
 * Show Approval Modal Action
 * Opens modal to approve a user and assign them to a league
 */
EventDelegation.register('show-approval-modal', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;

    if (!userId) {
        console.error('[show-approval-modal] Missing user ID');
        return;
    }

    if (typeof window.showApprovalModal === 'function') {
        window.showApprovalModal(parseInt(userId));
    } else {
        console.error('[show-approval-modal] showApprovalModal function not found');
    }
});

/**
 * Show Denial Modal Action
 * Opens modal to deny a user application
 */
EventDelegation.register('show-denial-modal', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;

    if (!userId) {
        console.error('[show-denial-modal] Missing user ID');
        return;
    }

    if (typeof window.showDenialModal === 'function') {
        window.showDenialModal(parseInt(userId));
    } else {
        console.error('[show-denial-modal] showDenialModal function not found');
    }
});

/**
 * Approve User Action
 * Submits user approval form
 */
EventDelegation.register('approve-user', function(element, e) {
    e.preventDefault();

    if (typeof window.submitApproval === 'function') {
        window.submitApproval();
    } else {
        console.error('[approve-user] submitApproval function not found');
    }
});

/**
 * Deny User Action
 * Submits user denial form
 */
EventDelegation.register('deny-user', function(element, e) {
    e.preventDefault();

    if (typeof window.submitDenial === 'function') {
        window.submitDenial();
    } else {
        console.error('[deny-user] submitDenial function not found');
    }
});

// Make globally available
window.EventDelegation = EventDelegation;

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = EventDelegation;
}
