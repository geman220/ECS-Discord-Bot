'use strict';

/**
 * Substitute Command Center — tabbed admin hub.
 *
 * Drives: tab switching, league/pool filters, the This-Week candidate slide-over
 * (request-select -> fetch ranked candidates -> assign in place, authority-aware),
 * the reach-out modal (whole-pool / specific-people targeting + live Discord-style
 * preview), settings save, and live Discord channel refresh.
 *
 * Server contracts (all on admin_panel_bp):
 *   GET  candidates-for-request?request_id=&league=  -> {candidates, can_assign, assign_url, match_id, team_id}
 *   GET  week-availability?week=&league_type=
 *   POST settings-save  (JSON of AdminConfig keys)
 *   GET  discord-channels
 *   POST reachout-web   (JSON {kind, league_type, match_date, time_slots, ...})
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
        reachoutUrl: r.dataset.reachoutUrl,
        assignUrl: r.dataset.assignUrl,
        csrf: r.dataset.csrf || (document.querySelector('meta[name=csrf-token]') || {}).content || '',
    };
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

function filterPool(status) {
    document.querySelectorAll('.sct-pool-card').forEach(el => {
        el.classList.toggle('hidden', !(status === 'all' || el.dataset.status === status));
    });
    document.querySelectorAll('.sct-pool-btn').forEach(b => {
        const on = b.dataset.status === status;
        b.classList.toggle('bg-white', on);
        b.classList.toggle('text-gray-900', on);
        b.classList.toggle('shadow-sm', on);
        b.classList.toggle('dark:bg-gray-700', on);
        b.classList.toggle('dark:text-white', on);
    });
    applyPoolSearch();
}

function applyPoolSearch() {
    const q = (document.getElementById('sct-pool-search')?.value || '').trim().toLowerCase();
    document.querySelectorAll('.sct-pool-card').forEach(el => {
        if (el.classList.contains('hidden') && !q) return;
        const hay = el.dataset.search || '';
        const hideForSearch = q && hay.indexOf(q) === -1;
        if (q) el.classList.toggle('hidden', hideForSearch);
    });
}

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

/* ------------------------------------------------------- reach-out modal */

const reachState = { kind: 'general', who: 'pool', leagueType: 'Premier', requestId: null,
                     matchDate: null, matchId: null, timeSlot: null };

function poolData() {
    try { return JSON.parse(document.getElementById('sct-pool-data').textContent) || []; }
    catch (e) { return []; }
}

function settingsData() {
    try { return JSON.parse(document.getElementById('sct-settings-data').textContent) || {}; }
    catch (e) { return {}; }
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

function updateReachPreview() {
    const msg = document.getElementById('sct-reach-msg');
    document.getElementById('sct-reach-preview').textContent = fillTokens(msg.value);
    const channels = Array.from(document.querySelectorAll('#sct-reach-channels input:checked')).length;
    const summary = document.getElementById('sct-reach-summary');
    const recips = reachState.who === 'specific'
        ? document.querySelectorAll('#sct-reach-list input:checked').length
        : (poolData().filter(m => (m.league_type || '').indexOf(reachState.leagueType) !== -1).length);
    summary.textContent = `Reaches ~${recips} sub${recips === 1 ? '' : 's'} · ${channels} channel${channels === 1 ? '' : 's'}`;
}

function openReach(el) {
    const d = el ? el.dataset : {};
    const kindEntry = d.kind || 'general';
    reachState.requestId = d.requestId || null;
    reachState.matchId = d.matchId || null;
    reachState.matchDate = d.matchDate || cfg().week;
    reachState.timeSlot = d.timeSlot || null;
    reachState.who = 'pool';

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
        reachState.leagueType = leagueSel.value || 'Premier';
        leagueSel.disabled = false;
        document.getElementById('sct-reach-title').textContent = 'Reach out to subs';
        document.getElementById('sct-reach-sub').textContent = 'Ask a league pool who can play this week';
        document.getElementById('sct-reach-msg').value = fillTokens(s.sub_reachout_msg_general || '');
    }

    // Default channels from settings.
    const defCh = (s.sub_reachout_default_channels || 'PUSH,DISCORD,EMAIL').toUpperCase();
    document.querySelectorAll('#sct-reach-channels input').forEach(cb => { cb.checked = defCh.indexOf(cb.value) !== -1; });

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
    document.getElementById('sct-reach-picker').classList.toggle('hidden', who !== 'specific');
    updateReachPreview();
}

async function sendReach() {
    const errEl = document.getElementById('sct-reach-error');
    errEl.classList.add('hidden');
    const channels = Array.from(document.querySelectorAll('#sct-reach-channels input:checked')).map(c => c.value);
    if (!channels.length) { errEl.textContent = 'Select at least one channel.'; errEl.classList.remove('hidden'); return; }

    const who = reachState.who;
    const kind = who === 'specific' ? 'targeted' : 'general';
    const recipientIds = Array.from(document.querySelectorAll('#sct-reach-list input:checked')).map(c => parseInt(c.value, 10));
    if (kind === 'targeted' && !recipientIds.length) { errEl.textContent = 'Pick at least one person.'; errEl.classList.remove('hidden'); return; }

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
    ED.register('sct-select-need', (el) => selectNeed(el.closest('.sct-need') || el));
    ED.register('sct-panel-close', () => closePanel());
    ED.register('sct-assign', (el) => assignCandidate(el));
    ED.register('sct-reachout-open', (el) => openReach(el));
    ED.register('sct-reach-close', () => closeReach());
    ED.register('sct-reach-who', (el) => setReachWho(el.dataset.who));
    ED.register('sct-reach-send', () => sendReach());
    ED.register('sct-settings-save', () => saveSettings());
    ED.register('sct-settings-reset', () => window.location.reload());
    ED.register('sct-refresh-channels', () => refreshChannels());
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
}

function init() {
    if (!root()) return;
    registerHandlers();
    bindDirect();
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
