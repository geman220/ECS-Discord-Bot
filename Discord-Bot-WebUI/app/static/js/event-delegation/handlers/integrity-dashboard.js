/**
 * Data Integrity Dashboard — contextual Resolve modal.
 *
 * Each finding on /admin-panel/integrity carries the fix_actions its detector
 * attached (see app/services/integrity_service.py). The Resolve button opens a
 * SweetAlert2 modal listing those actions; picking one POSTs to
 * /admin-panel/integrity/resolve, which dispatches integrity_fix_service.
 * Destructive actions require a second confirming click on the same button.
 */

import { escapeHtml } from '../../utils/sanitize.js';

function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

let _findings = null;

function getFinding(code, index) {
    if (_findings === null) {
        const blob = document.getElementById('integrity-findings');
        try {
            _findings = blob ? JSON.parse(blob.textContent) : {};
        } catch (e) {
            console.error('[integrity] bad findings payload', e);
            _findings = {};
        }
    }
    return (_findings[code] || [])[index] || null;
}

const BTN_STYLES = {
    primary: 'bg-ecs-green text-white hover:bg-ecs-green/90',
    danger: 'bg-red-600 text-white hover:bg-red-700',
    neutral: 'bg-gray-100 text-gray-800 hover:bg-gray-200 dark:bg-gray-700 dark:text-gray-200 dark:hover:bg-gray-600'
};

function buildModalHtml(finding, profileUrl, manageUrl) {
    const actions = finding.fix_actions || [];
    let html = `<p class="text-sm text-left text-gray-600 dark:text-gray-300 mb-4">${escapeHtml(finding.detail)}</p>`;

    if (actions.length) {
        html += '<div class="space-y-3 text-left">';
        actions.forEach((a, i) => {
            html += '<div class="rounded-lg border border-gray-200 dark:border-gray-600 p-3">';
            if (a.select) {
                const sel = a.select;
                html += `<label class="block text-xs font-semibold text-gray-500 dark:text-gray-400 mb-1">${escapeHtml(sel.label || sel.name)}</label>`;
                html += `<select id="integrity-select-${i}" class="w-full mb-2 rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white text-sm">`;
                (sel.options || []).forEach(o => {
                    const selected = o.value === sel.selected ? ' selected' : '';
                    html += `<option value="${escapeHtml(o.value)}"${selected}>${escapeHtml(o.label)}</option>`;
                });
                html += '</select>';
            }
            const style = BTN_STYLES[a.style] || BTN_STYLES.neutral;
            html += `<button type="button" data-fix-idx="${i}" class="w-full inline-flex items-center justify-center gap-1.5 h-9 px-3 rounded-lg text-sm font-semibold ${style}">${escapeHtml(a.label)}</button>`;
            if (a.confirm) {
                html += `<p data-confirm-note="${i}" class="hidden mt-2 text-xs text-red-600 dark:text-red-400">${escapeHtml(a.confirm)}</p>`;
            }
            html += '</div>';
        });
        html += '</div>';
    } else {
        html += '<p class="text-sm text-left text-gray-500 dark:text-gray-400">No one-click fix is available for this conflict — use the links below to resolve it manually.</p>';
    }

    html += '<div class="mt-4 pt-3 border-t border-gray-200 dark:border-gray-600 flex items-center justify-center gap-4">';
    if (profileUrl) {
        html += `<a href="${escapeHtml(profileUrl)}" class="text-xs text-ecs-green hover:underline"><i class="ti ti-user"></i> Player profile</a>`;
    }
    if (manageUrl) {
        html += `<a href="${escapeHtml(manageUrl)}" class="text-xs text-ecs-green hover:underline"><i class="ti ti-edit"></i> Full user editor</a>`;
    }
    html += '</div>';
    return html;
}

function executeFix(finding, action, params, popup) {
    popup.querySelectorAll('button[data-fix-idx]').forEach(b => { b.disabled = true; b.classList.add('opacity-60'); });
    fetch('/admin-panel/integrity/resolve', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({
            code: finding.code,
            action: action.action,
            user_id: finding.user_id,
            player_id: finding.player_id,
            params: params
        })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            window.Swal.fire({
                title: 'Resolved',
                text: data.message,
                icon: 'success',
                timer: 2200,
                showConfirmButton: false
            }).then(() => location.reload());
        } else {
            window.Swal.fire('Could not resolve', data.message || 'Fix failed.', 'error');
        }
    })
    .catch(err => {
        console.error('[integrity] resolve failed', err);
        window.Swal.fire('Error', 'Request failed — try again.', 'error');
    });
}

window.EventDelegation.register('integrity-manage', (element, event) => {
    event.preventDefault();
    const finding = getFinding(element.dataset.code, parseInt(element.dataset.index, 10));
    if (!finding || typeof window.Swal === 'undefined') {
        // No payload (stale page) — fall back to the full user editor.
        if (element.dataset.manageUrl) location.href = element.dataset.manageUrl;
        return;
    }

    window.Swal.fire({
        title: escapeHtml(finding.name || finding.title),
        html: buildModalHtml(finding, element.dataset.profileUrl, element.dataset.manageUrl),
        showConfirmButton: false,
        showCloseButton: true,
        width: '32rem',
        didOpen: (popup) => {
            popup.querySelectorAll('button[data-fix-idx]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const idx = parseInt(btn.dataset.fixIdx, 10);
                    const action = (finding.fix_actions || [])[idx];
                    if (!action) return;
                    // Destructive actions: reveal the consequence note and require a
                    // second click on the same button to proceed.
                    if (action.confirm && btn.dataset.armed !== '1') {
                        btn.dataset.armed = '1';
                        btn.textContent = 'Click again to confirm';
                        const note = popup.querySelector(`[data-confirm-note="${idx}"]`);
                        if (note) note.classList.remove('hidden');
                        return;
                    }
                    const params = Object.assign({}, action.params || {});
                    if (action.select) {
                        const sel = popup.querySelector(`#integrity-select-${idx}`);
                        if (sel) params[action.select.name] = sel.value;
                    }
                    executeFix(finding, action, params, popup);
                });
            });
        }
    });
});
