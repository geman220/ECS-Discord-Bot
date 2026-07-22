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
    const attendance = document.getElementById('cb-attendance')?.value || '';
    const rated = document.getElementById('cb-rated')?.value || '';
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
        if (show && attendance) {
            const att = parseFloat(card.dataset.attendance);   // -1 = no data
            if (attendance === 'none') show = att < 0;
            else if (attendance === 'lt60') show = att >= 0 && att < 60;
            else show = att >= parseFloat(attendance);
        }
        if (show && rated) {
            const composite = parseFloat(card.dataset.composite);  // -1 = none
            switch (rated) {
                case 'rated': show = card.dataset.rated === '1'; break;
                case 'unrated': show = card.dataset.rated !== '1' && card.dataset.coach === '0'; break;
                case 'c4': show = composite >= 4; break;
                case 'c3': show = composite >= 3; break;
                case 'clt3': show = composite >= 0 && composite < 3; break;
            }
        }
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

// ---------------------------------------------------------------------------
// Scouting notes (NADs — shared PlayerAdminNote thread)
// ---------------------------------------------------------------------------

let notesPlayerId = null;

function esc(value) {
    if (window.escapeHtml) return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function notesUrl(playerId) {
    return document.getElementById('classic-board-root')
        .dataset.notesUrlTemplate.replace('999999', String(playerId));
}

function renderNotes(notes) {
    const list = document.getElementById('cb-notes-list');
    if (!list) return;
    if (!notes || !notes.length) {
        list.innerHTML = '<div class="text-xs text-gray-400 text-center py-4">No notes yet — add the first.</div>';
        return;
    }
    list.innerHTML = notes.map(note => `
        <div class="rounded-lg border border-gray-200 dark:border-gray-700 p-2.5">
            <div class="flex items-center justify-between gap-2 text-[11px] text-gray-400">
                <span class="font-medium text-gray-600 dark:text-gray-300">${esc(note.author_name || note.author?.name || 'Coach')}</span>
                <span>${esc((note.created_at || '').slice(0, 10))}</span>
            </div>
            <p class="mt-1 text-xs text-gray-800 dark:text-gray-100 whitespace-pre-wrap">${esc(note.content)}</p>
        </div>`).join('');
}

async function openNotes(playerId, playerName) {
    notesPlayerId = playerId;
    const title = document.getElementById('cb-notes-player');
    if (title) title.textContent = playerName;
    const modal = document.getElementById('cb-notes-modal');
    if (modal) {
        modal.classList.remove('hidden');
        modal.classList.add('flex', 'bg-gray-900/50');
    }
    const list = document.getElementById('cb-notes-list');
    if (list) list.innerHTML = '<div class="text-xs text-gray-400 text-center py-4"><i class="ti ti-loader-2 animate-spin"></i> Loading…</div>';
    try {
        const resp = await fetch(notesUrl(playerId));
        const data = await resp.json();
        if (resp.ok && data.success) renderNotes(data.notes);
        else if (list) list.innerHTML = `<div class="text-xs text-red-500 text-center py-4">${esc(data.message || 'Could not load notes')}</div>`;
    } catch (err) {
        if (list) list.innerHTML = '<div class="text-xs text-red-500 text-center py-4">Network error</div>';
    }
}

async function addNote() {
    const input = document.getElementById('cb-notes-input');
    const content = (input?.value || '').trim();
    if (!content || !notesPlayerId) return;
    try {
        const resp = await fetch(notesUrl(notesPlayerId), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ content }),
        });
        const data = await resp.json();
        if (resp.ok && data.success) {
            input.value = '';
            openNotes(notesPlayerId, document.getElementById('cb-notes-player')?.textContent || '');
        } else if (window.Swal) {
            window.Swal.fire({ icon: 'error', title: 'Not saved', text: data.message || 'Could not add note',
                               toast: true, position: 'top-end', timer: 3000, showConfirmButton: false });
        }
    } catch (err) {
        if (window.Swal) {
            window.Swal.fire({ icon: 'error', title: 'Network error', toast: true,
                               position: 'top-end', timer: 3000, showConfirmButton: false });
        }
    }
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
        ED.register('classic-board-notes', (element) => {
            openNotes(Number(element.dataset.playerId), element.dataset.playerName || '');
        });
        ED.register('classic-board-note-add', () => addNote());
        ED.register('classic-board-notes-close', () => {
            const modal = document.getElementById('cb-notes-modal');
            if (modal) {
                modal.classList.add('hidden');
                modal.classList.remove('flex', 'bg-gray-900/50');
            }
            notesPlayerId = null;
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
