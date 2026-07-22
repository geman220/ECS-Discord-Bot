'use strict';

/**
 * Classic coach rating screen — focused-queue accordion.
 *
 * One expanded rating panel at a time; sliders autosave (debounced) to
 * POST /classic-board/rate/<player_id>; "Save & next unrated" flushes and
 * advances. All state lives in the DOM (data-* attributes) so the page is
 * resumable after reload — the server hydrates saved values.
 */

const SAVE_DEBOUNCE_MS = 800;

const state = {
    root: null,
    saveTimers: new Map(),   // playerId -> timeout id
    pending: new Map(),      // playerId -> {metric: value}
    activeFilter: 'all',
};

function root() { return state.root || (state.root = document.getElementById('classic-rate-root')); }
function canSubmit() { return root()?.dataset.canSubmit === 'true'; }
function saveUrl(playerId) { return root().dataset.saveUrlTemplate.replace('999999', String(playerId)); }
function rows() { return Array.from(document.querySelectorAll('#rate-list .rate-row')); }

function setSaveStatus(stateName, text) {
    const pill = document.getElementById('rate-save-status');
    if (!pill) return;
    pill.dataset.state = stateName;
    const styles = {
        idle: 'bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400',
        saving: 'bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300',
        saved: 'bg-ecs-green/10 text-ecs-green',
        error: 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300',
    };
    const icons = { idle: 'ti-circle-check', saving: 'ti-loader-2 animate-spin', saved: 'ti-check', error: 'ti-alert-triangle' };
    pill.className = `ml-auto inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs ${styles[stateName] || styles.idle}`;
    pill.innerHTML = `<i class="ti ${icons[stateName] || icons.idle} text-sm"></i><span></span>`;
    pill.querySelector('span').textContent = text;
}

function updateCounts() {
    const all = rows();
    const rated = all.filter(r => r.dataset.rated === '1').length;
    const total = all.length;
    const bar = document.getElementById('rate-progress-bar');
    if (bar) bar.style.width = total ? `${Math.round((rated / total) * 100)}%` : '0%';
    const count = document.getElementById('rate-progress-count');
    if (count) count.textContent = String(rated);
    const unratedEl = document.getElementById('rate-count-unrated');
    if (unratedEl) unratedEl.textContent = String(total - rated);
    const ratedEl = document.getElementById('rate-count-rated');
    if (ratedEl) ratedEl.textContent = String(rated);
}

function applyFilter() {
    const query = (document.getElementById('rate-quick-jump')?.value || '').trim().toLowerCase();
    rows().forEach(row => {
        const matchesTab = state.activeFilter === 'all'
            || (state.activeFilter === 'rated' ? row.dataset.rated === '1' : row.dataset.rated !== '1');
        const matchesQuery = !query || row.dataset.name.includes(query);
        row.classList.toggle('hidden', !(matchesTab && matchesQuery));
    });
}

function collapseAll() {
    rows().forEach(row => {
        row.querySelector('.rate-panel')?.classList.add('hidden');
        row.querySelector('.rate-chevron')?.classList.remove('rotate-180');
    });
}

function expandRow(row) {
    if (!row) return;
    collapseAll();
    row.querySelector('.rate-panel')?.classList.remove('hidden');
    row.querySelector('.rate-chevron')?.classList.add('rotate-180');
    row.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function rowValues(row) {
    const values = {};
    row.querySelectorAll('.rate-metric input[type="range"]').forEach(input => {
        if (input.dataset.set === '1') values[input.dataset.metric] = parseFloat(input.value);
    });
    return values;
}

function markRowRated(row) {
    const inputs = Array.from(row.querySelectorAll('.rate-metric input[type="range"]'));
    const complete = inputs.length > 0 && inputs.every(i => i.dataset.set === '1');
    row.dataset.rated = complete ? '1' : '0';
    const icon = row.querySelector('.rate-status-icon');
    if (icon) {
        icon.className = 'rate-status-icon shrink-0 w-6 h-6 rounded-full flex items-center justify-center '
            + (complete ? 'bg-ecs-green/10 text-ecs-green'
                        : 'border-2 border-gray-300 dark:border-gray-600 text-transparent');
    }
    inputs.forEach(input => {
        const chip = row.querySelector(`.rate-chip[data-metric="${input.dataset.metric}"]`);
        if (chip) chip.textContent = input.dataset.set === '1' ? parseFloat(input.value).toFixed(2) : '–';
    });
    updateCounts();
}

function scheduleSave(row) {
    if (!canSubmit()) return;
    const playerId = row.dataset.playerId;
    const existing = state.saveTimers.get(playerId);
    if (existing) clearTimeout(existing);
    state.saveTimers.set(playerId, setTimeout(() => flushSave(row), SAVE_DEBOUNCE_MS));
}

async function flushSave(row) {
    if (!canSubmit()) return true;
    const playerId = row.dataset.playerId;
    const timer = state.saveTimers.get(playerId);
    if (timer) { clearTimeout(timer); state.saveTimers.delete(playerId); }
    const values = rowValues(row);
    if (!Object.keys(values).length) return true;

    setSaveStatus('saving', 'Saving…');
    try {
        const resp = await fetch(saveUrl(playerId), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(values),
        });
        const data = await resp.json().catch(() => ({}));
        if (!resp.ok || !data.success) {
            const message = data.message || (data.error === 'WINDOW_CLOSED'
                ? 'The rating window is closed' : 'Save failed — try again');
            setSaveStatus('error', message);
            if (window.Swal) {
                window.Swal.fire({ icon: 'error', title: 'Not saved', text: message,
                                   timer: 2500, showConfirmButton: false, toast: true, position: 'top-end' });
            }
            return false;
        }
        setSaveStatus('saved', 'Saved');
        return true;
    } catch (err) {
        setSaveStatus('error', 'Network error — values kept, retry');
        return false;
    }
}

function nextUnrated(afterRow) {
    const all = rows().filter(r => !r.classList.contains('hidden'));
    const start = afterRow ? all.indexOf(afterRow) + 1 : 0;
    for (let i = 0; i < all.length; i++) {
        const row = all[(start + i) % all.length];
        if (row.dataset.rated !== '1' && row !== afterRow) return row;
    }
    return null;
}

function registerHandlers() {
    const ED = window.EventDelegation;
    if (!ED) return;

    ED.register('rating-toggle-player', (element) => {
        const row = element.closest('.rate-row');
        const panel = row?.querySelector('.rate-panel');
        if (!panel) return;
        if (panel.classList.contains('hidden')) expandRow(row);
        else { flushSave(row); collapseAll(); }
    });

    ED.register('rating-slider-input', (element) => {
        element.dataset.set = '1';
        const metricWrap = element.closest('.rate-metric');
        const readout = metricWrap?.querySelector('.rate-readout');
        if (readout) {
            readout.textContent = parseFloat(element.value).toFixed(2);
            readout.classList.remove('text-gray-300', 'dark:text-gray-600');
            readout.classList.add('text-ecs-green');
        }
        const row = element.closest('.rate-row');
        if (row) { markRowRated(row); scheduleSave(row); }
    });

    ED.register('rating-save-next', async (element) => {
        const row = element.closest('.rate-row');
        if (!row) return;
        const ok = await flushSave(row);
        if (!ok) return;   // keep the panel open so nothing is lost
        const next = nextUnrated(row);
        if (next) expandRow(next);
        else {
            collapseAll();
            setSaveStatus('saved', 'All done');
        }
    });

    ED.register('rating-skip', (element) => {
        const row = element.closest('.rate-row');
        const next = nextUnrated(row);
        if (next) expandRow(next); else collapseAll();
    });

    ED.register('rating-filter-tab', (element) => {
        state.activeFilter = element.dataset.filter || 'all';
        document.querySelectorAll('.rate-tab').forEach(tab => {
            const active = tab === element;
            tab.classList.toggle('bg-ecs-green', active);
            tab.classList.toggle('text-white', active);
            tab.classList.toggle('bg-white', !active);
            tab.classList.toggle('dark:bg-gray-800', !active);
            tab.classList.toggle('text-gray-600', !active);
            tab.classList.toggle('dark:text-gray-300', !active);
            tab.setAttribute('aria-pressed', active ? 'true' : 'false');
        });
        applyFilter();
    });

    ED.register('rating-quick-jump', () => applyFilter());
}

function init() {
    if (!document.getElementById('classic-rate-root')) return;
    registerHandlers();
    updateCounts();
    // Flush any pending debounced save if the coach navigates away.
    window.addEventListener('beforeunload', () => {
        state.saveTimers.forEach((timer, playerId) => {
            clearTimeout(timer);
            const row = document.querySelector(`.rate-row[data-player-id="${playerId}"]`);
            if (row && canSubmit()) {
                const values = rowValues(row);
                if (Object.keys(values).length) {
                    // keepalive fetch goes through the CSRF-patched fetch, unlike
                    // sendBeacon (which would be rejected without the token header).
                    fetch(saveUrl(playerId), {
                        method: 'POST',
                        keepalive: true,
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(values),
                    }).catch(() => {});
                }
            }
        });
    });
}

if (window.InitSystem?.register) {
    window.InitSystem.register('classic-ratings-rate', init, {
        priority: 40,
        reinitializable: false,
        description: 'Classic coach rating queue',
    });
} else {
    document.addEventListener('DOMContentLoaded', init);
}
