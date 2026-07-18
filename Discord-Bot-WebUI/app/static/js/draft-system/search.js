/**
 * Draft System - Search and Filter
 * Player search, filtering, and sorting for the pool.
 *
 * Works with the current Flowbite pool cards (`.js-draggable-player`, with data-player-name /
 * data-position / data-goals / data-attendance / data-experience on the card itself). The
 * position filter groups by the canonical position groups (goalkeeper / defender / midfielder /
 * forward), so filtering "Forward" matches Striker, Winger, CF, etc.
 *
 * @module draft-system/search
 */

// Canonical slug -> group (mirrors app/draft_position_analyzer.PositionAnalyzer.POSITION_GROUPS
// and app/constants/positions.SOCCER_POSITIONS). Keep in sync with the backend source of truth.
const SLUG_GROUP = {
    goalkeeper: 'goalkeeper',
    defender: 'defender', center_back: 'defender', left_back: 'defender', right_back: 'defender',
    full_back: 'defender', wing_back: 'defender',
    midfielder: 'midfielder', defensive_midfielder: 'midfielder', central_midfielder: 'midfielder',
    left_midfielder: 'midfielder', right_midfielder: 'midfielder', attacking_midfielder: 'midfielder',
    winger: 'forward', left_winger: 'forward', right_winger: 'forward', forward: 'forward',
    center_forward: 'forward', striker: 'forward', support_striker: 'forward'
};

function posGroupOf(raw) {
    const s = (raw || '').trim().toLowerCase().replace(/\s+/g, '_');
    return SLUG_GROUP[s] || '';
}

/** Does a player's stored position match a group filter (goalkeeper/defender/midfielder/forward)? */
function matchesPositionFilter(playerPosition, filter) {
    if (!filter) return true;
    const g = posGroupOf(playerPosition);
    if (g) return g === filter;
    // Legacy/unknown value: fall back to a loose substring match so nothing silently vanishes.
    return (playerPosition || '').toLowerCase().indexOf(filter) >= 0;
}

/** Resolve the player card element from a container child (the child usually IS the card). */
function getCard(col) {
    if (col.classList && col.classList.contains('js-draggable-player')) return col;
    return col.querySelector ? col.querySelector('.js-draggable-player, [data-component="player-card"]') : null;
}

function setVisible(col, show) {
    if (show) col.classList.remove('hidden');
    else col.classList.add('hidden');
}

/**
 * Handle player search by name.
 * @param {Event} event
 * @param {Function} onUpdate - called with the visible count
 */
export function handleSearch(event, onUpdate) {
    const searchTerm = (event.target.value || '').toLowerCase();
    const container = document.getElementById('available-players');
    if (!container) return 0;

    let visibleCount = 0;
    Array.from(container.children).forEach(col => {
        const card = getCard(col);
        if (!card) return;
        const playerName = card.getAttribute('data-player-name') || '';
        const show = !searchTerm || playerName.includes(searchTerm);
        setVisible(col, show);
        if (show) visibleCount++;
    });

    if (onUpdate) onUpdate(visibleCount);
    return visibleCount;
}

/**
 * Handle position filter (grouped: Forward matches Striker/Winger/CF, etc.).
 * @param {Event} event
 * @param {Function} onUpdate - called with the visible count
 */
export function handleFilter(event, onUpdate) {
    const position = (event.target.value || '').toLowerCase();
    const container = document.getElementById('available-players');
    if (!container) return 0;

    let visibleCount = 0;
    Array.from(container.children).forEach(col => {
        const card = getCard(col);
        if (!card) return;
        const playerPosition = card.getAttribute('data-position') || '';
        const show = matchesPositionFilter(playerPosition, position);
        setVisible(col, show);
        if (show) visibleCount++;
    });

    if (onUpdate) onUpdate(visibleCount);
    return visibleCount;
}

/**
 * Handle player sorting.
 * @param {Event} event
 */
export function handleSort(event) {
    const sortBy = event.target.value;
    const container = document.getElementById('available-players');
    if (!container) return;

    const cols = Array.from(container.children);
    cols.sort((a, b) => {
        const cardA = getCard(a), cardB = getCard(b);
        if (!cardA || !cardB) return 0;
        switch (sortBy) {
            case 'name':
                return (cardA.getAttribute('data-player-name') || '').localeCompare(cardB.getAttribute('data-player-name') || '');
            case 'experience':
                return (parseInt(cardB.getAttribute('data-experience')) || 0) - (parseInt(cardA.getAttribute('data-experience')) || 0);
            case 'attendance':
                return (parseInt(cardB.getAttribute('data-attendance')) || 0) - (parseInt(cardA.getAttribute('data-attendance')) || 0);
            case 'goals':
                return (parseInt(cardB.getAttribute('data-goals')) || 0) - (parseInt(cardA.getAttribute('data-goals')) || 0);
            default:
                return 0;
        }
    });
    cols.forEach(col => container.appendChild(col));
}

/** Legacy no-op kept for API compatibility (the Flowbite board has no empty column wrappers). */
export function cleanupEmptyColumns(container) {
    if (!container) return;
    Array.from(container.children).forEach(child => {
        if (child.getAttribute && child.getAttribute('data-component') === 'player-column' &&
            !child.querySelector('[data-component="player-card"], .js-draggable-player')) {
            child.remove();
        }
    });
}

/**
 * Re-apply the active search + position filter to a card that just (re)entered the pool.
 * @param {HTMLElement} col - the card / column element
 */
export function applyCurrentFilters(col) {
    const searchInput = document.getElementById('playerSearch');
    const positionFilter = document.getElementById('positionFilter');
    const card = getCard(col);
    if (!card) return;

    if (searchInput && searchInput.value) {
        const name = (card.getAttribute('data-player-name') || '');
        if (!name.includes(searchInput.value.toLowerCase())) { setVisible(col, false); return; }
    }
    if (positionFilter && positionFilter.value) {
        if (!matchesPositionFilter(card.getAttribute('data-position') || '', positionFilter.value.toLowerCase())) {
            setVisible(col, false); return;
        }
    }
    setVisible(col, true);
}

export default {
    handleSearch,
    handleFilter,
    handleSort,
    cleanupEmptyColumns,
    applyCurrentFilters
};
