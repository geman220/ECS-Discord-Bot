'use strict';

/**
 * Classic Board — client-side filter/sort over the server-rendered card grid.
 * All facts live in data-* attributes on .cb-card (NAD-board pattern, moved
 * from inline script into an EventDelegation module).
 */

let debounceTimer = null;

function cards() { return Array.from(document.querySelectorAll('#cb-grid .cb-card')); }

function applyFilters() {
    const query = (document.getElementById('cb-search')?.value || '').trim().toLowerCase();
    const status = document.getElementById('cb-status')?.value || '';
    const position = (document.getElementById('cb-position')?.value || '').toLowerCase();
    const sort = document.getElementById('cb-sort')?.value || 'name-asc';

    const grid = document.getElementById('cb-grid');
    if (!grid) return;

    let visible = 0;
    const all = cards();
    all.forEach(card => {
        let show = true;
        if (query && !card.dataset.name.includes(query)) show = false;
        if (show && status) {
            switch (status) {
                case 'new': show = card.dataset.new === '1'; break;
                case 'returning': show = card.dataset.new === '0' && card.dataset.coach === '0'; break;
                case 'assigned': show = card.dataset.assigned === '1'; break;
                case 'unassigned': show = card.dataset.assigned === '0'; break;
                case 'gk': show = card.dataset.gk === '1'; break;
            }
        }
        if (show && position && !card.dataset.positions.includes(position)) show = false;
        card.classList.toggle('hidden', !show);
        if (show) visible += 1;
    });

    const numeric = (card, key) => parseFloat(card.dataset[key]) || 0;
    const sorters = {
        'name-asc': (a, b) => a.dataset.name.localeCompare(b.dataset.name),
        'name-desc': (a, b) => b.dataset.name.localeCompare(a.dataset.name),
        'attendance': (a, b) => numeric(b, 'attendance') - numeric(a, 'attendance'),
        'goals': (a, b) => numeric(b, 'goals') - numeric(a, 'goals'),
        'assists': (a, b) => numeric(b, 'assists') - numeric(a, 'assists'),
        'composite': (a, b) => numeric(b, 'composite') - numeric(a, 'composite'),
    };
    all.sort(sorters[sort] || sorters['name-asc']).forEach(card => grid.appendChild(card));

    const count = document.getElementById('cb-count');
    if (count) count.textContent = `${visible} of ${all.length} shown`;
}

function populatePositions() {
    const select = document.getElementById('cb-position');
    if (!select) return;
    const seen = new Set();
    cards().forEach(card => (card.dataset.positions || '').split('|').forEach(pos => {
        if (pos) seen.add(pos);
    }));
    Array.from(seen).sort().forEach(pos => {
        const option = document.createElement('option');
        option.value = pos;
        option.textContent = pos.replace(/\b\w/g, c => c.toUpperCase());
        select.appendChild(option);
    });
}

function init() {
    if (!document.getElementById('classic-board-root')) return;
    const ED = window.EventDelegation;
    if (ED) {
        ED.register('classic-board-filter', (element) => {
            if (element.id === 'cb-search') {
                clearTimeout(debounceTimer);
                debounceTimer = setTimeout(applyFilters, 120);
            } else {
                applyFilters();
            }
        });
    }
    populatePositions();
    applyFilters();
}

if (window.InitSystem?.register) {
    window.InitSystem.register('classic-board', init, {
        priority: 40,
        reinitializable: false,
        description: 'Classic board filter/sort',
    });
} else {
    document.addEventListener('DOMContentLoaded', init);
}
