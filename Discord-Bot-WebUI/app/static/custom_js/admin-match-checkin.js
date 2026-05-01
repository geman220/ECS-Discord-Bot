/**
 * Admin Match Check-In
 *
 * Handles two pages in the admin panel:
 *   - List view (data-page="admin-match-checkin-list"): bulk-generate venue QRs
 *   - Per-match detail (data-page="admin-match-checkin-detail"): roster split,
 *     generate/revoke QR, manual mark/unmark, auto-refresh roster.
 *
 * EventDelegation handlers are registered at module scope so they bind once
 * regardless of how the page enters/leaves the DOM.
 */
'use strict';

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function getCsrfToken() {
    return document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    const div = document.createElement('div');
    div.textContent = String(str);
    return div.innerHTML;
}

function showToast(message, type = 'info') {
    if (window.ECS && window.ECS.ToastService && window.ECS.ToastService.show) {
        window.ECS.ToastService.show(message, type);
        return;
    }
    if (window.Swal) {
        window.Swal.fire({
            toast: true, position: 'top-end', icon: type, title: message,
            showConfirmButton: false, timer: 2500, timerProgressBar: true,
        });
        return;
    }
    console.log(`[${type}]`, message);
}

async function jsonPost(url, body) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
            'Accept': 'application/json',
        },
        body: JSON.stringify(body || {}),
    });
    let data = null;
    try { data = await resp.json(); } catch (_) { /* non-JSON */ }
    return { ok: resp.ok, status: resp.status, data };
}

async function jsonGet(url) {
    const resp = await fetch(url, { headers: { 'Accept': 'application/json' } });
    let data = null;
    try { data = await resp.json(); } catch (_) { /* non-JSON */ }
    return { ok: resp.ok, status: resp.status, data };
}

function copyToClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
        return navigator.clipboard.writeText(text);
    }
    // Fallback for older browsers / non-secure contexts.
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } finally { document.body.removeChild(ta); }
    return Promise.resolve();
}

// ----------------------------------------------------------------------------
// LIST PAGE: bulk generate
// ----------------------------------------------------------------------------

if (window.EventDelegation && window.EventDelegation.register) {
    window.EventDelegation.register('generate-tokens-bulk', async function (element, e) {
        e.preventDefault();
        const days = parseInt(element.dataset.days || '14', 10);
        const cfg = window.MATCH_CHECKIN_LIST_CONFIG || {};
        if (!cfg.bulkUrl) return;

        const result = await window.Swal.fire({
            title: 'Generate missing QRs?',
            text: `Adds a venue QR for every match in the next ${days} days that doesn't have one yet.`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Generate',
        });
        if (!result.isConfirmed) return;

        element.disabled = true;
        const { ok, data } = await jsonPost(cfg.bulkUrl, { days });
        element.disabled = false;
        if (ok && data && data.success) {
            showToast(data.message || 'Done', 'success');
            setTimeout(() => window.location.reload(), 600);
        } else {
            showToast((data && data.message) || 'Failed to generate tokens', 'error');
        }
    });
}

// ----------------------------------------------------------------------------
// DETAIL PAGE: roster + QR actions
// ----------------------------------------------------------------------------

let _detailState = null;
let _detailRefreshTimer = null;

function _detailCfg() { return window.MATCH_CHECKIN_DETAIL_CONFIG || null; }

function _renderRoster(scope) {
    const state = _detailState;
    if (!state) return;
    const list = scope === 'all' ? state.rosterFull : state.rosterYes;
    const notYetEl = document.getElementById('rosterNotYet');
    const checkedInEl = document.getElementById('rosterCheckedIn');
    if (!notYetEl || !checkedInEl) return;

    const notYet = list.filter(e => !e.checked_in);
    const checkedIn = list.filter(e => e.checked_in);

    document.getElementById('notYetCount').textContent = String(notYet.length);
    document.getElementById('checkedInCount').textContent = String(checkedIn.length);

    notYetEl.innerHTML = notYet.length
        ? notYet.map(_rowNotYet).join('')
        : '<li class="px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400">Everyone here has checked in.</li>';

    checkedInEl.innerHTML = checkedIn.length
        ? checkedIn.map(_rowCheckedIn).join('')
        : '<li class="px-4 py-6 text-center text-sm text-gray-500 dark:text-gray-400">No check-ins yet.</li>';
}

function _avatar(entry) {
    if (entry.profile_picture_url) {
        return `<img src="${escapeHtml(entry.profile_picture_url)}" alt=""
                     class="w-9 h-9 rounded-full object-cover bg-gray-200 dark:bg-gray-700">`;
    }
    return `<div class="w-9 h-9 rounded-full bg-gray-200 dark:bg-gray-700 flex items-center justify-center text-xs text-gray-500">
                <i class="ti ti-user"></i>
            </div>`;
}

function _rowNotYet(entry) {
    const jersey = entry.jersey_number ? `<span class="text-xs text-gray-500 dark:text-gray-400 ml-2">#${escapeHtml(entry.jersey_number)}</span>` : '';
    return `
    <li class="px-4 py-3 flex items-center justify-between gap-3">
        <div class="flex items-center gap-3 min-w-0">
            ${_avatar(entry)}
            <div class="min-w-0">
                <div class="text-sm font-medium text-gray-900 dark:text-white truncate">${escapeHtml(entry.player_name)}${jersey}</div>
            </div>
        </div>
        <button type="button" data-action="manual-mark-present"
                data-player-id="${entry.player_id}" data-player-name="${escapeHtml(entry.player_name)}"
                class="px-3 py-1 text-xs font-medium text-emerald-700 dark:text-emerald-300 bg-emerald-50 dark:bg-emerald-900/40 rounded hover:bg-emerald-100 dark:hover:bg-emerald-900/60">
            <i class="ti ti-check mr-1"></i>Mark present
        </button>
    </li>`;
}

function _rowCheckedIn(entry) {
    const at = entry.checked_in_at ? new Date(entry.checked_in_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
    const by = entry.checked_in_by ? `<span class="ml-1.5 text-[11px] uppercase tracking-wider text-gray-400">${escapeHtml(entry.checked_in_by)}</span>` : '';
    const jersey = entry.jersey_number ? `<span class="text-xs text-gray-500 dark:text-gray-400 ml-2">#${escapeHtml(entry.jersey_number)}</span>` : '';
    return `
    <li class="px-4 py-3 flex items-center justify-between gap-3">
        <div class="flex items-center gap-3 min-w-0">
            ${_avatar(entry)}
            <div class="min-w-0">
                <div class="text-sm font-medium text-gray-900 dark:text-white truncate">${escapeHtml(entry.player_name)}${jersey}</div>
                <div class="text-xs text-gray-500 dark:text-gray-400">${escapeHtml(at)} ${by}</div>
            </div>
        </div>
        <button type="button" data-action="unmark-attendance"
                data-player-id="${entry.player_id}" data-player-name="${escapeHtml(entry.player_name)}"
                class="px-2 py-1 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/30 rounded">
            <i class="ti ti-x"></i>
        </button>
    </li>`;
}

async function _refreshRoster() {
    const cfg = _detailCfg();
    if (!cfg || !_detailState) return;
    const scope = _detailState.scope;
    const url = `${cfg.rosterUrl}?include_all=${scope === 'all' ? 'true' : 'false'}`;
    const { ok, data } = await jsonGet(url);
    if (!ok || !data || !data.entries) return;
    if (scope === 'all') _detailState.rosterFull = data.entries;
    else _detailState.rosterYes = data.entries;
    _renderRoster(scope);
}

function _startAutoRefresh() {
    if (_detailRefreshTimer) clearInterval(_detailRefreshTimer);
    _detailRefreshTimer = setInterval(() => {
        if (document.hidden) return;
        _refreshRoster();
    }, 20000);
}

if (window.EventDelegation && window.EventDelegation.register) {
    window.EventDelegation.register('set-roster-scope', function (element, e) {
        e.preventDefault();
        if (!_detailState) return;
        const scope = element.dataset.scope === 'all' ? 'all' : 'yes';
        _detailState.scope = scope;
        document.querySelectorAll('.checkin-tab').forEach(b => {
            const isActive = b.dataset.scope === scope;
            b.className = isActive
                ? 'checkin-tab px-3 py-1.5 text-sm font-medium rounded bg-emerald-600 text-white'
                : 'checkin-tab px-3 py-1.5 text-sm font-medium rounded bg-gray-100 dark:bg-gray-700 text-gray-700 dark:text-gray-300';
        });
        _renderRoster(scope);
        _refreshRoster();
    });

    window.EventDelegation.register('generate-match-qr', async function (element, e) {
        e.preventDefault();
        const cfg = _detailCfg();
        if (!cfg) return;
        element.disabled = true;
        const { ok, data } = await jsonPost(cfg.generateUrl, {});
        element.disabled = false;
        if (ok && data && data.success) {
            showToast('QR generated', 'success');
            setTimeout(() => window.location.reload(), 400);
        } else {
            showToast((data && data.message) || 'Failed to generate QR', 'error');
        }
    });

    window.EventDelegation.register('rotate-match-qr', async function (element, e) {
        e.preventDefault();
        const cfg = _detailCfg();
        if (!cfg) return;
        const result = await window.Swal.fire({
            title: 'Rotate QR?',
            text: 'The current QR stops working immediately. Reprint and post the new one before the next match.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Rotate',
        });
        if (!result.isConfirmed) return;
        const { ok, data } = await jsonPost(cfg.generateUrl, { rotate: true });
        if (ok && data && data.success) {
            showToast('New QR generated', 'success');
            setTimeout(() => window.location.reload(), 400);
        } else {
            showToast((data && data.message) || 'Failed to rotate QR', 'error');
        }
    });

    window.EventDelegation.register('revoke-match-qr', async function (element, e) {
        e.preventDefault();
        const cfg = _detailCfg();
        if (!cfg) return;
        const result = await window.Swal.fire({
            title: 'Revoke QR?',
            text: 'Players scanning this QR will get a 404 until you generate a new one.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Revoke',
            confirmButtonColor: '#dc2626',
        });
        if (!result.isConfirmed) return;
        const { ok, data } = await jsonPost(cfg.revokeUrl, {});
        if (ok && data && data.success) {
            showToast('QR revoked', 'success');
            setTimeout(() => window.location.reload(), 400);
        } else {
            showToast((data && data.message) || 'Failed to revoke', 'error');
        }
    });

    window.EventDelegation.register('copy-checkin-url', async function (element, e) {
        e.preventDefault();
        const url = element.dataset.url || document.getElementById('checkInUrlText')?.textContent || '';
        if (!url) return;
        try {
            await copyToClipboard(url);
            showToast('Check-in URL copied', 'success');
        } catch (err) {
            showToast('Copy failed', 'error');
        }
    });

    window.EventDelegation.register('manual-mark-present', async function (element, e) {
        e.preventDefault();
        const cfg = _detailCfg();
        if (!cfg) return;
        const playerId = element.dataset.playerId;
        const playerName = element.dataset.playerName || 'this player';
        const result = await window.Swal.fire({
            title: 'Mark present?',
            text: `Check ${playerName} in for this match (RSVP/window override).`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Mark present',
        });
        if (!result.isConfirmed) return;
        const { ok, data } = await jsonPost(cfg.manualMarkUrl, { player_id: parseInt(playerId, 10) });
        if (ok && data && data.success) {
            showToast(data.message || 'Marked present', 'success');
            await _refreshRoster();
        } else {
            showToast((data && data.message) || 'Failed', 'error');
        }
    });

    window.EventDelegation.register('unmark-attendance', async function (element, e) {
        e.preventDefault();
        const cfg = _detailCfg();
        if (!cfg) return;
        const playerId = element.dataset.playerId;
        const playerName = element.dataset.playerName || 'this player';
        const result = await window.Swal.fire({
            title: 'Remove check-in?',
            text: `${playerName}'s attendance row will be deleted.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Remove',
            confirmButtonColor: '#dc2626',
        });
        if (!result.isConfirmed) return;
        const { ok, data } = await jsonPost(cfg.unmarkUrl, { player_id: parseInt(playerId, 10) });
        if (ok && data && data.success) {
            showToast('Check-in removed', 'success');
            await _refreshRoster();
        } else {
            showToast((data && data.message) || 'Failed', 'error');
        }
    });
}

// ----------------------------------------------------------------------------
// Init
// ----------------------------------------------------------------------------

function initListPage() {
    if (!document.querySelector('[data-page="admin-match-checkin-list"]')) return;
    // Filters use plain inline onchange; nothing else to init.
}

function initDetailPage() {
    const root = document.querySelector('[data-page="admin-match-checkin-detail"]');
    if (!root) return;
    const cfg = _detailCfg();
    if (!cfg) return;

    _detailState = {
        scope: 'yes',
        rosterYes: cfg.initialRosterYes || [],
        rosterFull: cfg.initialRosterFull || [],
    };
    _renderRoster('yes');
    _startAutoRefresh();

    document.addEventListener('visibilitychange', () => {
        if (!document.hidden) _refreshRoster();
    });
}

if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-match-checkin', () => {
        initListPage();
        initDetailPage();
    }, {
        priority: 50,
        reinitializable: false,
        description: 'Admin match check-in pages',
    });
}

export { initListPage, initDetailPage };
