'use strict';

/**
 * Draft Enhanced Search & Filter
 * Search, filter, and sort functionality
 * @module draft-enhanced/search-filter
 */

/**
 * Setup live search functionality
 */
export function setupLiveSearch() {
    const searchInput = document.getElementById('playerSearch');
    const positionFilter = document.getElementById('positionFilter');
    const sortBy = document.getElementById('sortBy');

    if (searchInput) {
        searchInput.addEventListener('input', filterPlayers);
    }
    if (positionFilter) {
        positionFilter.addEventListener('change', filterPlayers);
    }
    if (sortBy) {
        sortBy.addEventListener('change', filterPlayers);
    }
}

/**
 * Filter players in real-time
 */
export function filterPlayers() {
    const searchTerm = document.getElementById('playerSearch')?.value.toLowerCase() || '';
    const positionFilter = document.getElementById('positionFilter')?.value.toLowerCase() || '';
    const sortBy = document.getElementById('sortBy')?.value || 'name';

    const availablePlayersContainer = document.getElementById('available-players');
    const playerCards = availablePlayersContainer?.querySelectorAll('.col-xl-3, .col-lg-4, .col-md-6, .col-sm-6') || [];

    let visibleCount = 0;
    let filteredPlayers = [];

    // Filter and collect visible players
    playerCards.forEach(card => {
        const playerCard = card.querySelector('.player-card');
        if (!playerCard) return;

        const playerName = playerCard.getAttribute('data-player-name') || '';
        const playerPosition = playerCard.getAttribute('data-position') || '';

        // Check search term match
        const matchesSearch = !searchTerm || playerName.includes(searchTerm);

        // Check position filter match
        const matchesPosition = !positionFilter || playerPosition === positionFilter;

        const isVisible = matchesSearch && matchesPosition;

        if (isVisible) {
            card.classList.add('d-block');
            card.classList.remove('d-none');
            visibleCount++;

            // Collect data for sorting
            const experience = parseInt(playerCard.getAttribute('data-experience')) || 0;
            const attendance = parseFloat(playerCard.getAttribute('data-attendance')) || 0;
            const goals = parseInt(playerCard.getAttribute('data-goals')) || 0;

            filteredPlayers.push({
                element: card,
                name: playerName,
                experience: experience,
                attendance: attendance,
                goals: goals
            });
        } else {
            card.classList.add('d-none');
            card.classList.remove('d-block');
        }
    });

    // Sort the visible players
    if (sortBy && filteredPlayers.length > 0) {
        sortPlayers(filteredPlayers, sortBy);
    }

    // Update both counters
    updateAvailablePlayerCount(visibleCount);

    // Show/hide empty state
    const emptyState = document.getElementById('emptyState');
    if (emptyState) {
        emptyState.classList.toggle('is-visible', visibleCount === 0);
    }

    console.log(`Filtered players: ${visibleCount} visible`);
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
                return b.attendance - a.attendance; // Highest first
            case 'goals':
                return b.goals - a.goals; // Highest first
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
