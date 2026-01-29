'use strict';

/**
 * Quick Actions - Maintenance
 *
 * Event delegation handlers for system maintenance quick actions:
 * - Toggle maintenance mode
 * - Clear system logs
 * - Generate system reports
 *
 * @module quick-actions/maintenance
 */

/**
 * Toggle Maintenance Mode
 * Enables/disables system maintenance mode
 */
window.EventDelegation.register('toggle-maintenance-mode', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[toggle-maintenance-mode] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Toggle Maintenance Mode?',
        html: '<p>This will enable or disable system maintenance mode.</p><p class="text-yellow-500 dark:text-yellow-400 small"><i class="ti ti-alert-triangle me-1"></i>When enabled, non-admin users will see a maintenance page.</p>',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: 'Toggle Maintenance Mode'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Toggling Maintenance Mode...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/toggle-maintenance-mode', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            const isEnabled = data.maintenance_mode;
                            window.Swal.fire({
                                title: isEnabled ? 'Maintenance Mode Enabled' : 'Maintenance Mode Disabled',
                                html: `<p>${data.message}</p><p class="mt-2"><span class="px-2 py-0.5 text-xs font-medium rounded ${isEnabled ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300' : 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300'}" data-badge>${isEnabled ? 'MAINTENANCE' : 'NORMAL'}</span></p>`,
                                icon: isEnabled ? 'warning' : 'success'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to toggle maintenance mode', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[toggle-maintenance-mode] Error:', error);
                        window.Swal.fire('Error', 'Failed to toggle maintenance mode. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Clear System Logs
 * Clears all system and error logs
 */
window.EventDelegation.register('clear-system-logs', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[clear-system-logs] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Clear System Logs?',
        html: `
            <p>This will permanently delete system logs.</p>
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Retention Period</label>
                <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="logRetentionDays" data-form-select>
                    <option value="0">Delete ALL logs</option>
                    <option value="7" selected>Keep last 7 days</option>
                    <option value="30">Keep last 30 days</option>
                    <option value="90">Keep last 90 days</option>
                </select>
            </div>
            <p class="text-yellow-500 dark:text-yellow-400 small"><i class="ti ti-alert-triangle me-1"></i>This action cannot be undone.</p>
        `,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#f39c12',
        confirmButtonText: 'Clear Logs',
        preConfirm: () => {
            return {
                retention_days: parseInt(document.getElementById('logRetentionDays').value, 10)
            };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Clearing Logs...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/clear-system-logs', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(result.value)
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire({
                                title: 'Logs Cleared!',
                                html: `<p>${data.message}</p><p class="text-muted small mt-2">${data.deleted_count || 0} log entries deleted</p>`,
                                icon: 'success'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to clear logs', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[clear-system-logs] Error:', error);
                        window.Swal.fire('Error', 'Failed to clear logs. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Generate System Report
 * Generates a comprehensive system status report
 */
window.EventDelegation.register('generate-system-report', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[generate-system-report] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Generate System Report?',
        html: '<p>This will create a comprehensive system status report with current statistics.</p>',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Generate Report'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Generating Report...',
                html: '<p>Collecting system statistics...</p><p class="text-muted small">This may take a moment</p>',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/generate-system-report', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            const report = data.report;
                            window.Swal.fire({
                                title: 'System Report Generated!',
                                html: `
                                    <div class="text-start">
                                        <h6 class="mb-2">User Statistics</h6>
                                        <ul class="list-none small mb-3">
                                            <li>Total Users: <strong>${report.users?.total || 0}</strong></li>
                                            <li>Active Users: <strong>${report.users?.active || 0}</strong></li>
                                            <li>Pending Approval: <strong>${report.users?.pending || 0}</strong></li>
                                        </ul>
                                        <h6 class="mb-2">System Status</h6>
                                        <ul class="list-none small mb-3">
                                            <li>Teams: <strong>${report.teams?.total || 0}</strong></li>
                                            <li>Matches: <strong>${report.matches?.total || 0}</strong></li>
                                            <li>Templates: <strong>${report.templates?.total || 0}</strong></li>
                                        </ul>
                                        <p class="text-muted small mb-0">Generated: ${report.generated_at || 'Unknown'}</p>
                                    </div>
                                `,
                                icon: 'success',
                                confirmButtonText: 'Download Report',
                                showCancelButton: true,
                                cancelButtonText: 'Close'
                            }).then((downloadResult) => {
                                if (downloadResult.isConfirmed) {
                                    // Create download
                                    const blob = new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' });
                                    const url = window.URL.createObjectURL(blob);
                                    const a = document.createElement('a');
                                    a.href = url;
                                    a.download = `system-report-${new Date().toISOString().split('T')[0]}.json`;
                                    document.body.appendChild(a);
                                    a.click();
                                    window.URL.revokeObjectURL(url);
                                    document.body.removeChild(a);
                                }
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to generate report', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[generate-system-report] Error:', error);
                        window.Swal.fire('Error', 'Failed to generate report. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});
