/**
 * ============================================================================
 * ADMIN AUDIT LOGS - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles audit logs page interactions using data-attribute hooks
 * Follows event delegation pattern with window.InitSystem registration
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';

// Store config from data attributes
let exportLogsUrl = '';

/**
 * Initialize audit logs module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-audit-logs-config]');
    if (configEl) {
        exportLogsUrl = configEl.dataset.exportLogsUrl || '';
    }

    initializeEventDelegation();
}

/**
 * Initialize event delegation for all interactive elements
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch (action) {
            case 'export-logs':
                exportLogs(target.dataset.format);
                break;
            case 'show-log-details':
                showLogDetails(
                    target.dataset.logId,
                    target.dataset.oldValue,
                    target.dataset.newValue,
                    target.dataset.ipAddress
                );
                break;
        }
    });
}

/**
 * Show log details in a modal
 */
function showLogDetails(logId, oldValue, newValue, ipAddress) {
    let detailsHtml = '<div class="text-start">';

    if (oldValue) {
        detailsHtml += `<p><strong>Previous Value:</strong><br><code>${escapeHtml(oldValue)}</code></p>`;
    }
    if (newValue) {
        detailsHtml += `<p><strong>New Value:</strong><br><code>${escapeHtml(newValue)}</code></p>`;
    }
    if (ipAddress) {
        detailsHtml += `<p><strong>IP Address:</strong> ${escapeHtml(ipAddress)}</p>`;
    }

    if (!oldValue && !newValue && !ipAddress) {
        detailsHtml += '<p class="text-muted">No additional details available.</p>';
    }

    detailsHtml += '</div>';

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Log Details',
            html: detailsHtml,
            icon: 'info',
            confirmButtonText: 'Close'
        });
    }
}

/**
 * Export audit logs
 */
function exportLogs(format) {
    // Build export URL with current filters
    const params = new URLSearchParams(window.location.search);
    const url = exportLogsUrl || window.auditLogsConfig?.exportLogsUrl || '/admin-panel/audit-logs/export';
    const exportUrl = `${url}?${params.toString()}`;

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Export Audit Logs',
            text: 'This will download a CSV file with the filtered audit log entries. Continue?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Download CSV',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                window.location.href = exportUrl;
            }
        });
    } else {
        if (confirm('This will download a CSV file with the filtered audit log entries. Continue?')) {
            window.location.href = exportUrl;
        }
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Register with window.InitSystem
window.InitSystem.register('admin-audit-logs', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin audit logs page functionality'
});

// Fallback
// window.InitSystem handles initialization

// Export for ES modules
export {
    init,
    showLogDetails,
    exportLogs
};

// Backward compatibility
window.adminAuditLogsInit = init;
window.showLogDetails = showLogDetails;
window.exportLogs = exportLogs;
