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
            resultsDiv.innerHTML = '<div class="text-muted small">Type at least 2 characters to search</div>';
        }
        return;
    }

    // Show loading
    if (resultsDiv) {
        resultsDiv.innerHTML = '<div class="text-muted small" data-spinner><i class="spinner-border spinner-border-sm me-1"></i>Searching...</div>';
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
            let html = '<div class="mb-2"><small class="text-muted">Found ' + data.total_found + ' player(s):</small></div>';

            data.players.forEach(player => {
                const statusBadge = player.is_current ?
                    '<span class="badge bg-success" data-badge>Active</span>' :
                    '<span class="badge bg-warning" data-badge>Inactive</span>';

                let playerDetails = `Email: ${player.email}<br>Phone: ${player.phone}<br>League: ${player.league}`;
                if (player.jersey_size && player.jersey_size !== 'N/A') {
                    playerDetails += `<br>Jersey: ${player.jersey_size}`;
                }

                html += `
                    <div class="border rounded p-2 mb-2 player-result js-assign-player" data-action="assign-player" data-issue-id="${issueId}" data-order-index="${orderIndex}" data-player-id="${player.id}" data-player-name="${player.name}">
                        <div class="d-flex justify-content-between align-items-start">
                            <div>
                                <strong>${player.name}</strong> ${statusBadge}
                                <br><small class="text-muted">
                                    ${playerDetails}
                                </small>
                            </div>
                            <i class="ti ti-arrow-right"></i>
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
    if (searchDiv) searchDiv.classList.add('d-none');
}
