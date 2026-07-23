'use strict';

/**
 * Substitute Command Center — tabbed admin hub.
 *
 * Drives: tab switching, league/pool filters, the This-Week candidate slide-over
 * (request-select -> fetch ranked candidates -> assign in place, authority-aware),
 * the reach-out modal (whole-pool / available-this-week / by-position /
 * specific-people targeting, per-channel reach preview + live Discord-style message
 * preview), live Settings message previews, settings save, and Discord channel refresh.
 *
 * Server contracts (all on admin_panel_bp):
 *   GET  candidates-for-request?request_id=&league=  -> {candidates, can_assign, assign_url, match_id, team_id}
 *   GET  week-availability?week=&league_type=
 *   POST settings-save  (JSON of AdminConfig keys)
 *   GET  discord-channels
 *   POST reachout-web   (JSON {kind, league_type, match_date, time_slots, ...})
 *   POST reachout-reach (JSON {player_ids}) -> {counts:{PUSH,DISCORD,SMS,EMAIL}, total}
 * Assign dispatches to the existing per-league endpoints (Pub League: form body;
 * ECS FC: request_id in the URL). Authority is re-enforced server-side.
 */

function root() { return document.getElementById('substitute-command-center-root'); }

function esc(s) {
    if (window.escapeHtml) return window.escapeHtml(s);
    // Hard fallback so a missing global never degrades to raw (unescaped) insertion.
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

function cfg() {
    const r = root();
    return {
        week: r.dataset.week,
        candidatesUrl: r.dataset.candidatesUrl,
        weekAvailabilityUrl: r.dataset.weekAvailabilityUrl,
        settingsSaveUrl: r.dataset.settingsSaveUrl,
        discordChannelsUrl: r.dataset.discordChannelsUrl,
        discordRolesUrl: r.dataset.discordRolesUrl,
        reachoutUrl: r.dataset.reachoutUrl,
        reachoutReachUrl: r.dataset.reachoutReachUrl,
        requestOptionsUrl: r.dataset.requestOptionsUrl,
        requestCreateUrl: r.dataset.requestCreateUrl,
        requestEditUrl: r.dataset.requestEditUrl,
        requestCancelUrl: r.dataset.requestCancelUrl,
        assignUrl: r.dataset.assignUrl,
        poolSearchUrl: r.dataset.poolSearchUrl,
        poolAddUrl: r.dataset.poolAddUrl,
        poolRemoveUrl: r.dataset.poolRemoveUrl,
        poolApproveUrl: r.dataset.poolApproveUrl,
        poolSetActiveUrl: r.dataset.poolSetactiveUrl,
        poolRejectUrl: r.dataset.poolRejectUrl,
        csrf: r.dataset.csrf || (document.querySelector('meta[name=csrf-token]') || {}).content || '',
    };
}

// The pool endpoints carry the league type in the path. url_for rendered a
// literal __LT__ placeholder; swap in the (encoded) league type per call.
function poolUrl(tmpl, leagueType) {
    return (tmpl || '').replace('__LT__', encodeURIComponent(leagueType || ''));
}

function toast(icon, title, text) {
    if (!window.Swal) return;
    const dark = document.documentElement.classList.contains('dark');
    window.Swal.fire({
        icon, title, text: text || '',
        toast: true, position: 'top-end', timer: icon === 'error' ? 4000 : 2000,
        showConfirmButton: false,
        background: dark ? '#1f2937' : '#ffffff', color: dark ? '#f3f4f6' : '#111827',
    });
}

async function postJson(url, body) {
    const c = cfg();
    const resp = await fetch(url, {
        method: 'POST', credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': c.csrf, 'X-Requested-With': 'XMLHttpRequest' },
        body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    return { ok: resp.ok && data.success !== false, data };
}

/* ------------------------------------------------------------------ tabs */

function switchTab(key) {
    document.querySelectorAll('[data-tab-panel]').forEach(p => {
        p.classList.toggle('hidden', p.getAttribute('data-tab-panel') !== key);
    });
    document.querySelectorAll('.sct-tab').forEach(t => {
        const on = t.dataset.tab === key;
        t.classList.toggle('text-ecs-green', on);
        t.classList.toggle('border-ecs-green', on);
        t.classList.toggle('border-transparent', !on);
        t.classList.toggle('text-gray-500', !on);
        t.classList.toggle('dark:text-gray-400', !on);
    });
}

/* --------------------------------------------------------- league filter */

function filterNeeds(league) {
    let shown = 0;
    document.querySelectorAll('.sct-need').forEach(el => {
        const match = league === 'all' || el.dataset.leagueType === league;
        el.classList.toggle('hidden', !match);
        if (match) shown += 1;
    });
    const c = document.getElementById('sct-needs-count');
    if (c) c.textContent = shown;
    document.querySelectorAll('.sct-league-btn').forEach(b => {
        const on = b.dataset.league === league;
        b.classList.toggle('bg-white', on);
        b.classList.toggle('text-gray-900', on);
        b.classList.toggle('shadow-sm', on);
        b.classList.toggle('dark:bg-gray-700', on);
        b.classList.toggle('dark:text-white', on);
    });
}

// Sub Pool filters are ANDed: status × league × search. A card shows only if it
// matches the active status filter AND the active league filter AND the search.
let _poolStatus = 'all';
let _poolLeague = 'all';

function _poolBtnActive(selector, key, value) {
    document.querySelectorAll(selector).forEach(b => {
        const on = b.dataset[key] === value;
        b.classList.toggle('bg-white', on);
        b.classList.toggle('text-gray-900', on);
        b.classList.toggle('shadow-sm', on);
        b.classList.toggle('dark:bg-gray-700', on);
        b.classList.toggle('dark:text-white', on);
    });
}

function applyPoolFilters() {
    const q = (document.getElementById('sct-pool-search')?.value || '').trim().toLowerCase();
    document.querySelectorAll('.sct-pool-card').forEach(el => {
        const okStatus = _poolStatus === 'all' || el.dataset.status === _poolStatus;
        const okLeague = _poolLeague === 'all' || el.dataset.leagueType === _poolLeague;
        const okSearch = !q || (el.dataset.search || '').indexOf(q) !== -1;
        el.classList.toggle('hidden', !(okStatus && okLeague && okSearch));
    });
}

function filterPool(status) {
    _poolStatus = status;
    _poolBtnActive('.sct-pool-btn', 'status', status);
    applyPoolFilters();
}

function filterPoolLeague(league) {
    _poolLeague = league;
    _poolBtnActive('.sct-pool-league-btn', 'league', league);
    applyPoolFilters();
}

// Search input handler delegates into the combined filter.
function applyPoolSearch() { applyPoolFilters(); }

/* ------------------------------------------------ candidate slide-over */

function avatar(url, name, size) {
    const s = size || 42;
    if (url) return `<img src="${esc(url)}" alt="" class="rounded-full object-cover shrink-0" style="width:${s}px;height:${s}px">`;
    const parts = (name || '').split(' ').filter(Boolean);
    const initials = parts.length ? (parts[0][0] + (parts[parts.length - 1][0] || '')).toUpperCase() : '?';
    return `<span class="rounded-full bg-gray-200 dark:bg-gray-600 inline-flex items-center justify-center text-xs font-bold text-gray-600 dark:text-gray-200 shrink-0" style="width:${s}px;height:${s}px">${esc(initials)}</span>`;
}

function candidateRow(c, ctx) {
    const conflict = c.conflict
        ? `<span class="inline-flex items-center gap-0.5 text-[10px] font-bold text-red-600 bg-red-100 dark:bg-red-500/15 dark:text-red-300 px-1.5 py-0.5 rounded"><i class="ti ti-alert-triangle"></i>plays this team</span>` : '';
    const slots = (c.time_slots && c.time_slots.length) ? c.time_slots.join(', ') : (c.is_available ? 'available' : '');
    const rr = Math.round(c.response_rate || 0);
    // Soft signals — never hide a sub, just annotate fit + load for balance.
    const fitBadge = c.position_fit === true
        ? `<span class="inline-flex items-center gap-0.5 font-semibold text-green-600 dark:text-green-400"><i class="ti ti-target"></i>fits</span>`
        : (c.position_fit === false ? `<span class="text-gray-400">off-position</span>` : '');
    const capBadge = c.at_weekly_cap
        ? `<span class="inline-flex items-center gap-0.5 text-amber-600 dark:text-amber-400" title="At their preferred weekly sub cap"><i class="ti ti-alert-circle"></i>at weekly cap</span>` : '';
    const assignBtn = ctx.canAssign
        ? `<button type="button" data-action="sct-assign" data-assign-url="${esc(ctx.assignUrl)}" data-league="${esc(ctx.league)}" data-request-id="${esc(ctx.requestId)}" data-match-id="${esc(ctx.matchId)}" data-team-id="${esc(ctx.teamId)}" data-player-id="${esc(c.player_id)}" class="h-7 px-3 inline-flex items-center rounded-lg bg-ecs-green hover:bg-ecs-green-700 text-white text-xs font-semibold">Assign</button>`
        : `<span class="h-7 px-3 inline-flex items-center rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-400 text-xs font-semibold cursor-not-allowed" title="You do not have assignment authority for this request">Assign</span>`;
    return `
    <div class="flex gap-3 p-2.5 rounded-lg hover:bg-gray-50 dark:hover:bg-gray-700/50 items-center">
      ${avatar(c.avatar_url, c.name, 40)}
      <div class="flex-1 min-w-0">
        <div class="flex items-center gap-2"><span class="text-sm font-semibold text-gray-900 dark:text-white truncate">${esc(c.name)}</span>${conflict}</div>
        <div class="flex items-center gap-2.5 mt-0.5 text-[11px] text-gray-500 dark:text-gray-400 flex-wrap">
          ${c.preferred_position ? `<span class="inline-flex items-center gap-0.5"><i class="ti ti-user"></i>${esc(c.preferred_position)}</span>` : ''}
          ${fitBadge}
          <span>${rr}% response</span>
          <span class="font-mono">${esc(c.subbed_this_season || 0)} subs · season</span>
          ${capBadge}
        </div>
      </div>
      <div class="flex flex-col items-end gap-1.5 shrink-0">
        ${slots ? `<span class="text-[10px] font-bold px-2 py-0.5 rounded-full bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300">${esc(slots)}</span>` : ''}
        ${assignBtn}
      </div>
    </div>`;
}

async function selectNeed(el) {
    document.querySelectorAll('.sct-need').forEach(n => n.classList.remove('ring-2', 'ring-ecs-green'));
    el.classList.add('ring-2', 'ring-ecs-green');

    const d = el.dataset;
    const empty = document.getElementById('sct-panel-empty');
    const panel = document.getElementById('sct-panel-content');
    empty.classList.add('hidden');
    panel.classList.remove('hidden');

    const remaining = parseInt(d.needed, 10) - parseInt(d.assigned, 10);
    const authNote = d.league === 'ecs_fc'
        ? `<div class="mt-2.5 flex items-center gap-2 text-xs px-2.5 py-2 rounded-lg bg-ecs-green/10 text-ecs-green"><i class="ti ti-shield-check"></i>ECS FC — the team's coach or an admin can assign</div>`
        : `<div class="mt-2.5 flex items-center gap-2 text-xs px-2.5 py-2 rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"><i class="ti ti-lock"></i>Pub League — admins assign (coaches request only)</div>`;

    panel.innerHTML = `
      <div class="px-4 py-3.5 border-b border-gray-200 dark:border-gray-700">
        <div class="flex items-start justify-between gap-2">
          <h3 class="font-semibold text-gray-900 dark:text-white truncate">${esc(d.teamName)}</h3>
          <button type="button" data-action="sct-panel-close" aria-label="Close" class="h-7 w-7 inline-flex items-center justify-center rounded-lg text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700"><i class="ti ti-x"></i></button>
        </div>
        <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">${esc(d.matchLabel)}${d.timeLabel ? ' · ' + esc(d.timeLabel) : ''}</p>
        ${authNote}
      </div>
      <div class="grid grid-cols-3 divide-x divide-gray-200 dark:divide-gray-700 border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/40 text-center">
        <div class="py-2.5"><div class="font-mono text-lg font-bold text-amber-600 dark:text-amber-400">${remaining}</div><div class="text-[10px] uppercase tracking-wide text-gray-500">still needed</div></div>
        <div class="py-2.5"><div class="font-mono text-lg font-bold text-gray-900 dark:text-white">${esc(d.positions || '—')}</div><div class="text-[10px] uppercase tracking-wide text-gray-500">positions</div></div>
        <div class="py-2.5"><div class="font-mono text-lg font-bold text-green-600 dark:text-green-400" id="sct-cand-count">…</div><div class="text-[10px] uppercase tracking-wide text-gray-500">available</div></div>
      </div>
      <div class="px-4 pt-3 pb-1 text-xs uppercase tracking-wide text-gray-500 dark:text-gray-400 font-bold">Who can sub</div>
      <div id="sct-cand-list" class="max-h-[46vh] overflow-y-auto px-2 pb-2 space-y-1">
        <div class="animate-pulse space-y-2 p-3">
          <div class="h-10 rounded-lg bg-gray-100 dark:bg-gray-700"></div>
          <div class="h-10 rounded-lg bg-gray-100 dark:bg-gray-700"></div>
        </div>
      </div>
      ${d.league === 'ecs_fc' ? '' : `
      <div class="px-4 py-3 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/40">
        <button type="button" data-action="sct-reachout-open" data-kind="targeted"
                data-request-id="${esc(d.requestId)}" data-league-type="${esc(d.leagueType)}"
                data-team-name="${esc(d.teamName)}" data-time-label="${esc(d.timeLabel)}"
                data-time-slot="${esc(d.timeSlot)}" data-match-date="${esc(d.matchDate)}" data-match-id="${esc(d.matchId)}"
                class="w-full h-9 inline-flex items-center justify-center gap-1.5 rounded-lg border border-ecs-green text-ecs-green text-sm font-semibold hover:bg-ecs-green/10">
          <i class="ti ti-send"></i>Reach out to eligible ${esc(d.leagueType)} subs
        </button>
      </div>`}`;

    const list = document.getElementById('sct-cand-list');
    try {
        const url = `${cfg().candidatesUrl}?request_id=${encodeURIComponent(d.requestId)}&league=${encodeURIComponent(d.league)}`;
        const resp = await fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const j = await resp.json();
        const cands = (j && j.candidates) || [];
        const ctx = {
            league: d.league,
            requestId: d.requestId,
            assignUrl: j.assign_url || d.assignUrl,
            matchId: (j.match_id != null ? j.match_id : d.matchId),
            teamId: (j.team_id != null ? j.team_id : d.teamId),
            canAssign: (d.canAssign === '1') && (j.can_assign !== false),
        };
        document.getElementById('sct-cand-count').textContent = cands.filter(c => c.is_available).length || cands.length;
        if (!cands.length) {
            list.innerHTML = `<div class="px-3 py-8 text-center text-sm text-gray-400">No one available yet — reach out below.</div>`;
            return;
        }
        list.innerHTML = cands.map(c => candidateRow(c, ctx)).join('');
    } catch (e) {
        list.innerHTML = `<div class="px-3 py-8 text-center text-sm text-red-500">Could not load candidates.</div>`;
    }
}

function closePanel() {
    document.querySelectorAll('.sct-need').forEach(n => n.classList.remove('ring-2', 'ring-ecs-green'));
    document.getElementById('sct-panel-content').classList.add('hidden');
    document.getElementById('sct-panel-empty').classList.remove('hidden');
}

async function assignCandidate(el) {
    const d = el.dataset;
    const c = cfg();
    // Use the JSON assign endpoint so we can trust the outcome. The legacy
    // flash+redirect endpoints always look like HTTP 200 to fetch, so a
    // denied / already-filled / unavailable assign would falsely read as success.
    el.disabled = true;
    const orig = el.innerHTML;
    el.innerHTML = '…';
    try {
        const resp = await fetch(c.assignUrl, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': c.csrf },
            body: JSON.stringify({
                request_id: d.requestId,
                league: d.league,
                player_id: d.playerId,
                position: d.position || '',
            }),
        });
        let j = {};
        try { j = await resp.json(); } catch (e) { /* non-JSON */ }
        if (resp.ok && j && j.success) {
            toast('success', j.message || 'Substitute assigned');
            setTimeout(() => window.location.reload(), 800);
        } else {
            el.disabled = false; el.innerHTML = orig;
            toast('error', 'Could not assign', (j && j.error) || `Server responded ${resp.status}`);
        }
    } catch (e) {
        el.disabled = false; el.innerHTML = orig;
        toast('error', 'Network error');
    }
}

/* ---------------------------------------------- pool membership actions */

async function confirmAction(opts) {
    if (!window.Swal) return window.confirm(opts.text || 'Are you sure?');
    const dark = document.documentElement.classList.contains('dark');
    const res = await window.Swal.fire({
        title: opts.title || 'Are you sure?',
        text: opts.text || '',
        icon: opts.icon || 'warning',
        showCancelButton: true,
        confirmButtonText: opts.confirmText || 'Confirm',
        cancelButtonText: 'Cancel',
        confirmButtonColor: opts.danger ? '#dc2626' : '#16a34a',
        background: dark ? '#1f2937' : '#ffffff', color: dark ? '#f3f4f6' : '#111827',
    });
    return res.isConfirmed;
}

async function poolAction(url, body) {
    const { ok, data } = await postJson(url, body);
    if (ok) {
        toast('success', data.message || 'Done');
        setTimeout(() => window.location.reload(), 700);
    } else {
        toast('error', 'Action failed', (data && data.message) || '');
    }
}

function poolCardCtx(el) {
    const card = el.closest('.sct-pool-card');
    if (!card) return null;
    return { card, d: card.dataset, playerId: parseInt(card.dataset.playerId, 10), leagueType: card.dataset.leagueType };
}

function poolSetActive(el) {
    const ctx = poolCardCtx(el); if (!ctx) return;
    poolAction(poolUrl(cfg().poolSetActiveUrl, ctx.leagueType), {
        player_id: ctx.playerId, is_active: el.dataset.active === 'true',
    });
}

async function poolRemove(el) {
    const ctx = poolCardCtx(el); if (!ctx) return;
    const ok = await confirmAction({
        title: 'Remove from pool?',
        text: `Remove ${ctx.d.name} from the ${ctx.leagueType} substitute pool? Their sub role is revoked if they are in no other pool.`,
        confirmText: 'Remove', danger: true,
    });
    if (!ok) return;
    poolAction(poolUrl(cfg().poolRemoveUrl, ctx.leagueType), { player_id: ctx.playerId });
}

function poolApprove(el) {
    const ctx = poolCardCtx(el); if (!ctx) return;
    poolAction(poolUrl(cfg().poolApproveUrl, ctx.leagueType), { player_id: ctx.playerId });
}

async function poolReject(el) {
    const ctx = poolCardCtx(el); if (!ctx) return;
    const ok = await confirmAction({
        title: 'Reject applicant?',
        text: `Reject ${ctx.d.name} for the ${ctx.leagueType} substitute pool? They will not appear as available to add.`,
        confirmText: 'Reject', danger: true,
    });
    if (!ok) return;
    poolAction(poolUrl(cfg().poolRejectUrl, ctx.leagueType), { player_id: ctx.playerId });
}

// Multi-league membership: put the same person into another league's pool. The
// roster shows one card per (player, league), so the added league appears as its
// own card and can be removed independently via that card's Remove.
const POOL_LEAGUES = ['ECS FC', 'Classic', 'Premier'];

async function poolAddLeague(el) {
    const playerId = parseInt(el.dataset.playerId, 10);
    const name = el.dataset.playerName || 'this player';
    const current = el.dataset.currentLeague || '';
    const others = POOL_LEAGUES.filter(lt => lt !== current);
    if (!playerId || !others.length || !window.Swal) return;
    const dark = document.documentElement.classList.contains('dark');
    const inputOptions = {};
    others.forEach(lt => { inputOptions[lt] = lt; });
    const res = await window.Swal.fire({
        title: 'Add to another league',
        html: `Put <b>${esc(name)}</b> in an additional substitute pool.` +
              (current ? ` They currently sub for <b>${esc(current)}</b>.` : ''),
        input: 'select',
        inputOptions,
        inputValue: others[0],
        showCancelButton: true,
        confirmButtonText: 'Add to pool',
        cancelButtonText: 'Cancel',
        confirmButtonColor: '#16a34a',
        background: dark ? '#1f2937' : '#ffffff', color: dark ? '#f3f4f6' : '#111827',
    });
    if (!res.isConfirmed || !res.value) return;
    const chosen = res.value;
    const { ok, data } = await postJson(poolUrl(cfg().poolAddUrl, chosen), { player_id: playerId });
    if (ok) {
        toast('success', `Added ${name} to ${chosen}`);
        setTimeout(() => window.location.reload(), 700);
    } else {
        toast('error', 'Could not add', (data && data.message) || `${name} may already be in the ${chosen} pool.`);
    }
}

/* ----------------------------------------------------- add-to-pool modal */

const addState = { leagueType: 'ECS FC', addedAny: false };
let addSearchTimer = null;

function openAddPool() {
    addState.leagueType = 'ECS FC';
    addState.addedAny = false;
    setAddLeague('ECS FC', true);
    const s = document.getElementById('sct-add-search');
    if (s) s.value = '';
    document.getElementById('sct-add-error').classList.add('hidden');
    document.getElementById('sct-add-results').innerHTML =
        '<div class="px-3 py-6 text-xs text-gray-400 text-center">Type at least 2 characters to search.</div>';
    const m = document.getElementById('sct-add-modal');
    m.classList.remove('hidden'); m.classList.add('flex');
}

function closeAddPool() {
    const m = document.getElementById('sct-add-modal');
    m.classList.add('hidden'); m.classList.remove('flex');
    // A batch add doesn't live-mutate the server-rendered grid — refresh once
    // on close so the pool roster reflects everyone just added.
    if (addState.addedAny) setTimeout(() => window.location.reload(), 200);
}

function setAddLeague(lt, skipSearch) {
    addState.leagueType = lt;
    document.querySelectorAll('.sct-add-lt').forEach(b => {
        const on = b.dataset.leagueType === lt;
        b.classList.toggle('border-ecs-green', on);
        b.classList.toggle('bg-ecs-green/10', on);
        b.classList.toggle('text-ecs-green', on);
        b.classList.toggle('border-gray-200', !on);
        b.classList.toggle('text-gray-500', !on);
    });
    if (!skipSearch) searchAddPlayers();
}

function addRow(p) {
    const inPool = (p.current_pools || []).indexOf(addState.leagueType) !== -1;
    const btn = inPool
        ? `<span class="h-7 px-3 inline-flex items-center rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-400 text-xs font-semibold shrink-0">In pool</span>`
        : `<button type="button" data-action="sct-pool-add-player" data-player-id="${esc(p.id)}" class="h-7 px-3 inline-flex items-center gap-1 rounded-lg bg-ecs-green hover:bg-ecs-green-700 text-white text-xs font-semibold shrink-0"><i class="ti ti-plus"></i>Add</button>`;
    const leagues = (p.eligible_leagues && p.eligible_leagues.length)
        ? `<div class="text-[11px] text-gray-400">Eligible: ${esc(p.eligible_leagues.join(', '))}</div>` : '';
    return `<div class="flex items-center gap-2.5 px-3 py-2 hover:bg-gray-50 dark:hover:bg-gray-700/50">
      <div class="min-w-0 flex-1"><div class="text-sm font-medium text-gray-900 dark:text-white truncate">${esc(p.name)}</div>${leagues}</div>
      ${btn}
    </div>`;
}

function searchAddPlayers() {
    const wrap = document.getElementById('sct-add-results');
    if (!wrap) return;
    const q = (document.getElementById('sct-add-search')?.value || '').trim();
    if (q.length < 2) {
        wrap.innerHTML = '<div class="px-3 py-6 text-xs text-gray-400 text-center">Type at least 2 characters to search.</div>';
        return;
    }
    wrap.innerHTML = '<div class="px-3 py-6 text-xs text-gray-400 text-center">Searching…</div>';
    const url = `${cfg().poolSearchUrl}?q=${encodeURIComponent(q)}&league_type=${encodeURIComponent(addState.leagueType)}`;
    fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(r => r.json())
        .then(j => {
            const players = (j && j.players) || [];
            if (!players.length) {
                wrap.innerHTML = '<div class="px-3 py-6 text-xs text-gray-400 text-center">No players match.</div>';
                return;
            }
            wrap.innerHTML = players.map(addRow).join('');
        })
        .catch(() => { wrap.innerHTML = '<div class="px-3 py-6 text-xs text-red-500 text-center">Search failed.</div>'; });
}

async function addPlayerToPool(el) {
    const orig = el.innerHTML;
    el.disabled = true; el.innerHTML = '…';
    const { ok, data } = await postJson(poolUrl(cfg().poolAddUrl, addState.leagueType), {
        player_id: parseInt(el.dataset.playerId, 10),
    });
    if (ok) {
        addState.addedAny = true;
        toast('success', data.message || 'Added to pool');
        el.outerHTML = '<span class="h-7 px-3 inline-flex items-center rounded-lg bg-green-100 text-green-700 dark:bg-green-500/15 dark:text-green-300 text-xs font-semibold shrink-0">Added</span>';
    } else {
        el.disabled = false; el.innerHTML = orig;
        toast('error', 'Could not add', (data && data.message) || '');
    }
}

/* ------------------------------------------------------- reach-out modal */

// `who` is the targeting mode: 'pool' (whole league pool -> kind 'general'),
// 'available' (available this week), 'position' (by position) and 'specific'
// (hand-picked) all resolve recipient ids CLIENT-SIDE and send kind 'targeted'.
const reachState = { kind: 'general', who: 'pool', leagueType: 'Premier', requestId: null,
                     matchDate: null, matchId: null, timeSlot: null, position: null };

function poolData() {
    try { return JSON.parse(document.getElementById('sct-pool-data').textContent) || []; }
    catch (e) { return []; }
}

// Server-rendered week availability rows: {player_id, league_type, is_available, time_slots}.
function availabilityData() {
    const el = document.getElementById('sct-availability-data');
    if (!el) return [];
    try { return JSON.parse(el.textContent) || []; }
    catch (e) { return []; }
}

function settingsData() {
    try { return JSON.parse(document.getElementById('sct-settings-data').textContent) || {}; }
    catch (e) { return {}; }
}

// Position chooser tokens -> the words that show up in a pool member's humanized
// `positions` string ('Goalkeeper, Center Back'). Substring match, case-insensitive.
const POSITION_KEYWORDS = {
    GK: ['goalkeeper', 'keeper', 'gk'],
    DEF: ['defender', 'defence', 'defense', 'back', 'cb', 'rb', 'lb'],
    MID: ['midfield', 'mid', 'cm', 'dm', 'am'],
    FWD: ['forward', 'striker', 'winger', 'wing', 'attack', 'fwd', 'st'],
};

// Rows carry 'Premier' / 'Classic' / 'ECS FC'; the reach-out league select is
// Pub-League-only, so a case-insensitive contains keeps this tolerant of variants.
function reachLeagueMatch(leagueType) {
    const want = (reachState.leagueType || '').toLowerCase();
    if (!want) return true;
    return (leagueType || '').toLowerCase().indexOf(want) !== -1;
}

function dedupeInts(list) {
    const seen = {};
    const out = [];
    (list || []).forEach(v => {
        const n = parseInt(v, 10);
        if (!isNaN(n) && !seen[n]) { seen[n] = 1; out.push(n); }
    });
    return out;
}

// Resolve the recipient player ids for the current targeting mode, entirely from
// the page's server-rendered data (no round-trip). Whole-pool resolves too, so the
// per-channel reach preview can be computed for it as well.
function resolveRecipientIds() {
    const who = reachState.who;
    if (who === 'specific') {
        return dedupeInts(
            Array.from(document.querySelectorAll('#sct-reach-list input:checked')).map(c => c.value)
        );
    }
    if (who === 'available') {
        return dedupeInts(
            availabilityData()
                .filter(a => a && a.is_available && reachLeagueMatch(a.league_type))
                .map(a => a.player_id)
        );
    }
    if (who === 'position') {
        if (!reachState.position) return [];
        const kws = POSITION_KEYWORDS[reachState.position] || [];
        return dedupeInts(
            poolData()
                .filter(m => m && m.status === 'active' && reachLeagueMatch(m.league_type))
                .filter(m => {
                    const pos = (m.positions || '').toLowerCase();
                    return !!pos && kws.some(k => pos.indexOf(k) !== -1);
                })
                .map(m => m.player_id)
        );
    }
    // 'pool' — every active member of the selected league's pool.
    return dedupeInts(
        poolData()
            .filter(m => m && m.status === 'active' && reachLeagueMatch(m.league_type))
            .map(m => m.player_id)
    );
}

function fillTokens(tmpl) {
    const s = settingsData();
    return (tmpl || '')
        .replace(/\{league\}/g, reachState.leagueType || '')
        .replace(/\{date\}/g, reachState.matchDate || cfg().week || '')
        .replace(/\{slot\}/g, reachState.timeSlot || '')
        .replace(/\{slots\}/g, reachState.timeSlot || 'the listed times');
}

function renderReachPicker() {
    const wrap = document.getElementById('sct-reach-list');
    const q = (document.getElementById('sct-reach-search')?.value || '').trim().toLowerCase();
    const members = poolData().filter(m => (m.league_type || '').indexOf(reachState.leagueType) !== -1 || m.league === 'pub_league');
    wrap.innerHTML = members.filter(m => {
        const hay = ((m.name || '') + ' ' + (m.positions || '')).toLowerCase();
        return !q || hay.indexOf(q) !== -1;
    }).map(m => `
      <label class="flex items-center gap-2.5 px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50">
        <input type="checkbox" name="sct-recipient" value="${esc(m.player_id)}" class="rounded text-ecs-green focus:ring-ecs-green">
        <span class="text-sm text-gray-700 dark:text-gray-300">${esc(m.name)}</span>
        ${m.positions ? `<span class="text-[11px] text-gray-400">${esc(m.positions)}</span>` : ''}
      </label>`).join('') || '<div class="px-3 py-4 text-xs text-gray-400 text-center">No subs in this league\'s pool.</div>';
}

/* Per-channel reach counts — how many of the resolved recipients each channel can
   actually deliver to, so the admin sees the real blast size before sending.
   Debounced: targeting/recipient changes fire on every keystroke/checkbox. */
let _reachCountsTimer = null;
let _reachCountsSeq = 0;

function renderReachCounts(counts) {
    const el = document.getElementById('sct-reach-reach');
    if (!el) return;
    if (!counts) { el.textContent = ''; return; }
    const parts = [
        ['ti-device-mobile', 'Push', counts.PUSH],
        ['ti-brand-discord', 'Discord', counts.DISCORD],
        ['ti-message-2', 'SMS', counts.SMS],
        ['ti-mail', 'Email', counts.EMAIL],
    ];
    el.innerHTML = parts.map(p =>
        `<span class="inline-flex items-center gap-1"><i class="ti ${esc(p[0])}"></i>${esc(p[1])} ${esc(p[2] || 0)}</span>`
    ).join('<span class="text-gray-300 dark:text-gray-600">·</span>');
}

async function fetchReachCounts(ids, seq) {
    const el = document.getElementById('sct-reach-reach');
    if (!el) return;
    const url = cfg().reachoutReachUrl;
    if (!url || !ids.length) { el.textContent = ''; return; }
    try {
        const { ok, data } = await postJson(url, { player_ids: ids });
        // Ignore a stale response that lost the race with a newer resolve.
        if (seq !== _reachCountsSeq) return;
        renderReachCounts(ok && data ? data.counts : null);
    } catch (e) {
        if (seq === _reachCountsSeq) el.textContent = '';
    }
}

function scheduleReachCounts(ids) {
    const seq = ++_reachCountsSeq;
    clearTimeout(_reachCountsTimer);
    _reachCountsTimer = setTimeout(() => fetchReachCounts(ids, seq), 300);
}

function updateReachPreview() {
    const msg = document.getElementById('sct-reach-msg');
    const prev = document.getElementById('sct-reach-preview');
    if (msg && prev) prev.textContent = fillTokens(msg.value);
    const ids = resolveRecipientIds();
    const summary = document.getElementById('sct-reach-summary');
    if (summary) summary.textContent = `${ids.length} sub${ids.length === 1 ? '' : 's'}`;
    scheduleReachCounts(ids);
}

function openReach(el) {
    const d = el ? el.dataset : {};
    const kindEntry = d.kind || 'general';
    reachState.requestId = d.requestId || null;
    reachState.matchId = d.matchId || null;
    reachState.matchDate = d.matchDate || cfg().week;
    reachState.timeSlot = d.timeSlot || null;
    reachState.who = 'pool';
    reachState.position = null;

    const leagueSel = document.getElementById('sct-reach-league');
    const s = settingsData();
    if (kindEntry === 'targeted' && d.leagueType) {
        reachState.leagueType = d.leagueType;
        leagueSel.value = d.leagueType;
        leagueSel.disabled = true;
        document.getElementById('sct-reach-title').textContent = `Reach out — ${d.teamName || 'gap'}`;
        document.getElementById('sct-reach-sub').textContent =
            `Ask ${d.leagueType} subs${d.timeLabel ? ' about ' + d.timeLabel : ''} · team stays hidden`;
        document.getElementById('sct-reach-msg').value = fillTokens(s.sub_reachout_msg_targeted || '');
    } else {
        // Opened from a specific slot/league context (e.g. availability grid) —
        // pre-seed the league when it maps to a selectable option.
        if (d.leagueType) {
            const opt = Array.from(leagueSel.options).find(o => o.value === d.leagueType);
            if (opt) leagueSel.value = d.leagueType;
        }
        reachState.leagueType = leagueSel.value || 'Premier';
        leagueSel.disabled = false;
        document.getElementById('sct-reach-title').textContent = 'Reach out to subs';
        document.getElementById('sct-reach-sub').textContent = 'Ask a league pool who can play this week';
        document.getElementById('sct-reach-msg').value = fillTokens(s.sub_reachout_msg_general || '');
    }

    // Default channels from settings.
    const defCh = (s.sub_reachout_default_channels || 'PUSH,DISCORD,EMAIL').toUpperCase();
    document.querySelectorAll('#sct-reach-channels input').forEach(cb => { cb.checked = defCh.indexOf(cb.value) !== -1; });

    syncReachPosChips();
    setReachWho('pool');
    renderReachPicker();
    updateReachPreview();
    const modal = document.getElementById('sct-reach-modal');
    modal.classList.remove('hidden'); modal.classList.add('flex');
}

function closeReach() {
    const modal = document.getElementById('sct-reach-modal');
    modal.classList.add('hidden'); modal.classList.remove('flex');
}

function setReachWho(who) {
    reachState.who = who;
    document.querySelectorAll('.sct-who').forEach(b => {
        const on = b.dataset.who === who;
        b.classList.toggle('border-ecs-green', on);
        b.classList.toggle('bg-ecs-green/10', on);
        b.classList.toggle('text-ecs-green', on);
        b.classList.toggle('border-gray-200', !on);
        b.classList.toggle('text-gray-500', !on);
    });
    const picker = document.getElementById('sct-reach-picker');
    if (picker) picker.classList.toggle('hidden', who !== 'specific');
    const posWrap = document.getElementById('sct-reach-positions');
    if (posWrap) posWrap.classList.toggle('hidden', who !== 'position');
    updateReachPreview();
}

function syncReachPosChips() {
    document.querySelectorAll('.sct-reach-pos').forEach(b => {
        const on = b.dataset.pos === reachState.position;
        b.classList.toggle('border-ecs-green', on);
        b.classList.toggle('bg-ecs-green/10', on);
        b.classList.toggle('text-ecs-green', on);
        b.classList.toggle('border-gray-200', !on);
        b.classList.toggle('text-gray-500', !on);
    });
}

// Single-select position chooser (clicking the active one clears it).
function setReachPos(el) {
    const pos = (el && el.dataset.pos) || null;
    reachState.position = (reachState.position === pos) ? null : pos;
    syncReachPosChips();
    updateReachPreview();
}

async function sendReach() {
    const errEl = document.getElementById('sct-reach-error');
    errEl.classList.add('hidden');
    const channels = Array.from(document.querySelectorAll('#sct-reach-channels input:checked')).map(c => c.value);
    if (!channels.length) { errEl.textContent = 'Select at least one channel.'; errEl.classList.remove('hidden'); return; }

    // Whole pool is the only mode the server resolves for us ('general'); every
    // other mode resolves ids here and sends them as an explicit 'targeted' list.
    const who = reachState.who;
    const kind = who === 'pool' ? 'general' : 'targeted';
    const recipientIds = kind === 'targeted' ? resolveRecipientIds() : [];
    if (kind === 'targeted' && !recipientIds.length) {
        const why = who === 'specific'
            ? 'Pick at least one person.'
            : (who === 'position'
                ? (reachState.position ? 'No active subs in that league play that position.' : 'Pick a position.')
                : 'No subs have marked themselves available for that league this week.');
        errEl.textContent = why;
        errEl.classList.remove('hidden');
        return;
    }

    const payload = {
        kind,
        league_type: document.getElementById('sct-reach-league').value,
        match_date: reachState.matchDate || cfg().week,
        time_slots: reachState.timeSlot ? [reachState.timeSlot] : [],
        match_ids: reachState.matchId ? [parseInt(reachState.matchId, 10)] : [],
        request_id: reachState.requestId ? parseInt(reachState.requestId, 10) : null,
        recipient_player_ids: kind === 'targeted' ? recipientIds : [],
        channels,
        message: fillTokens(document.getElementById('sct-reach-msg').value),
    };

    const btn = document.querySelector('[data-action="sct-reach-send"]');
    const orig = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<i class="ti ti-loader animate-spin"></i>Sending…';
    const { ok, data } = await postJson(cfg().reachoutUrl, payload);
    btn.disabled = false; btn.innerHTML = orig;
    if (ok) {
        closeReach();
        toast('success', 'Reach-out sent', `${data.recipients_count || 0} contacted · ${data.notifications_sent || 0} notified`);
    } else {
        errEl.textContent = (data && data.error) || 'Could not send reach-out.';
        errEl.classList.remove('hidden');
    }
}

/* ------------------------------------------------- request-a-sub modal */

// Cache of the option payload so team→match cascades without re-fetching.
// `mode` flips the shared modal between creating a new request and editing an
// existing one (team + match locked, PATCH-style save to a different endpoint).
const reqState = { byId: {}, mode: 'create', editRequestId: null, editLeague: null };

// Toggle the shared modal chrome (title, team/match editability, submit label)
// between the create and edit flows so one modal serves both.
function setRequestModeUI(mode, ctx) {
    ctx = ctx || {};
    const isEdit = mode === 'edit';
    const title = document.getElementById('sct-req-title');
    const subtitle = document.getElementById('sct-req-subtitle');
    const teamSel = document.getElementById('sct-req-team');
    const matchSel = document.getElementById('sct-req-match');
    const teamStatic = document.getElementById('sct-req-team-static');
    const matchStatic = document.getElementById('sct-req-match-static');
    const editNote = document.getElementById('sct-req-edit-note');
    const btn = document.getElementById('sct-req-submit-btn');
    if (title) title.textContent = isEdit ? 'Edit request' : 'Request a sub';
    if (subtitle) subtitle.textContent = isEdit
        ? 'Update how many subs and which positions this request needs.'
        : 'Open a substitute request for one of your matches — the pool gets asked automatically.';
    // Team + match aren't editable here — show them as static text when editing.
    if (teamSel) teamSel.classList.toggle('hidden', isEdit);
    if (matchSel) matchSel.classList.toggle('hidden', isEdit);
    if (teamStatic) { teamStatic.classList.toggle('hidden', !isEdit); teamStatic.textContent = isEdit ? (ctx.teamName || '—') : ''; }
    if (matchStatic) { matchStatic.classList.toggle('hidden', !isEdit); matchStatic.textContent = isEdit ? (ctx.matchLabel || '—') : ''; }
    if (editNote) editNote.classList.toggle('hidden', !isEdit);
    if (btn) btn.innerHTML = isEdit
        ? '<i class="ti ti-device-floppy"></i>Save changes'
        : '<i class="ti ti-plus"></i>Create request';
}

function openRequest() {
    const err = document.getElementById('sct-req-error');
    err.classList.add('hidden'); err.textContent = '';
    reqState.mode = 'create';
    reqState.editRequestId = null;
    reqState.editLeague = null;
    setRequestModeUI('create');
    document.getElementById('sct-req-positions').value = '';
    document.getElementById('sct-req-gender').value = '';
    document.getElementById('sct-req-amount').value = '1';
    document.getElementById('sct-req-notes').value = '';
    syncPosChips();

    const teamSel = document.getElementById('sct-req-team');
    const matchSel = document.getElementById('sct-req-match');
    teamSel.innerHTML = '<option value="">Loading teams…</option>';
    teamSel.disabled = true;
    matchSel.innerHTML = '<option value="">Select a team first</option>';
    matchSel.disabled = true;

    const m = document.getElementById('sct-req-modal');
    m.classList.remove('hidden'); m.classList.add('flex');
    loadRequestOptions();
}

// Open the same modal in edit mode, prefilled from the row's current values.
// Team/match come along only as static labels — the backend edits positions,
// gender, amount and notes in place.
function openRequestEdit(el) {
    const d = el.dataset;
    const err = document.getElementById('sct-req-error');
    err.classList.add('hidden'); err.textContent = '';
    reqState.mode = 'edit';
    reqState.editRequestId = d.requestId;
    reqState.editLeague = d.league;

    document.getElementById('sct-req-positions').value = d.positions || '';
    document.getElementById('sct-req-gender').value = d.gender || '';
    const amt = parseInt(d.needed, 10);
    document.getElementById('sct-req-amount').value = (!isNaN(amt) && amt > 0) ? amt : '1';
    document.getElementById('sct-req-notes').value = d.notes || '';
    syncPosChips();

    setRequestModeUI('edit', { teamName: d.teamName, matchLabel: d.matchLabel });

    const m = document.getElementById('sct-req-modal');
    m.classList.remove('hidden'); m.classList.add('flex');
}

function closeRequest() {
    const m = document.getElementById('sct-req-modal');
    m.classList.add('hidden'); m.classList.remove('flex');
}

async function loadRequestOptions() {
    const teamSel = document.getElementById('sct-req-team');
    try {
        const resp = await fetch(cfg().requestOptionsUrl, {
            credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        const j = await resp.json();
        const teams = (j && j.teams) || [];
        reqState.byId = {};
        teams.forEach(t => { reqState.byId[String(t.id)] = t; });
        if (!teams.length) {
            teamSel.innerHTML = '<option value="">No teams available to you</option>';
            teamSel.disabled = true;
            return;
        }
        // Group by program so a coach with teams in both leagues sees them labeled.
        const order = ['pub_league', 'ecs_fc'];
        const labels = { pub_league: 'Pub League', ecs_fc: 'ECS FC' };
        const groups = {};
        teams.forEach(t => { (groups[t.program] = groups[t.program] || []).push(t); });
        const progs = order.filter(p => groups[p]).concat(Object.keys(groups).filter(p => order.indexOf(p) === -1));
        let html = '<option value="">Select a team…</option>';
        progs.forEach(prog => {
            html += `<optgroup label="${esc(labels[prog] || prog)}">`;
            groups[prog].forEach(t => {
                const lt = t.league_type ? ` (${t.league_type})` : '';
                html += `<option value="${esc(t.id)}">${esc(t.name)}${esc(lt)}</option>`;
            });
            html += '</optgroup>';
        });
        teamSel.innerHTML = html;
        teamSel.disabled = false;
    } catch (e) {
        teamSel.innerHTML = '<option value="">Could not load teams</option>';
        teamSel.disabled = true;
    }
}

function onRequestTeamChange() {
    const teamSel = document.getElementById('sct-req-team');
    const matchSel = document.getElementById('sct-req-match');
    const t = reqState.byId[String(teamSel.value)];
    if (!t) {
        matchSel.innerHTML = '<option value="">Select a team first</option>';
        matchSel.disabled = true;
        return;
    }
    const matches = t.matches || [];
    if (!matches.length) {
        matchSel.innerHTML = '<option value="">No upcoming matches</option>';
        matchSel.disabled = true;
        return;
    }
    matchSel.innerHTML = '<option value="">Select a match…</option>' + matches.map(mt => {
        const dt = mt.date ? ` · ${mt.date}` : '';
        return `<option value="${esc(mt.id)}">${esc(mt.label)}${esc(dt)}</option>`;
    }).join('');
    matchSel.disabled = false;
}

function togglePosChip(el) {
    const input = document.getElementById('sct-req-positions');
    const tok = (el.dataset.pos || '').trim();
    if (!tok) return;
    const toks = input.value.split(',').map(s => s.trim()).filter(Boolean);
    const i = toks.findIndex(x => x.toUpperCase() === tok.toUpperCase());
    if (i === -1) toks.push(tok); else toks.splice(i, 1);
    input.value = toks.join(', ');
    syncPosChips();
}

function syncPosChips() {
    const input = document.getElementById('sct-req-positions');
    const toks = (input.value || '').split(',').map(s => s.trim().toUpperCase()).filter(Boolean);
    document.querySelectorAll('.sct-req-pos').forEach(chip => {
        const on = toks.indexOf((chip.dataset.pos || '').toUpperCase()) !== -1;
        chip.classList.toggle('border-ecs-green', on);
        chip.classList.toggle('bg-ecs-green/10', on);
        chip.classList.toggle('text-ecs-green', on);
        chip.classList.toggle('border-gray-200', !on);
        chip.classList.toggle('dark:border-gray-700', !on);
        chip.classList.toggle('text-gray-500', !on);
        chip.classList.toggle('dark:text-gray-400', !on);
    });
}

async function submitRequest() {
    const err = document.getElementById('sct-req-error');
    err.classList.add('hidden'); err.textContent = '';
    const fail = (msg) => { err.textContent = msg; err.classList.remove('hidden'); };

    const amount = parseInt(document.getElementById('sct-req-amount').value, 10);
    if (!amount || amount < 1 || amount > 10) return fail('Enter how many subs are needed (1–10).');

    // Edit mode: team + match are fixed; save the editable fields in place.
    if (reqState.mode === 'edit') {
        const rid = parseInt(reqState.editRequestId, 10);
        const editPayload = {
            league: reqState.editLeague,
            request_id: isNaN(rid) ? reqState.editRequestId : rid,
            positions_needed: document.getElementById('sct-req-positions').value.trim(),
            gender_preference: document.getElementById('sct-req-gender').value,
            substitutes_needed: amount,
            notes: document.getElementById('sct-req-notes').value.trim(),
        };
        const editBtn = document.getElementById('sct-req-submit-btn');
        const editOrig = editBtn.innerHTML;
        editBtn.disabled = true; editBtn.innerHTML = '<i class="ti ti-loader animate-spin"></i>Saving…';
        const { ok: eok, data: edata } = await postJson(cfg().requestEditUrl, editPayload);
        editBtn.disabled = false; editBtn.innerHTML = editOrig;
        if (eok) {
            closeRequest();
            toast('success', 'Request updated', 'Your changes were saved.');
            setTimeout(() => window.location.reload(), 800);
        } else {
            fail((edata && edata.error) || 'Could not save your changes.');
        }
        return;
    }

    const teamSel = document.getElementById('sct-req-team');
    const matchSel = document.getElementById('sct-req-match');
    const t = reqState.byId[String(teamSel.value)];

    if (!t) return fail('Pick a team.');
    if (!matchSel.value) return fail('Pick a match.');

    const payload = {
        league: t.program,
        team_id: t.id,
        match_id: parseInt(matchSel.value, 10),
        positions_needed: document.getElementById('sct-req-positions').value.trim(),
        gender_preference: document.getElementById('sct-req-gender').value,
        substitutes_needed: amount,
        notes: document.getElementById('sct-req-notes').value.trim(),
    };

    const btn = document.querySelector('[data-action="sct-request-submit"]');
    const orig = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<i class="ti ti-loader animate-spin"></i>Creating…';
    const { ok, data } = await postJson(cfg().requestCreateUrl, payload);
    btn.disabled = false; btn.innerHTML = orig;
    if (ok) {
        closeRequest();
        toast('success', 'Request created', 'The sub pool is being asked now.');
        setTimeout(() => window.location.reload(), 800);
    } else {
        fail((data && data.error) || 'Could not create the request.');
    }
}

async function cancelRequest(el) {
    const league = el.dataset.league;
    const rid = parseInt(el.dataset.requestId, 10);
    const ok = await confirmAction({
        title: 'Cancel this request?',
        text: 'The substitute request will be closed and no longer shown as open.',
        confirmText: 'Cancel request', danger: true,
    });
    if (!ok) return;
    const { ok: done, data } = await postJson(cfg().requestCancelUrl, {
        league,
        request_id: isNaN(rid) ? el.dataset.requestId : rid,
    });
    if (done) {
        toast('success', data.message || 'Request cancelled');
        setTimeout(() => window.location.reload(), 700);
    } else {
        toast('error', 'Could not cancel', (data && data.error) || '');
    }
}

/* ------------------------------------------------ settings live previews */

// Sample values so the admin sees a realistic message while typing. {early}
// reads the live arrive-early input so the two settings stay visibly linked.
function fillSampleTokens(tmpl) {
    const earlyEl = document.querySelector('[data-setting="sub_arrive_early_min"]');
    const earlyRaw = earlyEl ? String(earlyEl.value || '').trim() : '';
    const early = earlyRaw === '' ? '15' : earlyRaw;
    return String(tmpl == null ? '' : tmpl)
        .replace(/\{date\}/g, 'Sun Jul 27')
        .replace(/\{team\}/g, 'Cascade FC')
        .replace(/\{time\}/g, '8:20am')
        .replace(/\{location\}/g, 'Starfire 3')
        .replace(/\{early\}/g, early)
        .replace(/\{slots\}/g, '8:20am, 9:30am')
        .replace(/\{slot\}/g, '8:20am')
        .replace(/\{league\}/g, 'Premier');
}

// AdminConfig key -> preview element id (rendered by _substitute_settings.html).
const SETTINGS_PREVIEWS = {
    sub_poll_question: 'sct-prev-poll',
    sub_reachout_msg_general: 'sct-prev-general',
    sub_reachout_msg_targeted: 'sct-prev-targeted',
    sub_confirmation_msg: 'sct-prev-confirm',
};

function renderSettingPreview(key) {
    const src = document.querySelector(`[data-setting="${key}"]`);
    const target = document.getElementById(SETTINGS_PREVIEWS[key]);
    if (!src || !target) return;
    // textContent — never innerHTML: the admin's raw template is untrusted markup.
    target.textContent = fillSampleTokens(src.value);
}

function initSettingsPreviews() {
    Object.keys(SETTINGS_PREVIEWS).forEach(key => {
        const src = document.querySelector(`[data-setting="${key}"]`);
        if (!src) return;
        renderSettingPreview(key);
        src.addEventListener('input', () => renderSettingPreview(key));
    });
    // {early} lives in the confirmation message — re-render it as the number changes.
    const early = document.querySelector('[data-setting="sub_arrive_early_min"]');
    if (early) early.addEventListener('input', () => renderSettingPreview('sub_confirmation_msg'));
}

/* ------------------------------------------------------------ settings */

function collectSettings() {
    const out = {};
    document.querySelectorAll('[data-setting]').forEach(el => {
        const key = el.dataset.setting;
        const type = el.dataset.settingType || 'string';
        let value;
        if (el.type === 'checkbox') value = el.checked;
        else if (type === 'boolean') value = el.value === 'true';
        else if (type === 'integer') value = parseInt(el.value, 10) || 0;
        else value = el.value;
        out[key] = value;
    });
    // Default reach-out channels are a checkbox group -> CSV.
    const ch = Array.from(document.querySelectorAll('[data-setting-channel]:checked')).map(c => c.value);
    out.sub_reachout_default_channels = ch.join(',');
    // Ping roles are a live checkbox picker -> CSV of role ids.
    const roles = Array.from(document.querySelectorAll('#sct-poll-roles input[type=checkbox]:checked')).map(c => c.value);
    out.sub_poll_role_ids = roles.join(',');
    return out;
}

async function saveSettings() {
    const btn = document.querySelector('[data-action="sct-settings-save"]');
    const orig = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<i class="ti ti-loader animate-spin"></i>Saving…';
    const { ok, data } = await postJson(cfg().settingsSaveUrl, collectSettings());
    btn.disabled = false; btn.innerHTML = orig;
    if (ok) toast('success', 'Settings saved', `${data.saved || 0} updated`);
    else toast('error', 'Could not save', (data && data.error) || '');
}

async function loadChannelsOnInit() {
    const sel = document.getElementById('sct-poll-channel');
    if (!sel) return;
    try {
        const resp = await fetch(cfg().discordChannelsUrl, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const j = await resp.json();
        if (!j || !j.channels || !j.channels.length) return;
        const saved = String(settingsData().sub_poll_channel_id || sel.value || '');
        sel.innerHTML = j.channels.map(c => `<option value="${esc(c.id)}" ${String(c.id) === saved ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
    } catch (e) { /* keep the server-rendered options on any failure */ }
}

async function loadRolesOnInit() {
    const box = document.getElementById('sct-poll-roles');
    if (!box) return;
    const selected = String(box.dataset.selected || '')
        .split(',').map(s => s.trim()).filter(Boolean);
    try {
        const resp = await fetch(cfg().discordRolesUrl, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const j = await resp.json();
        const roles = (j && j.roles) || [];
        if (!roles.length) {
            box.innerHTML = '<p class="text-xs text-gray-400 col-span-full py-1.5 px-1">No roles loaded (bot offline). Saved roles are kept on next save.</p>';
            return;
        }
        box.innerHTML = roles.map(r => {
            const checked = selected.indexOf(String(r.id)) !== -1 ? 'checked' : '';
            return `<label class="inline-flex items-center gap-2 px-1.5 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-600/50 cursor-pointer">
                <input type="checkbox" value="${esc(r.id)}" ${checked} class="rounded text-ecs-green focus:ring-ecs-green">
                <span class="text-sm text-gray-700 dark:text-gray-300 truncate">${esc(r.name)}</span></label>`;
        }).join('');
    } catch (e) {
        box.innerHTML = '<p class="text-xs text-red-400 col-span-full py-1.5 px-1">Could not load roles.</p>';
    }
}

async function refreshChannels() {
    try {
        const resp = await fetch(cfg().discordChannelsUrl, { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } });
        const j = await resp.json();
        const sel = document.getElementById('sct-poll-channel');
        if (!sel || !j.channels) return;
        const current = sel.value;
        sel.innerHTML = j.channels.map(c => `<option value="${esc(c.id)}" ${c.id === current ? 'selected' : ''}>${esc(c.name)}</option>`).join('');
        toast('success', 'Channels refreshed');
    } catch (e) { toast('error', 'Could not refresh channels'); }
}

/* --------------------------------------------------------------- init */

function registerHandlers() {
    const ED = window.EventDelegation;
    if (!ED) return;
    ED.register('sct-tab', (el) => switchTab(el.dataset.tab));
    ED.register('sct-league-filter', (el) => filterNeeds(el.dataset.league));
    ED.register('sct-pool-filter', (el) => filterPool(el.dataset.status));
    ED.register('sct-pool-league', (el) => filterPoolLeague(el.dataset.league));
    ED.register('sct-select-need', (el) => selectNeed(el.closest('.sct-need') || el));
    ED.register('sct-panel-close', () => closePanel());
    ED.register('sct-assign', (el) => assignCandidate(el));
    ED.register('sct-reachout-open', (el) => openReach(el));
    // Request-a-sub modal + in-hub cancel.
    ED.register('sct-request-open', () => openRequest());
    ED.register('sct-request-edit', (el) => openRequestEdit(el));
    ED.register('sct-request-close', () => closeRequest());
    ED.register('sct-request-submit', () => submitRequest());
    ED.register('sct-request-cancel', (el) => cancelRequest(el));
    ED.register('sct-req-pos-chip', (el) => togglePosChip(el));
    ED.register('sct-reach-close', () => closeReach());
    ED.register('sct-reach-who', (el) => setReachWho(el.dataset.who));
    ED.register('sct-reach-pos', (el) => setReachPos(el));
    ED.register('sct-reach-send', () => sendReach());
    ED.register('sct-settings-save', () => saveSettings());
    ED.register('sct-settings-reset', () => window.location.reload());
    ED.register('sct-refresh-channels', () => refreshChannels());
    // Pool membership actions (act in place, no bounce).
    ED.register('sct-pool-setactive', (el) => poolSetActive(el));
    ED.register('sct-pool-remove', (el) => poolRemove(el));
    ED.register('sct-pool-approve', (el) => poolApprove(el));
    ED.register('sct-pool-reject', (el) => poolReject(el));
    ED.register('sct-pool-addleague', (el) => poolAddLeague(el));
    // Add-to-pool modal.
    ED.register('sct-pool-add-open', () => openAddPool());
    ED.register('sct-pool-add-close', () => closeAddPool());
    ED.register('sct-pool-add-league', (el) => setAddLeague(el.dataset.leagueType));
    ED.register('sct-pool-add-player', (el) => addPlayerToPool(el));
}

function bindDirect() {
    const ps = document.getElementById('sct-pool-search');
    if (ps) ps.addEventListener('input', applyPoolSearch);

    const msg = document.getElementById('sct-reach-msg');
    if (msg) msg.addEventListener('input', updateReachPreview);

    const lg = document.getElementById('sct-reach-league');
    if (lg) lg.addEventListener('change', () => { reachState.leagueType = lg.value; renderReachPicker(); updateReachPreview(); });

    const search = document.getElementById('sct-reach-search');
    if (search) search.addEventListener('input', renderReachPicker);

    const list = document.getElementById('sct-reach-list');
    if (list) list.addEventListener('change', updateReachPreview);

    const chans = document.getElementById('sct-reach-channels');
    if (chans) chans.addEventListener('change', updateReachPreview);

    const modal = document.getElementById('sct-reach-modal');
    if (modal) modal.addEventListener('click', (e) => { if (e.target === modal) closeReach(); });

    const addSearch = document.getElementById('sct-add-search');
    if (addSearch) addSearch.addEventListener('input', () => {
        clearTimeout(addSearchTimer);
        addSearchTimer = setTimeout(searchAddPlayers, 250);
    });

    const addModal = document.getElementById('sct-add-modal');
    if (addModal) addModal.addEventListener('click', (e) => { if (e.target === addModal) closeAddPool(); });

    const reqTeam = document.getElementById('sct-req-team');
    if (reqTeam) reqTeam.addEventListener('change', onRequestTeamChange);

    const reqPositions = document.getElementById('sct-req-positions');
    if (reqPositions) reqPositions.addEventListener('input', syncPosChips);

    const reqModal = document.getElementById('sct-req-modal');
    if (reqModal) reqModal.addEventListener('click', (e) => { if (e.target === reqModal) closeRequest(); });
}

function init() {
    if (!root()) return;
    registerHandlers();
    bindDirect();
    initSettingsPreviews();
    loadChannelsOnInit();
    loadRolesOnInit();
}

if (window.InitSystem?.register) {
    window.InitSystem.register('substitute-command-center', init, {
        priority: 40,
        reinitializable: false,
        description: 'Substitute Command Center hub',
    });
} else {
    document.addEventListener('DOMContentLoaded', init);
}
