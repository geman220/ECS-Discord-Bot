/**
 * Match Reports - Event Handler and Chart Initialization
 * Handles all report generation and export actions
 */

(function() {
    'use strict';

    // Page guard - only run on match reports page
    const isMatchReportsPage = document.getElementById('matchStatusChart') ||
                                document.getElementById('matchesPerWeekChart') ||
                                document.querySelector('[data-action^="generate-"][data-action*="report"]') ||
                                document.querySelector('[data-action^="export-"]');

    if (!isMatchReportsPage) return;

    // Initialize charts and event handlers when DOM is loaded
    document.addEventListener('DOMContentLoaded', function() {
        initializeCharts();
    });

    /**
     * Initialize Chart.js charts
     */
    function initializeCharts() {
        const matchStatusCtx = document.getElementById('matchStatusChart');
        const matchesPerWeekCtx = document.getElementById('matchesPerWeekChart');

        if (matchStatusCtx) {
            new window.Chart(matchStatusCtx.getContext('2d'), {
                type: 'doughnut',
                data: {
                    labels: ['Completed', 'Upcoming', 'Live', 'Cancelled'],
                    datasets: [{
                        data: [
                            parseInt(matchStatusCtx.dataset.completed || 0),
                            parseInt(matchStatusCtx.dataset.pending || 0),
                            parseInt(matchStatusCtx.dataset.live || 0),
                            parseInt(matchStatusCtx.dataset.cancelled || 0)
                        ],
                        backgroundColor: [
                            getComputedStyle(document.documentElement).getPropertyValue('--color-success') || '#28a745',
                            getComputedStyle(document.documentElement).getPropertyValue('--color-warning') || '#ffc107',
                            getComputedStyle(document.documentElement).getPropertyValue('--color-primary') || '#007bff',
                            getComputedStyle(document.documentElement).getPropertyValue('--color-danger') || '#dc3545'
                        ]
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

        if (matchesPerWeekCtx) {
            new window.Chart(matchesPerWeekCtx.getContext('2d'), {
                type: 'line',
                data: {
                    labels: ['Week 1', 'Week 2', 'Week 3', 'Week 4', 'Week 5', 'Week 6'],
                    datasets: [{
                        label: 'Matches Played',
                        data: [12, 19, 3, 5, 2, 15],
                        borderColor: getComputedStyle(document.documentElement).getPropertyValue('--color-primary') || '#007bff',
                        backgroundColor: 'rgba(0, 123, 255, 0.1)',
                        tension: 0.4
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        }
    }

    /**
     * Report generation functions
     */
    function generateMatchReport(matchId = null) {
        console.log('Generate match report:', matchId);
        // Implementation from original file
    }

    function generateLeagueReport() {
        console.log('Generate league report');
        // Implementation from original file
    }

    function generateTeamReport(teamId = null) {
        console.log('Generate team report:', teamId);
        // Implementation from original file
    }

    function generateCustomReport() {
        console.log('Generate custom report');
        // Implementation from original file
    }

    /**
     * Quick report views
     */
    function viewRecentMatches() {
        window.location.href = '/admin-panel/matches/recent';
    }

    function viewUpcomingMatches() {
        window.location.href = '/admin-panel/matches/upcoming';
    }

    function viewTopScorers() {
        console.log('View top scorers');
    }

    function viewLeagueStandings() {
        window.location.href = '/admin-panel/match-operations/league-standings';
    }

    /**
     * Export functions
     */
    function exportPDF() {
        window.open('/admin/match-operations/reports/export?format=pdf', '_blank');
    }

    function exportExcel() {
        window.open('/admin/match-operations/reports/export?format=excel', '_blank');
    }

    function exportCSV() {
        window.open('/admin/match-operations/reports/export?format=csv', '_blank');
    }

    function scheduleReport() {
        console.log('Schedule report');
    }

    /**
     * Individual item views
     */
    function viewMatchReport(matchId) {
        window.location.href = `/admin/match-operations/match/${matchId}/report`;
    }

    function viewTeamReport(teamId) {
        window.location.href = `/admin/match-operations/team/${teamId}/report`;
    }

    function viewAllMatches() {
        window.location.href = '/admin-panel/matches';
    }

    // ========================================================================
    // EVENT DELEGATION REGISTRATIONS - Module scope
    // ========================================================================

    // Report Generation Actions
    window.EventDelegation.register('generate-match-report', function(element, e) {
        const matchId = element.dataset.matchId;
        generateMatchReport(matchId);
    }, { preventDefault: true });

    window.EventDelegation.register('generate-league-report', function(element, e) {
        generateLeagueReport();
    }, { preventDefault: true });

    window.EventDelegation.register('generate-team-report', function(element, e) {
        const teamId = element.dataset.teamId;
        generateTeamReport(teamId);
    }, { preventDefault: true });

    window.EventDelegation.register('generate-custom-report', function(element, e) {
        generateCustomReport();
    }, { preventDefault: true });

    // Quick View Actions
    window.EventDelegation.register('view-recent-matches', function(element, e) {
        viewRecentMatches();
    }, { preventDefault: true });

    window.EventDelegation.register('view-upcoming-matches', function(element, e) {
        viewUpcomingMatches();
    }, { preventDefault: true });

    window.EventDelegation.register('view-top-scorers', function(element, e) {
        viewTopScorers();
    }, { preventDefault: true });

    window.EventDelegation.register('view-league-standings', function(element, e) {
        viewLeagueStandings();
    }, { preventDefault: true });

    // Export Actions
    window.EventDelegation.register('export-pdf', function(element, e) {
        exportPDF();
    }, { preventDefault: true });

    window.EventDelegation.register('export-excel', function(element, e) {
        exportExcel();
    }, { preventDefault: true });

    window.EventDelegation.register('export-csv', function(element, e) {
        exportCSV();
    }, { preventDefault: true });

    window.EventDelegation.register('schedule-report', function(element, e) {
        scheduleReport();
    }, { preventDefault: true });

    // Individual Report View Actions
    window.EventDelegation.register('view-match-report', function(element, e) {
        const matchId = element.dataset.matchId;
        viewMatchReport(matchId);
    }, { preventDefault: true });

    window.EventDelegation.register('view-team-report', function(element, e) {
        const teamId = element.dataset.teamId;
        viewTeamReport(teamId);
    }, { preventDefault: true });

    window.EventDelegation.register('view-all-matches', function(element, e) {
        viewAllMatches();
    }, { preventDefault: true });

})();
