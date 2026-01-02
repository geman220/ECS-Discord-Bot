'use strict';

/**
 * Help Search Module
 * Handles debounced search for help topics
 *
 * @module help-search
 * @requires window.InitSystem
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Help Search functionality
 */
const HelpSearch = {
    // Debounce timeout
    debounceTimeout: null,

    /**
     * Initialize help search functionality
     */
    init() {
        this.setupFancybox();
        this.setupSearch();

        console.log('[HelpSearch] Initialized');
    },

    /**
     * Get search URL
     * @returns {string} Search URL
     */
    getSearchUrl() {
        // Try to get from data attribute or default
        const searchInput = document.querySelector('[data-action="search-topics"]');
        return searchInput?.dataset?.searchUrl || '/help/search';
    },

    /**
     * Get base help URL
     * @returns {string} Base help URL
     */
    getBaseUrl() {
        const searchInput = document.querySelector('[data-action="search-topics"]');
        return searchInput?.dataset?.baseUrl || '/help';
    },

    /**
     * Setup Fancybox if available
     */
    setupFancybox() {
        const fancyboxElements = document.querySelectorAll('[data-fancybox]');
        if (fancyboxElements.length > 0 && typeof Fancybox !== 'undefined') {
            Fancybox.bind('[data-fancybox]', {
                loop: true,
                buttons: ['zoom', 'slideShow', 'fullScreen', 'close'],
                animationEffect: 'zoom'
            });
        }
    },

    /**
     * Setup debounced search
     */
    setupSearch() {
        document.addEventListener('input', (e) => {
            const searchInput = e.target.closest('[data-action="search-topics"]');
            if (!searchInput) return;

            clearTimeout(this.debounceTimeout);
            const query = searchInput.value;

            this.debounceTimeout = setTimeout(() => {
                this.performSearch(query);
            }, 300);
        });
    },

    /**
     * Perform search
     * @param {string} query - Search query
     */
    performSearch(query) {
        const searchUrl = this.getSearchUrl();
        const baseUrl = this.getBaseUrl();

        fetch(`${searchUrl}?` + new URLSearchParams({ query: query }))
            .then(response => response.json())
            .then(data => {
                const list = document.querySelector('[data-topics-list]');
                if (!list) return;

                list.innerHTML = '';

                if (data.topics && data.topics.length) {
                    data.topics.forEach((topic) => {
                        const topicUrl = baseUrl.replace(/\/$/, '') + '/' + topic.id;
                        const li = document.createElement('li');
                        li.className = 'c-list-modern__item c-list-modern__item--clickable';
                        li.innerHTML = `
                            <a href="${topicUrl}"
                               class="c-list-modern__link"
                               data-action="view-topic"
                               data-topic-id="${topic.id}">
                                <i class="ti ti-book c-list-modern__icon"></i>
                                ${this.escapeHtml(topic.title)}
                                <i class="ti ti-chevron-right c-list-modern__chevron"></i>
                            </a>
                        `;
                        list.appendChild(li);
                    });
                } else {
                    list.innerHTML = '<li class="c-list-modern__item c-list-modern__item--empty"><i class="ti ti-info-circle c-list-modern__icon"></i>No help topics available.</li>';
                }
            })
            .catch(error => {
                console.error('Error while searching topics:', error);
            });
    },

    /**
     * Escape HTML to prevent XSS
     * @param {string} text - Text to escape
     * @returns {string} Escaped text
     */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
};

// Register with window.InitSystem
window.InitSystem.register('help-search', () => {
    // Only initialize on help index page
    if (document.querySelector('[data-action="search-topics"]') ||
        document.querySelector('[data-topics-list]')) {
        HelpSearch.init();
    }
}, {
    priority: 40,
    description: 'Help topics search functionality',
    reinitializable: true
});

// Export for direct use
export { HelpSearch };
