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
                        <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Date Range</label>
                        <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="exportDays" data-form-select>
                            <option value="7">Last 7 days</option>
                            <option value="30">Last 30 days</option>
                            <option value="90">Last 90 days</option>
                            <option value="all">All time</option>
                        </select>
                    </div>
                    <div class="mb-3">
                        <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Format</label>
                        <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="exportFormat" data-form-select>
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
                const exportUrl = element.dataset.exportUrl || '/admin-panel/mobile-features/error-analytics/errors';
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
                <p class="text-red-500"><strong>This action cannot be undone!</strong></p>
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
                const cleanupUrl = element.dataset.cleanupUrl || '/admin-panel/mobile-features/error-analytics/cleanup';

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
     * Change the error-volume trend period (24h / 7d / 30d).
     * Fetches the real series + derived stats and re-renders the chart in place.
     */
    ED.register('change-error-period', async (element, event) => {
        event.preventDefault();
        const section = element.closest('[data-error-volume]');
        if (!section) return;

        const period = element.dataset.period || '7d';
        const baseUrl = section.dataset.volumeUrl;
        if (!baseUrl) return;
        if (section.dataset.currentPeriod === period && !section.dataset.loadError) return;

        // Reflect active button state immediately.
        const buttons = section.querySelectorAll('[data-action="change-error-period"]');
        buttons.forEach((btn) => {
            const active = btn === element;
            btn.setAttribute('aria-pressed', active ? 'true' : 'false');
            btn.classList.toggle('font-semibold', active);
            btn.classList.toggle('bg-ecs-green', active);
            btn.classList.toggle('text-white', active);
            btn.classList.toggle('font-medium', !active);
            btn.classList.toggle('text-gray-600', !active);
            btn.classList.toggle('hover:bg-gray-50', !active);
            btn.classList.toggle('dark:text-gray-300', !active);
            btn.classList.toggle('dark:hover:bg-gray-700', !active);
        });

        try {
            const resp = await fetch(`${baseUrl}?period=${encodeURIComponent(period)}`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await resp.json();
            if (!data || data.success === false) {
                delete section.dataset.loadError;
            }
            section.dataset.currentPeriod = period;
            renderVolume(section, data || {});
        } catch (err) {
            console.error('Failed to load error volume for period', period, err);
            section.dataset.loadError = '1';
            if (window.Swal) {
                window.Swal.fire('Error', 'Failed to load trend for that period.', 'error');
            }
        }
    });

    /**
     * Re-render the volume chart + footer/severity stats from an AJAX payload.
     * @param {HTMLElement} section - the [data-error-volume] container
     * @param {Object} data - payload from /error-analytics/volume
     */
    function renderVolume(section, data) {
        const body = section.querySelector('[data-volume-body]');
        const badge = section.querySelector('[data-volume-badge]');
        const series = Array.isArray(data.volume_series) ? data.volume_series : [];
        const peak = Number(data.volume_peak) || 0;

        if (badge) badge.textContent = data.period || section.dataset.currentPeriod || '';

        // Footer + severity-panel stats (these live in the same page).
        const setText = (sel, val) => {
            const el = (sel.startsWith('[data-') ? document : section).querySelector(sel);
            if (el) el.textContent = val;
        };
        setText('[data-volume-total]', String(data.period_total ?? 0));
        setText('[data-volume-peak]', String(peak));

        const efEl = document.querySelector('[data-error-free]');
        if (efEl) {
            efEl.textContent = (data.error_free_pct === null || data.error_free_pct === undefined)
                ? 'n/a' : `${data.error_free_pct}%`;
        }
        const recEl = document.querySelector('[data-stat-recovery]');
        if (recEl) {
            recEl.textContent = (data.recovery_rate_pct === null || data.recovery_rate_pct === undefined)
                ? 'N/A' : `${data.recovery_rate_pct}%`;
        }

        // Top platform.
        const platEl = document.querySelector('[data-stat-platform]');
        if (platEl) {
            const plat = data.top_platform;
            if (!plat) {
                platEl.innerHTML = '<span class="text-gray-400 dark:text-gray-500 font-normal">n/a</span>';
            } else if (plat === 'iOS') {
                platEl.innerHTML = '<i class="ti ti-brand-apple" aria-hidden="true"></i> iOS';
            } else if (plat === 'Android') {
                platEl.innerHTML = '<i class="ti ti-brand-android" aria-hidden="true"></i> Android';
            } else {
                const safe = String(plat).replace(/[<>&"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', '"': '&quot;' }[c]));
                platEl.innerHTML = `<i class="ti ti-device-mobile" aria-hidden="true"></i> ${safe}`;
            }
        }

        // Critical trend.
        const trendEl = document.querySelector('[data-stat-trend]');
        if (trendEl) {
            const trend = data.critical_trend || 'flat';
            const delta = Number(data.critical_delta) || 0;
            trendEl.className = 'inline-flex items-center gap-1 font-semibold ' + (
                trend === 'up' ? 'text-red-600 dark:text-red-400'
                    : trend === 'down' ? 'text-green-600 dark:text-green-400'
                        : 'text-gray-500 dark:text-gray-400');
            const icon = trend === 'up' ? 'ti-trending-up' : trend === 'down' ? 'ti-trending-down' : 'ti-minus';
            const word = trend === 'up' ? 'Increasing' : trend === 'down' ? 'Decreasing' : 'Flat';
            const deltaStr = delta !== 0 ? ` <span class="font-mono text-xs">(${delta > 0 ? '+' : ''}${delta})</span>` : '';
            trendEl.innerHTML = `<i class="ti ${icon}" aria-hidden="true"></i> ${word}${deltaStr}`;
        }

        if (!body) return;

        // Empty state when no data for the period.
        if (!series.length || peak <= 0) {
            body.innerHTML = `
                <div class="text-center py-12">
                  <div class="flex items-center justify-center w-14 h-14 mx-auto rounded-full bg-gray-100 dark:bg-gray-700 mb-3">
                    <i class="ti ti-chart-line text-2xl text-gray-400 dark:text-gray-500"></i>
                  </div>
                  <p class="text-sm font-semibold text-gray-700 dark:text-gray-300">No volume data</p>
                  <p class="text-xs text-gray-500 dark:text-gray-400 mt-1">No errors recorded in this period to chart.</p>
                </div>`;
            return;
        }

        // Build SVG points (matches server-render math: y = 190 - (count/peak)*170).
        const n = series.length;
        const step = n > 1 ? (600 / (n - 1)) : 600;
        const pts = series.map((pt, i) => {
            const x = (i * step).toFixed(2);
            const y = (190 - ((Number(pt.count) || 0) / peak) * 170).toFixed(2);
            return `${x},${y}`;
        }).join(' ');

        const mid = Math.floor(n / 2);
        const labels = series.map((pt, i) => {
            const safe = String(pt.label || '').replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c]));
            const hide = (i === 0 || i === n - 1 || i === mid) ? '' : 'hidden sm:inline';
            return `<span class="${hide}">${safe}</span>`;
        }).join('');

        body.innerHTML = `
            <div class="relative h-52" role="img" aria-label="Mobile error volume, peak ${peak} errors in a bucket">
              <svg viewBox="0 0 600 200" preserveAspectRatio="none" class="w-full h-full">
                <defs>
                  <linearGradient id="errFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stop-color="rgb(245 158 11)" stop-opacity="0.30" />
                    <stop offset="100%" stop-color="rgb(245 158 11)" stop-opacity="0" />
                  </linearGradient>
                </defs>
                <line x1="0" y1="50" x2="600" y2="50" class="stroke-gray-200 dark:stroke-gray-700" stroke-width="1" />
                <line x1="0" y1="100" x2="600" y2="100" class="stroke-gray-200 dark:stroke-gray-700" stroke-width="1" />
                <line x1="0" y1="150" x2="600" y2="150" class="stroke-gray-200 dark:stroke-gray-700" stroke-width="1" />
                <polygon points="0,200 ${pts} 600,200" fill="url(#errFill)" />
                <polyline points="${pts}" fill="none" stroke="rgb(245 158 11)" stroke-width="2.5" vector-effect="non-scaling-stroke" stroke-linejoin="round" stroke-linecap="round" />
              </svg>
              <div class="absolute inset-x-0 bottom-0 flex justify-between text-[10px] text-gray-400 dark:text-gray-500 font-mono px-1">${labels}</div>
            </div>
            <div class="grid grid-cols-3 divide-x divide-gray-200 dark:divide-gray-700 border-t border-gray-200 dark:border-gray-700 text-center mt-4">
              <div class="px-3 py-3">
                <p class="text-[11px] uppercase tracking-wide text-gray-500 dark:text-gray-400">This Period</p>
                <p class="mt-0.5 font-mono text-lg font-bold text-amber-600 dark:text-amber-400" data-volume-total>${data.period_total ?? 0}</p>
              </div>
              <div class="px-3 py-3">
                <p class="text-[11px] uppercase tracking-wide text-gray-500 dark:text-gray-400">Peak</p>
                <p class="mt-0.5 font-mono text-lg font-bold text-gray-900 dark:text-white" data-volume-peak>${peak}</p>
              </div>
              <div class="px-3 py-3">
                <p class="text-[11px] uppercase tracking-wide text-gray-500 dark:text-gray-400" title="Share of mobile log lines not at ERROR/FATAL level">Error-Free Logs</p>
                <p class="mt-0.5 font-mono text-lg font-bold text-gray-900 dark:text-white" data-error-free>${(data.error_free_pct === null || data.error_free_pct === undefined) ? 'n/a' : data.error_free_pct + '%'}</p>
              </div>
            </div>`;
    }

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
                            <span class="px-2 py-0.5 text-xs font-medium rounded ${data.severity === 'critical' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300' : data.severity === 'error' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300' : 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300'}" data-badge>${data.severity}</span>
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
