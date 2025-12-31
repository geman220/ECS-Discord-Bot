/**
 * Manage Teams Page
 * Handles team CRUD operations with modal interactions
 */

(function() {
    'use strict';

    const ManageTeams = {
        init() {
            this.setupEventDelegation();
            this.setupModalHandlers();
            this.setupFormValidation();
        },

        setupEventDelegation() {
            document.addEventListener('click', (e) => {
                const target = e.target.closest('[data-action]');
                if (!target) return;

                const action = target.dataset.action;

                switch(action) {
                    case 'open-add-team-modal':
                        this.handleOpenAddTeamModal(target);
                        break;
                    case 'open-edit-team-modal':
                        this.handleOpenEditTeamModal(target);
                        break;
                    case 'delete-team':
                        this.handleDeleteTeam(target);
                        break;
                }
            });
        },

        setupModalHandlers() {
            // Add Team Modal
            const addTeamModal = document.getElementById('addTeamModal');
            if (addTeamModal) {
                addTeamModal.addEventListener('show.bs.modal', (event) => {
                    const button = event.relatedTarget;
                    if (!button) return;

                    const leagueName = button.dataset.leagueName;
                    const seasonId = button.dataset.seasonId;
                    const seasonName = button.dataset.seasonName;

                    const modalLeagueNameInput = addTeamModal.querySelector('#modal_league_name');
                    const modalSeasonIdInput = addTeamModal.querySelector('#modal_season_id');

                    if (modalLeagueNameInput) modalLeagueNameInput.value = leagueName;
                    if (modalSeasonIdInput) modalSeasonIdInput.value = seasonId;

                    const modalTitle = addTeamModal.querySelector('.modal-title');
                    if (modalTitle) {
                        modalTitle.textContent = `Add Team to ${leagueName} (${seasonName})`;
                    }
                });
            }

            // Edit Team Modal
            const editTeamModal = document.getElementById('editTeamModal');
            if (editTeamModal) {
                editTeamModal.addEventListener('show.bs.modal', (event) => {
                    const button = event.relatedTarget;
                    if (!button) return;

                    const teamId = button.dataset.teamId;
                    const teamName = button.dataset.teamName;
                    const leagueName = button.dataset.leagueName;
                    const seasonId = button.dataset.seasonId;

                    const modalTeamNameInput = editTeamModal.querySelector('#edit_team_name');
                    const modalTeamIdInput = editTeamModal.querySelector('#modal_team_id');
                    const modalLeagueNameInput = editTeamModal.querySelector('#edit_modal_league_name');
                    const modalSeasonIdInput = editTeamModal.querySelector('#edit_modal_season_id');

                    if (modalTeamNameInput) modalTeamNameInput.value = teamName;
                    if (modalTeamIdInput) modalTeamIdInput.value = teamId;
                    if (modalLeagueNameInput) modalLeagueNameInput.value = leagueName;
                    if (modalSeasonIdInput) modalSeasonIdInput.value = seasonId;

                    const modalTitle = editTeamModal.querySelector('.modal-title');
                    if (modalTitle) {
                        modalTitle.textContent = `Edit Team: ${teamName}`;
                    }
                });
            }
        },

        setupFormValidation() {
            const forms = document.querySelectorAll('.needs-validation');
            forms.forEach(form => {
                form.addEventListener('submit', (event) => {
                    if (!form.checkValidity()) {
                        event.preventDefault();
                        event.stopPropagation();
                    }
                    form.classList.add('was-validated');
                });
            });
        },

        handleOpenAddTeamModal(target) {
            // Already handled by Bootstrap data attributes
        },

        handleOpenEditTeamModal(target) {
            // Already handled by Bootstrap data attributes
        },

        handleDeleteTeam(target) {
            const teamId = target.dataset.teamId;
            const teamName = target.dataset.teamName;

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Are you sure?',
                    html: `Do you really want to delete <strong>${teamName}</strong>?<br><br>` +
                          '<span class="text-danger">This action cannot be undone.</span>',
                    icon: 'warning',
                    showCancelButton: true,
                    confirmButtonColor: this.getThemeColor('danger', '#dc3545'),
                    cancelButtonColor: this.getThemeColor('secondary', '#6c757d'),
                    confirmButtonText: 'Yes, delete it!',
                    cancelButtonText: 'Cancel'
                }).then((result) => {
                    if (result.isConfirmed) {
                        this.deleteTeam(teamId);
                    }
                });
            } else {
                if (confirm(`Do you really want to delete ${teamName}?\n\nThis action cannot be undone.`)) {
                    this.deleteTeam(teamId);
                }
            }
        },

        deleteTeam(teamId) {
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/publeague/delete_team';

            // Add CSRF token
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                             document.querySelector('[name="csrf_token"]')?.value;

            if (csrfToken) {
                const csrfInput = document.createElement('input');
                csrfInput.type = 'hidden';
                csrfInput.name = 'csrf_token';
                csrfInput.value = csrfToken;
                form.appendChild(csrfInput);
            }

            // Add team ID
            const teamIdInput = document.createElement('input');
            teamIdInput.type = 'hidden';
            teamIdInput.name = 'team_id';
            teamIdInput.value = teamId;
            form.appendChild(teamIdInput);

            document.body.appendChild(form);
            form.submit();
        },

        getThemeColor(colorName, fallback) {
            if (typeof window.ECSTheme !== 'undefined' && window.ECSTheme.getColor) {
                return window.ECSTheme.getColor(colorName);
            }

            const root = getComputedStyle(document.documentElement);
            const cssVar = root.getPropertyValue(`--ecs-${colorName}`).trim();

            return cssVar || fallback;
        }
    };

    // Add _initialized guard to init method
    const originalInit = ManageTeams.init;
    let _initialized = false;
    ManageTeams.init = function() {
        if (_initialized) return;
        _initialized = true;
        originalInit.call(this);
    };

    // Register with InitSystem (primary)
    if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
        window.InitSystem.register('manage-teams', () => ManageTeams.init(), {
            priority: 35,
            reinitializable: true,
            description: 'Manage teams page functionality'
        });
    }

    // Fallback
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => ManageTeams.init());
    } else {
        ManageTeams.init();
    }
})();
