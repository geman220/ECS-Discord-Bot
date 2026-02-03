'use strict';

/**
 * Draft Enhanced Search & Filter
 * Search, filter, and sort functionality
 * @module draft-enhanced/search-filter
 */

/**
 * Setup live search functionality
 * Note: Filter and pagination event handlers are now managed via event delegation
 * in event-delegation/handlers/draft-system.js using data-on-input, data-on-change,
 * and data-action attributes. This function is kept for backwards compatibility
 * but no longer adds event listeners (to prevent duplicate handlers).
 */
export function setupLiveSearch() {
    // Event listeners are now handled by event delegation in draft-system.js
    // using data-on-input="draft-filter-players", data-on-change="draft-filter-players",
    // data-on-change="draft-change-page-size", data-action="draft-prev-page", etc.
    //
    // This function is kept for backwards compatibility and any future
    // initialization needs that don't involve adding duplicate event listeners.
}

/**
 * Pagination state management
 */
export const PaginationState = {
    currentPage: 1,
    pageSize: 24,  // Default: 24 players per page (fits nicely in 4-col grid)
    totalPlayers: 0,
    filteredPlayers: []
};

/**
 * Normalize position name for display
 * @param {string} position
 * @returns {string}
 */
export function normalizePosition(position) {
    if (!position) return 'Any Position';
    return position
        .replace(/_/g, ' ')
        .split(' ')
        .map(word => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
        .join(' ');
}

/**
 * Filter players in real-time
 */
export function filterPlayers() {
    const searchTerm = document.getElementById('playerSearch')?.value.toLowerCase() || '';
    const positionFilter = document.getElementById('positionFilter')?.value.toLowerCase() || '';
    const sortBy = document.getElementById('sortBy')?.value || 'name';
    const attendanceFilter = document.getElementById('attendanceFilter')?.value || '';
    const goalsFilter = document.getElementById('goalsFilter')?.value || '';
    const prevDraftFilter = document.getElementById('prevDraftFilter')?.value || '';

    const availablePlayersContainer = document.getElementById('available-players');
    // Use :scope > to only select direct children (cards), NOT buttons inside cards
    const playerCards = availablePlayersContainer?.querySelectorAll(':scope > [data-player-id]') || [];

    let visibleCount = 0;
    let filteredPlayers = [];

    // Filter and collect visible players
    playerCards.forEach(card => {
        const playerName = card.getAttribute('data-player-name') || '';
        const playerPosition = card.getAttribute('data-position') || '';
        const attendance = parseFloat(card.getAttribute('data-attendance'));
        const goals = parseInt(card.getAttribute('data-goals')) || 0;
        const prevDraft = parseInt(card.getAttribute('data-prev-draft')) || 999;

        // Check search term match
        const matchesSearch = !searchTerm || playerName.includes(searchTerm);

        // Check position filter match (use includes for partial matching)
        const matchesPosition = !positionFilter || playerPosition.includes(positionFilter);

        // Check attendance filter match
        let matchesAttendance = true;
        if (attendanceFilter) {
            if (attendanceFilter === 'unknown') {
                matchesAttendance = isNaN(attendance) || attendance < 0;
            } else if (attendanceFilter === '80-100') {
                matchesAttendance = !isNaN(attendance) && attendance >= 80;
            } else if (attendanceFilter === '60-79') {
                matchesAttendance = !isNaN(attendance) && attendance >= 60 && attendance < 80;
            } else if (attendanceFilter === '0-59') {
                matchesAttendance = !isNaN(attendance) && attendance >= 0 && attendance < 60;
            }
        }

        // Check goals filter match
        let matchesGoals = true;
        if (goalsFilter) {
            if (goalsFilter === '10+') matchesGoals = goals >= 10;
            else if (goalsFilter === '5-9') matchesGoals = goals >= 5 && goals < 10;
            else if (goalsFilter === '1-4') matchesGoals = goals >= 1 && goals < 5;
            else if (goalsFilter === '0') matchesGoals = goals === 0;
        }

        // Check previous draft filter match
        let matchesPrevDraft = true;
        if (prevDraftFilter) {
            if (prevDraftFilter === '1-20') matchesPrevDraft = prevDraft >= 1 && prevDraft <= 20;
            else if (prevDraftFilter === '21-50') matchesPrevDraft = prevDraft >= 21 && prevDraft <= 50;
            else if (prevDraftFilter === '51+') matchesPrevDraft = prevDraft > 50 && prevDraft < 999;
            else if (prevDraftFilter === 'new') matchesPrevDraft = prevDraft >= 999;
        }

        const isVisible = matchesSearch && matchesPosition && matchesAttendance && matchesGoals && matchesPrevDraft;

        if (isVisible) {
            visibleCount++;

            // Collect data for sorting
            const experience = parseInt(card.getAttribute('data-experience')) || 0;

            filteredPlayers.push({
                element: card,
                name: playerName,
                experience: experience,
                attendance: isNaN(attendance) ? -1 : attendance,
                goals: goals,
                prevDraft: prevDraft
            });
        }

        // Hide all cards initially - pagination will show the right ones
        card.classList.add('hidden');
    });

    // Sort the visible players
    if (sortBy && filteredPlayers.length > 0) {
        sortPlayers(filteredPlayers, sortBy);
    }

    // Apply pagination
    paginatePlayers(filteredPlayers);

    // Update both counters with total filtered (not just current page)
    updateAvailablePlayerCount(visibleCount);

    // Show/hide empty state (using Tailwind's hidden class)
    const emptyState = document.getElementById('emptyState');
    if (emptyState) {
        if (visibleCount === 0) {
            emptyState.classList.remove('hidden');
            emptyState.classList.add('is-visible');
        } else {
            emptyState.classList.add('hidden');
            emptyState.classList.remove('is-visible');
        }
    }

    console.log(`Filtered players: ${visibleCount} total, showing page ${PaginationState.currentPage}`);
}

/**
 * Paginate players - show only the current page
 * @param {Array} filteredPlayers
 */
export function paginatePlayers(filteredPlayers) {
    PaginationState.filteredPlayers = filteredPlayers;
    PaginationState.totalPlayers = filteredPlayers.length;

    const pageSize = PaginationState.pageSize === 'all' ? filteredPlayers.length : PaginationState.pageSize;
    const totalPages = pageSize > 0 ? Math.ceil(filteredPlayers.length / pageSize) : 1;

    // Ensure current page is valid
    if (PaginationState.currentPage > totalPages) {
        PaginationState.currentPage = Math.max(1, totalPages);
    }

    // Calculate range for current page
    const start = PaginationState.pageSize === 'all' ? 0 : (PaginationState.currentPage - 1) * pageSize;
    const end = PaginationState.pageSize === 'all' ? filteredPlayers.length : start + pageSize;

    // Show only current page, hide others
    for (let i = 0; i < filteredPlayers.length; i++) {
        if (i >= start && i < end) {
            filteredPlayers[i].element.classList.remove('hidden');
        } else {
            filteredPlayers[i].element.classList.add('hidden');
        }
    }

    updatePaginationUI(totalPages);
}

/**
 * Update pagination UI controls
 * @param {number} totalPages
 */
export function updatePaginationUI(totalPages) {
    const pageInfo = document.getElementById('pageInfo');
    const prevBtn = document.getElementById('prevPage');
    const nextBtn = document.getElementById('nextPage');
    const paginationControls = document.getElementById('paginationControls');

    if (pageInfo) {
        pageInfo.textContent = `Page ${PaginationState.currentPage} of ${Math.max(1, totalPages)}`;
    }
    if (prevBtn) {
        prevBtn.disabled = PaginationState.currentPage <= 1;
    }
    if (nextBtn) {
        nextBtn.disabled = PaginationState.currentPage >= totalPages;
    }

    // Hide pagination if only one page or showing all
    if (paginationControls) {
        const shouldHide = totalPages <= 1 || PaginationState.pageSize === 'all';
        paginationControls.classList.toggle('hidden', shouldHide);
    }
}

/**
 * Go to next page
 */
export function nextPage() {
    const pageSize = PaginationState.pageSize === 'all' ? PaginationState.totalPlayers : PaginationState.pageSize;
    const totalPages = Math.ceil(PaginationState.totalPlayers / pageSize);

    if (PaginationState.currentPage < totalPages) {
        PaginationState.currentPage++;
        paginatePlayers(PaginationState.filteredPlayers);
    }
}

/**
 * Go to previous page
 */
export function prevPage() {
    if (PaginationState.currentPage > 1) {
        PaginationState.currentPage--;
        paginatePlayers(PaginationState.filteredPlayers);
    }
}

/**
 * Change page size
 * @param {number|string} newSize
 */
export function changePageSize(newSize) {
    PaginationState.pageSize = newSize === 'all' ? 'all' : parseInt(newSize);
    PaginationState.currentPage = 1;  // Reset to first page
    paginatePlayers(PaginationState.filteredPlayers);
}

/**
 * Clear all filters and reset to defaults
 */
export function clearFilters() {
    const searchInput = document.getElementById('playerSearch');
    const positionFilter = document.getElementById('positionFilter');
    const sortBy = document.getElementById('sortBy');
    const attendanceFilter = document.getElementById('attendanceFilter');
    const goalsFilter = document.getElementById('goalsFilter');
    const prevDraftFilter = document.getElementById('prevDraftFilter');

    if (searchInput) searchInput.value = '';
    if (positionFilter) positionFilter.value = '';
    if (sortBy) sortBy.value = 'name';
    if (attendanceFilter) attendanceFilter.value = '';
    if (goalsFilter) goalsFilter.value = '';
    if (prevDraftFilter) prevDraftFilter.value = '';

    PaginationState.currentPage = 1;
    filterPlayers();
}

/**
 * Sort players based on selected criteria
 * @param {Array} players
 * @param {string} sortBy
 */
export function sortPlayers(players, sortBy) {
    const container = document.getElementById('available-players');
    if (!container) return;

    players.sort((a, b) => {
        switch (sortBy) {
            case 'experience':
                return b.experience - a.experience; // Highest first
            case 'attendance':
                // Handle -1 (unknown) - put at the end
                if (a.attendance === -1 && b.attendance === -1) return 0;
                if (a.attendance === -1) return 1;
                if (b.attendance === -1) return -1;
                return b.attendance - a.attendance; // Highest first
            case 'goals':
                return b.goals - a.goals; // Highest first
            case 'prev_draft':
                // Put new players (999) at the end, otherwise sort by position
                if (a.prevDraft === 999 && b.prevDraft === 999) return 0;
                if (a.prevDraft === 999) return 1;
                if (b.prevDraft === 999) return -1;
                return a.prevDraft - b.prevDraft; // Lowest (best) draft pick first
            case 'name':
            default:
                return a.name.localeCompare(b.name); // Alphabetical
        }
    });

    // Reorder elements in the DOM
    players.forEach(player => {
        container.appendChild(player.element);
    });
}

/**
 * Update available player count in both locations
 * @param {number} count
 */
export function updateAvailablePlayerCount(count) {
    const availableCount = document.getElementById('availableCount');
    const availablePlayersCount = document.getElementById('available-players-count');

    if (availableCount) {
        availableCount.textContent = count;
    }
    if (availablePlayersCount) {
        availablePlayersCount.textContent = count;
    }
}
