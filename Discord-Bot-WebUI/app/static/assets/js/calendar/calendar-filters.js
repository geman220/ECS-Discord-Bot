/**
 * Calendar Filters Module
 *
 * Handles filtering of calendar events by type (matches, league events).
 * Provides UI controls and state management for calendar filtering.
 */

'use strict';

// Calendar Filter Manager
const CalendarFilterManager = (function() {
    // Filter state
    let filters = {
        showMatches: true,
        showLeagueEvents: true,
        showMyTeamOnly: false,
        divisions: [] // Empty means all divisions
    };

    // Callbacks
    let onFilterChange = null;

    /**
     * Initialize the filter manager
     * @param {Object} options - Configuration options
     */
    function init(options = {}) {
        // Set initial filter state from options
        if (options.initialFilters) {
            filters = { ...filters, ...options.initialFilters };
        }

        // Set callback for when filters change
        if (options.onFilterChange) {
            onFilterChange = options.onFilterChange;
        }

        // Bind event handlers
        bindEvents();

        // Apply initial state to UI
        syncUIWithState();
    }

    /**
     * Bind filter control event handlers
     */
    function bindEvents() {
        // Show matches toggle
        const showMatchesToggle = document.getElementById('filterShowMatches');
        if (showMatchesToggle) {
            showMatchesToggle.addEventListener('change', function() {
                filters.showMatches = this.checked;
                notifyFilterChange();
            });
        }

        // Show league events toggle
        const showLeagueEventsToggle = document.getElementById('filterShowLeagueEvents');
        if (showLeagueEventsToggle) {
            showLeagueEventsToggle.addEventListener('change', function() {
                filters.showLeagueEvents = this.checked;
                notifyFilterChange();
            });
        }

        // My team only toggle
        const myTeamOnlyToggle = document.getElementById('filterMyTeamOnly');
        if (myTeamOnlyToggle) {
            myTeamOnlyToggle.addEventListener('change', function() {
                filters.showMyTeamOnly = this.checked;
                notifyFilterChange();
            });
        }

        // Division checkboxes
        const divisionCheckboxes = document.querySelectorAll('.filter-division');
        divisionCheckboxes.forEach(checkbox => {
            checkbox.addEventListener('change', function() {
                updateDivisionFilters();
                notifyFilterChange();
            });
        });

        // Select all divisions
        const selectAllDivisions = document.getElementById('filterSelectAllDivisions');
        if (selectAllDivisions) {
            selectAllDivisions.addEventListener('click', function() {
                document.querySelectorAll('.filter-division').forEach(cb => {
                    cb.checked = true;
                });
                updateDivisionFilters();
                notifyFilterChange();
            });
        }

        // Clear all divisions
        const clearAllDivisions = document.getElementById('filterClearAllDivisions');
        if (clearAllDivisions) {
            clearAllDivisions.addEventListener('click', function() {
                document.querySelectorAll('.filter-division').forEach(cb => {
                    cb.checked = false;
                });
                updateDivisionFilters();
                notifyFilterChange();
            });
        }
    }

    /**
     * Update division filters from checkboxes
     */
    function updateDivisionFilters() {
        const checkedDivisions = [];
        document.querySelectorAll('.filter-division:checked').forEach(cb => {
            checkedDivisions.push(cb.value);
        });
        filters.divisions = checkedDivisions;
    }

    /**
     * Sync UI controls with current filter state
     */
    function syncUIWithState() {
        const showMatchesToggle = document.getElementById('filterShowMatches');
        if (showMatchesToggle) {
            showMatchesToggle.checked = filters.showMatches;
        }

        const showLeagueEventsToggle = document.getElementById('filterShowLeagueEvents');
        if (showLeagueEventsToggle) {
            showLeagueEventsToggle.checked = filters.showLeagueEvents;
        }

        const myTeamOnlyToggle = document.getElementById('filterMyTeamOnly');
        if (myTeamOnlyToggle) {
            myTeamOnlyToggle.checked = filters.showMyTeamOnly;
        }

        // Division checkboxes
        document.querySelectorAll('.filter-division').forEach(cb => {
            cb.checked = filters.divisions.length === 0 || filters.divisions.includes(cb.value);
        });
    }

    /**
     * Notify listeners that filters have changed
     */
    function notifyFilterChange() {
        // Save to localStorage for persistence
        saveFilters();

        // Call the callback if set
        if (onFilterChange) {
            onFilterChange(filters);
        }

        // Dispatch custom event for other modules
        document.dispatchEvent(new CustomEvent('calendarFiltersChanged', {
            detail: { filters: getFilters() }
        }));
    }

    /**
     * Save filters to localStorage
     */
    function saveFilters() {
        try {
            localStorage.setItem('calendarFilters', JSON.stringify(filters));
        } catch (e) {
            console.warn('Could not save calendar filters to localStorage:', e);
        }
    }

    /**
     * Load filters from localStorage
     */
    function loadFilters() {
        try {
            const saved = localStorage.getItem('calendarFilters');
            if (saved) {
                filters = { ...filters, ...JSON.parse(saved) };
            }
        } catch (e) {
            console.warn('Could not load calendar filters from localStorage:', e);
        }
        return filters;
    }

    /**
     * Get current filters
     * @returns {Object} Current filter state
     */
    function getFilters() {
        return { ...filters };
    }

    /**
     * Set filters programmatically
     * @param {Object} newFilters - New filter values
     */
    function setFilters(newFilters) {
        filters = { ...filters, ...newFilters };
        syncUIWithState();
        notifyFilterChange();
    }

    /**
     * Reset filters to defaults
     */
    function resetFilters() {
        filters = {
            showMatches: true,
            showLeagueEvents: true,
            showMyTeamOnly: false,
            divisions: []
        };
        syncUIWithState();
        notifyFilterChange();
    }

    /**
     * Apply filters to an array of events
     * @param {Array} events - Events to filter
     * @param {Object} userContext - User context (teams, isAdmin, etc.)
     * @returns {Array} Filtered events
     */
    function applyFilters(events, userContext = {}) {
        return events.filter(event => {
            // Check event type filters
            if (event.type === 'match' && !filters.showMatches) {
                return false;
            }
            if (event.type === 'league_event' && !filters.showLeagueEvents) {
                return false;
            }

            // Check division filter (matches only)
            if (event.type === 'match' && filters.divisions.length > 0) {
                const eventDivision = event.extendedProps?.division || event.division;
                if (!filters.divisions.includes(eventDivision)) {
                    return false;
                }
            }

            // My team only filter is handled server-side via API parameter
            // (role-based visibility service)

            return true;
        });
    }

    /**
     * Get filter query params for API requests
     * @returns {Object} Query parameters
     */
    function getQueryParams() {
        return {
            show_matches: filters.showMatches,
            show_league_events: filters.showLeagueEvents,
            my_team_only: filters.showMyTeamOnly,
            divisions: filters.divisions.length > 0 ? filters.divisions.join(',') : undefined
        };
    }

    /**
     * Create the filter controls HTML
     * @param {Object} options - Options (divisions list, isAdmin, etc.)
     * @returns {string} HTML string
     */
    function createFilterControlsHTML(options = {}) {
        const { divisions = ['Premier', 'Classic'], isAdmin = false } = options;

        return `
        <div class="calendar-filters">
            <h6 class="fw-semibold mb-3">
                <i class="ti ti-filter me-2"></i>Filters
            </h6>

            <!-- Event Type Filters -->
            <div class="mb-3">
                <label class="form-label text-muted small text-uppercase">Event Types</label>
                <div class="form-check form-switch mb-2">
                    <input class="form-check-input" type="checkbox" id="filterShowMatches" checked>
                    <label class="form-check-label" for="filterShowMatches">
                        <i class="ti ti-ball-football me-1"></i>Matches
                    </label>
                </div>
                <div class="form-check form-switch mb-2">
                    <input class="form-check-input" type="checkbox" id="filterShowLeagueEvents" checked>
                    <label class="form-check-label" for="filterShowLeagueEvents">
                        <i class="ti ti-calendar-event me-1"></i>League Events
                    </label>
                </div>
            </div>

            <!-- Team Filter (if not admin) -->
            ${!isAdmin ? `
            <div class="mb-3">
                <label class="form-label text-muted small text-uppercase">View</label>
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="filterMyTeamOnly">
                    <label class="form-check-label" for="filterMyTeamOnly">
                        <i class="ti ti-users me-1"></i>My Team Only
                    </label>
                </div>
            </div>
            ` : ''}

            <!-- Division Filters -->
            <div class="mb-3">
                <label class="form-label text-muted small text-uppercase d-flex justify-content-between align-items-center">
                    <span>Divisions</span>
                    <span>
                        <button type="button" class="btn btn-link btn-sm p-0 me-2" id="filterSelectAllDivisions">All</button>
                        <button type="button" class="btn btn-link btn-sm p-0" id="filterClearAllDivisions">None</button>
                    </span>
                </label>
                ${divisions.map(div => `
                <div class="form-check mb-2">
                    <input class="form-check-input filter-division" type="checkbox" value="${div}" id="filterDiv${div}" checked>
                    <label class="form-check-label" for="filterDiv${div}">
                        <span class="badge bg-${div === 'Premier' ? 'primary' : 'success'} me-1">&nbsp;</span>
                        ${div}
                    </label>
                </div>
                `).join('')}
            </div>

            <!-- Reset Button -->
            <div class="d-grid">
                <button type="button" class="btn btn-outline-secondary btn-sm" id="filterResetBtn">
                    <i class="ti ti-refresh me-1"></i>Reset Filters
                </button>
            </div>
        </div>
        `;
    }

    // Public API
    return {
        init,
        getFilters,
        setFilters,
        resetFilters,
        loadFilters,
        applyFilters,
        getQueryParams,
        createFilterControlsHTML
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = CalendarFilterManager;
}
