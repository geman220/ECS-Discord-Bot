/**
 * Match Reports - Event Handler and Chart Initialization
 * Handles all report generation and export actions
 */

// Initialize charts and event handlers when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    initializeCharts();
    initializeEventHandlers();
});

/**
 * Initialize Chart.js charts
 */
function initializeCharts() {
    const matchStatusCtx = document.getElementById('matchStatusChart');
    const matchesPerWeekCtx = document.getElementById('matchesPerWeekChart');

    if (matchStatusCtx) {
        new Chart(matchStatusCtx.getContext('2d'), {
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
        new Chart(matchesPerWeekCtx.getContext('2d'), {
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
 * Initialize all event handlers using event delegation
 */
function initializeEventHandlers() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;
        const matchId = target.dataset.matchId;
        const teamId = target.dataset.teamId;

        // Route to appropriate handler
        const handlers = {
            'generate-match-report': () => generateMatchReport(matchId),
            'generate-league-report': generateLeagueReport,
            'generate-team-report': () => generateTeamReport(teamId),
            'generate-custom-report': generateCustomReport,
            'view-recent-matches': viewRecentMatches,
            'view-upcoming-matches': viewUpcomingMatches,
            'view-top-scorers': viewTopScorers,
            'view-league-standings': viewLeagueStandings,
            'export-pdf': exportPDF,
            'export-excel': exportExcel,
            'export-csv': exportCSV,
            'schedule-report': scheduleReport,
            'view-match-report': () => viewMatchReport(matchId),
            'view-team-report': () => viewTeamReport(teamId),
            'view-all-matches': viewAllMatches
        };

        const handler = handlers[action];
        if (handler) {
            handler();
        }
    });
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
