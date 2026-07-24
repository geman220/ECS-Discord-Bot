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

function buildTriggerOptions(catalog) {
    const groups = {};
    Object.keys(catalog).forEach((k) => {
        const g = catalog[k].group || 'Other';
        (groups[g] = groups[g] || []).push(k);
    });
    return Object.keys(groups).sort().map((g) =>
        `<optgroup label="${escapeHtml(g)}">` +
        groups[g].map((k) =>
            `<option value="${escapeHtml(k)}">${escapeHtml(catalog[k].label)}</option>`).join('') +
        '</optgroup>').join('');
}

function buildAudienceOptions(audiences) {
    return audiences
        .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
        .join('');
}

// Fields that only make sense for particular triggers. Rendered once and shown
// or hidden as the trigger dropdown changes, so the modal stays one round-trip.
function conditionalFieldsHtml() {
    // Filled by syncConditionalFields from the server's field specs.
    return '<div id="afFields"></div>';
}

function buildTriggerFieldsHtml(specs, catalog, trigger) {
    const fields = ((catalog[trigger] || {}).fields) || [];
    return fields.map((name) => {
        const spec = specs[name];
        if (!spec) return '';
        const id = `af_${name}`;
        if (spec.type === 'choice') {
            const opts = (spec.choices || []).map(([v, l]) =>
                `<option value="${escapeHtml(v)}" ${v === spec.default ? 'selected' : ''}>${escapeHtml(l)}</option>`).join('');
            return `<div class="mt-3"><label class="block mb-1 text-sm font-medium">${escapeHtml(spec.label)}</label>` +
                   `<select id="${id}" data-af-field="${escapeHtml(name)}" class="w-full rounded-lg border border-gray-300 p-2 text-sm">${opts}</select></div>`;
        }
        return `<div class="mt-3"><label class="block mb-1 text-sm font-medium">${escapeHtml(spec.label)}</label>` +
               `<input type="number" id="${id}" data-af-field="${escapeHtml(name)}" value="${spec.default}" ` +
               `${spec.min !== null && spec.min !== undefined ? `min="${spec.min}"` : ''} ` +
               `${spec.max !== null && spec.max !== undefined ? `max="${spec.max}"` : ''} ` +
               `class="w-full rounded-lg border border-gray-300 p-2 text-sm"></div>`;
    }).join('');
}

function syncConditionalFields(catalog) {
    const trigger = document.getElementById('afTrigger')?.value;
    const meta = catalog[trigger] || {};
    const specs = readJsonScript('automationTriggerFieldSpecs', {});

    const holder = document.getElementById('afFields');
    if (holder) holder.innerHTML = buildTriggerFieldsHtml(specs, catalog, trigger);

    const helpEl = document.getElementById('afHelp');
    if (helpEl) helpEl.textContent = meta.help || '';
    const scopeEl = document.getElementById('afScope');
    if (scopeEl) scopeEl.textContent = meta.scope ? `Scope: ${meta.scope}` : '';

    // A per-person trigger can only ever target the person it fired for, so pin
    // the audience rather than letting an impossible one be chosen.
    const audienceEl = document.getElementById('afAudience');
    if (audienceEl && meta.default_audience) {
        const perPerson = meta.default_audience === 'the_subject';
        audienceEl.value = meta.default_audience;
        audienceEl.disabled = perPerson;
        audienceEl.title = perPerson
            ? 'A per-person trigger always sends to the person it fired for.'
            : '';
    }
}

async function handleNewAutomation() {
    const catalog = readJsonScript('automationTriggerCatalog', {});
    const audiences = readJsonScript('automationAudienceTypes', []);

    if (!Object.keys(catalog).length) {
        toastError('No trigger types are available.');
        return;
    }

    const result = await window.Swal.fire({
        title: 'New automation',
        width: 640,
        html:
            '<div class="text-start space-y-3">' +
            '<div><label class="block mb-1 text-sm font-medium">Name</label>' +
            '<input id="afName" class="w-full rounded-lg border border-gray-300 p-2 text-sm" ' +
            'placeholder="e.g. Welcome drafted players to Discord"></div>' +

            '<div><label class="block mb-1 text-sm font-medium">When should it fire?</label>' +
            `<select id="afTrigger" class="w-full rounded-lg border border-gray-300 p-2 text-sm">${buildTriggerOptions(catalog)}</select>` +
            '<p id="afHelp" class="mt-1 text-xs text-gray-500"></p>' +
            '<p id="afScope" class="mt-0.5 text-[11px] font-medium text-gray-400"></p></div>' +

            conditionalFieldsHtml() +

            '<div class="grid grid-cols-2 gap-2 mt-3">' +
            '<div><label class="block mb-1 text-sm font-medium">Who gets it</label>' +
            `<select id="afAudience" class="w-full rounded-lg border border-gray-300 p-2 text-sm">${buildAudienceOptions(audiences)}</select></div>` +
            '<div><label class="block mb-1 text-sm font-medium">Wait (hours)</label>' +
            '<input type="number" id="afDelay" value="24" min="0" max="720" class="w-full rounded-lg border border-gray-300 p-2 text-sm"></div>' +
            '</div>' +

            '<p class="mt-2 text-xs text-gray-500">It is created <strong>switched off</strong>. ' +
            'You will land in the editor to write the message, then turn it on when you are happy.</p>' +
            '</div>',
        didOpen: () => {
            syncConditionalFields(catalog);
            document.getElementById('afTrigger')
                ?.addEventListener('change', () => syncConditionalFields(catalog));
        },
        showCancelButton: true,
        confirmButtonText: 'Create',
        preConfirm: () => {
            const name = document.getElementById('afName')?.value?.trim();
            if (!name) {
                window.Swal.showValidationMessage('Give the automation a name');
                return false;
            }
            return {
                name,
                trigger_type: document.getElementById('afTrigger')?.value,
                // Read the select first. syncConditionalFields already pins it
                // to the required value (and disables it) for per-person
                // triggers, so this respects the admin's choice everywhere else
                // instead of always overriding with the catalog default.
                audience_type: document.getElementById('afAudience')?.value
                    || (catalog[document.getElementById('afTrigger')?.value] || {}).default_audience,
                delay_hours: parseInt(document.getElementById('afDelay')?.value || '24', 10),
                phase: document.getElementById('afPhaseValue')?.value,
                date_anchor: document.getElementById('afDateAnchor')?.value,
                days_offset: parseInt(document.getElementById('afDaysOffset')?.value || '0', 10),
                ...(function () {
                    const out = {};
                    document.querySelectorAll('[data-af-field]').forEach((el) => {
                        out[el.dataset.afField] = el.type === 'number'
                            ? parseInt(el.value || '0', 10) : el.value;
                    });
                    return out;
                }()),
            };
        },
    });

    if (!result.isConfirmed) return;

    try {
        const data = await apiCall(API_BASE, {
            method: 'POST',
            body: JSON.stringify(result.value),
        });
        window.location.href = data.redirect;
    } catch (e) {
        toastError(e.message);
    }
}

/* ========================================================================
   RICH TEXT EDITOR + EMAIL PREVIEW
   ======================================================================== */

// Read the body from TinyMCE when it is running, falling back to the raw
// textarea. TinyMCE does not write back to the textarea until it is asked to,
// so reading .value directly would save stale content.
function getBodyHtml() {
    const ed = window.tinymce && window.tinymce.get('ruleBody');
    if (ed) return ed.getContent();
    return document.getElementById('ruleBody')?.value ?? '';
}

function initEditor() {
    if (!window.tinymce || !document.getElementById('ruleBody')) return;
    const isDark = document.documentElement.classList.contains('dark');
    const isPhone = window.matchMedia && window.matchMedia('(max-width: 640px)').matches;

    window.tinymce.init({
        selector: '#ruleBody',
        width: '100%',
        height: isPhone ? 300 : 460,
        menubar: false,
        plugins: 'lists link image table code wordcount autolink',
        toolbar: isPhone
            ? 'undo redo | bold italic | bullist numlist | link inserttokens'
            : 'undo redo | blocks | bold italic underline | forecolor | alignleft aligncenter alignright | bullist numlist | link image table | inserttokens | code',
        toolbar_mode: 'sliding',
        content_style: 'body { font-family: Arial, sans-serif; font-size: 14px; }',
        skin: isDark ? 'oxide-dark' : 'oxide',
        content_css: isDark ? 'dark' : 'default',
        branding: false,
        promotion: false,
        // Email bodies rely on inline styles (buttons, spacing) that TinyMCE's
        // cleanup would otherwise strip, which would silently wreck the seeded
        // templates the moment someone opened and saved them.
        verify_html: false,
        valid_elements: '*[*]',
        extended_valid_elements: 'style,link[href|rel]',
        setup: function (editor) {
            editor.ui.registry.addMenuButton('inserttokens', {
                text: 'Insert',
                fetch: function (callback) {
                    const tokens = ['{first_name}', '{name}', '{team}', '{league}', '{season}',
                                    '{discord_invite_url}', '{support_email}'];
                    callback(tokens.map((t) => ({
                        type: 'menuitem', text: t,
                        onAction: () => editor.insertContent(t),
                    })));
                },
            });
        },
    });
}

async function handlePreviewEmail(element) {
    const ruleId = element.dataset.ruleId;
    if (!ruleId) return;

    window.Swal.fire({ title: 'Rendering…', allowOutsideClick: false,
                       didOpen: () => window.Swal.showLoading() });
    try {
        const data = await apiCall(`${API_BASE}/${ruleId}/preview-email`, {
            method: 'POST',
            body: JSON.stringify({
                body_html: getBodyHtml(),
                subject: document.getElementById('ruleSubject')?.value || '',
                template_id: document.getElementById('ruleTemplateId')?.value || null,
            }),
        });

        const warn = data.unresolved && data.unresolved.length
            ? `<div style="margin:0 0 10px;padding:8px 10px;border-radius:6px;background:#fef3c7;color:#92400e;font-size:12px;text-align:left;">
                 <strong>These will send literally:</strong> ${escapeHtml(data.unresolved.map((u) => '{' + u + '}').join(', '))}
               </div>`
            : '';

        // srcdoc keeps the email's own CSS from leaking into the admin page.
        window.Swal.fire({
            title: false,
            width: 720,
            html:
                `<p style="text-align:left;font-size:12px;color:#6b7280;margin:0 0 4px;">Subject</p>` +
                `<p style="text-align:left;font-weight:600;margin:0 0 10px;">${escapeHtml(data.subject)}</p>` +
                warn +
                `<iframe srcdoc="${escapeHtml(data.html)}" style="width:100%;height:60vh;border:1px solid #e5e7eb;border-radius:8px;background:#fff;" sandbox=""></iframe>` +
                `<p style="text-align:left;font-size:11px;color:#9ca3af;margin:8px 0 0;">` +
                `Personalised with your own details. ${data.wrapper ? 'Layout: ' + escapeHtml(data.wrapper) : 'No wrapper layout'}.</p>`,
            confirmButtonText: 'Close',
        });
    } catch (e) {
        toastError(e.message);
    }
}

/* ========================================================================
   PLAIN-TEXT CHANNEL PREVIEW (push / Discord / in-app)
   ======================================================================== */

// Practical limits: Android collapses a notification body around 240 chars and
// iOS shows ~178 on the lock screen. Discord DMs allow 2000.
const PUSH_SAFE_CHARS = 178;
const DISCORD_MAX_CHARS = 2000;

function syncShortMessagePreview() {
    const box = document.getElementById('ruleShortMessage');
    if (!box) return;
    const text = box.value || '';
    const subject = document.getElementById('ruleSubject')?.value || '';

    const count = document.getElementById('shortMessageCount');
    if (count) count.textContent = String(text.length);

    const warn = document.getElementById('shortMessageWarn');
    if (warn) {
        let msg = '';
        if (text.length > DISCORD_MAX_CHARS) {
            msg = `Over Discord's ${DISCORD_MAX_CHARS}-character limit — the DM will fail.`;
        } else if (text.length > PUSH_SAFE_CHARS) {
            msg = `Past ~${PUSH_SAFE_CHARS} characters a push notification gets cut off. Front-load the important part.`;
        } else if (/<[a-z][\s\S]*>/i.test(text)) {
            msg = 'That looks like HTML. These channels show it as raw text — use plain words and bare URLs.';
        }
        warn.textContent = msg;
        warn.classList.toggle('hidden', !msg);
    }

    const t = document.getElementById('pushPreviewTitle');
    const b = document.getElementById('pushPreviewBody');
    const d = document.getElementById('discordPreviewBody');
    if (t) t.textContent = subject || '—';
    if (b) b.textContent = text ? text.slice(0, PUSH_SAFE_CHARS) + (text.length > PUSH_SAFE_CHARS ? '…' : '') : '—';
    if (d) d.textContent = text || '—';
}


/* ========================================================================
   TRACE — "why didn't this person get it?"
   ======================================================================== */

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
        await apiCall(`${API_BASE}/${ruleId}/toggle`, {
            method: 'POST',
            body: JSON.stringify({ enabled: enabling }),
        });
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

window.EventDelegation.register('automation-new', handleNewAutomation, { preventDefault: true });
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

function initAutomations() {
    // Show only the trigger fields that apply to this rule's trigger type.
    const triggerType = document.querySelector('[data-trigger-type]')?.dataset.triggerType;
    document.querySelectorAll('[data-trigger-fields]').forEach((el) => {
        el.classList.toggle('hidden', el.dataset.triggerFields !== triggerType);
    });

    document.querySelectorAll('.rule-channel').forEach((el) => {
        el.addEventListener('change', syncShortMessageVisibility);
    });
    syncShortMessageVisibility();
    renderConditions();
    renderSteps();
    initEditor();

    const shortBox = document.getElementById('ruleShortMessage');
    if (shortBox) shortBox.addEventListener('input', syncShortMessagePreview);
    document.getElementById('ruleSubject')?.addEventListener('input', syncShortMessagePreview);
    syncShortMessagePreview();
}

window.InitSystem.register('automations', initAutomations, {
    priority: 40,
    reinitializable: false,
    description: 'Automated messaging rules',
});
