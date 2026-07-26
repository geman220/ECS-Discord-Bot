/**
 * ============================================================================
 * RSVP POSTING — timing, wording and response method for the availability
 * request posted to a team channel.
 * ============================================================================
 *
 * Powers /admin-panel/communication/rsvp-posting.
 *
 * The preview is rendered SERVER-SIDE on every edit rather than mirrored here.
 * A JS copy of the token substitution would eventually disagree with
 * rsvp_copy.render() and quietly show something the bot never sends — and the
 * whole point of a preview is that you can trust it.
 *
 * Dependencies: SweetAlert2 (window.Swal), window.EventDelegation,
 * window.InitSystem.
 * ============================================================================
 */
'use strict';

const API_BASE = '/admin-panel/api/rsvp-posting';

function getCsrfToken() {
    return document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
}

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

async function apiCall(url, options = {}) {
    const response = await fetch(url, {
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
        ...options,
    });
    let data;
    try {
        data = await response.json();
    } catch (e) {
        throw new Error(`Server returned ${response.status}`);
    }
    if (!data.success) throw new Error(data.error || `Request failed (${response.status})`);
    return data;
}

function toast(icon, title) {
    window.Swal?.fire({ icon, title, toast: true, position: 'top-end',
                        showConfirmButton: false, timer: 2600 });
}

function readJsonScript(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    try { return JSON.parse(el.textContent); } catch (e) { return fallback; }
}

/* ========================================================================
   FORM STATE
   ======================================================================== */

function activeProgram() {
    return document.querySelector('.rsvp-program:not(.hidden)')?.dataset.program || 'pub';
}

function collectCopy() {
    const copy = {};
    document.querySelectorAll('[data-copy-field]').forEach((el) => {
        const { program, field } = el.dataset;
        if (!program || !field) return;
        (copy[program] = copy[program] || {})[field] = el.value;
    });
    return copy;
}

function usingButtons() {
    return document.getElementById('useButtons')?.checked ?? false;
}

/* ========================================================================
   PREVIEW — rendered by the server, drawn here
   ======================================================================== */

// Discord renders **bold** / *italic*. The preview has to as well or the copy
// looks wrong in exactly the place you are trying to judge it. Escape FIRST,
// then introduce our own tags, so admin-typed HTML can never execute.
function discordMarkdown(text) {
    return escapeHtml(text)
        .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
}

const RESPONSE_BUTTONS = [
    ['Yes', '#248046'], ['No', '#da373c'], ['Maybe', '#4e5058'],
];
const RESPONSE_REACTIONS = { pub: ['👍', '👎', '🤷'], ecs_fc: ['✅', '❌', '❓'] };

function drawResponseAffordance(program, showsResponse) {
    const host = document.getElementById('pvResponse');
    if (!host) return;
    if (!showsResponse) {
        host.innerHTML = '<p class="text-[11px] text-[#949ba4] italic">'
                       + 'No way to respond — a BYE week is informational only.</p>';
        return;
    }
    if (usingButtons()) {
        host.innerHTML = '<div class="flex flex-wrap gap-2">'
            + RESPONSE_BUTTONS.map(([label, bg]) =>
                `<span style="background:${bg}" class="inline-flex items-center px-3 py-1.5 rounded text-[13px] font-medium text-white">${label}</span>`).join('')
            + '</div>';
    } else {
        const emoji = RESPONSE_REACTIONS[program] || RESPONSE_REACTIONS.pub;
        host.innerHTML = '<div class="flex flex-wrap gap-1.5">'
            + emoji.map((e) =>
                `<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-[#2b2d31] border border-[#3f4147] text-[13px]">${e}<span class="text-[11px] text-[#949ba4]">0</span></span>`).join('')
            + '</div>';
    }
}

let previewSeq = 0;

async function refreshPreview() {
    const program = activeProgram();
    const copy = collectCopy();
    const seq = ++previewSeq;

    let data;
    try {
        data = await apiCall(`${API_BASE}/preview`, {
            method: 'POST',
            body: JSON.stringify({ program, block: copy[program] || {},
                                   use_buttons: usingButtons() }),
        });
    } catch (e) {
        // Typing fast enough to outrun the request is normal; a failed preview
        // must never look like a failed save.
        return;
    }
    // Drop a stale response that arrived after a newer keystroke.
    if (seq !== previewSeq) return;

    const r = data.rendered || {};
    const set = (id, value, markdown) => {
        const el = document.getElementById(id);
        if (!el) return;
        el.innerHTML = markdown ? discordMarkdown(value || '') : escapeHtml(value || '');
        el.classList.toggle('hidden', !value);
    };
    set('pvContent', r.content, true);
    set('pvTitle', r.title, false);
    set('pvDescription', r.description, true);
    set('pvFooter', r.footer, false);

    // The live embed grows a tally field per response as people answer. Show it
    // so the preview is not misleadingly short.
    const fields = document.getElementById('pvFields');
    if (fields) {
        fields.innerHTML = data.shows_response
            ? ['👍 Yes (0)', '👎 No (0)', '🤷 Maybe (0)'].map((n) =>
                `<div><div class="text-[13px] font-semibold text-white">${escapeHtml(n)}</div>`
                + '<div class="text-[13px] text-[#dbdee1]">None</div></div>').join('')
            : '';
    }

    drawResponseAffordance(program, data.shows_response);

    const note = document.getElementById('pvNote');
    if (note) {
        note.textContent = data.shows_response
            ? (usingButtons()
                ? 'Buttons apply to posts made after you save. Existing messages keep their reactions.'
                : 'Players answer by reacting. Tick the buttons option above to switch.')
            : 'BYE weeks never ask for a response.';
    }
}

let previewTimer = null;
function schedulePreview() {
    clearTimeout(previewTimer);
    previewTimer = setTimeout(refreshPreview, 220);
}

/* ========================================================================
   ACTIONS
   ======================================================================== */

function switchProgram(el) {
    const program = el.dataset.program;
    document.querySelectorAll('.rsvp-program').forEach((p) => {
        p.classList.toggle('hidden', p.dataset.program !== program);
    });
    document.querySelectorAll('.rsvp-tab').forEach((t) => {
        const on = t.dataset.program === program;
        t.classList.toggle('border-ecs-green', on);
        t.classList.toggle('text-ecs-green', on);
        t.classList.toggle('border-transparent', !on);
        t.classList.toggle('text-gray-500', !on);
    });
    refreshPreview();
}

function resetField(el) {
    const { program, field } = el.dataset;
    const defaults = readJsonScript('rsvpPostingDefaults', {});
    const value = defaults?.[program]?.[field];
    if (value === undefined) return;
    const input = document.querySelector(
        `[data-copy-field][data-program="${program}"][data-field="${field}"]`);
    if (!input) return;
    input.value = value;
    refreshPreview();
}

async function copyToken(el) {
    const token = el.dataset.token || '';
    try {
        await navigator.clipboard.writeText(token);
        toast('success', `Copied ${token}`);
    } catch (e) {
        toast('info', token);
    }
}

async function save(button) {
    const original = button.innerHTML;
    button.disabled = true;
    button.innerHTML = '<i class="ti ti-loader-2 animate-spin"></i><span>Saving…</span>';
    try {
        await apiCall(API_BASE, {
            method: 'POST',
            body: JSON.stringify({
                days_before: parseInt(document.getElementById('daysBefore')?.value || '6', 10),
                post_hour: parseInt(document.getElementById('postHour')?.value || '8', 10),
                use_buttons: usingButtons(),
                copy: collectCopy(),
            }),
        });
        toast('success', 'RSVP posting settings saved');
    } catch (e) {
        window.Swal?.fire({ icon: 'error', title: 'Could not save', text: e.message });
    } finally {
        button.disabled = false;
        button.innerHTML = original;
    }
}

/* ========================================================================
   INIT
   ======================================================================== */

function initRsvpPosting() {
    if (!document.querySelector('[data-page="rsvp-posting"]')) return;

    document.querySelectorAll('[data-copy-field]').forEach((el) => {
        el.addEventListener('input', schedulePreview);
    });
    document.getElementById('useButtons')?.addEventListener('change', refreshPreview);
    // The preview's timestamp line shows the configured hour.
    document.getElementById('postHour')?.addEventListener('change', refreshPreview);

    refreshPreview();
}

if (window.EventDelegation) {
    window.EventDelegation.register('rsvp-program-tab', switchProgram);
    window.EventDelegation.register('rsvp-reset-field', resetField);
    window.EventDelegation.register('rsvp-copy-token', copyToken);
    window.EventDelegation.register('rsvp-posting-save', save);
}

window.InitSystem.register('rsvp-posting', initRsvpPosting, {
    priority: 40,
    reinitializable: false,
    description: 'RSVP posting settings',
});
