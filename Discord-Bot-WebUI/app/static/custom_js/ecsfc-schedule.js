import { InitSystem } from '../js/init-system.js';

/**
 * ============================================================================
 * ECS FC Schedule Management
 * ============================================================================
 *
 * Handles all interactions for the ECS FC schedule management page including:
 * - Bulk match generation
 * - Single week/match operations
 * - Modal interactions
 * - Event delegation for dynamic content
 *
 * Dependencies:
 * - ModalManager (from modal-helpers.js)
 * - Bootstrap 5.x
 *
 * ============================================================================
 */

// Guard against duplicate initialization (using window to prevent redeclaration errors if script loads twice)
if (typeof window._ecsfcInitialized === 'undefined') {
    window._ecsfcInitialized = false;
}

export class ECSFCScheduleManager {
    constructor() {
        if (window._ecsfcInitialized) return;
        window._ecsfcInitialized = true;

        this.leagues = [];
        this.csrfToken = '';
        this.init();
    }

    init() {
        // Get leagues data from page
        this.leagues = window.leagues || [];
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content ||
                        document.querySelector('input[name="csrf_token"]')?.value || '';

        // Setup event delegation
        this.setupEventDelegation();

        // Setup modal handlers
        this.setupModals();
    }

    setupEventDelegation() {
        // Event delegation for all schedule actions
        document.addEventListener('click', (e) => {
            const action = e.target.closest('[data-action]')?.dataset.action;
            if (!action) return;

            const target = e.target.closest('[data-action]');

            switch(action) {
                case 'generate-form':
                    this.handleGenerateForm(target.dataset.leagueName);
                    break;
                case 'edit-match':
                    this.handleEditMatch(target);
                    break;
                case 'add-single-week':
                    // Handled by Bootstrap modal
                    break;
                default:
                    break;
            }
        });
    }

    setupModals() {
        // Add Week Modal setup
        const addWeekModal = document.getElementById('addWeekModal');
        if (addWeekModal) {
            addWeekModal.addEventListener('show.bs.modal', (event) => {
                const button = event.relatedTarget;
                if (!button) return;

                const leagueName = button.getAttribute('data-league-name');
                document.getElementById('modal_league_name').value = leagueName;

                // Populate team dropdowns
                const league = this.leagues.find(l => l.name === leagueName);
                if (league) {
                    this.populateTeamSelects(league.teams, ['teamA', 'teamB']);
                }
            });
        }
    }

    handleGenerateForm(leagueName) {
        const totalWeeks = document.getElementById(`total_weeks-${leagueName}`)?.value;
        const matchesPerWeek = document.getElementById(`matches_per_week-${leagueName}`)?.value;
        const funWeek = document.getElementById(`fun_week-${leagueName}`)?.value;
        const tstWeek = document.getElementById(`tst_week-${leagueName}`)?.value;
        const startTimeStr = document.getElementById(`start_time-${leagueName}`)?.value;
        const location = document.getElementById(`location-${leagueName}`)?.value;

        if (!totalWeeks || !matchesPerWeek || !startTimeStr) {
            this.showAlert('Total Weeks, Matches Per Week, and Start Time are required!', 'warning');
            return;
        }

        const league = this.leagues.find(l => l.name === leagueName);
        if (!league) {
            this.showAlert('League not found', 'danger');
            return;
        }

        const detailedForm = this.generateDetailedInputForm(
            totalWeeks, matchesPerWeek, funWeek, tstWeek,
            startTimeStr, location, league.teams, leagueName
        );

        const container = document.getElementById(`detailedInputForm-${leagueName}`);
        if (container) {
            container.innerHTML = detailedForm;
        }
    }

    generateDetailedInputForm(totalWeeks, matchesPerWeek, funWeek, tstWeek, startTimeStr, location, teams, leagueName) {
        let formHTML = `
            <form method="POST" action="/ecsfc/bulk_create_matches/${window.seasonId || ''}/${leagueName}" data-component="detailed-bulk-form">
                <input type="hidden" name="csrf_token" value="${this.csrfToken}">
                <div class="row g-3">
        `;

        for (let week = 1; week <= totalWeeks; week++) {
            let weekDetails = week == funWeek ? 'Fun Week' : week == tstWeek ? 'TST Week' : `Week ${week}`;

            formHTML += `
                <div class="col-lg-4 col-md-6 col-sm-12">
                    <div class="c-week-form-card card">
                        <div class="card-header c-week-form-card__header">
                            <h6 class="c-week-form-card__title">${weekDetails}</h6>
                        </div>
                        <div class="card-body">
            `;

            if (week == funWeek || week == tstWeek) {
                formHTML += `<p class="c-week-form-card__special">No matches scheduled this week.</p>`;
            } else {
                formHTML += `
                    <div class="c-form-group">
                        <label class="c-form-group__label">Date</label>
                        <input type="date" class="c-form-group__input" name="date_week${week}" required data-form-control>
                    </div>
                `;

                for (let match = 1; match <= matchesPerWeek; match++) {
                    formHTML += this.generateMatchInput(week, match, teams, startTimeStr, location);
                }
            }

            formHTML += `
                        </div>
                    </div>
                </div>
            `;
        }

        formHTML += `
                </div>
                <div class="mt-3">
                    <button type="submit" class="btn btn-success" data-action="save-matches">
                        <i class="ti ti-check me-1"></i>
                        Save Matches
                    </button>
                </div>
            </form>
        `;

        return formHTML;
    }

    generateMatchInput(week, match, teams, startTimeStr, location) {
        const teamsOptions = teams.map(team =>
            `<option value="${team.id}">${team.name}</option>`
        ).join('');

        return `
            <div class="c-match-input" data-component="match-input">
                <div class="row g-2 align-items-center mb-2">
                    <div class="col-6 col-md-3">
                        <select class="c-match-input__select" name="teamA_week${week}_match${match}" required data-form-select>
                            <option value="">Team A</option>
                            ${teamsOptions}
                        </select>
                    </div>
                    <div class="col-6 col-md-3">
                        <select class="c-match-input__select" name="teamB_week${week}_match${match}" required data-form-select>
                            <option value="">Team B</option>
                            ${teamsOptions}
                        </select>
                    </div>
                    <div class="col-6 col-md-3">
                        <input type="time"
                               class="c-match-input__time"
                               name="time_week${week}_match${match}"
                               value="${startTimeStr}"
                               required
                               data-form-control>
                    </div>
                    <div class="col-6 col-md-3">
                        <select class="c-match-input__location" name="location_week${week}_match${match}" required data-form-select>
                            <option value="North" ${location === 'North' ? 'selected' : ''}>North</option>
                            <option value="South" ${location === 'South' ? 'selected' : ''}>South</option>
                        </select>
                    </div>
                </div>
            </div>
        `;
    }

    handleEditMatch(button) {
        const matchId = button.dataset.matchId;
        const teamA = button.dataset.teamA;
        const teamB = button.dataset.teamB;
        const time = button.dataset.time;
        const location = button.dataset.location;
        const date = button.dataset.date;
        const leagueName = button.dataset.leagueName;

        this.loadMatchData(matchId, teamA, teamB, time, location, date, leagueName);
    }

    loadMatchData(matchId, teamA, teamB, time, location, date, leagueName) {
        // Format date
        const formattedDate = new Date(date).toISOString().split('T')[0];

        // Format time from 12-hour to 24-hour
        const formattedTime = this.convertTo24Hour(time);

        // Populate team selects
        const league = this.leagues.find(l => l.name === leagueName);
        if (league) {
            this.populateTeamSelectsWithSelection(league.teams, 'edit_team_a', teamA);
            this.populateTeamSelectsWithSelection(league.teams, 'edit_team_b', teamB);
        }

        // Set form values
        document.getElementById('edit_time').value = formattedTime;
        document.getElementById('edit_location').value = location;
        document.getElementById('edit_date').value = formattedDate;

        // Set form action
        const form = document.querySelector('#manage-ecsfc-editModal form');
        if (form) {
            form.action = `/ecsfc/edit_match/${matchId}`;
        }
    }

    convertTo24Hour(timeStr) {
        const match = timeStr.match(/(\d+):(\d+)\s*(AM|PM)/i);
        if (!match) return timeStr;

        let [, hour, minute, period] = match;
        hour = parseInt(hour);

        if (period.toUpperCase() === 'PM' && hour < 12) {
            hour += 12;
        } else if (period.toUpperCase() === 'AM' && hour === 12) {
            hour = 0;
        }

        return `${hour.toString().padStart(2, '0')}:${minute}`;
    }

    populateTeamSelects(teams, selectIds) {
        selectIds.forEach(selectId => {
            const select = document.getElementById(selectId);
            if (!select) return;

            select.innerHTML = teams.map(team =>
                `<option value="${team.name}">${team.name}</option>`
            ).join('');
        });
    }

    populateTeamSelectsWithSelection(teams, selectId, selectedTeam) {
        const select = document.getElementById(selectId);
        if (!select) return;

        select.innerHTML = teams.map(team =>
            `<option value="${team.name}" ${team.name === selectedTeam ? 'selected' : ''}>${team.name}</option>`
        ).join('');
    }

    showAlert(message, type = 'info') {
        // Use SweetAlert if available, otherwise use native alert
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: type === 'warning' ? 'warning' : type === 'danger' ? 'error' : 'info',
                title: message,
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 3000,
                timerProgressBar: true
            });
        } else {
            alert(message);
        }
    }
}

// Initialize function for InitSystem
export function initEcsfcSchedule() {
    if (_ecsfcInitialized) return;
    window.ecsfcScheduleManager = new ECSFCScheduleManager();
}

// Register with InitSystem (primary)
if (true && InitSystem.register) {
    InitSystem.register('ecsfc-schedule', initEcsfcSchedule, {
        priority: 40,
        reinitializable: false,
        description: 'ECS FC schedule management'
    });
}

// Fallback
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initEcsfcSchedule);
} else {
    initEcsfcSchedule();
}

// Backward compatibility
window.ECSFCScheduleManager = ECSFCScheduleManager;

// Backward compatibility
window.initEcsfcSchedule = initEcsfcSchedule;
