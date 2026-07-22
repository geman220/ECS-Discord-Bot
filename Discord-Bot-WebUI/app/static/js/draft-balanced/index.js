'use strict';

/**
 * Classic Balanced Draft — entry point. Bootstraps state from the embedded
 * JSON, wires EventDelegation actions, drag-and-drop, tabs, and sockets.
 */

import { state, loadInitial, findTeam } from './state.js';
import {
    renderAll, renderPool, renderSuggestions, renderSuggestTeams,
    populatePositionFilter, updateMultiBar,
} from './render.js';
import { setupSocket, emitDraft, emitRemove, scheduleResync } from './socket.js';

let searchDebounce = null;
let suggestionsAbort = null;

function root() { return document.getElementById('draft-balanced-root'); }

/**
 * Viewer scope: the pick/remove socket events are team-ownership-guarded
 * server-side, so non-admin coaches may only draft to / remove from their
 * own team(s). Stamped on the root by the route.
 */
function viewerScope() {
    const r = root();
    return {
        admin: r?.dataset.isAdmin === '1',
        mine: (r?.dataset.myTeams || '').split(',').filter(Boolean).map(Number),
    };
}

function draftableTeams() {
    const { admin, mine } = viewerScope();
    return admin ? state.teams : state.teams.filter(t => mine.includes(t.id));
}

function canOperateTeam(teamId) {
    const { admin, mine } = viewerScope();
    return admin || mine.includes(Number(teamId));
}

async function refreshSuggestions() {
    if (state.railTab !== 'suggest' || !state.suggestTeamId) return;
    renderSuggestions(null, true);
    try {
        suggestionsAbort?.abort();
        suggestionsAbort = new AbortController();
        const url = `${root().dataset.suggestionsUrl}?team_id=${state.suggestTeamId}`;
        const resp = await fetch(url, { signal: suggestionsAbort.signal });
        const data = await resp.json();
        if (!resp.ok || !data.success) {
            renderSuggestions(null, false, data.message || 'Could not load suggestions');
            return;
        }
        renderSuggestions(data.suggestions);
    } catch (err) {
        if (err.name !== 'AbortError') renderSuggestions(null, false, 'Network error');
    }
}

function chooseTeamAndDraft(playerId) {
    const player = state.pool.find(p => p.id === Number(playerId));
    const teams = draftableTeams();
    if (!teams.length) {
        if (window.Swal) window.Swal.fire({
            icon: 'info',
            title: "You're not marked as a coach of a Classic team",
            text: 'Ask an admin to set you as your team\'s coach — until then picks are view-only.',
        });
        return;
    }
    const buttons = teams.map(team =>
        `<button type="button" class="swal2-styled" data-swal-team="${team.id}" style="margin:4px">${
            (window.escapeHtml || (s => s))(team.name)} (${team.roster.filter(p => !p.is_coach).length})</button>`).join('');
    if (!window.Swal) return;
    window.Swal.fire({
        title: `Draft ${(window.escapeHtml || (s => s))(player?.name || 'player')} to…`,
        html: `<div class="flex flex-wrap justify-center">${buttons}</div>`,
        showConfirmButton: false,
        showCancelButton: true,
        didOpen: (popup) => {
            popup.querySelectorAll('[data-swal-team]').forEach(button => {
                button.addEventListener('click', () => {
                    window.Swal.close();
                    emitDraft(playerId, button.dataset.swalTeam);
                });
            });
        },
    });
}

function chooseTeamForMulti() {
    const teams = draftableTeams();
    if (!teams.length || !window.Swal) return;
    const buttons = teams.map(team =>
        `<button type="button" class="swal2-styled" data-swal-team="${team.id}" style="margin:4px">${
            (window.escapeHtml || (s => s))(team.name)} (${team.roster.filter(p => !p.is_coach).length})</button>`).join('');
    window.Swal.fire({
        title: `Assign ${state.selectedIds.size} selected to…`,
        html: `<div class="flex flex-wrap justify-center">${buttons}</div>`,
        showConfirmButton: false,
        showCancelButton: true,
        didOpen: (popup) => {
            popup.querySelectorAll('[data-swal-team]').forEach(button => {
                button.addEventListener('click', () => {
                    window.Swal.close();
                    assignSelectedTo(Number(button.dataset.swalTeam));
                });
            });
        },
    });
}

async function assignSelectedTo(teamId) {
    const ids = Array.from(state.selectedIds);
    if (!ids.length) return;
    const team = state.teams.find(t => t.id === Number(teamId));

    // Preview the combined impact via /classic-draft/check (advisory only).
    let preview = '';
    try {
        const resp = await fetch(root().dataset.checkUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                assignments: ids.map(id => ({ player_id: id, team_id: Number(teamId) })),
            }),
        });
        const data = await resp.json();
        const last = data?.steps?.[data.steps.length - 1];
        if (resp.ok && data.success && last && !last.error) {
            const gapsLine = Object.entries(last.gaps || {})
                .map(([metric, gap]) => `${metric.split('_')[0]} ${gap}`).join(' · ');
            preview = last.violates_gap
                ? `⚠️ At least one metric gap would exceed the limit afterwards (${gapsLine}).`
                : `All metric gaps stay within the limit (${gapsLine}).`;
        }
    } catch (err) { /* preview is best-effort */ }

    const proceed = () => {
        ids.forEach(id => emitDraft(id, teamId));
        state.selectedIds.clear();
        updateMultiBar();
    };
    if (window.Swal) {
        window.Swal.fire({
            icon: 'question',
            title: `Assign ${ids.length} player${ids.length > 1 ? 's' : ''} to ${(window.escapeHtml || (s => s))(team?.name || 'team')}?`,
            text: preview || undefined,
            showCancelButton: true,
            confirmButtonText: 'Assign all',
        }).then(result => { if (result.isConfirmed) proceed(); });
    } else {
        proceed();
    }
}

function setRailTab(tab) {
    state.railTab = tab;
    const poolPanel = document.getElementById('db-pool-panel');
    const suggestPanel = document.getElementById('db-suggest-panel');
    poolPanel?.classList.toggle('hidden', tab !== 'pool');
    poolPanel?.classList.toggle('flex', tab === 'pool');
    suggestPanel?.classList.toggle('hidden', tab !== 'suggest');
    suggestPanel?.classList.toggle('flex', tab === 'suggest');
    document.querySelectorAll('.db-rail-tab').forEach(button => {
        const active = button.dataset.tab === tab;
        button.classList.toggle('text-ecs-green', active);
        button.classList.toggle('border-ecs-green', active);
        button.classList.toggle('text-gray-500', !active);
        button.classList.toggle('border-transparent', !active);
    });
    if (tab === 'suggest') refreshSuggestions();
}

function readFilters() {
    state.filters = {
        search: (document.getElementById('db-pool-search')?.value || '').trim().toLowerCase(),
        intensity: document.getElementById('db-f-intensity')?.value || '',
        on_ball_skill: document.getElementById('db-f-on_ball_skill')?.value || '',
        spirit: document.getElementById('db-f-spirit')?.value || '',
        knowledge_movement: document.getElementById('db-f-knowledge_movement')?.value || '',
        position: document.getElementById('db-f-position')?.value || '',
        gender: document.getElementById('db-f-gender')?.value || '',
        status: document.getElementById('db-f-status')?.value || '',
        attendance: document.getElementById('db-f-attendance')?.value || '',
    };
}

function registerHandlers() {
    const ED = window.EventDelegation;
    if (!ED) return;

    ED.register('balanced-select-team', (element) => {
        const teamId = Number(element.dataset.teamId);
        state.activeTeamId = state.activeTeamId === teamId ? null : teamId;
        state.suggestTeamId = teamId;
        renderAll();
        if (state.railTab === 'suggest') refreshSuggestions();
    });

    ED.register('balanced-draft-player', (element) => {
        const playerId = element.dataset.playerId;
        const explicitTeam = element.dataset.teamId;
        const teamId = explicitTeam || state.activeTeamId;
        // Non-admin coaches can only draft to their own team — a suggestion or
        // active-team pointing elsewhere falls back to the (scoped) team picker.
        if (teamId && canOperateTeam(teamId)) emitDraft(playerId, teamId);
        else chooseTeamAndDraft(playerId);
    });

    ED.register('balanced-remove-player', (element) => {
        const playerId = Number(element.dataset.playerId);
        const team = state.teams.find(t => t.roster.some(p => p.id === playerId));
        if (!team) return;
        if (!canOperateTeam(team.id)) {
            if (window.Swal) window.Swal.fire({
                icon: 'info',
                title: 'Not your team',
                text: `Only ${team.name}'s coach or an admin can remove this player.`,
            });
            return;
        }
        const player = team.roster.find(p => p.id === playerId);
        if (window.Swal) {
            window.Swal.fire({
                icon: 'question',
                title: `Remove ${(window.escapeHtml || (s => s))(player?.name || 'player')}?`,
                text: `They return to the draft pool from ${team.name}.`,
                showCancelButton: true,
                confirmButtonText: 'Remove',
            }).then(result => { if (result.isConfirmed) emitRemove(playerId, team.id); });
        } else {
            emitRemove(playerId, team.id);
        }
    });

    ED.register('balanced-toggle-player-detail', (element) => {
        const detail = document.getElementById(element.dataset.target);
        if (!detail) return;
        const opening = detail.classList.contains('hidden');
        detail.classList.toggle('hidden', !opening);
        element.querySelector('i')?.classList.toggle('rotate-180', opening);
    });

    ED.register('balanced-filter', (element) => {
        if (element.id === 'db-pool-search') {
            clearTimeout(searchDebounce);
            searchDebounce = setTimeout(() => { readFilters(); renderPool(); }, 120);
        } else {
            readFilters();
            renderPool();
        }
    });

    ED.register('balanced-clear-filters', (element, event) => {
        // The button lives inside the <details> summary — without this the
        // click also toggles the filter panel closed.
        event?.preventDefault();
        event?.stopPropagation();
        ['db-pool-search', 'db-f-intensity', 'db-f-on_ball_skill', 'db-f-spirit',
         'db-f-knowledge_movement', 'db-f-position', 'db-f-gender', 'db-f-status',
         'db-f-attendance'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.value = '';
        });
        readFilters();
        renderPool();
    });

    ED.register('balanced-multi-toggle', (element) => {
        const playerId = Number(element.dataset.playerId);
        if (element.checked) state.selectedIds.add(playerId);
        else state.selectedIds.delete(playerId);
        updateMultiBar();
    });

    ED.register('balanced-multi-clear', () => {
        state.selectedIds.clear();
        renderPool();
    });

    ED.register('balanced-assign-selected', () => {
        if (!state.selectedIds.size) return;
        const target = state.activeTeamId && canOperateTeam(state.activeTeamId)
            ? state.activeTeamId : null;
        if (target) assignSelectedTo(target);
        else chooseTeamForMulti();
    });

    ED.register('balanced-pool-tab', () => setRailTab('pool'));
    ED.register('balanced-suggest-tab', () => setRailTab('suggest'));

    ED.register('balanced-suggest-for-team', (element) => {
        state.suggestTeamId = Number(element.dataset.teamId);
        renderSuggestTeams();
        refreshSuggestions();
    });
}

function setupDragAndDrop() {
    const container = root();
    if (!container) return;

    container.addEventListener('dragstart', (event) => {
        const row = event.target.closest('.db-pool-row');
        if (!row) return;
        event.dataTransfer.setData('text/plain', row.dataset.playerId);
        event.dataTransfer.effectAllowed = 'move';
    });

    container.addEventListener('dragover', (event) => {
        const column = event.target.closest('[data-drop-target]');
        if (!column) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        column.classList.add('ring-2', 'ring-ecs-green/60');
    });

    container.addEventListener('dragleave', (event) => {
        const column = event.target.closest('[data-drop-target]');
        if (column && !column.contains(event.relatedTarget)) {
            column.classList.remove('ring-2', 'ring-ecs-green/60');
        }
    });

    container.addEventListener('drop', (event) => {
        const column = event.target.closest('[data-drop-target]');
        if (!column) return;
        event.preventDefault();
        column.classList.remove('ring-2', 'ring-ecs-green/60');
        const playerId = event.dataTransfer.getData('text/plain');
        const teamId = column.dataset.teamId;
        if (playerId && teamId && findTeam(teamId)) emitDraft(playerId, teamId);
    });
}

function init() {
    if (!root()) return;

    const bootstrap = document.getElementById('db-initial-state');
    if (bootstrap) {
        try {
            loadInitial(JSON.parse(bootstrap.textContent));
        } catch (err) {
            console.error('[draft-balanced] bad initial state, refetching', err);
            scheduleResync();
        }
    }

    registerHandlers();
    setupDragAndDrop();
    setupSocket(() => { if (state.railTab === 'suggest') refreshSuggestions(); });

    populatePositionFilter();
    renderAll();
}

if (window.InitSystem?.register) {
    window.InitSystem.register('draft-balanced', init, {
        priority: 40,
        reinitializable: false,
        description: 'Classic balanced draft board',
    });
} else {
    document.addEventListener('DOMContentLoaded', init);
}
