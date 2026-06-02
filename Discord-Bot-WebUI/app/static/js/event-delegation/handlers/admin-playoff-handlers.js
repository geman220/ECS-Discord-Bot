'use strict';

/**
 * Admin Playoff Handlers
 *
 * Event delegation handlers for admin panel playoff management:
 * - playoff_management.html
 *
 * @version 1.1.0
 */

import { EventDelegation } from '../core.js';

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Prompt user to select a league and navigate to the playoff page
 * @param {string} page - Page type: 'manage', 'generator', 'bracket'
 * @param {string} title - Dialog title
 */
async function promptForLeagueAndNavigate(page, title) {
    if (typeof window.Swal === 'undefined') {
        console.error('[promptForLeagueAndNavigate] SweetAlert2 not available');
        return;
    }

    // Try to get leagues from the page or fetch them
    let leagues = window.PLAYOFF_CONFIG?.leagues || [];

    if (leagues.length === 0) {
        // Fetch real leagues from the admin-panel leagues endpoint.
        // Returns {success: true, leagues: [{id, name, team_count}]}.
        try {
            const response = await fetch('/admin-panel/api/push/leagues');
            if (response.ok) {
                const data = await response.json();
                if (data.success && Array.isArray(data.leagues)) {
                    leagues = data.leagues;
                }
            }
        } catch (error) {
            console.error('[promptForLeagueAndNavigate] Error fetching leagues:', error);
        }
    }

    if (leagues.length === 0) {
        // No real leagues available - surface the error rather than fabricating IDs.
        await window.Swal.fire({
            title: 'No Leagues Available',
            text: 'Could not load any leagues. Please ensure a current season with leagues exists, then try again.',
            icon: 'error'
        });
        return;
    }

    const leagueOptions = leagues.map(l => `<option value="${l.id}">${l.name}</option>`).join('');

    const { value: leagueId } = await window.Swal.fire({
        title: title,
        html: `
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Select League</label>
                <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="leagueSelect" data-form-select>
                    <option value="">Choose a league...</option>
                    ${leagueOptions}
                </select>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Continue',
        cancelButtonText: 'Cancel',
        preConfirm: () => {
            const selected = document.getElementById('leagueSelect').value;
            if (!selected) {
                window.Swal.showValidationMessage('Please select a league');
                return false;
            }
            return selected;
        }
    });

    if (leagueId) {
        const urls = {
            'manage': `/playoffs/league/${leagueId}/manage`,
            'generator': `/playoffs/league/${leagueId}/generator`,
            'bracket': `/playoffs/league/${leagueId}/bracket`
        };
        window.location.href = urls[page] || urls['manage'];
    }
}

// ============================================================================
// PLAYOFF NAVIGATION & MANAGEMENT
// ============================================================================

/**
 * View Active Playoffs
 * Shows active playoff tournaments - navigates to playoff management for a league
 */
window.EventDelegation.register('view-active', function(element, e) {
    e.preventDefault();
    promptForLeagueAndNavigate('manage', 'View Active Playoffs');
});

/**
 * Bracket Generator
 * Opens the bracket generator tool - navigates to playoff generator for a league
 */
window.EventDelegation.register('bracket-gen', function(element, e) {
    e.preventDefault();
    promptForLeagueAndNavigate('generator', 'Bracket Generator');
});

/**
 * Seed Teams
 * Opens team seeding interface - part of the generator workflow
 */
window.EventDelegation.register('seed-teams', function(element, e) {
    e.preventDefault();
    promptForLeagueAndNavigate('generator', 'Seed Teams');
});

// ============================================================================
// RESULTS & REPORTING
// ============================================================================

/**
 * Update Results
 * Opens match results update interface - navigates to playoff management
 */
window.EventDelegation.register('update-results', function(element, e) {
    e.preventDefault();
    promptForLeagueAndNavigate('manage', 'Update Match Results');
});

/**
 * View Brackets
 * Shows bracket visualization - navigates to bracket view
 */
window.EventDelegation.register('view-brackets', function(element, e) {
    e.preventDefault();
    promptForLeagueAndNavigate('bracket', 'View Brackets');
});

/**
 * Playoff History
 * Shows historical playoff data - navigates to bracket view (shows past playoffs)
 */
window.EventDelegation.register('playoff-history', function(element, e) {
    e.preventDefault();
    promptForLeagueAndNavigate('bracket', 'Playoff History');
});

/**
 * Generate Reports
 * Generates playoff reports - exports bracket/standings data
 */
window.EventDelegation.register('generate-reports', function(element, e) {
    e.preventDefault();
    promptForLeagueAndNavigate('bracket', 'Generate Reports');
});

// ============================================================================
// TOURNAMENT MANAGEMENT
// ============================================================================

/**
 * Manage Tournament
 * Opens tournament management interface - navigates to manage page
 */
window.EventDelegation.register('manage-tournament', function(element, e) {
    e.preventDefault();

    const tournamentId = element.dataset.tournamentId;
    const leagueId = element.dataset.leagueId;

    if (leagueId) {
        window.location.href = `/playoffs/league/${leagueId}/manage`;
    } else {
        promptForLeagueAndNavigate('manage', 'Manage Tournament');
    }
});

/**
 * View Bracket
 * Shows bracket for specific tournament - navigates to bracket view
 */
window.EventDelegation.register('view-bracket', function(element, e) {
    e.preventDefault();

    const tournamentId = element.dataset.tournamentId;
    const leagueId = element.dataset.leagueId;

    if (leagueId) {
        window.location.href = `/playoffs/league/${leagueId}/bracket`;
    } else {
        promptForLeagueAndNavigate('bracket', 'View Bracket');
    }
});

// Handlers loaded
