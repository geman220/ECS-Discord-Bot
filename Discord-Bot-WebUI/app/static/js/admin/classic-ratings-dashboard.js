'use strict';

/**
 * Admin Classic Ratings dashboard — table filter, per-player detail rows,
 * override save/revert, window toggle, config modal, gender override.
 */

function root() { return document.getElementById('classic-ratings-admin-root'); }

function applyTableFilter() {
    const query = (document.getElementById('cr-table-search')?.value || '').trim().toLowerCase();
    const show = document.getElementById('cr-table-show')?.value || '';
    let visible = 0;
    const rowPairs = document.querySelectorAll('.cr-row');
    rowPairs.forEach(row => {
        let match = !query || row.dataset.name.includes(query);
        if (match && show === 'overridden') match = row.dataset.overridden === '1';
        if (match && show === 'incomplete') match = row.dataset.rated !== '1';
        row.classList.toggle('hidden', !match);
        if (!match) {
            document.querySelector(`.cr-detail[data-player-id="${row.dataset.playerId}"]`)
                ?.classList.add('hidden');
            row.querySelector('.cr-detail-chevron')?.classList.remove('rotate-180');
        }
        if (match) visible += 1;
    });
    const count = document.getElementById('cr-table-count');
    if (count) count.textContent = `${visible} of ${rowPairs.length} shown`;
}

async function postJson(url, body) {
    const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || !data.success) {
        throw new Error(data.message || `Request failed (${resp.status})`);
    }
    return data;
}

function toastError(message) {
    if (window.Swal) {
        window.Swal.fire({ icon: 'error', title: 'Error', text: message,
                           toast: true, position: 'top-end', timer: 3500, showConfirmButton: false });
    }
}

function toastOk(message) {
    if (window.Swal) {
        window.Swal.fire({ icon: 'success', title: message,
                           toast: true, position: 'top-end', timer: 1800, showConfirmButton: false });
    }
}

async function saveOverrides(playerId) {
    const detail = document.querySelector(`.cr-detail[data-player-id="${playerId}"]`);
    if (!detail) return;
    const reason = detail.querySelector('.cr-override-reason')?.value?.trim() || null;
    const inputs = detail.querySelectorAll('.cr-override-input');
    const url = root().dataset.overrideUrl;

    let lastResult = null;
    for (const input of inputs) {
        const metric = input.dataset.metric;
        const raw = input.value.trim();
        // Tracked via data-overridden (server-rendered, updated after every
        // save below) — NOT the styling class, so set→clear works without F5.
        const wasOverridden = input.dataset.overridden === '1';
        const value = raw === '' ? null : parseFloat(raw);
        // Only send changes: a blank that wasn't overridden is a no-op.
        if (value === null && !wasOverridden) continue;
        try {
            lastResult = await postJson(url, {
                player_id: parseInt(playerId, 10), metric, value, reason,
            });
        } catch (err) {
            toastError(`${metric}: ${err.message}`);
            return;
        }
    }
    toastOk('Overrides saved');
    // Reflect new finals in the main row + input state without a full reload.
    if (lastResult) {
        updateRowFinals(playerId, lastResult);
        inputs.forEach(input => {
            const final = lastResult.final?.[input.dataset.metric];
            const overridden = Boolean(final?.overridden);
            input.dataset.overridden = overridden ? '1' : '0';
            input.classList.toggle('border-amber-400', overridden);
            input.classList.toggle('ring-1', overridden);
            input.classList.toggle('ring-amber-300', overridden);
            input.classList.toggle('border-gray-200', !overridden);
            if (!overridden) input.value = '';
        });
    } else {
        window.location.reload();
    }
}

function updateRowFinals(playerId, result) {
    const row = document.querySelector(`.cr-row[data-player-id="${playerId}"]`);
    if (!row || !result.final) { window.location.reload(); return; }
    let anyOverride = false;
    Object.entries(result.final).forEach(([metric, f]) => {
        const cell = row.querySelector(`.cr-cell[data-metric="${metric}"]`);
        if (!cell) return;
        if (f.value === null) {
            cell.innerHTML = '<span class="text-gray-300 dark:text-gray-600">—</span>';
        } else {
            const overridden = f.overridden;
            anyOverride = anyOverride || overridden;
            const cls = overridden ? 'text-amber-600 dark:text-amber-400 font-semibold'
                                   : 'text-gray-900 dark:text-white';
            const icon = overridden ? '<i class="ti ti-pencil text-[10px] ml-0.5"></i>' : '';
            const title = overridden && f.avg !== null ? ` title="Admin override — average was ${f.avg.toFixed(2)}"` : '';
            cell.innerHTML = `<span class="${cls}"${title}>${f.value.toFixed(2)}${icon}</span>`;
        }
    });
    row.dataset.overridden = anyOverride ? '1' : '0';
    const flag = row.querySelector('.cr-flag');
    if (flag) flag.innerHTML = anyOverride
        ? '<span class="inline-block w-2 h-2 rounded-full bg-amber-400" title="Has admin override"></span>' : '';
    const composite = row.querySelector('.cr-composite');
    if (composite) {
        composite.textContent = result.composite === null ? '—' : result.composite.toFixed(2);
        composite.classList.toggle('text-ecs-green', result.composite !== null);
        composite.classList.toggle('text-gray-300', result.composite === null);
    }
}

function registerHandlers() {
    const ED = window.EventDelegation;
    if (!ED) return;

    ED.register('ratings-table-filter', () => applyTableFilter());

    ED.register('ratings-toggle-player-detail', (element) => {
        const row = element.closest('.cr-row');
        const detail = document.querySelector(`.cr-detail[data-player-id="${row.dataset.playerId}"]`);
        const chevron = row.querySelector('.cr-detail-chevron');
        if (!detail) return;
        const opening = detail.classList.contains('hidden');
        detail.classList.toggle('hidden', !opening);
        chevron?.classList.toggle('rotate-180', opening);
    });

    ED.register('ratings-override-save', (element) => {
        const playerId = element.dataset.playerId;
        if (window.Swal) {
            window.Swal.fire({
                icon: 'question',
                title: 'Apply overrides?',
                text: 'Overrides replace the coach average as the final score. Blank fields revert to the average.',
                showCancelButton: true,
                confirmButtonText: 'Apply',
            }).then(result => { if (result.isConfirmed) saveOverrides(playerId); });
        } else {
            saveOverrides(playerId);
        }
    });

    ED.register('ratings-toggle-window', async (element) => {
        const open = element.dataset.open === '1';
        try {
            await postJson(root().dataset.windowUrl, { open });
            window.location.reload();
        } catch (err) { toastError(err.message); }
    });

    ED.register('ratings-metric-pick', (element) => {
        document.querySelectorAll('.cr-metric-form').forEach(form => {
            form.classList.toggle('hidden', form.dataset.metric !== element.value);
        });
    });

    ED.register('ratings-metric-save', async () => {
        const key = document.getElementById('cr-metric-picker')?.value;
        const form = document.querySelector(`.cr-metric-form[data-metric="${key}"]`);
        if (!key || !form) return;
        const field = name => form.querySelector(`[name="${name}"]`)?.value ?? '';
        try {
            await postJson(root().dataset.metricsUrl, {
                key,
                label: field('label'),
                description: field('description'),
                anchor_1: field('anchor_1'),
                anchor_3: field('anchor_3'),
                anchor_5: field('anchor_5'),
            });
            toastOk('Metric guide saved');
        } catch (err) { toastError(err.message); }
    });

    ED.register('ratings-set-gender', async (element) => {
        const url = root().dataset.genderUrlTemplate.replace('999999', element.dataset.playerId);
        try {
            await postJson(url, { balance_gender: element.value || null });
            toastOk('Gender updated');
        } catch (err) { toastError(err.message); }
    });
}

function bindConfigForm() {
    const form = document.getElementById('cr-config-form');
    if (!form) return;

    const updateSum = () => {
        const sum = Array.from(form.querySelectorAll('.cr-weight'))
            .reduce((total, input) => total + (parseFloat(input.value) || 0), 0);
        const label = document.getElementById('cr-weight-sum');
        if (label) {
            label.textContent = String(sum);
            label.classList.toggle('text-red-500', sum !== 100);
            label.classList.toggle('text-gray-500', sum === 100);
        }
    };
    form.querySelectorAll('.cr-weight').forEach(input => input.addEventListener('input', updateSum));
    updateSum();

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const value = name => form.elements[name]?.value;
        const payload = {
            weights: {
                intensity: parseFloat(value('weight_intensity')),
                on_ball_skill: parseFloat(value('weight_on_ball_skill')),
                spirit: parseFloat(value('weight_spirit')),
                knowledge_movement: parseFloat(value('weight_knowledge_movement')),
            },
            max_metric_gap: parseFloat(value('max_metric_gap')),
            unrated_default: parseFloat(value('unrated_default')),
            suggestion_count: parseInt(value('suggestion_count'), 10),
            gender_balance_enabled: form.elements.gender_balance_enabled.checked,
            balanced_draft_enabled: form.elements.balanced_draft_enabled.checked,
            suggestion_coefficients: {
                balance: parseFloat(value('coeff_balance')),
                need: parseFloat(value('coeff_need')),
                gender: parseFloat(value('coeff_gender')),
                position: parseFloat(value('coeff_position')),
            },
        };
        try {
            await postJson(root().dataset.configUrl, payload);
            toastOk('Configuration saved');
            setTimeout(() => window.location.reload(), 600);
        } catch (err) { toastError(err.message); }
    });
}

function init() {
    if (!root()) return;
    registerHandlers();
    bindConfigForm();
    applyTableFilter();
}

if (window.InitSystem?.register) {
    window.InitSystem.register('classic-ratings-admin', init, {
        priority: 40,
        reinitializable: false,
        description: 'Admin Classic ratings dashboard',
    });
} else {
    document.addEventListener('DOMContentLoaded', init);
}
