/**
 * Player Search Autocomplete - Vanilla JS + Tailwind
 * Touch-friendly replacement for jQuery UI Autocomplete
 *
 * Features:
 * - Touch-optimized with touchend handlers (prevents 300ms delay)
 * - Debounced search requests
 * - Keyboard navigation (arrow keys, enter, escape)
 * - Dark mode support via Tailwind classes
 * - Works on both desktop and mobile
 *
 * @module navbar/player-autocomplete
 */

import { CONFIG, escapeHtml } from './config.js';

/**
 * Initialize player search autocomplete
 * @param {string} inputSelector - CSS selector for the search input
 * @param {string} resultsSelector - CSS selector for the results container
 * @param {string} searchUrl - URL for the search API endpoint
 * @param {string} profileBaseUrl - Base URL for player profiles
 */
export function initPlayerSearch(inputSelector, resultsSelector, searchUrl, profileBaseUrl) {
  const input = document.querySelector(inputSelector);
  const results = document.querySelector(resultsSelector);
  if (!input || !results) return;

  let debounceTimer = null;
  let selectedIndex = -1;
  let currentResults = [];

  // Debounced search on input
  input.addEventListener('input', (e) => {
    clearTimeout(debounceTimer);
    const term = e.target.value.trim();

    if (term.length < 1) {
      hideResults();
      return;
    }

    debounceTimer = setTimeout(() => fetchResults(term), CONFIG.searchDebounce || 150);
  });

  // Touch-friendly selection (prevents 300ms mobile delay)
  results.addEventListener('touchend', (e) => {
    e.preventDefault();
    handleSelection(e);
  });

  // Click selection for desktop
  results.addEventListener('click', handleSelection);

  // Keyboard navigation
  input.addEventListener('keydown', handleKeyboard);

  // Close on outside click/touch
  document.addEventListener('click', (e) => {
    if (!input.contains(e.target) && !results.contains(e.target)) {
      hideResults();
    }
  });

  // Close on escape when input focused
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      hideResults();
      input.blur();
    }
  });

  /**
   * Fetch search results from the API
   * @param {string} term - Search term
   */
  async function fetchResults(term) {
    try {
      const response = await fetch(`${searchUrl}?term=${encodeURIComponent(term)}`);
      if (!response.ok) throw new Error('Search request failed');

      currentResults = await response.json();
      renderResults();
    } catch (err) {
      console.error('[PlayerAutocomplete] Search failed:', err);
      results.innerHTML = `
        <div class="px-4 py-3 text-sm text-red-500 dark:text-red-400">
          Search failed. Please try again.
        </div>
      `;
      showResults();
    }
  }

  /**
   * Render search results in the dropdown
   */
  function renderResults() {
    if (currentResults.length === 0) {
      results.innerHTML = `
        <div class="px-4 py-3 text-sm text-gray-500 dark:text-gray-400">
          No players found
        </div>
      `;
    } else {
      results.innerHTML = currentResults.map((player, i) => {
        const isSelected = i === selectedIndex;
        const selectedClass = isSelected ? 'bg-gray-100 dark:bg-gray-600' : '';
        const profilePicUrl = player.profile_picture_url || '/static/img/default_player.png';
        const playerName = escapeHtml(player.name || 'Unknown Player');

        return `
          <div class="flex items-center gap-3 px-4 py-3 cursor-pointer
                      hover:bg-gray-100 dark:hover:bg-gray-600 ${selectedClass}"
               data-player-id="${player.id}"
               data-index="${i}"
               role="option"
               aria-selected="${isSelected}">
            <img src="${profilePicUrl}" alt=""
                 class="w-8 h-8 rounded-full object-cover flex-shrink-0"
                 onerror="this.src='/static/img/default_player.png'">
            <span class="text-gray-900 dark:text-white truncate">${playerName}</span>
          </div>
        `;
      }).join('');
    }
    showResults();
  }

  /**
   * Handle item selection
   * @param {Event} e - Click or touch event
   */
  function handleSelection(e) {
    const item = e.target.closest('[data-player-id]');
    if (item) {
      const playerId = item.dataset.playerId;
      window.location.href = `${profileBaseUrl}${playerId}`;
    }
  }

  /**
   * Handle keyboard navigation
   * @param {KeyboardEvent} e - Keyboard event
   */
  function handleKeyboard(e) {
    if (results.classList.contains('hidden')) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      selectedIndex = Math.min(selectedIndex + 1, currentResults.length - 1);
      renderResults();
      scrollSelectedIntoView();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      selectedIndex = Math.max(selectedIndex - 1, 0);
      renderResults();
      scrollSelectedIntoView();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (selectedIndex >= 0 && currentResults[selectedIndex]) {
        window.location.href = `${profileBaseUrl}${currentResults[selectedIndex].id}`;
      } else if (currentResults.length > 0) {
        // Select first result if none highlighted
        window.location.href = `${profileBaseUrl}${currentResults[0].id}`;
      }
    }
  }

  /**
   * Scroll selected item into view
   */
  function scrollSelectedIntoView() {
    const selected = results.querySelector(`[data-index="${selectedIndex}"]`);
    if (selected) {
      selected.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
  }

  /**
   * Show the results dropdown
   */
  function showResults() {
    results.classList.remove('hidden');
    input.setAttribute('aria-expanded', 'true');
  }

  /**
   * Hide the results dropdown
   */
  function hideResults() {
    results.classList.add('hidden');
    input.setAttribute('aria-expanded', 'false');
    selectedIndex = -1;
    currentResults = [];
  }
}

/**
 * Initialize all player search inputs on the page
 * Automatically finds desktop and mobile search inputs
 * @param {string} searchUrl - URL for the search API endpoint
 * @param {string} profileBaseUrl - Base URL for player profiles
 */
export function initAllPlayerSearches(searchUrl, profileBaseUrl) {
  // Desktop search
  initPlayerSearch(
    '#player-search-flowbite',
    '#search-results-desktop',
    searchUrl,
    profileBaseUrl
  );

  // Mobile search
  initPlayerSearch(
    '#player-search-mobile',
    '#search-results-mobile',
    searchUrl,
    profileBaseUrl
  );
}

export default { initPlayerSearch, initAllPlayerSearches };
