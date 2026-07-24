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
    return Object.keys(catalog)
        .map((key) => `<option value="${escapeHtml(key)}">${escapeHtml(catalog[key].label)}</option>`)
        .join('');
}

function buildAudienceOptions(audiences) {
    return audiences
        .map(([value, label]) => `<option value="${escapeHtml(value)}">${escapeHtml(label)}</option>`)
        .join('');
}

// Fields that only make sense for particular triggers. Rendered once and shown
// or hidden as the trigger dropdown changes, so the modal stays one round-trip.
function conditionalFieldsHtml() {
    return (
        '<div id="afPhase" class="hidden mt-3">' +
        '<label class="block mb-1 text-sm font-medium">Fires when the season enters</label>' +
        '<select id="afPhaseValue" class="swal2-select-like w-full rounded-lg border border-gray-300 p-2 text-sm">' +
        '<option value="preseason">Preseason</option>' +
        '<option value="in_season">In season</option>' +
        '<option value="break">Break</option>' +
        '<option value="offseason" selected>Offseason</option>' +
        '</select></div>' +

        '<div id="afDate" class="hidden mt-3 grid grid-cols-2 gap-2">' +
        '<div><label class="block mb-1 text-sm font-medium">Anchor</label>' +
        '<select id="afDateAnchor" class="w-full rounded-lg border border-gray-300 p-2 text-sm">' +
        '<option value="start">Season start date</option>' +
        '<option value="end">Season end date</option>' +
        '</select></div>' +
        '<div><label class="block mb-1 text-sm font-medium">Days offset</label>' +
        '<input type="number" id="afDaysOffset" value="0" class="w-full rounded-lg border border-gray-300 p-2 text-sm">' +
        '<p class="mt-1 text-[11px] text-gray-500">-3 = 3 days before, +1 = day after</p></div>' +
        '</div>' +

        '<div id="afStuck" class="hidden mt-3">' +
        '<label class="block mb-1 text-sm font-medium">Waiting longer than (days)</label>' +
        '<input type="number" id="afStuckDays" value="14" min="1" class="w-full rounded-lg border border-gray-300 p-2 text-sm"></div>' +

        '<div id="afSilence" class="hidden mt-3">' +
        '<label class="block mb-1 text-sm font-medium">Silent for (hours)</label>' +
        '<input type="number" id="afSilenceHours" value="24" min="1" class="w-full rounded-lg border border-gray-300 p-2 text-sm"></div>'
    );
}

function syncConditionalFields(catalog) {
    const trigger = document.getElementById('afTrigger')?.value;
    const meta = catalog[trigger] || {};
    const fields = meta.fields || [];

    document.getElementById('afPhase')?.classList.toggle('hidden', !fields.includes('phase'));
    document.getElementById('afDate')?.classList.toggle('hidden', !fields.includes('date_anchor'));
    document.getElementById('afStuck')?.classList.toggle('hidden', !fields.includes('stuck_days'));
    document.getElementById('afSilence')?.classList.toggle('hidden', !fields.includes('silence_hours'));

    // Per-person triggers can only ever target the person they fired for, so
    // pin the audience rather than letting the admin pick an impossible one.
    const audienceEl = document.getElementById('afAudience');
    if (audienceEl && meta.default_audience) {
        const perPerson = meta.default_audience === 'the_subject';
        audienceEl.value = meta.default_audience;
        audienceEl.disabled = perPerson;
        audienceEl.title = perPerson
            ? 'A per-person trigger always sends to the person it fired for.'
            : '';
    }

    const helpEl = document.getElementById('afHelp');
    if (helpEl) {
        helpEl.textContent = meta.help || '';
    }
    const scopeEl = document.getElementById('afScope');
    if (scopeEl) {
        scopeEl.textContent = meta.scope ? `Scope: ${meta.scope}` : '';
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
                stuck_days: parseInt(document.getElementById('afStuckDays')?.value || '14', 10),
                silence_hours: parseInt(document.getElementById('afSilenceHours')?.value || '24', 10),
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
    const num = (id) => {
        const el = document.getElementById(id);
        return el && el.value !== '' ? parseInt(el.value, 10) : null;
    };

    const channels = Array.from(document.querySelectorAll('.rule-channel:checked'))
        .map((el) => el.value);

    const payload = {
        name: val('ruleName'),
        description: val('ruleDescription'),
        subject: val('ruleSubject'),
        body_html: val('ruleBody'),
        short_message: val('ruleShortMessage'),
        channels: channels.length ? channels : ['email'],
        conditions: collectConditions(),
        delay_hours: num('ruleDelayHours'),
        audience_type: val('ruleAudienceType'),
        send_mode: val('ruleSendMode'),
        force_send: document.getElementById('ruleForceSend')?.checked ?? false,
        template_id: val('ruleTemplateId') || null,
    };

    // Only submit trigger fields belonging to THIS rule's trigger. Every block
    // is present in the DOM and merely CSS-hidden, so reading them all would
    // write e.g. min_players_per_team into a season_phase rule's config.
    const activeTrigger = document.querySelector('[data-trigger-type]')?.dataset.triggerType;
    const visible = (id) => {
        const el = document.getElementById(id);
        if (!el) return false;
        const block = el.closest('[data-trigger-fields]');
        return !block || block.dataset.triggerFields === activeTrigger;
    };

    // Applies to every trigger type. Send the key even when the box was cleared
    // (num() -> null): dropping it made Save report success while the old value
    // silently came back. The server validates and returns a real error.
    if (document.getElementById('ruleMaxEventAge')) {
        payload.max_event_age_days = num('ruleMaxEventAge');
    }

    if (visible('ruleMinPlayers')) {
        payload.min_players_per_team = num('ruleMinPlayers');
    }
    if (visible('rulePhase')) {
        const phase = document.getElementById('rulePhase')?.value;
        if (phase) payload.phase = phase;
    }
    for (const [id, key] of [['ruleStuckDays', 'stuck_days'],
                             ['ruleSilenceHours', 'silence_hours']]) {
        if (visible(id)) {
            payload[key] = num(id);
        }
    }
    if (visible('ruleDateAnchor')) {
        payload.date_anchor = document.getElementById('ruleDateAnchor')?.value;
        payload.days_offset = num('ruleDaysOffset') ?? 0;
    }

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
}

window.InitSystem.register('automations', initAutomations, {
    priority: 40,
    reinitializable: false,
    description: 'Automated messaging rules',
});
