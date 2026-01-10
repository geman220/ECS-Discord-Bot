/**
 * Calendar Filters Module
 *
 * Handles filtering of calendar events by type (matches, league events).
 * Provides UI controls and state management for calendar filtering.
 */
// ES Module
'use strict';

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
export function init(options = {}) {
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
export function loadFilters() {
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
export function getFilters() {
    return { ...filters };
}

/**
 * Set filters programmatically
 * @param {Object} newFilters - New filter values
 */
export function setFilters(newFilters) {
    filters = { ...filters, ...newFilters };
    syncUIWithState();
    notifyFilterChange();
}

/**
 * Reset filters to defaults
 */
export function resetFilters() {
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
export function applyFilters(events, userContext = {}) {
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
export function getQueryParams() {
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
export function createFilterControlsHTML(options = {}) {
    const { divisions = ['Premier', 'Classic'], isAdmin = false } = options;

    return `
    <div class="calendar-filters">
        <h6 class="font-semibold mb-3 text-gray-900 dark:text-white">
            <i class="ti ti-filter me-2"></i>Filters
        </h6>

        <!-- Event Type Filters -->
        <div class="mb-3">
            <label class="block mb-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">Event Types</label>
            <label class="relative inline-flex items-center cursor-pointer mb-2 w-full">
                <input type="checkbox" id="filterShowMatches" class="sr-only peer" checked>
                <div class="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-ecs-green/20 dark:peer-focus:ring-ecs-green/30 rounded-full peer dark:bg-gray-600 peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-gray-500 peer-checked:bg-ecs-green"></div>
                <span class="ms-3 text-sm font-medium text-gray-900 dark:text-gray-300"><i class="ti ti-ball-football me-1"></i>Matches</span>
            </label>
            <label class="relative inline-flex items-center cursor-pointer mb-2 w-full">
                <input type="checkbox" id="filterShowLeagueEvents" class="sr-only peer" checked>
                <div class="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-ecs-green/20 dark:peer-focus:ring-ecs-green/30 rounded-full peer dark:bg-gray-600 peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-gray-500 peer-checked:bg-ecs-green"></div>
                <span class="ms-3 text-sm font-medium text-gray-900 dark:text-gray-300"><i class="ti ti-calendar-event me-1"></i>League Events</span>
            </label>
        </div>

        <!-- Team Filter (if not admin) -->
        ${!isAdmin ? `
        <div class="mb-3">
            <label class="block mb-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">View</label>
            <label class="relative inline-flex items-center cursor-pointer w-full">
                <input type="checkbox" id="filterMyTeamOnly" class="sr-only peer">
                <div class="w-9 h-5 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-ecs-green/20 dark:peer-focus:ring-ecs-green/30 rounded-full peer dark:bg-gray-600 peer-checked:after:translate-x-full rtl:peer-checked:after:-translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all dark:border-gray-500 peer-checked:bg-ecs-green"></div>
                <span class="ms-3 text-sm font-medium text-gray-900 dark:text-gray-300"><i class="ti ti-users me-1"></i>My Team Only</span>
            </label>
        </div>
        ` : ''}

        <!-- Division Filters -->
        <div class="mb-3">
            <label class="flex justify-between items-center mb-2 text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">
                <span>Divisions</span>
                <span>
                    <button type="button" class="text-ecs-green hover:text-ecs-green-dark text-sm p-0 me-2" id="filterSelectAllDivisions">All</button>
                    <button type="button" class="text-ecs-green hover:text-ecs-green-dark text-sm p-0" id="filterClearAllDivisions">None</button>
                </span>
            </label>
            ${divisions.map(div => `
            <div class="flex items-center mb-2">
                <input type="checkbox" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600 filter-division" value="${div}" id="filterDiv${div}" checked>
                <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="filterDiv${div}">
                    <span class="inline-block w-3 h-3 rounded ${div === 'Premier' ? 'bg-blue-600' : 'bg-green-600'} me-1"></span>
                    ${div}
                </label>
            </div>
            `).join('')}
        </div>

        <!-- Reset Button -->
        <div class="w-full">
            <button type="button" class="w-full text-gray-900 bg-white border border-gray-300 focus:outline-none hover:bg-gray-100 focus:ring-4 focus:ring-gray-100 font-medium rounded-lg text-sm px-5 py-2.5 dark:bg-gray-800 dark:text-white dark:border-gray-600 dark:hover:bg-gray-700 dark:focus:ring-gray-700" id="filterResetBtn">
                <i class="ti ti-refresh me-1"></i>Reset Filters
            </button>
        </div>
    </div>
    `;
}

// CalendarFilterManager object for backward compatibility
export const CalendarFilterManager = {
    init,
    getFilters,
    setFilters,
    resetFilters,
    loadFilters,
    applyFilters,
    getQueryParams,
    createFilterControlsHTML
};

// Backward compatibility
window.CalendarFilterManager = CalendarFilterManager;
