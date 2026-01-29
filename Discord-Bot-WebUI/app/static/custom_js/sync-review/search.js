'use strict';

/**
 * Sync Review Search
 * Player search functionality
 * @module sync-review/search
 */

import { getCSRFToken, clearSearchTimeoutRef, setSearchTimeout } from './state.js';

/**
 * Search players with delay
 * @param {HTMLInputElement} input
 * @param {string} issueId
 * @param {string} orderIndex
 */
export function searchPlayersDelayed(input, issueId, orderIndex) {
    clearSearchTimeoutRef();
    const query = input.value.trim();
    const resultsDiv = document.getElementById(`search-results-${issueId}-${orderIndex}`);

    if (query.length < 2) {
        if (resultsDiv) {
            resultsDiv.innerHTML = '<div class="text-xs text-gray-500 dark:text-gray-400">Type at least 2 characters to search</div>';
        }
        return;
    }

    // Show loading
    if (resultsDiv) {
        resultsDiv.innerHTML = '<div class="text-gray-500 dark:text-gray-400 text-sm" data-spinner><span class="inline-block w-4 h-4 border-2 border-ecs-green border-t-transparent rounded-full animate-spin mr-1"></span>Searching...</div>';
    }

    setSearchTimeout(setTimeout(() => {
        searchPlayers(query, issueId, orderIndex);
    }, 300));
}

/**
 * Search players
 * @param {string} query
 * @param {string} issueId
 * @param {string} orderIndex
 */
export function searchPlayers(query, issueId, orderIndex) {
    fetch('/user_management/search_players', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({
            search_term: query
        })
    })
    .then(response => response.json())
    .then(data => {
        const resultsDiv = document.getElementById(`search-results-${issueId}-${orderIndex}`);
        if (!resultsDiv) return;

        if (data.success && data.players.length > 0) {
            let html = '<div class="mb-2"><p class="text-xs text-gray-500 dark:text-gray-400">Found ' + data.total_found + ' player(s):</p></div>';

            data.players.forEach(player => {
                const statusBadge = player.is_current ?
                    '<span class="px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300" data-badge>Active</span>' :
                    '<span class="px-2 py-0.5 text-xs font-medium rounded bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300" data-badge>Inactive</span>';

                let playerDetails = `Email: ${player.email}<br>Phone: ${player.phone}<br>League: ${player.league}`;
                if (player.jersey_size && player.jersey_size !== 'N/A') {
                    playerDetails += `<br>Jersey: ${player.jersey_size}`;
                }

                html += `
                    <div class="border border-gray-200 dark:border-gray-700 rounded-lg p-2 mb-2 hover:bg-gray-50 dark:hover:bg-gray-700 cursor-pointer player-result js-assign-player" data-action="assign-player" data-issue-id="${issueId}" data-order-index="${orderIndex}" data-player-id="${player.id}" data-player-name="${player.name}">
                        <div class="flex justify-between items-start">
                            <div>
                                <span class="text-sm font-semibold text-gray-900 dark:text-white">${player.name}</span> ${statusBadge}
                                <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">
                                    ${playerDetails}
                                </p>
                            </div>
                            <i class="ti ti-arrow-right text-gray-400"></i>
                        </div>
                    </div>
                `;
            });

            resultsDiv.innerHTML = html;
        } else if (data.success && data.players.length === 0) {
            resultsDiv.innerHTML = '<div class="text-warning small"><i class="ti ti-search me-1"></i>No players found matching "' + query + '"</div>';
        } else {
            resultsDiv.innerHTML = '<div class="text-danger small" data-alert><i class="ti ti-alert-circle me-1"></i>Error searching: ' + (data.error || 'Unknown error') + '</div>';
        }
    })
    .catch(error => {
        console.error('Search error:', error);
        const resultsDiv = document.getElementById(`search-results-${issueId}-${orderIndex}`);
        if (resultsDiv) {
            resultsDiv.innerHTML = '<div class="text-danger small" data-alert><i class="ti ti-alert-circle me-1"></i>Search failed</div>';
        }
    });
}

/**
 * Cancel player search
 * @param {string} issueId
 * @param {string} orderIndex
 */
export function cancelPlayerSearch(issueId, orderIndex) {
    const select = document.querySelector(`[data-issue-id="${issueId}"][data-order-index="${orderIndex}"]`);
    if (select) select.value = '';

    const searchDiv = document.getElementById(`search-${issueId}-${orderIndex}`);
    if (searchDiv) searchDiv.classList.add('hidden');
}
