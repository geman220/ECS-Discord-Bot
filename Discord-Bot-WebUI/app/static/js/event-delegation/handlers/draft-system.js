import { EventDelegation } from '../core.js';

/**
 * Draft System Action Handlers
 * Handles player drafting, team assignment, filtering, pagination, and draft UI
 */

// ============================================================================
// PAGINATION STATE
// ============================================================================

const DraftPaginationState = {
    currentPage: 1,
    pageSize: 24,
    totalPlayers: 0,
    filteredPlayers: []
};

// ============================================================================
// FILTER AND PAGINATION FUNCTIONS
// ============================================================================

/**
 * Main filter function - filters, sorts, and paginates players
 */
function filterDraftPlayers() {
    const searchTerm = document.getElementById('playerSearch')?.value.toLowerCase() || '';
    const positionFilter = document.getElementById('positionFilter')?.value.toLowerCase() || '';
    const sortBy = document.getElementById('sortBy')?.value || 'name';
    const attendanceFilter = document.getElementById('attendanceFilter')?.value || '';
    const goalsFilter = document.getElementById('goalsFilter')?.value || '';
    const prevDraftFilter = document.getElementById('prevDraftFilter')?.value || '';

    const container = document.getElementById('available-players');
    // Use :scope > to only select direct children (cards), NOT buttons inside cards
    const playerCards = container?.querySelectorAll(':scope > [data-player-id]') || [];

    let visibleCount = 0;
    let filteredPlayers = [];

    playerCards.forEach(card => {
        const playerName = card.getAttribute('data-player-name') || '';
        const playerPosition = card.getAttribute('data-position') || '';
        const attendance = parseFloat(card.getAttribute('data-attendance'));
        const goals = parseInt(card.getAttribute('data-goals')) || 0;
        const prevDraft = parseInt(card.getAttribute('data-prev-draft')) || 999;
        const experience = parseInt(card.getAttribute('data-experience')) || 0;

        // Search match
        const matchesSearch = !searchTerm || playerName.includes(searchTerm);

        // Position match (partial)
        const matchesPosition = !positionFilter || playerPosition.includes(positionFilter);

        // Attendance match
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

        // Goals match
        let matchesGoals = true;
        if (goalsFilter) {
            if (goalsFilter === '10+') matchesGoals = goals >= 10;
            else if (goalsFilter === '5-9') matchesGoals = goals >= 5 && goals < 10;
            else if (goalsFilter === '1-4') matchesGoals = goals >= 1 && goals < 5;
            else if (goalsFilter === '0') matchesGoals = goals === 0;
        }

        // Previous draft match
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
            filteredPlayers.push({
                id: card.getAttribute('data-player-id'),
                element: card,
                name: playerName,
                experience: experience,
                attendance: isNaN(attendance) ? -1 : attendance,
                goals: goals,
                prevDraft: prevDraft
            });
        }

        // Hide all initially - pagination will show correct ones
        card.classList.add('hidden');
    });

    // Sort
    sortDraftPlayers(filteredPlayers, sortBy, container);

    // Paginate
    paginateDraftPlayers(filteredPlayers);

    // Update counts
    updateDraftPlayerCount(visibleCount);

    // Empty state
    const emptyState = document.getElementById('emptyState');
    if (emptyState) {
        if (visibleCount === 0) {
            emptyState.classList.remove('hidden');
        } else {
            emptyState.classList.add('hidden');
        }
    }
}

/**
 * Sort players
 */
function sortDraftPlayers(players, sortBy, container) {
    if (!container) return;

    players.sort((a, b) => {
        switch (sortBy) {
            case 'experience':
                return b.experience - a.experience;
            case 'attendance':
                if (a.attendance === -1 && b.attendance === -1) return 0;
                if (a.attendance === -1) return 1;
                if (b.attendance === -1) return -1;
                return b.attendance - a.attendance;
            case 'goals':
                return b.goals - a.goals;
            case 'prev_draft':
                if (a.prevDraft === 999 && b.prevDraft === 999) return 0;
                if (a.prevDraft === 999) return 1;
                if (b.prevDraft === 999) return -1;
                return a.prevDraft - b.prevDraft;
            case 'name':
            default:
                return a.name.localeCompare(b.name);
        }
    });

    // Reorder DOM
    players.forEach(p => container.appendChild(p.element));
}

/**
 * Paginate players - show only current page
 * Uses fresh DOM queries to avoid stale element references
 */
function paginateDraftPlayers(filteredPlayers) {
    DraftPaginationState.filteredPlayers = filteredPlayers;
    DraftPaginationState.totalPlayers = filteredPlayers.length;

    const pageSize = DraftPaginationState.pageSize === 'all' ? filteredPlayers.length : DraftPaginationState.pageSize;
    const totalPages = pageSize > 0 ? Math.ceil(filteredPlayers.length / pageSize) : 1;

    // Ensure current page is valid
    if (DraftPaginationState.currentPage > totalPages) {
        DraftPaginationState.currentPage = Math.max(1, totalPages);
    }

    // Calculate range for current page
    const start = DraftPaginationState.pageSize === 'all' ? 0 : (DraftPaginationState.currentPage - 1) * pageSize;
    const end = DraftPaginationState.pageSize === 'all' ? filteredPlayers.length : start + pageSize;

    // Re-query DOM for fresh element references and show/hide based on index
    const container = document.getElementById('available-players');
    if (!container) return;

    // First hide ALL cards in container (use :scope > to only select direct children, NOT buttons)
    container.querySelectorAll(':scope > [data-player-id]').forEach(card => {
        card.classList.add('hidden');
    });

    // Then show only the ones in current page range
    for (let i = start; i < end && i < filteredPlayers.length; i++) {
        const playerId = filteredPlayers[i].id;
        const card = container.querySelector(`[data-player-id="${playerId}"]`);
        if (card) {
            card.classList.remove('hidden');
        }
    }

    updatePaginationUI(totalPages);
    console.log(`[draft-pagination] Page ${DraftPaginationState.currentPage}/${totalPages}, showing ${start}-${end-1} of ${filteredPlayers.length}`);
}

/**
 * Update pagination UI
 */
function updatePaginationUI(totalPages) {
    const pageInfo = document.getElementById('pageInfo');
    const paginationControls = document.getElementById('paginationControls');

    if (pageInfo) {
        pageInfo.textContent = `Page ${DraftPaginationState.currentPage} of ${Math.max(1, totalPages)}`;
    }

    // Hide pagination if only one page
    if (paginationControls) {
        const shouldHide = totalPages <= 1 || DraftPaginationState.pageSize === 'all';
        paginationControls.classList.toggle('hidden', shouldHide);
    }
}

/**
 * Update player counts in UI
 */
function updateDraftPlayerCount(count) {
    const availableCount = document.getElementById('availableCount');
    const availablePlayersCount = document.getElementById('available-players-count');

    if (availableCount) availableCount.textContent = count;
    if (availablePlayersCount) availablePlayersCount.textContent = count;
}

// ============================================================================
// EVENT DELEGATION HANDLERS
// ============================================================================

/**
 * Filter players (triggered by input or change)
 */
window.EventDelegation.register('draft-filter-players', function(element, e) {
    DraftPaginationState.currentPage = 1; // Reset to first page on filter change
    filterDraftPlayers();
});

/**
 * Clear all filters
 */
window.EventDelegation.register('draft-clear-filters', function(element, e) {
    e.preventDefault();

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

    DraftPaginationState.currentPage = 1;
    filterDraftPlayers();
});

/**
 * Change page size
 */
window.EventDelegation.register('draft-change-page-size', function(element, e) {
    const newSize = element.value;
    DraftPaginationState.pageSize = newSize === 'all' ? 'all' : parseInt(newSize);
    DraftPaginationState.currentPage = 1;
    paginateDraftPlayers(DraftPaginationState.filteredPlayers);
});

/**
 * Previous page
 */
window.EventDelegation.register('draft-prev-page', function(element, e) {
    e.preventDefault();
    if (DraftPaginationState.currentPage > 1) {
        DraftPaginationState.currentPage--;
        paginateDraftPlayers(DraftPaginationState.filteredPlayers);
    }
});

/**
 * Next page
 */
window.EventDelegation.register('draft-next-page', function(element, e) {
    e.preventDefault();
    const pageSize = DraftPaginationState.pageSize === 'all' ? DraftPaginationState.totalPlayers : DraftPaginationState.pageSize;
    const totalPages = Math.ceil(DraftPaginationState.totalPlayers / pageSize);

    if (DraftPaginationState.currentPage < totalPages) {
        DraftPaginationState.currentPage++;
        paginateDraftPlayers(DraftPaginationState.filteredPlayers);
    }
});

// ============================================================================
// DRAFT ACTIONS
// ============================================================================

/**
 * Draft Player Action
 * Shows modal to select team and draft player
 */
window.EventDelegation.register('draft-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.targetPlayerId;
    const playerName = element.dataset.playerName;

    if (!playerId || !playerName) {
        console.error('[draft-player] Missing required data attributes');
        return;
    }

    // Call global function
    if (typeof window.confirmDraftPlayer === 'function') {
        window.confirmDraftPlayer(playerId, playerName);
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
window.EventDelegation.register('remove-player', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.targetPlayerId;
    const teamId = element.dataset.teamId;
    const playerName = element.dataset.playerName;
    const teamName = element.dataset.teamName;

    if (!playerId || !teamId) {
        console.error('[remove-player] Missing required data attributes');
        return;
    }

    // Call global function
    if (typeof window.confirmRemovePlayer === 'function') {
        window.confirmRemovePlayer(playerId, teamId, playerName, teamName);
    } else {
        console.error('[remove-player] Function not found');
    }
});

/**
 * View Player Profile Action
 * Opens modal with player details
 */
window.EventDelegation.register('view-player-profile', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.targetPlayerId;

    if (!playerId) {
        console.error('[view-player-profile] Missing player ID');
        return;
    }

    // Check for instance method first, then global
    if (window.draftSystemInstance && typeof window.draftSystemInstance.openPlayerModal === 'function') {
        window.draftSystemInstance.openPlayerModal(playerId);
    } else if (typeof window.openPlayerModal === 'function') {
        window.openPlayerModal(playerId);
    } else {
        console.error('[view-player-profile] No modal function available');
    }
});

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize draft filters on page load
 */
function initDraftFilters() {
    // Only run on draft pages
    const availablePlayers = document.getElementById('available-players');
    if (!availablePlayers) return;

    console.log('[draft-system] Initializing draft filters...');
    // Use :scope > to only count direct children (cards), NOT buttons inside
    const cards = availablePlayers.querySelectorAll(':scope > [data-player-id]');
    console.log(`[draft-system] Found ${cards.length} player cards`);

    // Initial filter to set up pagination
    filterDraftPlayers();

    // Verify cards are visible after filter (use :scope > to only count cards, not buttons)
    const visibleCards = availablePlayers.querySelectorAll(':scope > [data-player-id]:not(.hidden)');
    console.log(`[draft-system] After filter: ${visibleCards.length} cards visible`);

    // Check first visible card structure
    if (visibleCards.length > 0) {
        const firstCard = visibleCards[0];
        const hasImage = firstCard.querySelector('img') !== null;
        const hasDraftBtn = firstCard.querySelector('[data-action="draft-player"]') !== null;
        const hasMoreInfo = firstCard.querySelector('[data-action="view-player-profile"]') !== null;
        console.log(`[draft-system] First card check - Image: ${hasImage}, Draft btn: ${hasDraftBtn}, More Info: ${hasMoreInfo}`);
    }
}

// DISABLED - auto-initialization was hiding cards
// Pagination/filtering will be triggered by user interaction only
// If you need auto-init, uncomment below:
// if (document.readyState === 'loading') {
//     document.addEventListener('DOMContentLoaded', initDraftFilters);
// } else {
//     setTimeout(initDraftFilters, 0);
// }

// Handlers loaded
