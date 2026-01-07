'use strict';

/**
 * Admin Panel Base - Loading
 * Progressive loading and responsive tables
 * @module admin-panel-base/loading
 */

import { CONFIG, debounce } from './config.js';

/**
 * Progressive loading for heavy content
 * Uses data-lazy-load attribute
 */
export function initProgressiveLoading(context) {
    context = context || document;

    if ('IntersectionObserver' in window) {
        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    entry.target.classList.add('loaded');
                    entry.target.dataset.loaded = 'true';
                    observer.unobserve(entry.target);
                }
            });
        }, {
            rootMargin: '50px'
        });

        context.querySelectorAll('[data-lazy-load]').forEach(el => {
            if (el.dataset.loaded !== 'true') {
                observer.observe(el);
            }
        });
    }
}

/**
 * Responsive table handling
 * Uses data-responsive-table or .table-responsive
 */
export function initResponsiveTables(context) {
    context = context || document;

    function handleResponsiveTables() {
        // Query by data attribute first, then fall back to class
        const tableContainers = context.querySelectorAll('[data-responsive-table], .table-responsive');

        tableContainers.forEach(container => {
            const table = container.tagName === 'TABLE' ? container : container.querySelector('table');
            if (!table) return;

            if (window.innerWidth < CONFIG.MOBILE_BREAKPOINT) {
                // Add mobile-friendly data-label attributes
                const headers = table.querySelectorAll('th');
                const rows = table.querySelectorAll('tbody tr');

                rows.forEach(row => {
                    const cells = row.querySelectorAll('td');
                    cells.forEach((cell, index) => {
                        if (headers[index]) {
                            cell.setAttribute('data-label', headers[index].textContent);
                        }
                    });
                });

                // Add mobile stack class for very small screens
                if (window.innerWidth < 576) {
                    table.classList.add('table-mobile-stack');
                    table.dataset.mobileStack = 'true';
                }
            } else {
                table.classList.remove('table-mobile-stack');
                table.dataset.mobileStack = 'false';
            }
        });
    }

    // Call on load and resize
    handleResponsiveTables();
    window.addEventListener('resize', debounce(handleResponsiveTables, CONFIG.DEBOUNCE_WAIT));
}
