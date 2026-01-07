'use strict';

/**
 * Error Handlers
 * Handles error_analytics.html, error_cleanup.html, error_list.html actions
 * @module event-delegation/handlers/mobile/errors
 */

/**
 * Initialize error handlers
 * @param {Object} ED - EventDelegation instance
 */
export function initErrorHandlers(ED) {
    /**
     * Export error data
     */
    ED.register('export-errors', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Export Errors',
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <label class="form-label">Date Range</label>
                        <select class="form-select" id="exportDays" data-form-select>
                            <option value="7">Last 7 days</option>
                            <option value="30">Last 30 days</option>
                            <option value="90">Last 90 days</option>
                            <option value="all">All time</option>
                        </select>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Format</label>
                        <select class="form-select" id="exportFormat" data-form-select>
                            <option value="csv">CSV</option>
                            <option value="json">JSON</option>
                        </select>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Export'
        }).then((result) => {
            if (result.isConfirmed) {
                const days = document.getElementById('exportDays')?.value || '7';
                const format = document.getElementById('exportFormat')?.value || 'csv';
                const exportUrl = element.dataset.exportUrl || '/admin/mobile/errors';
                window.location.href = `${exportUrl}?export=true&days=${days}&format=${format}`;
                window.Swal.fire('Exporting...', 'Your download will start shortly.', 'info');
            }
        });
    });

    /**
     * Execute error data cleanup
     */
    ED.register('execute-cleanup', (element, event) => {
        event.preventDefault();
        const confirmCheckbox = document.getElementById('confirmCleanup');

        if (!confirmCheckbox?.checked) {
            window.Swal.fire('Confirmation Required', 'Please check the confirmation box before proceeding.', 'warning');
            return;
        }

        window.Swal.fire({
            title: 'Execute Cleanup?',
            html: `
                <p>This will permanently delete old error data based on retention settings.</p>
                <p class="text-danger"><strong>This action cannot be undone!</strong></p>
            `,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
            confirmButtonText: 'Yes, delete data',
            cancelButtonText: 'Cancel'
        }).then(async (result) => {
            if (!result.isConfirmed) return;

            window.Swal.fire({
                title: 'Executing Cleanup...',
                text: 'Please wait while old data is being deleted',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();
                }
            });

            try {
                const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
                const cleanupUrl = element.dataset.cleanupUrl || '/admin/mobile/errors/cleanup';

                const response = await fetch(cleanupUrl, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify({ confirmed: true })
                });

                const data = await response.json();

                if (data.status === 'success') {
                    await window.Swal.fire({
                        icon: 'success',
                        title: 'Cleanup Complete',
                        html: `
                            <p>Successfully deleted:</p>
                            <ul class="text-start">
                                <li>${data.deleted_errors || 0} error records</li>
                                <li>${data.deleted_logs || 0} log entries</li>
                                <li>${data.deleted_patterns || 0} error patterns</li>
                            </ul>
                        `,
                        confirmButtonText: 'OK'
                    });
                    location.reload();
                } else {
                    window.Swal.fire('Error', data.error || 'Cleanup failed', 'error');
                }
            } catch (error) {
                console.error('Cleanup error:', error);
                window.Swal.fire('Error', 'Failed to execute cleanup. Please try again.', 'error');
            }
        });
    });

    /**
     * View error details
     */
    ED.register('view-error', async (element, event) => {
        event.preventDefault();
        const errorUrl = element.dataset.errorUrl;

        if (!errorUrl) {
            window.Swal.fire('Error', 'Error details URL not available', 'error');
            return;
        }

        try {
            const response = await fetch(errorUrl);
            const data = await response.json();

            if (data.error) {
                window.Swal.fire('Error', data.error, 'error');
                return;
            }

            window.Swal.fire({
                title: 'Error Details',
                html: `
                    <div class="text-start">
                        <div class="mb-3">
                            <strong>Error Type:</strong><br>
                            <code>${data.error_type}</code>
                        </div>
                        <div class="mb-3">
                            <strong>Severity:</strong><br>
                            <span class="badge bg-${data.severity === 'critical' ? 'danger' : data.severity === 'error' ? 'warning' : 'info'}" data-badge>${data.severity}</span>
                        </div>
                        <div class="mb-3">
                            <strong>Message:</strong><br>
                            ${data.message}
                        </div>
                        ${data.stack_trace ? `
                        <div class="mb-3">
                            <strong>Stack Trace:</strong><br>
                            <pre class="bg-light p-2 rounded scroll-container-sm code-display-sm">${data.stack_trace}</pre>
                        </div>
                        ` : ''}
                        ${data.device_info ? `
                        <div class="mb-3">
                            <strong>Device Info:</strong><br>
                            <pre class="bg-light p-2 rounded">${JSON.stringify(data.device_info, null, 2)}</pre>
                        </div>
                        ` : ''}
                        <div class="mb-3">
                            <strong>Timestamp:</strong><br>
                            ${data.created_at || 'N/A'}
                        </div>
                    </div>
                `,
                width: '600px',
                confirmButtonText: 'Close'
            });
        } catch (error) {
            console.error('Error fetching error details:', error);
            window.Swal.fire('Error', 'Failed to load error details', 'error');
        }
    });
}
