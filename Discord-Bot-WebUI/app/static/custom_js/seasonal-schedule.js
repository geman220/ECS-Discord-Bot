'use strict';

/**
 * Seasonal Schedule View Module
 * Handles schedule viewing, filtering, editing, and export functionality
 *
 * @module seasonal-schedule
 * @requires window.InitSystem
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Seasonal Schedule functionality
 */
const SeasonalSchedule = {
    // State
    editMode: false,

    /**
     * Initialize seasonal schedule functionality
     */
    init() {
        this.setupToggleEditMode();
        this.setupFilters();
        this.setupWeekOperations();
        this.setupMatchOperations();
        this.setupExportOptions();
        this.setupModals();
        this.setupLeagueFilterChange();
        this.checkUrlFilters();
        this.initializeEditModeForAdmin();

        console.log('[SeasonalSchedule] Initialized');
    },

    /**
     * Get CSRF token
     * @returns {string} CSRF token
     */
    getCsrfToken() {
        const metaToken = document.querySelector('meta[name="csrf-token"]');
        return metaToken ? metaToken.getAttribute('content') : '';
    },

    /**
     * Get current league ID from filter
     * @returns {string} League ID
     */
    getCurrentLeagueId() {
        const leagueFilter = document.getElementById('leagueFilter');
        return leagueFilter ? leagueFilter.value : '';
    },

    /**
     * Setup toggle edit mode
     */
    setupToggleEditMode() {
        document.addEventListener('click', (e) => {
            const toggleBtn = e.target.closest('[data-action="toggle-edit"]');
            if (!toggleBtn) return;

            e.preventDefault();
            this.toggleEditMode();
        });
    },

    /**
     * Toggle edit mode
     */
    toggleEditMode() {
        this.editMode = !this.editMode;
        const editControls = document.querySelectorAll('.edit-controls');

        editControls.forEach(control => {
            if (this.editMode) {
                if (control.tagName === 'TH' || control.tagName === 'TD') {
                    control.classList.add('edit-controls-visible');
                } else {
                    control.classList.add('edit-controls-btn-visible');
                }
            } else {
                control.classList.remove('edit-controls-visible', 'edit-controls-btn-visible');
            }
        });

        // Update button text
        const button = document.querySelector('[data-action="toggle-edit"]');
        if (button) {
            button.innerHTML = this.editMode
                ? '<i class="ti ti-eye me-1"></i>Exit Edit Mode'
                : '<i class="ti ti-edit me-1"></i>Toggle Edit Mode';
        }
    },

    /**
     * Setup filters
     */
    setupFilters() {
        document.addEventListener('click', (e) => {
            const filterBtn = e.target.closest('[data-action="apply-filters"]');
            if (!filterBtn) return;

            this.applyFilters();
        });
    },

    /**
     * Apply filters
     */
    applyFilters() {
        const leagueFilter = document.getElementById('leagueFilter');
        const teamFilter = document.getElementById('teamFilter');
        const weekTypeFilter = document.getElementById('weekTypeFilter');

        const leagueValue = leagueFilter ? leagueFilter.value : '';
        const teamValue = teamFilter ? teamFilter.value : '';
        const weekTypeValue = weekTypeFilter ? weekTypeFilter.value : '';

        // Filter weeks
        document.querySelectorAll('.week-container').forEach(weekContainer => {
            const weekType = weekContainer.dataset.weekType;
            let showWeek = true;

            if (weekTypeValue && weekType !== weekTypeValue) {
                showWeek = false;
            }

            weekContainer.classList.toggle('d-none', !showWeek);
        });

        // Filter matches
        document.querySelectorAll('.match-row').forEach(row => {
            let show = true;

            if (leagueValue && row.dataset.league !== leagueValue) {
                show = false;
            }

            if (teamValue) {
                const homeTeam = row.dataset.homeTeam;
                const awayTeam = row.dataset.awayTeam;
                if (homeTeam !== teamValue && awayTeam !== teamValue) {
                    show = false;
                }
            }

            row.classList.toggle('filtered-out', !show);
        });

        // Update match counts
        document.querySelectorAll('.week-container').forEach(weekContainer => {
            const visibleMatches = weekContainer.querySelectorAll('.match-row:not(.filtered-out)').length;
            const matchCountSpan = weekContainer.querySelector('.text-muted');
            if (matchCountSpan) {
                matchCountSpan.textContent = `${visibleMatches} matches`;
            }
        });
    },

    /**
     * Setup week operations
     */
    setupWeekOperations() {
        document.addEventListener('click', (e) => {
            // Toggle week
            const toggleBtn = e.target.closest('[data-action="toggle-week"]');
            if (toggleBtn) {
                const weekNum = toggleBtn.dataset.week;
                this.toggleWeek(weekNum);
                return;
            }

            // Edit week
            const editBtn = e.target.closest('[data-action="edit-week"]');
            if (editBtn) {
                const weekNum = editBtn.dataset.week;
                this.editWeek(weekNum);
                return;
            }

            // Save week
            const saveBtn = e.target.closest('[data-action="save-week"]');
            if (saveBtn) {
                const weekNum = saveBtn.dataset.week;
                this.saveWeek(weekNum);
                return;
            }

            // Cancel week edit
            const cancelBtn = e.target.closest('[data-action="cancel-week-edit"]');
            if (cancelBtn) {
                const weekNum = cancelBtn.dataset.week;
                this.cancelWeekEdit(weekNum);
                return;
            }

            // Delete week
            const deleteBtn = e.target.closest('[data-action="delete-week"]');
            if (deleteBtn) {
                const weekNum = deleteBtn.dataset.week;
                this.deleteWeek(weekNum);
                return;
            }

            // Add match
            const addMatchBtn = e.target.closest('[data-action="add-match"]');
            if (addMatchBtn) {
                const weekNum = addMatchBtn.dataset.week;
                this.addMatch(weekNum);
                return;
            }
        });
    },

    /**
     * Toggle week visibility
     * @param {string} weekNum - Week number
     */
    toggleWeek(weekNum) {
        const content = document.getElementById(`week-${weekNum}`);
        const button = document.querySelector(`[data-action="toggle-week"][data-week="${weekNum}"]`);
        const icon = button ? button.querySelector('i') : null;

        if (!content) return;

        if (content.classList.contains('week-content-collapsed')) {
            content.classList.remove('week-content-collapsed');
            if (icon) {
                icon.classList.remove('ti-chevron-right');
                icon.classList.add('ti-chevron-down');
            }
        } else {
            content.classList.add('week-content-collapsed');
            if (icon) {
                icon.classList.remove('ti-chevron-down');
                icon.classList.add('ti-chevron-right');
            }
        }
    },

    /**
     * Edit week
     * @param {string} weekNum - Week number
     */
    editWeek(weekNum) {
        const weekHeader = document.querySelector(`.week-header[data-week="${weekNum}"]`);
        if (!weekHeader) return;

        const weekTitle = weekHeader.querySelector('.week-title');
        const weekEditForm = weekHeader.querySelector('.week-edit-form');

        if (weekTitle) weekTitle.classList.add('d-none');
        if (weekEditForm) weekEditForm.classList.remove('week-edit-form-hidden');

        // Get first match time as default
        const firstMatch = document.querySelector(`[data-week="${weekNum}"] .match-time`);
        if (firstMatch) {
            const timeInput = document.getElementById(`week-time-${weekNum}`);
            if (timeInput) {
                timeInput.value = firstMatch.dataset.time || '19:00';
            }
        }
    },

    /**
     * Cancel week edit
     * @param {string} weekNum - Week number
     */
    cancelWeekEdit(weekNum) {
        const weekHeader = document.querySelector(`.week-header[data-week="${weekNum}"]`);
        if (!weekHeader) return;

        const weekTitle = weekHeader.querySelector('.week-title');
        const weekEditForm = weekHeader.querySelector('.week-edit-form');

        if (weekTitle) weekTitle.classList.remove('d-none');
        if (weekEditForm) weekEditForm.classList.add('week-edit-form-hidden');
    },

    /**
     * Save week
     * @param {string} weekNum - Week number
     */
    saveWeek(weekNum) {
        const dateInput = document.getElementById(`week-date-${weekNum}`);
        const timeInput = document.getElementById(`week-time-${weekNum}`);

        const data = {
            week_number: weekNum,
            league_id: this.getCurrentLeagueId(),
            date: dateInput ? dateInput.value : '',
            start_time: timeInput ? timeInput.value : ''
        };

        fetch('/auto-schedule/update-week', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showAlert('success', data.message);
                location.reload();
            } else {
                this.showAlert('error', data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            this.showAlert('error', 'An error occurred while updating the week');
        });
    },

    /**
     * Delete week
     * @param {string} weekNum - Week number
     */
    deleteWeek(weekNum) {
        window.Swal.fire({
            title: 'Delete Entire Week?',
            text: 'Are you sure you want to delete this entire week and all its matches? This action cannot be undone.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: 'Yes, delete it',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                this.performDeleteWeek(weekNum);
            }
        });
    },

    /**
     * Perform delete week
     * @param {string} weekNum - Week number
     */
    performDeleteWeek(weekNum) {
        const leagueId = this.getCurrentLeagueId();

        fetch(`/auto-schedule/league/${leagueId}/delete-week`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify({ week_number: weekNum })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Deleted!',
                        text: data.message,
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => {
                        location.reload();
                    });
                } else {
                    location.reload();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: data.error
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'An error occurred while deleting the week'
                });
            }
        });
    },

    /**
     * Add match
     * @param {string} weekNum - Week number
     */
    addMatch(weekNum) {
        // Get week date
        const weekContainer = document.querySelector(`.week-container[data-week="${weekNum}"]`);
        const weekTitle = weekContainer ? weekContainer.querySelector('.week-title') : null;
        const weekTitleText = weekTitle ? weekTitle.textContent : '';
        const dateMatch = weekTitleText.match(/- (.+?)(?:\s|$)/);
        const weekDate = dateMatch ? dateMatch[1] : new Date().toISOString().split('T')[0];

        // Set up modal
        const addMatchWeek = document.getElementById('addMatchWeek');
        const addMatchDate = document.getElementById('addMatchDate');
        const leagueFilter = document.getElementById('leagueFilter');
        const addMatchLeague = document.getElementById('addMatchLeague');

        if (addMatchWeek) addMatchWeek.value = weekNum;
        if (addMatchDate) {
            try {
                addMatchDate.value = new Date(weekDate).toISOString().split('T')[0];
            } catch (e) {
                addMatchDate.value = '';
            }
        }

        // Set default league
        const defaultLeague = leagueFilter && leagueFilter.value ? leagueFilter.value : '';
        if (addMatchLeague && defaultLeague) {
            addMatchLeague.value = defaultLeague;
        }

        // Populate team options
        this.updateAddMatchTeams();

        // Show modal
        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('addMatchModal');
        } else if (typeof window.bootstrap !== 'undefined') {
            const modal = new window.bootstrap.Modal(document.getElementById('addMatchModal'));
            modal.show();
        }
    },

    /**
     * Update add match teams based on selected league
     */
    updateAddMatchTeams() {
        const leagueSelect = document.getElementById('addMatchLeague');
        const homeTeamSelect = document.getElementById('addMatchHomeTeam');
        const awayTeamSelect = document.getElementById('addMatchAwayTeam');

        if (!leagueSelect || !homeTeamSelect || !awayTeamSelect) return;

        this.populateTeamOptions(homeTeamSelect, leagueSelect.value);
        this.populateTeamOptions(awayTeamSelect, leagueSelect.value);
    },

    /**
     * Populate team options for a select element
     * @param {HTMLSelectElement} selectElement - Select element
     * @param {string} leagueId - League ID
     * @param {string} selectedTeamId - Selected team ID
     */
    populateTeamOptions(selectElement, leagueId, selectedTeamId = null) {
        selectElement.innerHTML = '<option value="">Select Team</option>';

        // Get teams for the specified league from the team filter
        const teamFilter = document.getElementById('teamFilter');
        if (teamFilter) {
            Array.from(teamFilter.options).forEach(option => {
                if (option.value && option.value !== '' && option.dataset.league === leagueId) {
                    const optionElement = document.createElement('option');
                    optionElement.value = option.value;
                    optionElement.textContent = option.textContent;
                    // Handle both string and number comparison
                    if (selectedTeamId && (option.value == selectedTeamId || option.value === String(selectedTeamId))) {
                        optionElement.selected = true;
                    }
                    selectElement.appendChild(optionElement);
                }
            });
        }
    },

    /**
     * Setup match operations
     */
    setupMatchOperations() {
        document.addEventListener('click', (e) => {
            // Edit match
            const editBtn = e.target.closest('[data-action="edit-match"]');
            if (editBtn) {
                const matchId = editBtn.dataset.matchId;
                this.editMatch(matchId);
                return;
            }

            // Delete match
            const deleteBtn = e.target.closest('[data-action="delete-match"]');
            if (deleteBtn) {
                const matchId = deleteBtn.dataset.matchId;
                this.deleteMatch(matchId);
                return;
            }
        });
    },

    /**
     * Edit match
     * @param {string} matchId - Match ID
     */
    editMatch(matchId) {
        fetch(`/auto-schedule/get-match-data?match_id=${matchId}`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Populate modal
                    const editMatchId = document.getElementById('editMatchId');
                    const editMatchTime = document.getElementById('editMatchTime');
                    const editMatchField = document.getElementById('editMatchField');
                    const homeTeamSelect = document.getElementById('editMatchHomeTeam');
                    const awayTeamSelect = document.getElementById('editMatchAwayTeam');

                    if (editMatchId) editMatchId.value = matchId;
                    if (editMatchTime) editMatchTime.value = data.match.time;
                    if (editMatchField) editMatchField.value = data.match.field;

                    // Populate team options
                    const matchRow = document.querySelector(`[data-match-id="${matchId}"]`);
                    const leagueId = matchRow ? matchRow.dataset.league : '';

                    if (homeTeamSelect) {
                        this.populateTeamOptions(homeTeamSelect, leagueId, data.match.home_team_id);
                    }
                    if (awayTeamSelect) {
                        this.populateTeamOptions(awayTeamSelect, leagueId, data.match.away_team_id);
                    }

                    // Show modal
                    if (typeof window.ModalManager !== 'undefined') {
                        window.ModalManager.show('editMatchModal');
                    } else if (typeof window.bootstrap !== 'undefined') {
                        const modal = new window.bootstrap.Modal(document.getElementById('editMatchModal'));
                        modal.show();
                    }
                } else {
                    this.showAlert('error', data.error);
                }
            })
            .catch(error => {
                console.error('Error:', error);
                this.showAlert('error', 'An error occurred while loading match data');
            });
    },

    /**
     * Delete match
     * @param {string} matchId - Match ID
     */
    deleteMatch(matchId) {
        window.Swal.fire({
            title: 'Delete Match?',
            text: 'Are you sure you want to delete this match? This action cannot be undone.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: 'Yes, delete it',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                this.performDeleteMatch(matchId);
            }
        });
    },

    /**
     * Perform delete match
     * @param {string} matchId - Match ID
     */
    performDeleteMatch(matchId) {
        fetch('/auto-schedule/delete-match', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': this.getCsrfToken()
            },
            body: JSON.stringify({ match_id: matchId })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Deleted!',
                        text: data.message,
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => {
                        location.reload();
                    });
                } else {
                    location.reload();
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: data.error
                    });
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'An error occurred while deleting the match'
                });
            }
        });
    },

    /**
     * Setup modals using event delegation
     */
    setupModals() {
        const self = this;

        // Save match from edit modal
        document.addEventListener('click', (e) => {
            const saveBtn = e.target.closest('[data-action="save-match-modal"]');
            if (saveBtn) {
                self.saveMatchFromModal();
                return;
            }

            const addBtn = e.target.closest('[data-action="save-match-add"]');
            if (addBtn) {
                self.saveMatchFromAddModal();
                return;
            }
        });

        // Delegated change handler for add match league select
        document.addEventListener('change', (e) => {
            if (e.target.id === 'addMatchLeague') {
                self.updateAddMatchTeams();
            }
        });
    },

    /**
     * Save match from edit modal
     */
    saveMatchFromModal() {
        const matchId = document.getElementById('editMatchId')?.value;
        const time = document.getElementById('editMatchTime')?.value;
        const field = document.getElementById('editMatchField')?.value;
        const homeTeamId = document.getElementById('editMatchHomeTeam')?.value;
        const awayTeamId = document.getElementById('editMatchAwayTeam')?.value;

        if (homeTeamId === awayTeamId) {
            this.showAlert('error', 'Home and away teams cannot be the same');
            return;
        }

        const data = {
            match_id: matchId,
            time: time,
            field: field,
            home_team_id: homeTeamId,
            away_team_id: awayTeamId
        };

        fetch('/auto-schedule/update-match', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showAlert('success', data.message);
                // Hide modal
                if (typeof window.bootstrap !== 'undefined') {
                    const modalEl = document.getElementById('editMatchModal');
                    const modal = window.bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                }
                location.reload();
            } else {
                this.showAlert('error', data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            this.showAlert('error', 'An error occurred while updating the match');
        });
    },

    /**
     * Save match from add modal
     */
    saveMatchFromAddModal() {
        const weekNum = document.getElementById('addMatchWeek')?.value;
        const date = document.getElementById('addMatchDate')?.value;
        const time = document.getElementById('addMatchTime')?.value;
        const field = document.getElementById('addMatchField')?.value;
        const leagueId = document.getElementById('addMatchLeague')?.value;
        const homeTeamId = document.getElementById('addMatchHomeTeam')?.value;
        const awayTeamId = document.getElementById('addMatchAwayTeam')?.value;

        if (homeTeamId === awayTeamId) {
            this.showAlert('error', 'Home and away teams cannot be the same');
            return;
        }

        const data = {
            week_number: weekNum,
            league_id: leagueId,
            date: date,
            time: time,
            field: field,
            home_team_id: homeTeamId,
            away_team_id: awayTeamId
        };

        fetch('/auto-schedule/add-match', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                this.showAlert('success', data.message);
                // Hide modal
                if (typeof window.bootstrap !== 'undefined') {
                    const modalEl = document.getElementById('addMatchModal');
                    const modal = window.bootstrap.Modal.getInstance(modalEl);
                    if (modal) modal.hide();
                }
                location.reload();
            } else {
                this.showAlert('error', data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            this.showAlert('error', 'An error occurred while adding the match');
        });
    },

    /**
     * Setup export options
     */
    setupExportOptions() {
        document.addEventListener('click', (e) => {
            const exportBtn = e.target.closest('[data-action="export-csv"]');
            if (exportBtn) {
                this.exportToCSV();
                return;
            }

            const printBtn = e.target.closest('[data-action="print-schedule"]');
            if (printBtn) {
                this.printSchedule();
                return;
            }

            const shareBtn = e.target.closest('[data-action="share-schedule"]');
            if (shareBtn) {
                this.shareSchedule();
                return;
            }
        });
    },

    /**
     * Export to CSV
     */
    exportToCSV() {
        let csv = 'Week,Date,Time,Field,League,Home Team,Away Team,Status\n';

        document.querySelectorAll('.week-container:not(.d-none)').forEach(weekContainer => {
            const weekNum = weekContainer.dataset.week;
            const weekTitle = weekContainer.querySelector('.week-title');
            const weekTitleText = weekTitle ? weekTitle.textContent : '';
            const dateMatch = weekTitleText.match(/- (.+?)(?:\s|$)/);
            const weekDate = dateMatch ? dateMatch[1] : '';

            weekContainer.querySelectorAll('.match-row:not(.filtered-out)').forEach(row => {
                const cells = row.querySelectorAll('td');
                const time = cells[0] ? cells[0].textContent.trim() : '';
                const field = cells[1] ? cells[1].textContent.trim() : '';
                const league = cells[2] ? cells[2].textContent.trim() : '';
                const homeTeam = cells[3] ? cells[3].textContent.trim() : '';
                const awayTeam = cells[4] ? cells[4].textContent.trim() : '';
                const status = cells[5] ? cells[5].textContent.trim() : '';

                csv += `${weekNum},"${weekDate}","${time}","${field}","${league}","${homeTeam}","${awayTeam}","${status}"\n`;
            });
        });

        // Download CSV
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'schedule.csv';
        a.click();
        window.URL.revokeObjectURL(url);
    },

    /**
     * Print schedule
     */
    printSchedule() {
        window.print();
    },

    /**
     * Share schedule
     */
    shareSchedule() {
        const url = window.location.href;
        if (navigator.share) {
            navigator.share({
                title: 'Season Schedule',
                text: 'Check out the season schedule',
                url: url
            });
        } else {
            // Copy to clipboard
            navigator.clipboard.writeText(url).then(() => {
                this.showAlert('success', 'Schedule link copied to clipboard!');
            });
        }
    },

    /**
     * Setup league filter change handler using event delegation
     */
    setupLeagueFilterChange() {
        // Delegated change handler for league filter
        document.addEventListener('change', (e) => {
            if (e.target.id !== 'leagueFilter') return;

            const selectedLeague = e.target.value;
            const teamFilter = document.getElementById('teamFilter');

            if (!teamFilter) return;

            // Show/hide team options based on selected league
            Array.from(teamFilter.options).forEach(option => {
                if (option.value === '') return; // Skip "All Teams" option

                if (selectedLeague === '' || option.dataset.league === selectedLeague) {
                    option.classList.remove('d-none');
                } else {
                    option.classList.add('d-none');
                }
            });

            // Reset team filter if current selection is hidden
            if (teamFilter.value && teamFilter.options[teamFilter.selectedIndex].classList.contains('d-none')) {
                teamFilter.value = '';
            }
        });
    },

    /**
     * Check URL filters
     */
    checkUrlFilters() {
        const urlParams = new URLSearchParams(window.location.search);
        const leagueId = urlParams.get('league');
        const teamId = urlParams.get('team');

        if (leagueId) {
            const leagueFilter = document.getElementById('leagueFilter');
            if (leagueFilter) leagueFilter.value = leagueId;
        }
        if (teamId) {
            const teamFilter = document.getElementById('teamFilter');
            if (teamFilter) teamFilter.value = teamId;
        }

        if (leagueId || teamId) {
            this.applyFilters();
        }
    },

    /**
     * Initialize edit mode for admin users
     */
    initializeEditModeForAdmin() {
        // Check if user is admin by looking for admin-only elements
        const adminTools = document.querySelector('[data-action="toggle-edit"]');
        if (!adminTools) return;

        // Show edit controls by default for admin users
        this.editMode = true;
        const editControls = document.querySelectorAll('.edit-controls');
        editControls.forEach(control => {
            if (control.tagName === 'TH' || control.tagName === 'TD') {
                control.classList.add('edit-controls-visible');
            } else {
                control.classList.add('edit-controls-btn-visible');
            }
        });

        // Update button text
        const button = document.querySelector('[data-action="toggle-edit"]');
        if (button) {
            button.innerHTML = '<i class="ti ti-eye me-1"></i>Exit Edit Mode';
        }
    },

    /**
     * Show alert
     * @param {string} type - Alert type ('success' or 'error')
     * @param {string} message - Alert message
     */
    showAlert(type, message) {
        // Create alert element
        const alert = document.createElement('div');
        alert.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show`;
        alert.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        // Add to page
        const container = document.querySelector('.container-xxl');
        if (container) {
            container.insertBefore(alert, container.firstChild);
        }

        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            if (alert.parentNode) {
                alert.remove();
            }
        }, 5000);
    }
};

// Register with window.InitSystem
window.InitSystem.register('seasonal-schedule', () => {
    // Only initialize on seasonal schedule page
    if (document.getElementById('scheduleContainer') ||
        document.querySelector('.week-container')) {
        SeasonalSchedule.init();
    }
}, {
    priority: 40,
    description: 'Seasonal schedule view functionality',
    reinitializable: false
});

// Export for direct use
export { SeasonalSchedule };
