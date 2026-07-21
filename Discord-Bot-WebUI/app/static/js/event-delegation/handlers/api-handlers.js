import { EventDelegation } from '../core.js';
import { ModalManager } from '../../modal-manager.js';

/**
 * API Management Action Handlers
 * Handles API logs. (The API-key generate/revoke/toggle handlers and the
 * "Global API Configuration" save/reset handlers were removed 2026-07: the
 * keys they generated were never validated by anything — real API auth is the
 * env-configured MOBILE_API_KEY — and the config form saved api_config_* rows
 * no code ever read.)
 */

// ============================================================================
// REMOVED: API KEY MANAGEMENT + API CONFIGURATION (dead endpoints)
// ============================================================================

// ============================================================================
// API LOGS
// ============================================================================

/**
 * Refresh API Logs
 * Refreshes the API logs view
 */
window.EventDelegation.register('refresh-api-logs', function(element, e) {
    e.preventDefault();
    window.location.reload();
});

/**
 * Clear API Logs
 * Clears old API logs
 */
window.EventDelegation.register('clear-api-logs', function(element, e) {
    e.preventDefault();

    const daysToKeep = element.dataset.daysToKeep || 30;

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Clear API Logs',
            text: `This will delete API logs older than ${daysToKeep} days. Continue?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Clear Logs',
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                performClearApiLogs(daysToKeep, element);
            }
        });
    }
});

function performClearApiLogs(daysToKeep, element) {
    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Clearing...';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin-panel/api/logs/clear', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({ days_to_keep: parseInt(daysToKeep) })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Logs Cleared',
                    text: data.message || 'Old logs have been cleared',
                    timer: 2000,
                    showConfirmButton: false
                }).then(() => location.reload());
            } else {
                location.reload();
            }
        } else {
            throw new Error(data.error || 'Failed to clear logs');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
}

// NOTE: export-api-logs was removed — there is no /admin-panel/api/logs/export
// route (audit-log exports live at /admin-panel/audit-logs/export) and no
// template renders the button.

/**
 * Filter API Logs
 * Applies filters to API logs
 */
window.EventDelegation.register('filter-api-logs', function(element, e) {
    e.preventDefault();

    const statusFilter = document.getElementById('log-status-filter')?.value || '';
    const endpointFilter = document.getElementById('log-endpoint-filter')?.value || '';
    const dateFrom = document.getElementById('log-date-from')?.value || '';
    const dateTo = document.getElementById('log-date-to')?.value || '';

    const params = new URLSearchParams();
    if (statusFilter) params.append('status', statusFilter);
    if (endpointFilter) params.append('endpoint', endpointFilter);
    if (dateFrom) params.append('from', dateFrom);
    if (dateTo) params.append('to', dateTo);

    window.location.href = window.location.pathname + '?' + params.toString();
});

// NOTE: view-api-log-details was removed — there is no /admin-panel/api/logs/<id>
// route and no template renders the button.

// ============================================================================

// Handlers loaded
