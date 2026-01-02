/**
 * User Analytics Module
 * Extracted from admin_panel/users/analytics.html
 * Handles chart initialization, data export, and analytics functionality
 */

// Initialize when DOM is ready or via InitSystem
(function() {
    'use strict';

    // Register with InitSystem if available
    if (typeof InitSystem !== 'undefined') {
        InitSystem.register('userAnalytics', initUserAnalytics, {
            requires: [],
            priority: 10
        });
    } else {
        document.addEventListener('DOMContentLoaded', initUserAnalytics);
    }

    // Store chart instances for cleanup
    let registrationTrendsChart = null;
    let approvalStatusChart = null;

    /**
     * Initialize User Analytics functionality
     */
    function initUserAnalytics() {
        // Check if we're on the analytics page
        const analyticsPage = document.getElementById('registrationTrendsChart');
        if (!analyticsPage) return;

        initializeCharts();
        applyProgressBarWidths();
        setupTrendPeriodSelection();
        setupAutoRefresh();

        console.log('[UserAnalytics] Initialized');
    }

    /**
     * Apply dynamic progress bar widths from data attributes
     */
    function applyProgressBarWidths() {
        document.querySelectorAll('[data-width-percent]').forEach(bar => {
            const width = bar.getAttribute('data-width-percent');
            bar.style.width = width + '%';
        });
    }

    /**
     * Initialize all charts
     */
    function initializeCharts() {
        initializeRegistrationTrendsChart();
        initializeApprovalStatusChart();
    }

    /**
     * Initialize Registration Trends Chart
     */
    function initializeRegistrationTrendsChart() {
        const ctx = document.getElementById('registrationTrendsChart');
        if (!ctx) return;

        // Get trends data from global variable or data attribute
        const trendsData = window.analyticsRegistrationTrends || [];

        const labels = trendsData.map(item => item.month);
        const data = trendsData.map(item => item.count);

        registrationTrendsChart = new Chart(ctx.getContext('2d'), {
            type: 'line',
            data: {
                labels: labels,
                datasets: [{
                    label: 'New Registrations',
                    data: data,
                    borderColor: '#007bff',
                    backgroundColor: 'rgba(0, 123, 255, 0.1)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.4
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: false
                    }
                },
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            stepSize: 1
                        }
                    }
                }
            }
        });
    }

    /**
     * Initialize Approval Status Chart
     */
    function initializeApprovalStatusChart() {
        const ctx = document.getElementById('approvalStatusChart');
        if (!ctx) return;

        // Get approvals data from global variable or data attribute
        const approvalData = window.analyticsApprovalsData || { approved: 0, pending: 0, denied: 0 };

        approvalStatusChart = new Chart(ctx.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: ['Approved', 'Pending', 'Denied'],
                datasets: [{
                    data: [approvalData.approved, approvalData.pending, approvalData.denied],
                    backgroundColor: ['#28a745', '#ffc107', '#dc3545'],
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            padding: 20,
                            usePointStyle: true
                        }
                    }
                }
            }
        });
    }

    /**
     * Export analytics data
     * @param {string} type - The type of export (users, roles, activity, leagues, comprehensive)
     * @param {string} format - The format of export (csv, json, pdf)
     */
    function exportAnalytics(type, format) {
        // Show loading
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Exporting Analytics',
                text: 'Preparing your export...',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                }
            });
        }

        fetch('/admin-panel/users/analytics/export', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                type: type,
                format: format,
                date_range: '30_days'
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof Swal !== 'undefined') {
                    Swal.fire({
                        title: 'Export Ready',
                        text: 'Your analytics export is ready for download.',
                        icon: 'success',
                        showCancelButton: true,
                        confirmButtonText: 'Download',
                        cancelButtonText: 'Close'
                    }).then((result) => {
                        if (result.isConfirmed) {
                            window.open(data.download_url, '_blank');
                        }
                    });
                } else {
                    window.open(data.download_url, '_blank');
                }
            } else {
                if (typeof Swal !== 'undefined') {
                    Swal.fire('Error', data.message || 'Export failed', 'error');
                } else {
                    alert('Error: ' + (data.message || 'Export failed'));
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof Swal !== 'undefined') {
                Swal.fire('Error', 'Could not export analytics data', 'error');
            } else {
                alert('Could not export analytics data');
            }
        });
    }

    /**
     * Export role data
     */
    function exportRoleData() {
        exportAnalytics('roles', 'csv');
    }

    /**
     * Export league data
     */
    function exportLeagueData() {
        exportAnalytics('leagues', 'csv');
    }

    /**
     * Generate comprehensive report
     */
    function generateReport() {
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Generate Comprehensive Report',
                text: 'This will generate a detailed analytics report including all metrics.',
                icon: 'info',
                showCancelButton: true,
                confirmButtonText: 'Generate Report'
            }).then((result) => {
                if (result.isConfirmed) {
                    exportAnalytics('comprehensive', 'pdf');
                }
            });
        } else {
            if (confirm('Generate a comprehensive analytics report?')) {
                exportAnalytics('comprehensive', 'pdf');
            }
        }
    }

    /**
     * Setup trend period radio button selection
     */
    function setupTrendPeriodSelection() {
        document.querySelectorAll('input[name="trendPeriod"]').forEach(radio => {
            radio.addEventListener('change', function() {
                // In a full implementation, this would update the chart with new data
                console.log('[UserAnalytics] Trend period changed to:', this.id);
            });
        });
    }

    /**
     * Setup auto-refresh for analytics data
     */
    function setupAutoRefresh() {
        // Auto-refresh analytics every 5 minutes
        setInterval(() => {
            console.log('[UserAnalytics] Auto-refreshing analytics data...');
            // In a full implementation, this would refresh key metrics
        }, 300000); // 5 minutes
    }

    /**
     * Cleanup function to destroy charts
     */
    function cleanup() {
        if (registrationTrendsChart) {
            registrationTrendsChart.destroy();
            registrationTrendsChart = null;
        }
        if (approvalStatusChart) {
            approvalStatusChart.destroy();
            approvalStatusChart = null;
        }
    }

    // Note: EventDelegation handlers are registered in:
    // - admin-panel-dashboard.js: generate-report
    // - mobile-features-handlers.js: export-analytics
    // This file exposes functions globally for those handlers to use
    if (typeof EventDelegation !== 'undefined') {
        EventDelegation.register('export-role-data', exportRoleData);
        EventDelegation.register('export-league-data', exportLeagueData);
    }

    // Expose functions globally for backward compatibility
    window.UserAnalytics = {
        init: initUserAnalytics,
        exportAnalytics: exportAnalytics,
        exportRoleData: exportRoleData,
        exportLeagueData: exportLeagueData,
        generateReport: generateReport,
        cleanup: cleanup
    };
})();
