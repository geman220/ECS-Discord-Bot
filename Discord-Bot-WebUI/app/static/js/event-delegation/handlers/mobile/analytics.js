'use strict';

/**
 * Mobile Analytics Handlers
 * Handles mobile_analytics.html actions
 * @module event-delegation/handlers/mobile/analytics
 */

/**
 * Initialize mobile analytics handlers
 * @param {Object} ED - EventDelegation instance
 */
export function initMobileAnalyticsHandlers(ED) {
    /**
     * Update chart with time period
     */
    ED.register('update-chart', (element, event) => {
        event.preventDefault();
        const period = element.dataset.period;

        const btnGroup = element.closest('.btn-group');
        if (btnGroup) {
            btnGroup.querySelectorAll('.c-btn, .btn').forEach(btn => btn.classList.remove('active'));
            element.classList.add('active');
        }

        window.Swal.fire({
            title: 'Loading Data...',
            text: `Loading ${period} analytics data`,
            allowOutsideClick: false,
            timer: 1500,
            didOpen: () => {
                window.Swal.showLoading();
            }
        });
    });

    /**
     * Export analytics data
     */
    ED.register('export-analytics', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'Export Analytics',
            text: 'Choose export format and date range',
            icon: 'info',
            showCancelButton: true,
            confirmButtonText: 'Export',
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <label class="form-label">Date Range</label>
                        <select class="form-select" id="exportDateRange" data-form-select>
                            <option value="7d">Last 7 days</option>
                            <option value="30d">Last 30 days</option>
                            <option value="90d">Last 90 days</option>
                            <option value="all">All time</option>
                        </select>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Format</label>
                        <select class="form-select" id="exportFormat" data-form-select>
                            <option value="csv">CSV</option>
                            <option value="json">JSON</option>
                            <option value="pdf">PDF Report</option>
                        </select>
                    </div>
                </div>
            `
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire('Export Started', 'Your analytics export will download shortly.', 'success');
            }
        });
    });

    /**
     * Refresh analytics data
     */
    ED.register('refresh-analytics', (element, event) => {
        event.preventDefault();
        location.reload();
    });

    /**
     * View detailed user flow analysis
     */
    ED.register('view-detailed-flow', (element, event) => {
        event.preventDefault();
        window.Swal.fire({
            title: 'User Flow Analysis',
            html: `
                <div class="text-start">
                    <p>Detailed user flow analysis shows the paths users take through the app.</p>
                    <div class="mt-3">
                        <h6>Entry Points:</h6>
                        <ul>
                            <li>Direct App Launch: 65%</li>
                            <li>Push Notification: 25%</li>
                            <li>Deep Link: 10%</li>
                        </ul>
                    </div>
                    <div class="mt-3">
                        <h6>Exit Points:</h6>
                        <ul>
                            <li>Home Screen: 40%</li>
                            <li>Match Details: 25%</li>
                            <li>Settings: 20%</li>
                            <li>Other: 15%</li>
                        </ul>
                    </div>
                </div>
            `,
            width: '600px',
            confirmButtonText: 'Close'
        });
    });
}
