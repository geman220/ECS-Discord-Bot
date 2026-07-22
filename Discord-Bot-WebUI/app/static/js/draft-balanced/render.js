'use strict';

/**
 * Balanced-draft DOM rendering. Everything user-controlled goes through esc()
 * before hitting innerHTML.
 */

import {
    METRICS, METRIC_SHORT, state, teamTotals, computeGaps,
    draftedCount, totalPlayers, isRated,
} from './state.js';

function esc(value) {
    if (window.escapeHtml) return window.escapeHtml(String(value ?? ''));
    return String(value ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
        .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function fmt(value, digits = 2) {
    return (value === null || value === undefined) ? '—' : Number(value).toFixed(digits);
}

function genderGlyph(gender) {
    if (gender === 'M') return '<span class="text-sky-500 font-mono text-[10px]">M</span>';
    if (gender === 'F') return '<span class="text-pink-500 font-mono text-[10px]">F</span>';
    return '<span class="text-gray-400 font-mono text-[10px]">·</span>';
}

function compositeChip(player) {
    const composite = player?.ratings?.composite;
    if (composite === null || composite === undefined) {
        return '<span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-gray-100 dark:bg-gray-700 text-gray-400">?</span>';
    }
    return `<span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-ecs-green/10 text-ecs-green">${fmt(composite)}</span>`;
}

function metricLabel(key) {
    const metric = state.metrics.find(m => m.key === key);
    return metric ? metric.label : key;
}

// ---------------------------------------------------------------------------
// Header: balance chips, progress, league genders
// ---------------------------------------------------------------------------

export function renderHeader() {
    const gaps = computeGaps();
    const chips = document.getElementById('db-balance-chips');
    if (chips) {
        chips.innerHTML = METRICS.map(metric => {
            const gap = gaps[metric];
            const ok = gap.withinLimit;
            return `<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-sm font-medium ${
                ok ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-300'
                   : 'bg-red-100 dark:bg-red-900/30 text-red-700 dark:text-red-300 animate-pulse'
            }" title="${esc(metricLabel(metric))}: highest−lowest team total (limit ${esc(state.config.max_metric_gap)})">
                ${METRIC_SHORT[metric]} gap <span class="font-mono font-bold">${fmt(gap.gap, 1)}</span>
                <i class="ti ${ok ? 'ti-check' : 'ti-alert-triangle'} text-xs"></i>
            </span>`;
        }).join('');
    }

    const progress = document.getElementById('db-progress');
    if (progress) progress.textContent = `Drafted ${draftedCount()}/${totalPlayers()}`;

    const genders = { M: 0, F: 0 };
    state.teams.forEach(t => t.roster.forEach(p => { if (!p.is_coach && genders[p.gender] !== undefined) genders[p.gender] += 1; }));
    state.pool.forEach(p => { if (!p.is_coach && genders[p.gender] !== undefined) genders[p.gender] += 1; });
    const genderEl = document.getElementById('db-league-genders');
    if (genderEl) genderEl.textContent = `League ${genders.M}M · ${genders.F}F`;
}

// ---------------------------------------------------------------------------
// Team columns
// ---------------------------------------------------------------------------

function rosterRow(player) {
    const detailId = `db-roster-detail-${player.id}`;
    return `
    <div class="db-roster-row" data-player-id="${player.id}">
        <div class="flex items-center gap-2 px-2 py-1.5">
            ${player.avatar_url
                ? `<img src="${esc(player.avatar_url)}" class="w-6 h-6 rounded-full object-cover shrink-0" alt="" loading="lazy" onerror="this.style.display='none'">`
                : `<span class="w-6 h-6 rounded-full bg-ecs-green/10 text-ecs-green flex items-center justify-center text-[10px] font-semibold shrink-0">${esc((player.name || '?')[0].toUpperCase())}</span>`}
            <span class="min-w-0 flex-1 flex items-center gap-1.5">
                <span class="text-xs font-medium text-gray-900 dark:text-white truncate">${esc(player.name)}</span>
                ${player.is_coach ? '<span class="px-1 py-0.5 rounded text-[9px] font-bold bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-300">C</span>' : genderGlyph(player.gender)}
                ${!player.is_coach && !isRated(player) ? '<span class="px-1 py-0.5 rounded text-[9px] bg-gray-100 dark:bg-gray-700 text-gray-400">unrated</span>' : ''}
            </span>
            ${player.is_coach ? '' : compositeChip(player)}
            <button type="button" data-action="balanced-toggle-player-detail" data-target="${detailId}"
                    class="p-1 rounded text-gray-400 hover:text-ecs-green"><i class="ti ti-chevron-down text-xs transition-transform"></i></button>
        </div>
        <div id="${detailId}" class="hidden px-2 pb-2 text-[11px] text-gray-500 dark:text-gray-400 space-y-1">
            ${playerDetailHtml(player)}
            ${player.is_coach ? '' : `<button type="button" data-action="balanced-remove-player" data-player-id="${player.id}"
                class="mt-1 inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20">
                <i class="ti ti-x text-xs"></i>Remove from team</button>`}
        </div>
    </div>`;
}

function playerDetailHtml(player) {
    const positions = [];
    if (player.favorite_position) positions.push(`<span class="text-ecs-green">${esc(player.favorite_position)}</span>`);
    (player.other_positions || []).forEach(p => positions.push(esc(p)));
    const avoid = (player.positions_not_to_play || []).map(p => `<span class="line-through text-red-400">${esc(p)}</span>`);
    const metricsLine = player.is_coach ? '' : METRICS.map(m => {
        const value = player?.ratings?.metrics?.[m];
        return `${METRIC_SHORT[m]} <span class="font-mono">${value === null || value === undefined ? '–' : fmt(value)}</span>`;
    }).join(' · ');
    return `
        ${positions.length ? `<div>Pos: ${positions.join(', ')}${avoid.length ? ` · avoid ${avoid.join(', ')}` : ''}</div>` : ''}
        ${player.wants_gk ? `<div><i class="ti ti-hand-stop"></i> GK: ${esc(player.gk_willingness || 'willing')}</div>` : ''}
        <div>${player.has_attendance_data && player.attendance_rate !== null ? `Att ${Math.round(player.attendance_rate)}% · ` : ''}${player.career_goals ?? 0} G · ${player.career_assists ?? 0} A career${player.is_new ? ' · <span class="text-amber-500">NEW</span>' : ''}</div>
        ${metricsLine ? `<div>${metricsLine}</div>` : ''}`;
}

export function renderTeams() {
    const container = document.getElementById('db-teams');
    if (!container) return;
    const gaps = computeGaps();

    container.innerHTML = state.teams.map(team => {
        const totals = teamTotals(team);
        const active = state.activeTeamId === team.id;
        const metricRows = METRICS.map(metric => {
            const entry = totals.metrics[metric];
            const offending = !gaps[metric].withinLimit
                && (gaps[metric].maxTeamId === team.id || gaps[metric].minTeamId === team.id);
            const barWidth = entry.avg === null ? 0 : Math.max(0, Math.min(100, ((entry.avg - 1) / 4) * 100));
            return `
            <div class="flex items-center gap-1.5 text-base ${offending ? 'ring-1 ring-red-400 rounded px-1 -mx-1' : ''}"
                 title="${esc(metricLabel(metric))} — total ${fmt(entry.total, 1)}, avg ${fmt(entry.avg)}">
                <span class="w-8 shrink-0 text-[11px] text-gray-500 dark:text-gray-400">${METRIC_SHORT[metric]}</span>
                <div class="flex-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
                    <div class="h-1.5 bg-ecs-green rounded-full" style="width:${barWidth}%"></div>
                </div>
                <span class="w-12 text-right font-mono text-sm text-gray-900 dark:text-white">${fmt(entry.total, 1)}</span>
                ${offending ? '<i class="ti ti-alert-triangle text-red-500 text-xs"></i>' : ''}
            </div>`;
        }).join('');

        return `
        <div class="db-team bg-white dark:bg-gray-800 border ${active ? 'border-ecs-green ring-2 ring-ecs-green/40' : 'border-gray-200 dark:border-gray-700'} rounded-xl flex flex-col"
             data-team-id="${team.id}" data-drop-target="true">
            <button type="button" data-action="balanced-select-team" data-team-id="${team.id}"
                    class="w-full px-3 py-2.5 text-left border-b border-gray-200 dark:border-gray-700">
                <span class="flex items-center gap-2">
                    <span class="text-sm font-bold text-gray-900 dark:text-white truncate flex-1">${esc(team.name)}</span>
                    ${active ? '<span class="px-1.5 py-0.5 rounded text-[10px] font-bold bg-ecs-green text-white">TARGET</span>' : ''}
                </span>
                <span class="mt-0.5 flex items-center gap-2 text-[11px] text-gray-500 dark:text-gray-400">
                    <span>${totals.size} players</span>
                    <span class="font-mono">${totals.genders.M}M · ${totals.genders.F}F</span>
                    ${totals.unratedCount ? `<span class="text-gray-400">${totals.unratedCount} unrated</span>` : ''}
                </span>
            </button>
            <div class="px-3 py-2 space-y-1 border-b border-gray-200 dark:border-gray-700">${metricRows}</div>
            <div class="db-team-roster divide-y divide-gray-100 dark:divide-gray-700/60 min-h-[40px]" data-team-id="${team.id}">
                ${team.roster.map(rosterRow).join('') || '<div class="px-3 py-3 text-xs text-gray-400 text-center">Drop players here</div>'}
            </div>
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Pool
// ---------------------------------------------------------------------------

function passesFilters(player) {
    const f = state.filters;
    if (player.is_coach) return false;
    if (f.search && !(player.name || '').toLowerCase().includes(f.search)) return false;
    for (const metric of METRICS) {
        const rule = f[metric];
        if (!rule) continue;
        const value = player?.ratings?.metrics?.[metric];
        if (rule === 'lt3') {
            if (value === null || value === undefined || value >= 3) return false;
        } else if (value === null || value === undefined || value < parseFloat(rule)) {
            return false;
        }
    }
    if (f.position) {
        const all = [player.favorite_position, ...(player.other_positions || [])]
            .filter(Boolean).map(p => p.toLowerCase());
        if (!all.some(p => p.includes(f.position))) return false;
    }
    if (f.gender && (player.gender || 'X') !== f.gender) return false;
    if (f.status === 'new' && !player.is_new) return false;
    if (f.status === 'returning' && player.is_new) return false;
    if (f.status === 'gk' && !player.wants_gk) return false;
    if (f.status === 'unrated' && isRated(player)) return false;
    if (f.attendance) {
        const att = player.has_attendance_data ? player.attendance_rate : null;
        if (f.attendance === 'lt60') {
            if (att === null || att >= 60) return false;
        } else if (att === null || att < parseFloat(f.attendance)) {
            return false;
        }
    }
    return true;
}

export function renderPool() {
    const container = document.getElementById('db-pool');
    if (!container) return;
    const visible = state.pool.filter(passesFilters);

    container.innerHTML = visible.map(player => {
        const detailId = `db-pool-detail-${player.id}`;
        return `
        <div class="db-pool-row" data-player-id="${player.id}" draggable="true">
            <div class="flex items-center gap-2 px-2.5 py-2 cursor-grab active:cursor-grabbing">
                <input type="checkbox" data-on-change="balanced-multi-toggle" data-player-id="${player.id}"
                       ${state.selectedIds.has(player.id) ? 'checked' : ''}
                       class="db-multi-check w-3.5 h-3.5 rounded text-ecs-green focus:ring-ecs-green shrink-0"
                       aria-label="Select ${esc(player.name)} for multi-assign">
                ${player.avatar_url
                    ? `<img src="${esc(player.avatar_url)}" class="w-7 h-7 rounded-full object-cover shrink-0" alt="" loading="lazy" onerror="this.style.display='none'">`
                    : `<span class="w-7 h-7 rounded-full bg-ecs-green/10 text-ecs-green flex items-center justify-center text-[11px] font-semibold shrink-0">${esc((player.name || '?')[0].toUpperCase())}</span>`}
                <span class="min-w-0 flex-1">
                    <span class="flex items-center gap-1.5">
                        <span class="text-xs font-medium text-gray-900 dark:text-white truncate">${esc(player.name)}</span>
                        ${genderGlyph(player.gender)}
                        ${player.is_new ? '<span class="px-1 py-0.5 rounded text-[9px] font-bold bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">NEW</span>' : ''}
                        ${player.wants_gk ? '<span class="text-sky-500" title="Willing to GK"><i class="ti ti-hand-stop text-xs"></i></span>' : ''}
                    </span>
                </span>
                ${compositeChip(player)}
                <button type="button" data-action="balanced-toggle-player-detail" data-target="${detailId}"
                        class="p-1 rounded text-gray-400 hover:text-ecs-green"><i class="ti ti-chevron-down text-xs transition-transform"></i></button>
                <button type="button" data-action="balanced-draft-player" data-player-id="${player.id}"
                        class="px-2 py-1 rounded-lg text-[11px] font-semibold bg-ecs-green text-white hover:bg-ecs-green/90">Draft</button>
            </div>
            <div id="${detailId}" class="hidden px-2.5 pb-2 text-[11px] text-gray-500 dark:text-gray-400 space-y-1">
                ${playerDetailHtml(player)}
            </div>
        </div>`;
    }).join('') || '<div class="px-3 py-6 text-xs text-gray-400 text-center">No players match the filters.</div>';

    const count = document.getElementById('db-pool-count');
    if (count) count.textContent = `(${visible.length})`;
    updateMultiBar();
}

export function updateMultiBar() {
    const bar = document.getElementById('db-multi-bar');
    if (!bar) return;
    const n = state.selectedIds.size;
    bar.classList.toggle('hidden', n === 0);
    bar.classList.toggle('flex', n > 0);
    const countEl = document.getElementById('db-multi-count');
    if (countEl) countEl.textContent = String(n);
}

export function populatePositionFilter() {
    const select = document.getElementById('db-f-position');
    if (!select || select.options.length > 1) return;
    const seen = new Set();
    state.pool.concat(state.teams.flatMap(t => t.roster)).forEach(player => {
        [player.favorite_position, ...(player.other_positions || [])].filter(Boolean)
            .forEach(p => seen.add(p));
    });
    Array.from(seen).sort().forEach(position => {
        const option = document.createElement('option');
        option.value = position.toLowerCase();
        option.textContent = position;
        select.appendChild(option);
    });
}

// ---------------------------------------------------------------------------
// Suggestions
// ---------------------------------------------------------------------------

export function renderSuggestTeams() {
    const container = document.getElementById('db-suggest-teams');
    if (!container) return;
    container.innerHTML = '<span class="text-[11px] text-gray-400 mr-1">For:</span>' + state.teams.map(team => `
        <button type="button" data-action="balanced-suggest-for-team" data-team-id="${team.id}"
                class="px-2 py-1 rounded-lg text-[11px] font-semibold ${
                    state.suggestTeamId === team.id
                        ? 'bg-ecs-green text-white'
                        : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200'
                }">${esc(team.name)}</button>`).join('');
}

export function renderSuggestions(suggestions, loading = false, error = null) {
    const container = document.getElementById('db-suggest-list');
    if (!container) return;
    if (loading) {
        container.innerHTML = '<div class="px-3 py-6 text-xs text-gray-400 text-center"><i class="ti ti-loader-2 animate-spin"></i> Computing…</div>';
        return;
    }
    if (error) {
        container.innerHTML = `<div class="px-3 py-6 text-xs text-red-500 text-center">${esc(error)}</div>`;
        return;
    }
    if (!suggestions || !suggestions.length) {
        container.innerHTML = '<div class="px-3 py-6 text-xs text-gray-400 text-center">No candidates in the pool.</div>';
        return;
    }
    container.innerHTML = suggestions.map(s => {
        const deltas = METRICS.map(metric => {
            const proj = s.projection[metric];
            const closes = proj.gap_after < proj.gap_before;
            const worsens = proj.gap_after > proj.gap_before;
            const arrow = closes ? '↓' : (worsens ? '↑' : '−');
            const color = closes ? 'text-green-600 dark:text-green-400' : (worsens ? 'text-red-500' : 'text-gray-400');
            return `<span class="${color}" title="${esc(metricLabel(metric))} team total ${proj.team_total_before}→${proj.team_total_after}, gap ${proj.gap_before}→${proj.gap_after}">${METRIC_SHORT[metric]} ${arrow}${Math.abs(proj.gap_after - proj.gap_before).toFixed(1)}</span>`;
        }).join(' ');
        const positions = [s.favorite_position, ...(s.other_positions || [])].filter(Boolean).slice(0, 3);
        return `
        <div class="px-2.5 py-2 space-y-1 ${s.violates_gap ? 'opacity-70' : ''}">
            <div class="flex items-center gap-2">
                <span class="w-5 text-center font-mono text-[11px] text-gray-400">${s.rank}</span>
                <span class="min-w-0 flex-1 flex items-center gap-1.5">
                    <span class="text-xs font-semibold text-gray-900 dark:text-white truncate">${esc(s.name)}</span>
                    ${genderGlyph(s.gender)}
                    ${s.is_rated ? '' : '<span class="px-1 py-0.5 rounded text-[9px] bg-gray-100 dark:bg-gray-700 text-gray-400">unrated</span>'}
                    ${s.wants_gk ? '<span class="text-sky-500"><i class="ti ti-hand-stop text-xs"></i></span>' : ''}
                    ${s.violates_gap ? '<span class="px-1 py-0.5 rounded text-[9px] font-bold bg-red-100 dark:bg-red-900/30 text-red-500" title="Would push a metric gap over the limit">gap!</span>' : ''}
                </span>
                <span class="font-mono text-[11px] text-gray-500" title="Fit score (balance ${s.components.balance}, need ${s.components.need}, gender ${s.components.gender}, position ${s.components.position})">fit ${s.fit_score}</span>
                <button type="button" data-action="balanced-draft-player" data-player-id="${s.player_id}" data-team-id="${state.suggestTeamId}"
                        class="px-2 py-1 rounded-lg text-[11px] font-semibold bg-ecs-green text-white hover:bg-ecs-green/90">Draft</button>
            </div>
            <div class="pl-7 flex items-center gap-2 flex-wrap text-[10px] font-mono">${deltas}</div>
            ${positions.length ? `<div class="pl-7 text-[10px] text-gray-400">${positions.map(esc).join(' · ')}</div>` : ''}
        </div>`;
    }).join('');
}

// ---------------------------------------------------------------------------
// Balance matrix drawer
// ---------------------------------------------------------------------------

export function renderMatrix() {
    const container = document.getElementById('db-balance-matrix');
    if (!container) return;
    const gaps = computeGaps();
    const perTeam = state.teams.map(team => ({ team, totals: teamTotals(team) }));

    const headers = perTeam.map(({ team }) =>
        `<th class="px-2 py-1.5 text-right font-medium">${esc(team.name)}</th>`).join('');
    const rows = METRICS.map(metric => {
        const gap = gaps[metric];
        const cells = perTeam.map(({ team, totals }) => {
            const isMax = gap.maxTeamId === team.id;
            const isMin = gap.minTeamId === team.id;
            const highlight = !gap.withinLimit && (isMax || isMin) ? 'text-red-500 font-bold' : '';
            return `<td class="px-2 py-1.5 text-right font-mono ${highlight}">${totals.metrics[metric].total.toFixed(1)}${isMax ? ' ▲' : isMin ? ' ▼' : ''}</td>`;
        }).join('');
        return `<tr class="border-t border-gray-100 dark:border-gray-700">
            <td class="px-2 py-1.5 text-gray-500 dark:text-gray-400">${esc(metricLabel(metric))}</td>
            ${cells}
            <td class="px-2 py-1.5 text-right font-mono ${gap.withinLimit ? 'text-green-600 dark:text-green-400' : 'text-red-500 font-bold'}">${gap.gap.toFixed(1)}</td>
        </tr>`;
    }).join('');
    const genderCells = perTeam.map(({ totals }) =>
        `<td class="px-2 py-1.5 text-right font-mono">${totals.genders.M}M/${totals.genders.F}F</td>`).join('');

    container.innerHTML = `
        <table class="w-full">
            <thead><tr class="text-gray-400"><th class="px-2 py-1.5 text-left font-medium">Metric</th>${headers}<th class="px-2 py-1.5 text-right font-medium">Gap ≤ ${esc(state.config.max_metric_gap)}</th></tr></thead>
            <tbody>${rows}
                <tr class="border-t border-gray-200 dark:border-gray-600"><td class="px-2 py-1.5 text-gray-500 dark:text-gray-400">M/F</td>${genderCells}<td></td></tr>
            </tbody>
        </table>`;
}

export function renderActiveTarget() {
    const label = document.getElementById('db-active-target');
    if (!label) return;
    const team = state.teams.find(t => t.id === state.activeTeamId);
    label.innerHTML = team
        ? `Drafting to <span class="font-semibold text-ecs-green">${esc(team.name)}</span> — click a team header to change, or drag rows onto a column.`
        : 'Click a team header to set a draft target, or drag rows onto a column.';
}

export function renderAll() {
    renderHeader();
    renderTeams();
    renderPool();
    renderSuggestTeams();
    renderMatrix();
    renderActiveTarget();
}
