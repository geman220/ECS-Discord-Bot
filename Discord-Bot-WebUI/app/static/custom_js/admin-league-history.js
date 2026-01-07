/**
 * Admin League History
 * Handles player history lookup and search functionality
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

/**
 * History Manager Class
 */
class AdminLeagueHistoryManager {
    constructor() {
        this.searchTimeout = null;
        this.selectedIndex = -1;
        this.searchResults = [];
    }

    /**
     * Initialize the manager
     */
    init() {
        this.setupSearchInput();
        this.setupKeyboardNavigation();
        this.setupClickOutside();
        this.setupLookupButton();
        this.setupEventDelegation();
    }

    /**
     * Setup search input handler with debounce
     */
    setupSearchInput() {
        const searchInput = document.getElementById('playerSearchInput');
        if (!searchInput) return;

        searchInput.addEventListener('input', (e) => {
            const query = e.target.value.trim();

            if (this.searchTimeout) {
                clearTimeout(this.searchTimeout);
            }

            // Clear selection when typing
            document.getElementById('selectedPlayerId').value = '';
            document.getElementById('selectedPlayerInfo').textContent = '';
            const lookupBtn = document.getElementById('lookupBtn');
            if (lookupBtn) lookupBtn.disabled = true;

            const resultsDiv = document.getElementById('playerSearchResults');
            if (query.length < 2) {
                if (resultsDiv) resultsDiv.classList.remove('show');
                this.searchResults = [];
                return;
            }

            this.searchTimeout = setTimeout(() => this.searchPlayers(query), 300);
        });
    }

    /**
     * Setup keyboard navigation
     */
    setupKeyboardNavigation() {
        const searchInput = document.getElementById('playerSearchInput');
        if (!searchInput) return;

        searchInput.addEventListener('keydown', (e) => {
            const resultsDiv = document.getElementById('playerSearchResults');
            const items = resultsDiv ? resultsDiv.querySelectorAll('.player-search-item') : [];

            if (e.key === 'ArrowDown') {
                e.preventDefault();
                this.selectedIndex = Math.min(this.selectedIndex + 1, items.length - 1);
                this.updateSelection(items);
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                this.selectedIndex = Math.max(this.selectedIndex - 1, 0);
                this.updateSelection(items);
            } else if (e.key === 'Enter' && this.selectedIndex >= 0) {
                e.preventDefault();
                this.selectPlayer(this.searchResults[this.selectedIndex]);
            } else if (e.key === 'Escape') {
                if (resultsDiv) resultsDiv.classList.remove('show');
            }
        });
    }

    /**
     * Setup click outside to close results
     */
    setupClickOutside() {
        document.addEventListener('click', (e) => {
            if (!e.target.closest('.player-search-container')) {
                const resultsDiv = document.getElementById('playerSearchResults');
                if (resultsDiv) resultsDiv.classList.remove('show');
            }
        });
    }

    /**
     * Setup lookup button click handler
     */
    setupLookupButton() {
        const lookupBtn = document.getElementById('lookupBtn');
        if (lookupBtn) {
            lookupBtn.addEventListener('click', () => this.lookupPlayerHistory());
        }
    }

    /**
     * Setup event delegation for player selection
     */
    setupEventDelegation() {
        document.addEventListener('click', (e) => {
            const item = e.target.closest('[data-action="select-player"]');
            if (item && item.classList.contains('js-player-option')) {
                const playerIndex = parseInt(item.dataset.playerIndex, 10);
                if (this.searchResults[playerIndex]) {
                    this.selectPlayer(this.searchResults[playerIndex]);
                }
            }
        });
    }

    /**
     * Update keyboard selection display
     * @param {NodeList} items - List of search result items
     */
    updateSelection(items) {
        items.forEach((item, idx) => {
            item.classList.toggle('selected', idx === this.selectedIndex);
        });
        if (items[this.selectedIndex]) {
            items[this.selectedIndex].scrollIntoView({ block: 'nearest' });
        }
    }

    /**
     * Search for players
     * @param {string} query - Search query
     */
    searchPlayers(query) {
        fetch(`/admin-panel/league-management/history/api/search-players?q=${encodeURIComponent(query)}`)
            .then(response => response.json())
            .then(result => {
                const resultsDiv = document.getElementById('playerSearchResults');
                this.searchResults = result.players || [];
                this.selectedIndex = -1;

                if (this.searchResults.length === 0) {
                    resultsDiv.innerHTML = '<div class="player-search-item text-muted">No players found</div>';
                } else {
                    resultsDiv.innerHTML = this.searchResults.map((player, idx) => `
                        <div class="player-search-item js-player-option" data-action="select-player" data-player-index="${idx}">
                            <span class="player-name">${this.escapeHtml(player.name)}</span>
                            <span class="player-id ms-2">(ID: ${player.id})</span>
                        </div>
                    `).join('');
                }

                resultsDiv.classList.add('show');
            })
            .catch(error => {
                console.error('[AdminLeagueHistoryManager] Search error:', error);
            });
    }

    /**
     * Select a player from search results
     * @param {Object} player - Player object
     */
    selectPlayer(player) {
        document.getElementById('playerSearchInput').value = player.name;
        document.getElementById('selectedPlayerId').value = player.id;
        document.getElementById('selectedPlayerInfo').textContent = `Selected: ${player.name} (ID: ${player.id})`;
        document.getElementById('playerSearchResults').classList.remove('show');
        document.getElementById('lookupBtn').disabled = false;
    }

    /**
     * Escape HTML for safe display
     * @param {string} text - Text to escape
     * @returns {string} Escaped HTML
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Lookup player team history
     */
    lookupPlayerHistory() {
        const playerId = document.getElementById('selectedPlayerId').value;
        const playerName = document.getElementById('playerSearchInput').value;

        if (!playerId) {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Please select a player from the search results', 'warning');
            }
            return;
        }

        const resultDiv = document.getElementById('playerHistoryResult');
        const contentDiv = document.getElementById('playerHistoryContent');
        const titleDiv = document.getElementById('playerHistoryTitle');

        resultDiv.style.display = 'block';
        contentDiv.innerHTML = '<div class="spinner-border spinner-border-sm" data-spinner></div> Loading...';
        titleDiv.textContent = `Team History for ${playerName}`;

        fetch(`/admin-panel/league-management/history/api/player/${playerId}`)
            .then(response => response.json())
            .then(result => {
                if (result.success && result.history.length > 0) {
                    let html = '<table class="c-table c-table--compact" data-table data-mobile-table data-table-type="history"><thead scope="col"><tr><th scope="col">Season</th><th scope="col">Team</th></tr></thead><tbody>';
                    result.history.forEach(h => {
                        html += `<tr><td>${this.escapeHtml(h.season_name)}</td><td>${this.escapeHtml(h.team_name)}</td></tr>`;
                    });
                    html += '</tbody></table>';
                    contentDiv.innerHTML = html;
                } else if (result.success) {
                    contentDiv.innerHTML = '<p class="text-muted">No team history found for this player</p>';
                } else {
                    contentDiv.innerHTML = '<p class="text-danger">Error loading history</p>';
                }
            })
            .catch(error => {
                console.error('[AdminLeagueHistoryManager] Error:', error);
                contentDiv.innerHTML = '<p class="text-danger">Error loading history</p>';
            });
    }
}

// Create singleton instance
let historyManager = null;

/**
 * Get or create manager instance
 */
function getManager() {
    if (!historyManager) {
        historyManager = new AdminLeagueHistoryManager();
    }
    return historyManager;
}

/**
 * Initialize function
 */
function initAdminLeagueHistory() {
    if (_initialized) return;
    _initialized = true;

    const manager = getManager();
    manager.init();

    // Expose methods globally for backward compatibility
    window.searchResults = manager.searchResults;
    window.selectPlayer = (player) => manager.selectPlayer(player);
    window.lookupPlayerHistory = () => manager.lookupPlayerHistory();
}

// Register with window.InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-league-history', initAdminLeagueHistory, {
        priority: 40,
        reinitializable: false,
        description: 'Admin league history lookup'
    });
}

// Fallback for direct script loading
// window.InitSystem handles initialization

// Export for ES modules
export { AdminLeagueHistoryManager, getManager, initAdminLeagueHistory };
