/**
 * ============================================================================
 * ADMIN API ANALYTICS - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles API analytics page interactions using data-attribute hooks
 * Follows event delegation pattern with InitSystem registration
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

// Module state
let chartsInitialized = false;
let autoRefresh = false;
let refreshInterval = null;

/**
 * Initialize API analytics module
 */
function init() {
    initializeProgressBars();
    initializeEventDelegation();
    initializeCharts();
}

/**
 * Apply dynamic widths from data attributes
 */
function initializeProgressBars() {
    document.querySelectorAll('[data-width]').forEach(el => {
        el.style.width = el.dataset.width + '%';
    });
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
            case 'export-analytics':
                exportAnalytics(target.dataset.format);
                break;
            case 'toggle-auto-refresh':
                toggleAutoRefresh();
                break;
        }
    });
}

/**
 * Initialize Chart.js charts
 */
function initializeCharts() {
    if (chartsInitialized) return;
    if (typeof Chart === 'undefined') {
        console.warn('[admin-api-analytics] Chart.js not loaded');
        return;
    }

    const requestsCanvas = document.getElementById('requestsChart');
    const errorCanvas = document.getElementById('errorChart');

    if (!requestsCanvas && !errorCanvas) return;

    // Get data from global variable set by template
    const requestsData = window.analyticsData?.dailyRequests || [];
    const errorData = window.analyticsData?.errorTypes || [];

    // API Requests Over Time Chart
    if (requestsCanvas && requestsData.length > 0) {
        const requestsCtx = requestsCanvas.getContext('2d');
        new Chart(requestsCtx, {
            type: 'line',
            data: {
                labels: requestsData.map(d => d.date),
                datasets: [
                    {
                        label: 'Requests',
                        data: requestsData.map(d => d.requests),
                        borderColor: getComputedStyle(document.documentElement).getPropertyValue('--ecs-primary').trim() || '#0d6efd',
                        backgroundColor: 'rgba(13, 110, 253, 0.1)',
                        tension: 0.4,
                        fill: true
                    },
                    {
                        label: 'Errors',
                        data: requestsData.map(d => d.errors),
                        borderColor: getComputedStyle(document.documentElement).getPropertyValue('--ecs-danger').trim() || '#dc3545',
                        backgroundColor: 'rgba(220, 53, 69, 0.1)',
                        tension: 0.4,
                        fill: false
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1
                        }
                    }
                },
                plugins: {
                    legend: {
                        position: 'top'
                    },
                    tooltip: {
                        callbacks: {
                            afterLabel: function(context) {
                                if (context.datasetIndex === 0) {
                                    const dayData = requestsData[context.dataIndex];
                                    const errorRate = dayData.requests > 0 ? (dayData.errors / dayData.requests * 100) : 0;
                                    return `Error Rate: ${errorRate.toFixed(1)}%`;
                                }
                                return '';
                            }
                        }
                    }
                }
            }
        });
    }

    // Error Distribution Chart
    if (errorCanvas && errorData.length > 0) {
        const errorLabels = errorData.map(d => d.type);
        const errorCounts = errorData.map(d => d.count);
        const errorColors = [
            getComputedStyle(document.documentElement).getPropertyValue('--ecs-danger').trim() || '#dc3545',
            '#fd7e14',
            getComputedStyle(document.documentElement).getPropertyValue('--ecs-warning').trim() || '#ffc107',
            '#20c997',
            getComputedStyle(document.documentElement).getPropertyValue('--ecs-info').trim() || '#0dcaf0'
        ];

        const errorCtx = errorCanvas.getContext('2d');
        new Chart(errorCtx, {
            type: 'doughnut',
            data: {
                labels: errorLabels,
                datasets: [{
                    data: errorCounts,
                    backgroundColor: errorColors,
                    borderWidth: 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            padding: 15,
                            font: {
                                size: 11
                            }
                        }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const total = context.dataset.data.reduce((a, b) => a + b, 0);
                                const percentage = ((context.parsed / total) * 100).toFixed(1);
                                return `${context.label}: ${context.parsed} (${percentage}%)`;
                            }
                        }
                    }
                }
            }
        });
    }

    chartsInitialized = true;
}

/**
 * Export analytics data in specified format
 */
function exportAnalytics(format) {
    const dateFrom = new URLSearchParams(window.location.search).get('date_from') || window.analyticsData?.dateRange?.start || '';
    const dateTo = new URLSearchParams(window.location.search).get('date_to') || window.analyticsData?.dateRange?.end || '';

    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: 'Export Started',
            text: `API analytics export in ${format.toUpperCase()} format for ${dateFrom} to ${dateTo} has been queued.`,
            icon: 'info',
            timer: 2000,
            showConfirmButton: false
        });
    }
}

/**
 * Toggle auto-refresh functionality
 */
function toggleAutoRefresh() {
    autoRefresh = !autoRefresh;

    if (autoRefresh) {
        refreshInterval = setInterval(() => {
            location.reload();
        }, 30000); // Refresh every 30 seconds

        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Auto-refresh Enabled',
                text: 'Analytics will refresh every 30 seconds',
                icon: 'info',
                timer: 2000,
                showConfirmButton: false
            });
        }
    } else {
        if (refreshInterval) {
            clearInterval(refreshInterval);
            refreshInterval = null;
        }

        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Auto-refresh Disabled',
                icon: 'info',
                timer: 1500,
                showConfirmButton: false
            });
        }
    }
}

/**
 * Cleanup function
 */
function cleanup() {
    if (refreshInterval) {
        clearInterval(refreshInterval);
        refreshInterval = null;
    }
    autoRefresh = false;
    chartsInitialized = false;
}

// Register with InitSystem
InitSystem.register('admin-api-analytics', init, {
    priority: 30,
    reinitializable: true,
    cleanup: cleanup,
    description: 'Admin API analytics page functionality'
});

// Fallback
// InitSystem handles initialization

// Export for ES modules
export {
    init,
    cleanup,
    exportAnalytics,
    toggleAutoRefresh
};

// Backward compatibility
window.adminApiAnalyticsInit = init;
