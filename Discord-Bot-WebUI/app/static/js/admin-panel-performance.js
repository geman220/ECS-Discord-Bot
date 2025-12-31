/**
 * ============================================================================
 * PERFORMANCE MONITORING PAGE - JAVASCRIPT
 * ============================================================================
 *
 * Handles performance monitoring charts and real-time updates
 * Uses Chart.js for visualizations and event delegation for interactions
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks
 * - No inline event handlers
 * - State-driven styling with classList
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';

let autoRefresh = true;
let refreshInterval;
let queryPerformanceChart;
let cacheUsageChart;
let _initialized = false;

/**
 * Initialize on DOM load
 */
function init() {
    // Guard against duplicate initialization
    if (_initialized) return;
    _initialized = true;

    // Page guard: only run on performance monitoring pages
    const isPerfPage = document.querySelector('[data-page="admin-performance"]') ||
                       document.querySelector('.admin-performance') ||
                       window.location.pathname.includes('performance');

    if (!isPerfPage) {
        return;
    }

    initializeCharts();
    registerEventHandlers();
    startAutoRefresh();
}

/**
 * Initialize Chart.js visualizations
 */
function initializeCharts() {
    // Get data from hidden data element
    const perfData = document.querySelector('[data-perf-data]');
    if (!perfData) return;

    const avgQueryTime = parseFloat(perfData.dataset.dbAvgQueryTime || 0);
    const cacheActive = parseInt(perfData.dataset.cacheActive || 0);
    const cacheExpired = parseInt(perfData.dataset.cacheExpired || 0);

    // Query Performance Chart
    const queryCtx = document.querySelector('[data-chart="query-performance"]');
    if (queryCtx) {
        queryPerformanceChart = new window.Chart(queryCtx.getContext('2d'), {
            type: 'line',
            data: {
                labels: ['5min ago', '4min ago', '3min ago', '2min ago', '1min ago', 'Now'],
                datasets: [{
                    label: 'Avg Query Time (ms)',
                    data: [
                        avgQueryTime * 1000,
                        avgQueryTime * 1000 * 0.9,
                        avgQueryTime * 1000 * 1.1,
                        avgQueryTime * 1000 * 0.8,
                        avgQueryTime * 1000 * 1.2,
                        avgQueryTime * 1000
                    ],
                    borderColor: getCSSVariable('--color-primary') || '#0d6efd',
                    backgroundColor: 'rgba(13, 110, 253, 0.1)',
                    tension: 0.4,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Time (ms)'
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    }
                }
            }
        });
    }

    // Cache Usage Chart
    const cacheCtx = document.querySelector('[data-chart="cache-usage"]');
    if (cacheCtx) {
        cacheUsageChart = new window.Chart(cacheCtx.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: ['Active', 'Expired'],
                datasets: [{
                    data: [cacheActive, cacheExpired],
                    backgroundColor: [
                        getCSSVariable('--color-success') || '#198754',
                        getCSSVariable('--color-danger') || '#dc3545'
                    ],
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom'
                    }
                }
            }
        });
    }
}

/**
 * Register event handlers - now a no-op, handlers registered at module scope
 */
function registerEventHandlers() {
    // Handlers are now registered at module scope for proper timing
    // See bottom of file for EventDelegation.register() calls
}

/**
 * Handle auto-refresh toggle
 */
function handleToggleAutoRefresh() {
    autoRefresh = !autoRefresh;
    const statusSpan = document.querySelector('[data-status="auto-refresh"]');

    if (autoRefresh) {
        if (statusSpan) statusSpan.textContent = 'ON';
        startAutoRefresh();
    } else {
        if (statusSpan) statusSpan.textContent = 'OFF';
        clearInterval(refreshInterval);
    }
}

/**
 * Handle cache clear with confirmation
 */
function handleClearCache(e) {
    const confirmed = confirm('Are you sure you want to clear all cache?');
    if (!confirmed) {
        e.preventDefault();
        return false;
    }
}

/**
 * Start auto-refresh interval
 */
function startAutoRefresh() {
    // Clear any existing interval
    if (refreshInterval) {
        clearInterval(refreshInterval);
    }

    // Update every 30 seconds
    refreshInterval = setInterval(updateMetrics, 30000);
}

/**
 * Update real-time metrics from server
 */
function updateMetrics() {
    if (!autoRefresh) return;

    fetch('/admin_panel/performance/api/metrics')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const report = data.data;

                // Update live metrics
                updateLiveValue('query-time', (report.database.avg_query_time * 1000).toFixed(1) + 'ms');
                updateLiveValue('slow-queries', report.database.slow_queries);
                updateLiveValue('cache-hits', report.cache.active_entries);
                updateLiveValue('cache-size', report.cache.cache_size_mb.toFixed(1) + 'MB');

                // Update timestamp
                const timestampEl = document.querySelector('[data-timestamp]');
                if (timestampEl) {
                    timestampEl.textContent = new Date(report.timestamp).toLocaleString();
                }

                // Update colors based on thresholds
                updateMetricColors(report);

                // Update charts if they exist
                if (queryPerformanceChart) {
                    updateQueryChart(report.database.avg_query_time * 1000);
                }

                if (cacheUsageChart) {
                    updateCacheChart(report.cache.active_entries, report.cache.expired_entries);
                }
            }
        })
        .catch(error => {
            console.error('Error updating metrics:', error);
        });
}

/**
 * Update a live value element
 */
function updateLiveValue(metric, value) {
    const element = document.querySelector(`[data-live-value="${metric}"]`);
    if (element) {
        element.textContent = value;
    }
}

/**
 * Update metric colors based on thresholds
 */
function updateMetricColors(report) {
    const slowQueriesEl = document.querySelector('[data-live-value="slow-queries"]');
    if (slowQueriesEl) {
        slowQueriesEl.className = 'c-perf-realtime__value';
        if (report.database.slow_queries > 5) {
            slowQueriesEl.classList.add('c-perf-realtime__value--danger');
        } else if (report.database.slow_queries > 2) {
            slowQueriesEl.classList.add('c-perf-realtime__value--warning');
        } else {
            slowQueriesEl.classList.add('c-perf-realtime__value--success');
        }
    }

    const cacheSizeEl = document.querySelector('[data-live-value="cache-size"]');
    if (cacheSizeEl) {
        cacheSizeEl.className = 'c-perf-realtime__value';
        if (report.cache.cache_size_mb > 50) {
            cacheSizeEl.classList.add('c-perf-realtime__value--warning');
        } else {
            cacheSizeEl.classList.add('c-perf-realtime__value--secondary');
        }
    }
}

/**
 * Update query performance chart
 */
function updateQueryChart(newValue) {
    if (!queryPerformanceChart) return;

    const data = queryPerformanceChart.data.datasets[0].data;
    data.shift(); // Remove first element
    data.push(newValue); // Add new value

    queryPerformanceChart.update();
}

/**
 * Update cache usage chart
 */
function updateCacheChart(active, expired) {
    if (!cacheUsageChart) return;

    cacheUsageChart.data.datasets[0].data = [active, expired];
    cacheUsageChart.update();
}

/**
 * Get CSS variable value
 */
function getCSSVariable(varName) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(varName);
    return value ? value.trim() : null;
}

// ============================================================================
// EVENT DELEGATION - Registered at module scope
// ============================================================================

EventDelegation.register('toggle-auto-refresh', handleToggleAutoRefresh, { preventDefault: true });
EventDelegation.register('clear-cache', handleClearCache, { preventDefault: true });

// Register with InitSystem
InitSystem.register('admin-panel-performance', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin panel performance monitoring'
});

// Fallback
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Backward compatibility exports
window.init = init;
window.initializeCharts = initializeCharts;
window.registerEventHandlers = registerEventHandlers;
window.handleToggleAutoRefresh = handleToggleAutoRefresh;
window.handleClearCache = handleClearCache;
window.startAutoRefresh = startAutoRefresh;
window.updateMetrics = updateMetrics;
window.updateLiveValue = updateLiveValue;
window.updateMetricColors = updateMetricColors;
window.updateQueryChart = updateQueryChart;
window.updateCacheChart = updateCacheChart;
window.getCSSVariable = getCSSVariable;

// Named exports for ES modules
export {
    init,
    initializeCharts,
    registerEventHandlers,
    handleToggleAutoRefresh,
    handleClearCache,
    startAutoRefresh,
    updateMetrics,
    updateLiveValue,
    updateMetricColors,
    updateQueryChart,
    updateCacheChart,
    getCSSVariable
};
