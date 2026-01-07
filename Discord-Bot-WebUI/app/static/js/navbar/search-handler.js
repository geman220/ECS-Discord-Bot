/**
 * Navbar - Search Handler
 * Search functionality with autocomplete
 *
 * @module navbar/search-handler
 */

import { CONFIG } from './config.js';

let searchTimeout = null;

/**
 * Initialize search functionality
 */
export function initSearch() {
  const searchContainer = document.querySelector('.c-navbar-modern__search');
  const searchInput = document.querySelector('.c-navbar-modern__search-input');
  if (!searchInput || !searchContainer) return;

  // Prevent form submission
  const form = searchInput.closest('form');
  if (form) {
    form.addEventListener('submit', (e) => {
      e.preventDefault();
    });
  }

  // Search input handling
  searchInput.addEventListener('input', (e) => {
    clearTimeout(searchTimeout);

    const query = e.target.value.trim();

    if (query.length >= 2) {
      searchTimeout = setTimeout(() => {
        performSearch(query);
      }, CONFIG.searchDebounce);
    }
  });

  // Focus animation
  searchInput.addEventListener('focus', () => {
    searchContainer.classList.add('is-focused');
    // On mobile, expand the search
    if (window.innerWidth <= 767.98) {
      searchContainer.classList.add('is-expanded');
    }
  });

  searchInput.addEventListener('blur', () => {
    searchContainer.classList.remove('is-focused');
    // On mobile, collapse if empty
    if (window.innerWidth <= 767.98 && !searchInput.value.trim()) {
      setTimeout(() => {
        searchContainer.classList.remove('is-expanded');
      }, 150);
    }
  });

  // Mobile: Click on collapsed search icon to expand
  searchContainer.addEventListener('click', (e) => {
    if (window.innerWidth <= 767.98 && !searchContainer.classList.contains('is-expanded')) {
      e.preventDefault();
      searchContainer.classList.add('is-expanded');
      searchInput.focus();
    }
  });

  // Close expanded search when clicking outside
  document.addEventListener('click', (e) => {
    if (window.innerWidth <= 767.98 &&
        searchContainer.classList.contains('is-expanded') &&
        !searchContainer.contains(e.target) &&
        !searchInput.value.trim()) {
      searchContainer.classList.remove('is-expanded');
    }
  });

  // Handle escape key to close expanded search
  searchInput.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && window.innerWidth <= 767.98) {
      searchInput.blur();
      searchContainer.classList.remove('is-expanded');
    }
  });
}

/**
 * Perform search (integrate with existing autocomplete)
 * @param {string} query - Search query
 */
export function performSearch(query) {
  // This integrates with the existing player search autocomplete
  if (typeof window.initializePlayerSearch === 'function') {
    // Use existing search function
    console.log('Searching for:', query);
  }
}

export default { initSearch, performSearch };
