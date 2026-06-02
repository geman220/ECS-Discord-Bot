/**
 * Match Reports - Event Handler and window.Chart Initialization
 * Handles all report generation and export actions
 */
'use strict';

import { InitSystem } from '../init-system.js';
import { EventDelegation } from '../event-delegation/core.js';

let _initialized = false;
/**
 * Initialize window.Chart.js charts
 */
export function initializeCharts() {
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
        // Real per-week match counts are fetched from the backend; the chart is
        // only created once the data arrives so no placeholder/fake series is shown.
        fetch('/admin-panel/match-operations/reports/matches-per-week', {
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin'
        })
            .then(function(resp) { return resp.ok ? resp.json() : null; })
            .then(function(data) {
                if (!data || !data.success || !Array.isArray(data.labels) || data.labels.length === 0) {
                    return;
                }
                new window.Chart(matchesPerWeekCtx.getContext('2d'), {
                    type: 'line',
                    data: {
                        labels: data.labels,
                        datasets: [{
                            label: 'Matches Played',
                            data: data.counts,
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
            })
            .catch(function() { /* No real data available; leave the canvas empty. */ });
    }
}

/**
 * Report generation functions — each downloads a real CSV from the
 * match_operations report-export routes. Match Summary exports the full match
 * results set (matchId is not a backend filter; the per-match view button uses
 * viewMatchReport instead), League exports the Standings model, Team exports a
 * single team's stats + roster.
 */
export function generateMatchReport(matchId = null) {
    window.location.href = '/admin-panel/match-operations/reports/export/matches';
}

export function generateLeagueReport() {
    window.location.href = '/admin-panel/match-operations/reports/export/standings';
}

export function generateTeamReport(teamId = null) {
    if (!teamId) return;
    window.location.href = '/admin-panel/match-operations/reports/export/team?team_id=' + encodeURIComponent(teamId);
}

// "Custom Report" has no full report-builder UI/backend (no column picker, no
// saved filters), so it is wired to the same real match-results CSV export as
// Match Summary rather than faking a builder. The export route accepts optional
// season_id/league_id params if a future filter UI wants to pass them.
export function generateCustomReport() {
    window.location.href = '/admin-panel/match-operations/reports/export/matches';
}

/**
 * Quick report views
 */
export function viewRecentMatches() {
    // Real route: admin_panel.view_matches (filtered to already-played matches).
    window.location.href = '/admin-panel/match-operations/matches?status=past';
}

export function viewUpcomingMatches() {
    // Real route: admin_panel.upcoming_matches
    window.location.href = '/admin-panel/match-operations/upcoming';
}

export function viewTopScorers() {
    // No top-scorers route/data source exists; route to standings (the closest
    // real ranking view) rather than dead-ending. The Quick View button itself
    // is removed in the template, so this is only a backward-compat shim.
    window.location.href = '/admin-panel/match-operations/standings';
}

export function viewLeagueStandings() {
    // Real route: admin_panel.league_standings
    window.location.href = '/admin-panel/match-operations/standings';
}

// There is no reusable Celery task for emailing reports on a schedule, so rather
// than fake a scheduled-email success this handler honestly tells the user the
// feature is not available and points them at the immediate CSV download. (The
// template button cannot be removed from here; this keeps the click honest.)
export function scheduleReport() {
    const message = 'Scheduled report delivery is not available. Use Generate Report to download the data as CSV now.';
    if (window.Swal && window.Swal.fire) {
        window.Swal.fire({
            icon: 'info',
            title: 'Not available',
            text: message
        });
    } else {
        window.alert(message);
    }
}

/**
 * Individual item views
 */
export function viewMatchReport(matchId) {
    // Real route: teams.report_match (full match report form/page).
    window.location.href = `/teams/report_match/${matchId}`;
}

export function viewTeamReport(teamId) {
    // Real route: teams.team_details (per-team page with stats/standings).
    window.location.href = `/teams/${teamId}`;
}

export function viewAllMatches() {
    // Real route: admin_panel.view_matches
    window.location.href = '/admin-panel/match-operations/matches';
}

/**
 * Initialize module
 */
export function initMatchReports() {
    if (_initialized) return;

    // Page guard - only run on match reports page
    const isMatchReportsPage = document.getElementById('matchStatusChart') ||
        document.getElementById('matchesPerWeekChart') ||
        document.querySelector('[data-action^="generate-"][data-action*="report"]') ||
        document.querySelector('[data-action^="export-"]');

    if (!isMatchReportsPage) return;

    _initialized = true;

    initializeCharts();
    registerEventHandlers();
}

/**
 * Register event delegation handlers
 */
export function registerEventHandlers() {
    if (typeof window.EventDelegation === 'undefined') return;

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

    // Export Actions removed: no report-export backend route exists (the old
    // window.open('/admin/match-operations/reports/export?...') target 404s), so
    // the export buttons were removed from the template rather than shipping a
    // dead/404 action. Re-add export-report-pdf/excel/csv handlers here once a
    // real export endpoint exists.

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
}

// Register with window.InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('match-reports', initMatchReports, {
        priority: 30,
        reinitializable: false,
        description: 'Match reports page with charts'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.initializeCharts = initializeCharts;
window.generateMatchReport = generateMatchReport;
window.viewRecentMatches = viewRecentMatches;
window.viewMatchReport = viewMatchReport;
