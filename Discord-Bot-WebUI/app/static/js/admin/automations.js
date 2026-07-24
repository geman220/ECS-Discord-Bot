/**
 * ============================================================================
 * AUTOMATED MESSAGING - Lifecycle rule configuration
 * ============================================================================
 *
 * Powers /admin-panel/communication/automations and the per-rule editor:
 * enable/disable, save configuration + copy, dry-run the audience, send a test
 * to yourself, and run/cancel an individual scheduled run.
 *
 * Dependencies:
 * - SweetAlert2 (window.Swal)
 * - window.EventDelegation
 * - window.InitSystem
 * ============================================================================
 */
'use strict';

import { InitSystem } from '../init-system.js';

/* ========================================================================
   UTILITIES
   ======================================================================== */

function getCsrfToken() {
    return document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
}

// NOTE: the textContent/innerHTML trick used elsewhere in this codebase escapes
// &, < and > but NOT quotes, so it is unsafe in an ATTRIBUTE context. This
// module interpolates stored condition values into value="..." , so escape
// quotes explicitly.
function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

const API_BASE = '/admin-panel/api/automations';

async function apiCall(url, options = {}) {
    const response = await fetch(url, {
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        ...options,
    });
    let data;
    try {
        data = await response.json();
    } catch (e) {
        throw new Error(`Server returned ${response.status}`);
    }
    if (!data.success) {
        throw new Error(data.error || `Request failed (${response.status})`);
    }
    return data;
}

function toastError(message) {
    window.Swal.fire({ icon: 'error', title: 'Something went wrong', text: message });
}

/* ========================================================================
   NEW AUTOMATION (builder)
   ======================================================================== */

function readJsonScript(id, fallback) {
    const el = document.getElementById(id);
    if (!el) return fallback;
    try {
        return JSON.parse(el.textContent);
    } catch (e) {
        return fallback;
    }
}

function buildAudienceOptions(audiences) {
    return audiences
        .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
        .join('');
}

/* ========================================================================
   NEW AUTOMATION PAGE
   ======================================================================== */

// Render this trigger's knobs from the server's field specs, so a new knob
// needs no change here.
function renderNewTriggerFields(trigger) {
    const holder = document.getElementById('newTriggerFields');
    if (!holder) return;
    const catalog = readJsonScript('automationTriggerCatalog', {});
    const specs = readJsonScript('automationTriggerFieldSpecs', {});
    const fields = ((catalog[trigger] || {}).fields) || [];

    holder.innerHTML = fields.map((name) => {
        const spec = specs[name];
        if (!spec) return '';
        const id = `nf_${name}`;
        const help = spec.help
            ? `<p class="mt-1.5 text-xs text-gray-500 dark:text-gray-400">${escapeHtml(spec.help)}</p>` : '';
        const cls = 'w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 ' +
                    'dark:bg-gray-700 text-gray-900 dark:text-white text-sm p-2.5 ' +
                    'focus:ring-ecs-green focus:border-ecs-green';
        if (spec.type === 'choice') {
            const opts = (spec.choices || []).map(([v, l]) =>
                `<option value="${escapeHtml(v)}" ${v === spec.default ? 'selected' : ''}>${escapeHtml(l)}</option>`).join('');
            return `<div><label for="${id}" class="block mb-1.5 text-sm font-medium text-gray-900 dark:text-white">${escapeHtml(spec.label)}</label>` +
                   `<select id="${id}" data-nf-field="${escapeHtml(name)}" class="${cls}">${opts}</select>${help}</div>`;
        }
        const min = (spec.min !== null && spec.min !== undefined) ? `min="${spec.min}"` : '';
        const max = (spec.max !== null && spec.max !== undefined) ? `max="${spec.max}"` : '';
        return `<div><label for="${id}" class="block mb-1.5 text-sm font-medium text-gray-900 dark:text-white">${escapeHtml(spec.label)}</label>` +
               `<input type="number" id="${id}" data-nf-field="${escapeHtml(name)}" value="${spec.default}" ${min} ${max} class="${cls}">${help}</div>`;
    }).join('');
}

function selectedNewTrigger() {
    return document.querySelector('.new-trigger:checked')?.value || null;
}

// Mirrors summarize_rule() on the server so the page reads back the same way
// the saved rule will.
function updateNewSummary() {
    const el = document.getElementById('newSummary');
    if (!el) return;
    const trigger = selectedNewTrigger();
    if (!trigger) {
        el.textContent = 'Pick a trigger below to get started.';
        return;
    }
    const catalog = readJsonScript('automationTriggerCatalog', {});
    const audiences = readJsonScript('automationAudienceTypes', []);
    const label = (catalog[trigger] || {}).label || trigger;
    const audVal = document.getElementById('newAudience')?.value;
    const audLabel = (audiences.find((a) => a[0] === audVal) || [])[1] || audVal || 'someone';
    const hours = parseInt(document.getElementById('newDelay')?.value || '0', 10) || 0;

    let wait;
    if (hours === 0) wait = 'immediately';
    else if (hours % 24 === 0) {
        const d = hours / 24;
        wait = `wait ${d} day${d === 1 ? '' : 's'}, then`;
    } else wait = `wait ${hours} hour${hours === 1 ? '' : 's'}, then`;

    const when = label.charAt(0).toLowerCase() + label.slice(1);
    el.textContent = `When ${when}, ${wait} message ${audLabel.toLowerCase()} by email.`;
}

function syncNewOverlap() {
    const wrap = document.getElementById('newOverlap');
    if (!wrap) return;
    const overlaps = readJsonScript('automationOverlaps', {});
    const meta = overlaps[selectedNewTrigger()];
    wrap.classList.toggle('hidden', !meta);
    if (!meta) return;
    const t = document.getElementById('newOverlapText');
    const w = document.getElementById('newOverlapWhere');
    if (t) t.textContent = meta.text || '';
    if (w) w.textContent = meta.where ? `Configured in: ${meta.where}` : '';
}

function syncNewAudience() {
    const trigger = selectedNewTrigger();
    if (!trigger) return;
    const perSubject = readJsonScript('automationPerSubject', []);
    const audiences = readJsonScript('automationAudienceTypes', []);
    const sel = document.getElementById('newAudience');
    const pinned = document.getElementById('newAudiencePinned');
    const help = document.getElementById('newAudienceHelp');
    if (!sel) return;

    const isPerSubject = perSubject.includes(trigger);
    const def = document.querySelector('.new-trigger:checked')?.dataset.defaultAudience;
    if (def) sel.value = def;
    // A per-person trigger fires for one person, so it can only target them.
    sel.disabled = isPerSubject;
    pinned?.classList.toggle('hidden', !isPerSubject);

    const meta = audiences.find((a) => a[0] === sel.value);
    if (help) help.textContent = meta ? meta[2] : '';
}

function initNewAutomationPage() {
    if (!document.querySelector('[data-page="automation-new"]')) return;

    document.querySelectorAll('.new-trigger').forEach((el) => {
        el.addEventListener('change', () => {
            renderNewTriggerFields(el.value);
            syncNewAudience();
            syncNewOverlap();
            updateNewSummary();
        });
    });
    document.getElementById('newAudience')?.addEventListener('change', () => {
        syncNewAudience();
        updateNewSummary();
    });
    document.getElementById('newDelay')?.addEventListener('input', updateNewSummary);
    updateNewSummary();
}

async function handleCreateAutomation() {
    const trigger = selectedNewTrigger();
    if (!trigger) {
        toastError('Pick a trigger first — it decides what starts the automation.');
        return;
    }
    const name = document.getElementById('newName')?.value?.trim();
    if (!name) {
        toastError('Give the automation a name so you can find it later.');
        document.getElementById('newName')?.focus();
        return;
    }

    const payload = {
        name,
        description: document.getElementById('newDescription')?.value?.trim() || '',
        trigger_type: trigger,
        audience_type: document.getElementById('newAudience')?.value,
        delay_hours: parseInt(document.getElementById('newDelay')?.value || '24', 10),
    };
    document.querySelectorAll('[data-nf-field]').forEach((el) => {
        payload[el.dataset.nfField] = el.type === 'number'
            ? parseInt(el.value || '0', 10) : el.value;
    });

    try {
        const data = await apiCall(API_BASE, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        window.location.href = data.redirect;
    } catch (e) {
        toastError(e.message);
    }
}

/* ========================================================================
   TRACE — "why didn't this person get it?"
   ======================================================================== */

async function handleSaveVariables() {
    const payload = {};
    document.querySelectorAll('[data-global-var]').forEach((el) => {
        payload[el.dataset.globalVar] = el.value.trim();
    });
    if (!Object.keys(payload).length) return;
    try {
        await apiCall(`${API_BASE}/variables`, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        window.Swal.fire({
            icon: 'success', title: 'Saved',
            text: 'These now apply to every automation.',
            timer: 1600, showConfirmButton: false,
        });
    } catch (e) {
        toastError(e.message);
    }
}

async function handleExplain(element) {
    const ruleId = element.dataset.ruleId;
    if (!ruleId) return;

    const picked = await window.Swal.fire({
        title: 'Who are you checking?',
        input: 'text',
        inputPlaceholder: 'Start typing a name…',
        inputAttributes: { autocomplete: 'off' },
        showCancelButton: true,
        confirmButtonText: 'Search',
        inputValidator: (v) => (!v || v.trim().length < 2)
            ? 'Type at least two characters' : undefined,
    });
    if (!picked.isConfirmed) return;

    let people = [];
    try {
        const r = await fetch(
            `${API_BASE}/search-people?q=${encodeURIComponent(picked.value.trim())}`);
        people = (await r.json()).people || [];
    } catch (e) {
        toastError('Could not search for people.');
        return;
    }
    if (!people.length) {
        toastError('Nobody matched that name.');
        return;
    }

    const chosen = await window.Swal.fire({
        title: 'Pick the person',
        input: 'select',
        inputOptions: people.reduce((a, p) => { a[p.user_id] = p.label; return a; }, {}),
        showCancelButton: true,
        confirmButtonText: 'Explain',
    });
    if (!chosen.isConfirmed) return;

    window.Swal.fire({ title: 'Working it out…', allowOutsideClick: false,
                       didOpen: () => window.Swal.showLoading() });
    try {
        const data = await apiCall(`${API_BASE}/${ruleId}/explain`, {
            method: 'POST',
            body: JSON.stringify({ user_id: parseInt(chosen.value, 10) }),
        });
        const rows = (data.stages || []).map((st) => {
            const icon = st.ok ? '✅' : '⛔';
            return '<li style="margin:0 0 8px;list-style:none;">' +
                   `<strong>${icon} ${escapeHtml(st.name)}</strong>` +
                   `<div style="font-size:12px;color:#6b7280;margin-top:2px;">${escapeHtml(st.detail)}</div>` +
                   '</li>';
        }).join('');
        window.Swal.fire({
            title: false,
            width: 620,
            html: `<p style="text-align:left;font-weight:600;margin:0 0 12px;">${escapeHtml(data.verdict)}</p>` +
                  `<ul style="text-align:left;padding:0;margin:0;">${rows}</ul>` +
                  '<p style="text-align:left;font-size:11px;color:#9ca3af;margin:12px 0 0;">' +
                  'Worked out live against the rule as it is saved right now.</p>',
            confirmButtonText: 'Close',
        });
    } catch (e) {
        toastError(e.message);
    }
}


/* ========================================================================
   EMAIL BODY EDITOR (TinyMCE)
   ======================================================================== */

// Truncation limits copied from _dispatch_multichannel() in automation_service:
// the push/Discord title is cut at 100 chars, and when a step has no short
// message the HTML body is stripped and cut at 900. The previews below have to
// use the same numbers or they would promise something the send does not do.
const PUSH_TITLE_MAX = 100;
const PUSH_BODY_FALLBACK_MAX = 900;

// The vendor script is a classic <script> in extra_js while this module is
// deferred, so tinymce is normally there already; the retry only covers a slow
// or blocked asset. Falling back to the bare textarea keeps the page usable
// instead of leaving an admin typing into nothing.
const EDITOR_RETRIES = 20;

function editorTextareaFallback() {
    const target = document.getElementById('ruleBody');
    if (!target) return;
    target.classList.add(
        'w-full', 'rounded-lg', 'border', 'border-gray-300', 'dark:border-gray-600',
        'bg-gray-50', 'dark:bg-gray-700', 'text-gray-900', 'dark:text-white',
        'text-sm', 'p-2.5', 'font-mono', 'focus:ring-ecs-green', 'focus:border-ecs-green');
}

function initEditor(attempt = 0) {
    const target = document.getElementById('ruleBody');
    if (!target) return;                       // list page / new-rule page
    if (window.tinymce && window.tinymce.get('ruleBody')) return;

    if (!window.tinymce) {
        if (attempt < EDITOR_RETRIES) {
            setTimeout(() => initEditor(attempt + 1), 100);
        } else {
            console.warn('[Automations] TinyMCE never loaded; using the plain textarea.');
            editorTextareaFallback();
        }
        return;
    }

    const isDark = document.documentElement.classList.contains('dark');
    const isPhone = window.matchMedia && window.matchMedia('(max-width: 640px)').matches;

    window.tinymce.init({
        // Self-hosted GPL build — required from TinyMCE 7 on or the editor
        // renders as "disabled because a license key has not been provided".
        license_key: 'gpl',
        selector: '#ruleBody',
        width: '100%',
        height: isPhone ? 320 : 460,
        menubar: false,
        plugins: 'lists link image table code wordcount autolink',
        toolbar: isPhone
            ? 'undo redo | bold italic | bullist numlist | link inserttokens'
            : 'undo redo | blocks | bold italic underline strikethrough | forecolor backcolor | '
              + 'alignleft aligncenter alignright | bullist numlist | link image table | inserttokens | code',
        toolbar_mode: 'sliding',
        content_style: 'body { font-family: Arial, sans-serif; font-size: 14px; }',
        skin: isDark ? 'oxide-dark' : 'oxide',
        content_css: isDark ? 'dark' : 'default',
        branding: false,
        promotion: false,
        setup: function (editor) {
            editor.ui.registry.addMenuButton('inserttokens', {
                text: 'Insert Token',
                fetch: function (callback) {
                    callback(['{first_name}', '{name}', '{team}', '{league}', '{season}',
                        '{discord_invite_url}', '{support_email}'].map((token) => ({
                        type: 'menuitem',
                        text: token,
                        onAction: () => editor.insertContent(token),
                    })));
                },
            });
            // The push/Discord preview falls back to the stripped email body, so
            // it has to follow body edits, not just short-message edits.
            editor.on('change keyup SetContent', () => syncShortMessagePreview());
        },
        init_instance_callback: () => syncShortMessagePreview(),
    });
}

// Reads the body from TinyMCE when it is running and from the raw textarea when
// it is not. Without the fallback a blocked vendor script would silently save an
// empty body over a rule that already had one.
function getBodyHtml() {
    const editor = window.tinymce && window.tinymce.get('ruleBody');
    if (editor) return editor.getContent();
    return document.getElementById('ruleBody')?.value || '';
}


/* ========================================================================
   ACTION SEQUENCE (follow-up steps)
   ======================================================================== */

const STEP_CHANNELS = [
    ['email', 'Email'], ['push', 'Push'], ['discord', 'Discord DM'], ['in_app', 'In-app'],
];

function num(id) {
    const el = document.getElementById(id);
    return el && el.value !== '' ? parseInt(el.value, 10) : null;
}

function stepRowHtml(step, index) {
    const chans = step.channels || ['email'];
    const boxes = STEP_CHANNELS.map(([v, lbl]) =>
        `<label class="inline-flex items-center gap-1 text-xs mr-2">` +
        `<input type="checkbox" class="step-channel w-3.5 h-3.5 rounded border-gray-300 text-ecs-green focus:ring-ecs-green" ` +
        `value="${escapeHtml(v)}" ${chans.includes(v) ? 'checked' : ''}>` +
        `<span>${escapeHtml(lbl)}</span></label>`).join('');

    return (
        '<div class="step-row rounded-lg border border-gray-200 dark:border-gray-700 p-2.5 space-y-2">' +
        '<div class="flex items-center justify-between gap-2">' +
        `<span class="text-xs font-bold uppercase tracking-wide text-ecs-green">Follow-up ${index + 2}</span>` +
        '<button type="button" data-action="automation-remove-step" class="px-1.5 py-0.5 rounded text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-500/15"><i class="ti ti-x"></i></button>' +
        '</div>' +
        '<div class="flex items-center gap-1.5">' +
        '<span class="text-xs text-gray-500 dark:text-gray-400">Send</span>' +
        `<input type="number" min="0" max="1440" class="step-wait w-20 rounded border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-xs p-1" value="${parseInt(step.wait_hours || 0, 10)}">` +
        '<span class="text-xs text-gray-500 dark:text-gray-400">hours after the previous message</span>' +
        '</div>' +
        `<input type="text" class="step-subject w-full rounded border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-xs p-1.5" placeholder="Subject line" value="${escapeHtml(step.subject || '')}">` +
        `<textarea rows="3" class="step-body w-full rounded border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-xs p-1.5" placeholder="Message (HTML allowed for email)">${escapeHtml(step.body_html || '')}</textarea>` +
        `<textarea rows="2" class="step-short w-full rounded border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-xs p-1.5" placeholder="Short plain-text version (needed for push / Discord / in-app)">${escapeHtml(step.short_message || '')}</textarea>` +
        `<div>${boxes}</div>` +
        '</div>'
    );
}

function renderSteps() {
    const wrap = document.getElementById('stepRows');
    if (!wrap) return;
    // Step 1 is the main editor above; only follow-ups render here.
    const stored = readJsonScript('automationSteps', []);
    const followUps = stored.length > 1 ? stored.slice(1) : [];
    wrap.innerHTML = followUps.map(stepRowHtml).join('');
}

function handleAddStep() {
    const wrap = document.getElementById('stepRows');
    if (!wrap) return;
    const count = wrap.querySelectorAll('.step-row').length;
    if (count >= 5) {
        toastError('Five follow-ups is the maximum.');
        return;
    }
    wrap.insertAdjacentHTML('beforeend',
        stepRowHtml({ wait_hours: 72, channels: ['email'] }, count));
}

function handleRemoveStep(element) {
    element.closest('.step-row')?.remove();
    // Renumber so the labels stay in order after a removal.
    document.querySelectorAll('#stepRows .step-row').forEach((row, i) => {
        const badge = row.querySelector('span');
        if (badge) badge.textContent = `Follow-up ${i + 2}`;
    });
}

// Step 1 is always the main editor; follow-ups are appended.
function collectSteps() {
    const first = {
        wait_hours: num('ruleDelayHours') ?? 0,
        channels: Array.from(document.querySelectorAll('.rule-channel:checked')).map((e) => e.value),
        subject: document.getElementById('ruleSubject')?.value || '',
        body_html: getBodyHtml(),
        short_message: document.getElementById('ruleShortMessage')?.value || '',
    };
    if (!first.channels.length) first.channels = ['email'];

    const rest = Array.from(document.querySelectorAll('#stepRows .step-row')).map((row) => ({
        wait_hours: parseInt(row.querySelector('.step-wait')?.value || '0', 10),
        channels: Array.from(row.querySelectorAll('.step-channel:checked')).map((e) => e.value),
        subject: row.querySelector('.step-subject')?.value || '',
        body_html: row.querySelector('.step-body')?.value || '',
        short_message: row.querySelector('.step-short')?.value || '',
    }));
    return [first, ...rest];
}


/* ========================================================================
   CONDITIONS BUILDER
   ======================================================================== */

// Ops that need a value box; the rest are unary tests.
const VALUE_OPS = ['eq', 'neq'];

// Which operators actually make sense per field TYPE. Offering all six for
// every field lets an admin build a condition that silently matches nobody --
// e.g. "Approval status" + "is yes" tests `'approved' is True`, which is never
// true, and the rule then sends to no one and records itself as skipped.
const OPS_FOR_TYPE = {
    bool: ['is_true', 'is_false'],
    exists: ['exists', 'missing'],
    str: ['eq', 'neq', 'exists', 'missing'],
};

function opsForField(fields, fieldKey) {
    const type = (fields[fieldKey] || [])[1];
    return OPS_FOR_TYPE[type] || Object.keys(OPS_FOR_TYPE).reduce((a, k) => a.concat(OPS_FOR_TYPE[k]), []);
}

function conditionRowHtml(cond) {
    const fields = readJsonScript('automationConditionFields', {});
    const ops = readJsonScript('automationConditionOps', {});
    const fieldKeys = Object.keys(fields);
    const activeField = cond.field && fields[cond.field] ? cond.field : fieldKeys[0];
    const fieldOpts = fieldKeys
        .map((k) => `<option value="${escapeHtml(k)}" ${k === activeField ? 'selected' : ''}>${escapeHtml(fields[k][0])}</option>`)
        .join('');
    const allowed = opsForField(fields, activeField);
    const activeOp = allowed.includes(cond.op) ? cond.op : allowed[0];
    const opOpts = allowed
        .map((k) => `<option value="${escapeHtml(k)}" ${k === activeOp ? 'selected' : ''}>${escapeHtml(ops[k] || k)}</option>`)
        .join('');
    const needsValue = VALUE_OPS.includes(activeOp);
    return (
        '<div class="condition-row flex flex-wrap items-center gap-1.5">' +
        `<select class="cond-field flex-1 min-w-[9rem] rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white text-xs p-1.5">${fieldOpts}</select>` +
        `<select class="cond-op rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white text-xs p-1.5">${opOpts}</select>` +
        `<input class="cond-value ${needsValue ? '' : 'hidden'} flex-1 min-w-[6rem] rounded-lg border border-gray-300 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white text-xs p-1.5" value="${escapeHtml(cond.value || '')}" placeholder="value">` +
        '<button type="button" data-action="automation-remove-condition" class="px-1.5 py-1 rounded text-xs text-red-600 hover:bg-red-50 dark:hover:bg-red-500/15" title="Remove"><i class="ti ti-x"></i></button>' +
        '</div>'
    );
}

function wireConditionRow(row) {
    const field = row.querySelector('.cond-field');
    const op = row.querySelector('.cond-op');
    const value = row.querySelector('.cond-value');
    if (!field || !op || !value) return;

    const syncValueBox = () => {
        value.classList.toggle('hidden', !VALUE_OPS.includes(op.value));
    };
    op.addEventListener('change', syncValueBox);

    // Changing the field re-narrows the operator list to the ones its type
    // supports, so an impossible pairing cannot be built.
    field.addEventListener('change', () => {
        const fields = readJsonScript('automationConditionFields', {});
        const ops = readJsonScript('automationConditionOps', {});
        const allowed = opsForField(fields, field.value);
        op.innerHTML = allowed
            .map((k) => `<option value="${escapeHtml(k)}">${escapeHtml(ops[k] || k)}</option>`)
            .join('');
        syncValueBox();
    });
}

function renderConditions() {
    const wrap = document.getElementById('conditionRows');
    if (!wrap) return;
    const existing = readJsonScript('automationConditions', []);
    wrap.innerHTML = existing.map(conditionRowHtml).join('');
    wrap.querySelectorAll('.condition-row').forEach(wireConditionRow);
}

function handleAddCondition() {
    const wrap = document.getElementById('conditionRows');
    if (!wrap) return;
    wrap.insertAdjacentHTML('beforeend', conditionRowHtml({}));
    const row = wrap.lastElementChild;
    if (row) wireConditionRow(row);
}

function handleRemoveCondition(element) {
    element.closest('.condition-row')?.remove();
}

function collectConditions() {
    return Array.from(document.querySelectorAll('#conditionRows .condition-row'))
        .map((row) => {
            const field = row.querySelector('.cond-field')?.value;
            const op = row.querySelector('.cond-op')?.value;
            const value = row.querySelector('.cond-value')?.value?.trim();
            if (!field || !op) return null;
            const out = { field, op };
            if (VALUE_OPS.includes(op)) out.value = value || '';
            return out;
        })
        .filter(Boolean);
}

/* ========================================================================
   ENABLE / DISABLE
   ======================================================================== */

async function handleToggle(element) {
    const ruleId = element.dataset.ruleId;
    const enabling = element.dataset.enabled !== 'true';
    if (!ruleId) return;

    // Turning an automation ON means it can send real email unattended, so make
    // the consequence explicit rather than flipping silently.
    if (enabling) {
        const confirmed = await window.Swal.fire({
            icon: 'warning',
            title: 'Turn this automation on?',
            html:
                'Once enabled, this rule sends email automatically when its trigger fires ' +
                '&mdash; no further approval.<br><br>' +
                'Preview the audience first if you have not already.',
            showCancelButton: true,
            confirmButtonText: 'Turn it on',
            cancelButtonText: 'Not yet',
        });
        if (!confirmed.isConfirmed) return;
    }

    try {
        const data = await apiCall(`${API_BASE}/${ruleId}/toggle`, {
            method: 'POST',
            body: JSON.stringify({ enabled: enabling }),
        });
        if (data.warning) {
            await window.Swal.fire({
                icon: 'warning',
                title: 'Switched on — but check this',
                text: data.warning,
                confirmButtonText: 'Got it',
            });
        }
        window.location.reload();
    } catch (e) {
        toastError(e.message);
    }
}

/* ========================================================================
   SAVE RULE
   ======================================================================== */

function collectRuleForm() {
    const val = (id) => document.getElementById(id)?.value ?? '';
    // num() is module-level (shared with collectSteps).

    const channels = Array.from(document.querySelectorAll('.rule-channel:checked'))
        .map((el) => el.value);

    const payload = {
        name: val('ruleName'),
        description: val('ruleDescription'),
        subject: val('ruleSubject'),
        body_html: getBodyHtml(),
        short_message: val('ruleShortMessage'),
        channels: channels.length ? channels : ['email'],
        conditions: collectConditions(),
        steps: collectSteps(),
        stop_when_resolved: document.getElementById('ruleStopWhenResolved')?.checked ?? true,
        delay_hours: num('ruleDelayHours'),
        audience_type: val('ruleAudienceType'),
        send_mode: val('ruleSendMode'),
        force_send: document.getElementById('ruleForceSend')?.checked ?? false,
        template_id: val('ruleTemplateId') || null,
        ...(document.getElementById('ruleTriggerType')
            ? { trigger_type: document.getElementById('ruleTriggerType').value } : {}),
    };

    // Trigger knobs are rendered from TRIGGER_FIELD_SPECS and tagged with
    // data-trigger-field, so this needs no per-knob code.
    document.querySelectorAll('[data-trigger-field]').forEach((el) => {
        const name = el.dataset.triggerField;
        if (!name) return;
        payload[name] = el.type === 'number'
            ? (el.value === '' ? null : parseInt(el.value, 10))
            : el.value;
    });

    return payload;
}

// Catch an incomplete condition row before sending. The whole editor is saved
// in one PUT, so a server-side 400 would throw away unsaved subject/body edits.
function validateConditions() {
    const rows = Array.from(document.querySelectorAll('#conditionRows .condition-row'));
    for (let i = 0; i < rows.length; i += 1) {
        const op = rows[i].querySelector('.cond-op')?.value;
        const value = rows[i].querySelector('.cond-value')?.value?.trim();
        if (VALUE_OPS.includes(op) && !value) {
            rows[i].querySelector('.cond-value')?.focus();
            return `Condition ${i + 1} needs a value to compare against.`;
        }
    }
    return null;
}

async function handleSave(element) {
    const ruleId = element.dataset.ruleId;
    if (!ruleId) return;

    const conditionError = validateConditions();
    if (conditionError) {
        toastError(conditionError);
        return;
    }

    const original = element.innerHTML;
    element.disabled = true;
    element.innerHTML = '<i class="ti ti-loader-2 animate-spin"></i><span>Saving…</span>';

    try {
        await apiCall(`${API_BASE}/${ruleId}`, {
            method: 'PUT',
            body: JSON.stringify(collectRuleForm()),
        });
        await window.Swal.fire({
            icon: 'success', title: 'Saved', timer: 1200, showConfirmButton: false,
        });
        window.location.reload();
    } catch (e) {
        toastError(e.message);
    } finally {
        element.disabled = false;
        element.innerHTML = original;
    }
}

/* ========================================================================
   AUDIENCE PREVIEW (dry run)
   ======================================================================== */

function renderPreview(data) {
    if (!data.triggered) {
        return (
            '<div class="text-start text-sm text-gray-600 dark:text-gray-300">' +
            '<p class="mb-2"><strong>Nothing would send right now.</strong></p>' +
            '<p>The trigger condition is not met yet &mdash; for a draft rule that means at ' +
            'least one active team is still below the players-per-team threshold.</p>' +
            '</div>'
        );
    }

    let html = '<div class="text-start space-y-3">';
    data.scopes.forEach((scope) => {
        const already = scope.already_run
            ? `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300">already ${escapeHtml(scope.already_run)}</span>`
            : '';
        const sample = scope.sample.length
            ? `<p class="mt-1 text-xs text-gray-500 dark:text-gray-400">e.g. ${escapeHtml(scope.sample.join(', '))}${scope.recipient_count > scope.sample.length ? '…' : ''}</p>`
            : '';
        html +=
            '<div class="rounded-lg border border-gray-200 dark:border-gray-700 p-3">' +
            `<div class="flex items-center justify-between gap-2"><strong class="text-sm">${escapeHtml(scope.label)}</strong>${already}</div>` +
            `<p class="mt-1 text-sm"><span class="font-mono font-bold text-ecs-green">${scope.recipient_count}</span> recipient(s) &mdash; ${escapeHtml(scope.filter_description)}</p>` +
            sample +
            `<p class="mt-2 text-xs text-gray-500 dark:text-gray-400">Trigger fired ${escapeHtml(scope.event_at)} → would send ${escapeHtml(scope.scheduled_for)}</p>` +
            '</div>';
    });
    html += '</div>';
    return html;
}

async function handlePreview(element) {
    const ruleId = element.dataset.ruleId;
    if (!ruleId) return;

    const refresh = await window.Swal.fire({
        icon: 'question',
        title: 'Check Discord live?',
        html:
            'A live check asks the bot whether each player is actually in the server, so the ' +
            'count is current. It makes one call per stale player and takes longer.<br><br>' +
            'Otherwise the last synced values are used.',
        showCancelButton: true,
        showDenyButton: true,
        confirmButtonText: 'Live check',
        denyButtonText: 'Use cached',
        cancelButtonText: 'Cancel',
    });
    if (refresh.isDismissed) return;

    window.Swal.fire({
        title: 'Working it out…',
        allowOutsideClick: false,
        didOpen: () => window.Swal.showLoading(),
    });

    try {
        const data = await apiCall(`${API_BASE}/${ruleId}/preview`, {
            method: 'POST',
            body: JSON.stringify({ refresh: refresh.isConfirmed }),
        });
        window.Swal.fire({
            title: 'Dry run — nothing sent',
            html: renderPreview(data),
            width: 640,
            confirmButtonText: 'Close',
        });
    } catch (e) {
        toastError(e.message);
    }
}

/* ========================================================================
   TEST SEND
   ======================================================================== */

async function handleSendTest(element) {
    const ruleId = element.dataset.ruleId;
    if (!ruleId) return;

    const confirmed = await window.Swal.fire({
        icon: 'question',
        title: 'Send yourself a test?',
        text: 'The email goes only to your own address, using your name for personalization.',
        showCancelButton: true,
        confirmButtonText: 'Send test',
    });
    if (!confirmed.isConfirmed) return;

    try {
        const data = await apiCall(`${API_BASE}/${ruleId}/send-test`, { method: 'POST' });
        window.Swal.fire({ icon: 'success', title: 'Test sent', text: data.message });
    } catch (e) {
        toastError(e.message);
    }
}

/* ========================================================================
   RUN ACTIONS
   ======================================================================== */

async function handleRunNow(element) {
    const runId = element.dataset.runId;
    const label = element.dataset.runLabel || 'this run';
    if (!runId) return;

    const confirmed = await window.Swal.fire({
        icon: 'warning',
        title: 'Send now?',
        html:
            `This sends <strong>${escapeHtml(label)}</strong> immediately, ignoring its delay.<br><br>` +
            'Real email goes to every matching recipient. This cannot be undone.',
        showCancelButton: true,
        confirmButtonText: 'Send it now',
        cancelButtonText: 'Cancel',
    });
    if (!confirmed.isConfirmed) return;

    try {
        const data = await apiCall(`${API_BASE}/runs/${runId}/send-now`, { method: 'POST' });
        await window.Swal.fire({ icon: 'success', title: 'Sending', text: data.message });
        window.location.reload();
    } catch (e) {
        toastError(e.message);
    }
}

async function handleForceRun(element) {
    const ruleId = element.dataset.ruleId;
    const ruleName = element.dataset.ruleName || 'this automation';
    if (!ruleId) return;

    // Deliberately a two-step confirm: this is the one action that sends real
    // email to a real audience with no delay and no enabled-check protecting it.
    const first = await window.Swal.fire({
        icon: 'warning',
        title: 'Force this automation to run?',
        html:
            `<div class="text-start text-sm">` +
            `<p class="mb-2">This runs <strong>${escapeHtml(ruleName)}</strong> right now:</p>` +
            '<ul class="list-disc ps-5 space-y-1">' +
            '<li>ignores the wait period</li>' +
            '<li>ignores the freshness window</li>' +
            '<li>works even while the rule is turned off</li>' +
            '</ul>' +
            '<p class="mt-2">Use it when the trigger already happened before the rule existed ' +
            '&mdash; for example the draft is finished and you just set this up.</p>' +
            '<p class="mt-2"><strong>Run a dry run first</strong> if you have not checked who it reaches.</p>' +
            '</div>',
        showCancelButton: true,
        confirmButtonText: 'Continue',
        cancelButtonText: 'Cancel',
    });
    if (!first.isConfirmed) return;

    const second = await window.Swal.fire({
        icon: 'warning',
        title: 'Send real email now?',
        text: 'This cannot be undone. A scope that already sent will not send twice.',
        showCancelButton: true,
        confirmButtonText: 'Yes, send it',
        cancelButtonText: 'Back out',
        confirmButtonColor: '#d33',
    });
    if (!second.isConfirmed) return;

    try {
        const data = await apiCall(`${API_BASE}/${ruleId}/force-run`, {
            method: 'POST',
            body: JSON.stringify({}),
        });
        await window.Swal.fire({ icon: 'success', title: 'Running', text: data.message });
        window.location.href = '/admin-panel/communication/automations?tab=history';
    } catch (e) {
        toastError(e.message);
    }
}

async function handleDuplicateRule(element) {
    const ruleId = element.dataset.ruleId;
    if (!ruleId) return;
    try {
        const data = await apiCall(`${API_BASE}/${ruleId}/duplicate`, { method: 'POST' });
        window.location.href = data.redirect;
    } catch (e) {
        toastError(e.message);
    }
}

async function handleDeleteRule(element) {
    const ruleId = element.dataset.ruleId;
    const ruleName = element.dataset.ruleName || 'this automation';
    if (!ruleId) return;

    const confirmed = await window.Swal.fire({
        icon: 'warning',
        title: 'Delete this automation?',
        html: `<strong>${escapeHtml(ruleName)}</strong> and its whole run history will be removed. This cannot be undone.`,
        showCancelButton: true,
        confirmButtonText: 'Delete it',
        cancelButtonText: 'Keep it',
        confirmButtonColor: '#d33',
    });
    if (!confirmed.isConfirmed) return;

    try {
        await apiCall(`${API_BASE}/${ruleId}`, { method: 'DELETE' });
        window.location.href = '/admin-panel/communication/automations';
    } catch (e) {
        toastError(e.message);
    }
}

async function handleCancelRun(element) {
    const runId = element.dataset.runId;
    if (!runId) return;

    const confirmed = await window.Swal.fire({
        icon: 'warning',
        title: 'Cancel this scheduled send?',
        text: 'It will never send. The rule will not re-schedule it for the same league and season.',
        showCancelButton: true,
        confirmButtonText: 'Cancel the send',
        cancelButtonText: 'Keep it',
    });
    if (!confirmed.isConfirmed) return;

    try {
        await apiCall(`${API_BASE}/runs/${runId}/cancel`, { method: 'POST' });
        window.location.reload();
    } catch (e) {
        toastError(e.message);
    }
}

/* ========================================================================
   EVENT DELEGATION REGISTRATION
   ======================================================================== */

window.EventDelegation.register('automation-create', handleCreateAutomation, { preventDefault: true });
window.EventDelegation.register('automation-toggle', handleToggle, { preventDefault: true });
window.EventDelegation.register('automation-save', handleSave, { preventDefault: true });
window.EventDelegation.register('automation-preview', handlePreview, { preventDefault: true });
window.EventDelegation.register('automation-send-test', handleSendTest, { preventDefault: true });
window.EventDelegation.register('automation-run-now', handleRunNow, { preventDefault: true });
window.EventDelegation.register('automation-force-run', handleForceRun, { preventDefault: true });
window.EventDelegation.register('automation-cancel-run', handleCancelRun, { preventDefault: true });
window.EventDelegation.register('automation-delete', handleDeleteRule, { preventDefault: true });
window.EventDelegation.register('automation-preview-email', handlePreviewEmail, { preventDefault: true });
window.EventDelegation.register('automation-duplicate', handleDuplicateRule, { preventDefault: true });
window.EventDelegation.register('automation-explain', handleExplain, { preventDefault: true });
window.EventDelegation.register('automation-save-variables', handleSaveVariables, { preventDefault: true });
window.EventDelegation.register('automation-add-step', handleAddStep, { preventDefault: true });
window.EventDelegation.register('automation-remove-step', handleRemoveStep, { preventDefault: true });
window.EventDelegation.register('automation-add-condition', handleAddCondition, { preventDefault: true });
window.EventDelegation.register('automation-remove-condition', handleRemoveCondition, { preventDefault: true });

/* ========================================================================
   INIT
   ======================================================================== */

function syncShortMessageVisibility() {
    const wrap = document.getElementById('shortMessageWrap');
    if (!wrap) return;
    const selected = Array.from(document.querySelectorAll('.rule-channel:checked'))
        .map((el) => el.value);
    // Only email selected => the HTML body is the whole message, no short copy needed.
    const emailOnly = selected.length === 1 && selected[0] === 'email';
    wrap.classList.toggle('hidden', emailOnly);
}

// DOMParser rather than innerHTML: a detached <img onerror> still fires in
// Chrome, and this runs over stored rule bodies.
function stripHtml(html) {
    if (!html) return '';
    const doc = new DOMParser().parseFromString(html, 'text/html');
    return (doc.body.textContent || '').replace(/\s+/g, ' ').trim();
}

// Shows what push / Discord / in-app actually deliver: the short message if
// there is one, otherwise the stripped email body the server would fall back to.
function syncShortMessagePreview() {
    const box = document.getElementById('ruleShortMessage');
    if (!box) return;

    const short = box.value.trim();
    const counter = document.getElementById('shortMessageCount');
    if (counter) counter.textContent = `${box.value.length} / 1000`;

    const title = (document.getElementById('ruleSubject')?.value || '').trim()
        || (document.getElementById('ruleName')?.value || '').trim();
    const fallback = stripHtml(getBodyHtml()).slice(0, PUSH_BODY_FALLBACK_MAX);
    const body = short || fallback;

    const set = (id, text) => {
        const el = document.getElementById(id);
        if (el) el.textContent = text || '—';
    };
    set('pushPreviewTitle', title.slice(0, PUSH_TITLE_MAX));
    set('pushPreviewBody', body);
    set('discordPreviewBody', body);

    const warn = document.getElementById('shortMessageWarn');
    if (!warn) return;
    const notes = [];
    const nonEmail = Array.from(document.querySelectorAll('.rule-channel:checked'))
        .map((el) => el.value).filter((c) => c !== 'email');
    if (nonEmail.length && !short) {
        // Matches the 400 the PUT returns, so the problem shows up before saving.
        notes.push('Push, Discord and in-app need a short message — saving will be '
            + 'refused until you add one.');
    }
    if (title.length > PUSH_TITLE_MAX) {
        notes.push(`The subject is ${title.length} characters; notifications cut the `
            + `title at ${PUSH_TITLE_MAX}.`);
    }
    warn.textContent = notes.join(' ');
    warn.classList.toggle('hidden', notes.length === 0);
}

function initAutomations() {
    // Show only the trigger fields that apply to this rule's trigger type.
    const triggerType = document.querySelector('[data-trigger-type]')?.dataset.triggerType;
    document.querySelectorAll('[data-trigger-fields]').forEach((el) => {
        el.classList.toggle('hidden', el.dataset.triggerFields !== triggerType);
    });

    document.querySelectorAll('.rule-channel').forEach((el) => {
        el.addEventListener('change', () => {
            syncShortMessageVisibility();
            // The "needs a short message" warning depends on the channel mix.
            syncShortMessagePreview();
        });
    });
    syncShortMessageVisibility();
    initNewAutomationPage();
    renderConditions();
    renderSteps();
    initEditor();

    const shortBox = document.getElementById('ruleShortMessage');
    if (shortBox) shortBox.addEventListener('input', syncShortMessagePreview);
    document.getElementById('ruleSubject')?.addEventListener('input', syncShortMessagePreview);
    // With no subject the notification title falls back to the rule name.
    document.getElementById('ruleName')?.addEventListener('input', syncShortMessagePreview);
    syncShortMessagePreview();
}

window.InitSystem.register('automations', initAutomations, {
    priority: 40,
    reinitializable: false,
    description: 'Automated messaging rules',
});
