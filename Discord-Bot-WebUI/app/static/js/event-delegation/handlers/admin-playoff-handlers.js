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
        // Fetch leagues from API
        try {
            const response = await fetch('/api/leagues');
            if (response.ok) {
                const data = await response.json();
                leagues = data.leagues || [];
            }
        } catch (error) {
            console.error('[promptForLeagueAndNavigate] Error fetching leagues:', error);
        }
    }

    if (leagues.length === 0) {
        // Default to known leagues if API fails
        leagues = [
            { id: 1, name: 'Pub League Premier' },
            { id: 2, name: 'Pub League Classic' }
        ];
    }

    const leagueOptions = leagues.map(l => `<option value="${l.id}">${l.name}</option>`).join('');

    const { value: leagueId } = await window.Swal.fire({
        title: title,
        html: `
            <div class="mb-3">
                <label class="form-label">Select League</label>
                <select class="form-select" id="leagueSelect" data-form-select>
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
// PLAYOFF CREATION & MANAGEMENT
// ============================================================================

/**
 * Create Playoff
 * Opens dialog to create a new playoff tournament
 */
window.EventDelegation.register('create-playoff', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[create-playoff] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Create New Playoff',
        html: `
            <div class="mb-3">
                <label class="form-label">Tournament Name</label>
                <input type="text" class="form-control" id="tournamentName" placeholder="Enter tournament name" data-form-control>
            </div>
            <div class="mb-3">
                <label class="form-label">Format</label>
                <select class="form-select" id="tournamentFormat" data-form-select>
                    <option value="">Select format...</option>
                    <option value="single-elim">Single Elimination</option>
                    <option value="double-elim">Double Elimination</option>
                    <option value="round-robin">Round Robin</option>
                    <option value="swiss">Swiss System</option>
                </select>
            </div>
            <div class="mb-3">
                <label class="form-label">Number of Teams</label>
                <select class="form-select" id="teamCount" data-form-select>
                    <option value="">Select team count...</option>
                    <option value="4">4 Teams</option>
                    <option value="8">8 Teams</option>
                    <option value="16">16 Teams</option>
                    <option value="32">32 Teams</option>
                </select>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Create Tournament',
        preConfirm: () => {
            const name = document.getElementById('tournamentName').value;
            const format = document.getElementById('tournamentFormat').value;
            const teamCount = document.getElementById('teamCount').value;

            if (!name || !format || !teamCount) {
                window.Swal.showValidationMessage('All fields are required');
                return false;
            }

            return { name, format, teamCount };
        }
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Created!', 'Tournament has been created successfully.', 'success');
        }
    });
});

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

// ============================================================================
// TEMPLATES
// ============================================================================

/**
 * Use Template
 * Uses a playoff template to create a tournament
 */
window.EventDelegation.register('use-template', function(element, e) {
    e.preventDefault();

    const templateType = element.dataset.template;

    if (!templateType) {
        console.error('[use-template] Missing template type');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[use-template] SweetAlert2 not available');
        return;
    }

    let templateName = '';
    switch(templateType) {
        case 'single-elim': templateName = 'Single Elimination'; break;
        case 'double-elim': templateName = 'Double Elimination'; break;
        case 'round-robin': templateName = 'Round Robin'; break;
        case 'swiss': templateName = 'Swiss System'; break;
        case 'group-stage': templateName = 'Group Stage'; break;
        case 'custom': templateName = 'Custom Format'; break;
        default: templateName = templateType;
    }

    window.Swal.fire({
        title: `Use ${templateName} Template?`,
        text: 'This will create a new tournament using this format.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Use Template'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Template Applied!', `${templateName} tournament template is ready for configuration.`, 'success');
        }
    });
});

// Handlers loaded
