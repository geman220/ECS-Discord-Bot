/**
 * Draft System - Search and Filter
 * Player search, filtering, and sorting functionality
 *
 * @module draft-system/search
 */

/**
 * Handle player search by name
 * @param {Event} event - Input event
 * @param {Function} onUpdate - Callback for count update
 */
export function handleSearch(event, onUpdate) {
    const searchTerm = event.target.value.toLowerCase();
    const container = document.getElementById('available-players');
    if (!container) return;

    const playerColumns = Array.from(container.children);
    let visibleCount = 0;

    playerColumns.forEach(column => {
        const playerCard = column.querySelector('[data-component="player-card"]');
        if (playerCard) {
            const playerName = playerCard.getAttribute('data-player-name') || '';
            const shouldShow = playerName.includes(searchTerm);

            if (shouldShow) {
                column.classList.remove('hidden');
                column.classList.add('block');
                visibleCount++;
            } else {
                column.classList.add('hidden');
                column.classList.remove('block');
            }
        }
    });

    if (onUpdate) {
        onUpdate(visibleCount);
    }

    return visibleCount;
}

/**
 * Handle position filter
 * @param {Event} event - Change event
 * @param {Function} onUpdate - Callback for count update
 */
export function handleFilter(event, onUpdate) {
    const position = event.target.value.toLowerCase();
    const container = document.getElementById('available-players');
    if (!container) return;

    const playerColumns = Array.from(container.children);
    let visibleCount = 0;

    playerColumns.forEach(column => {
        const playerCard = column.querySelector('[data-component="player-card"]');
        if (playerCard) {
            const playerPosition = playerCard.getAttribute('data-position') || '';
            const shouldShow = !position || playerPosition.includes(position);

            if (shouldShow) {
                column.classList.remove('hidden');
                column.classList.add('block');
                visibleCount++;
            } else {
                column.classList.add('hidden');
                column.classList.remove('block');
            }
        }
    });

    if (onUpdate) {
        onUpdate(visibleCount);
    }

    return visibleCount;
}

/**
 * Handle player sorting
 * @param {Event} event - Change event
 */
export function handleSort(event) {
    const sortBy = event.target.value;
    const container = document.getElementById('available-players');
    if (!container) return;

    const players = Array.from(container.children);

    players.sort((a, b) => {
        const cardA = a.querySelector('[data-component="player-card"]');
        const cardB = b.querySelector('[data-component="player-card"]');

        if (!cardA || !cardB) return 0;

        let aValue, bValue;

        switch (sortBy) {
            case 'name':
                aValue = cardA.getAttribute('data-player-name') || '';
                bValue = cardB.getAttribute('data-player-name') || '';
                return aValue.localeCompare(bValue);

            case 'experience':
                aValue = parseInt(cardA.getAttribute('data-experience')) || 0;
                bValue = parseInt(cardB.getAttribute('data-experience')) || 0;
                return bValue - aValue;

            case 'attendance':
                aValue = parseInt(cardA.getAttribute('data-attendance')) || 0;
                bValue = parseInt(cardB.getAttribute('data-attendance')) || 0;
                return bValue - aValue;

            case 'goals':
                aValue = parseInt(cardA.getAttribute('data-goals')) || 0;
                bValue = parseInt(cardB.getAttribute('data-goals')) || 0;
                return bValue - aValue;

            default:
                return 0;
        }
    });

    // Clear the container and re-add in sorted order
    players.forEach(player => {
        container.appendChild(player);
    });

    // Clean up any empty column divs
    cleanupEmptyColumns(container);
}

/**
 * Remove empty player column divs
 * @param {HTMLElement} container - Players container
 */
export function cleanupEmptyColumns(container) {
    Array.from(container.children).forEach(child => {
        if (child.hasAttribute('data-component') &&
            child.getAttribute('data-component') === 'player-column' &&
            !child.querySelector('[data-component="player-card"]')) {
            child.remove();
        }
    });
}

/**
 * Apply current filters to a newly added player card
 * @param {HTMLElement} playerCard - Player card element
 */
export function applyCurrentFilters(playerCard) {
    const searchInput = document.getElementById('searchPlayers');
    const positionFilter = document.getElementById('filterPosition');

    if (searchInput && searchInput.value) {
        const searchTerm = searchInput.value.toLowerCase();
        const cardElement = playerCard.querySelector('[data-component="player-card"]');
        const playerName = cardElement?.getAttribute('data-player-name') || '';
        if (!playerName.includes(searchTerm)) {
            playerCard.classList.add('hidden');
        }
    }

    if (positionFilter && positionFilter.value) {
        const filterPosition = positionFilter.value.toLowerCase();
        const cardElement = playerCard.querySelector('[data-component="player-card"]');
        const playerPosition = cardElement?.getAttribute('data-position') || '';
        if (filterPosition && !playerPosition.includes(filterPosition)) {
            playerCard.classList.add('hidden');
        }
    }
}

export default {
    handleSearch,
    handleFilter,
    handleSort,
    cleanupEmptyColumns,
    applyCurrentFilters
};
