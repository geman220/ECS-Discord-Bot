/**
 * Admin Match Operations
 * Handles match scheduling, team management, and related operations
 */
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

let _initialized = false;

/**
 * Match Operations Manager Class
 */
class AdminMatchOperationsManager {
    constructor() {
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || null;
    }

    /**
     * Initialize the manager
     */
    init() {
        this.setupEventDelegation();
    }

    /**
     * Get CSRF token
     */
    getCSRFToken() {
        return this.csrfToken;
    }

    /**
     * Setup event delegation for all match operations actions
     */
    setupEventDelegation() {
        document.addEventListener('click', (e) => {
            const target = e.target.closest('[data-action]');
            if (!target) return;

            const action = target.dataset.action;
            const matchId = target.dataset.matchId;
            const teamId = target.dataset.teamId;
            const playerId = target.dataset.playerId;

            switch(action) {
                // Team Management
                case 'create-team':
                    this.createTeam();
                    break;
                case 'view-team':
                    this.viewTeam(teamId);
                    break;
                case 'edit-team':
                    this.editTeam(teamId);
                    break;
                case 'manage-roster':
                    this.manageRoster(teamId);
                    break;

                // Match Scheduling
                case 'schedule-match':
                    this.scheduleMatch(matchId);
                    break;
                case 'quick-schedule':
                    this.quickSchedule();
                    break;
                case 'create-new-match':
                    this.createNewMatch();
                    break;
                case 'view-match':
                    this.viewMatch(matchId);
                    break;
                case 'edit-match':
                    this.editMatch(matchId);
                    break;
                case 'enter-result':
                    this.enterResult(matchId);
                    break;

                // Player Transfers
                case 'approve-transfer':
                    this.approveTransfer(target.dataset.requestId);
                    break;
                case 'reject-transfer':
                    this.rejectTransfer(target.dataset.requestId);
                    break;
                case 'export-transfer-history':
                    this.exportTransferHistory();
                    break;

                // Team Rosters
                case 'manage-player-assignments':
                    this.managePlayerAssignments();
                    break;
                case 'view-team-roster':
                    this.viewTeamRoster(teamId);
                    break;
                case 'edit-team-roster':
                    this.editTeamRoster(teamId);
                    break;
                case 'show-teams-without-players':
                    this.showTeamsWithoutPlayers();
                    break;
            }
        });
    }

    // Team Management Methods
    createTeam() {
        const leaguesData = window.MATCH_OPS_CONFIG?.leaguesData || [];
        let leagueOptions = leaguesData.map(l =>
            `<option value="${l.id}">${l.name}${l.leagueType ? ` (${l.leagueType})` : ''}</option>`
        ).join('');

        Swal.fire({
            title: 'Create New Team',
            html: `
                <div class="text-start">
                    <div class="mb-3">
                        <label class="form-label">Team Name <span class="text-danger">*</span></label>
                        <input type="text" id="teamName" class="form-control" placeholder="e.g., FC United">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">League / Division</label>
                        <select id="teamLeagueId" class="form-select">
                            <option value="">-- Select League --</option>
                            ${leagueOptions}
                        </select>
                        <small class="form-text text-muted">Select an ECS FC or Pub League division</small>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Create Team',
            cancelButtonText: 'Cancel',
            preConfirm: () => {
                const name = document.getElementById('teamName').value;
                if (!name) {
                    Swal.showValidationMessage('Team name is required');
                    return false;
                }
                return {
                    name: name,
                    league_id: document.getElementById('teamLeagueId').value
                };
            }
        }).then((result) => {
            if (result.isConfirmed) {
                const formData = new FormData();
                formData.append('name', result.value.name);
                if (result.value.league_id) {
                    formData.append('league_id', result.value.league_id);
                }

                const url = window.MATCH_OPS_CONFIG?.createTeamUrl || '/admin-panel/match-operations/teams/create';
                fetch(url, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': this.getCSRFToken()
                    },
                    body: formData
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire('Success', data.message, 'success').then(() => location.reload());
                    } else {
                        Swal.fire('Error', data.message, 'error');
                    }
                })
                .catch(() => Swal.fire('Error', 'Failed to create team', 'error'));
            }
        });
    }

    viewTeam(teamId) {
        fetch(`/admin-panel/match-operations/teams/${teamId}/details`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const team = data.team;
                    Swal.fire({
                        title: team.name,
                        html: `
                            <div class="text-start">
                                <p><strong>Team ID:</strong> ${team.id}</p>
                                <p><strong>League:</strong> ${team.league_name || 'No League'}</p>
                                <p><strong>Players:</strong> ${team.player_count}</p>
                            </div>
                        `,
                        icon: 'info'
                    });
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to load team details', 'error'));
    }

    editTeam(teamId) {
        fetch(`/admin-panel/match-operations/teams/${teamId}/details`)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const team = data.team;
                    Swal.fire({
                        title: 'Edit Team',
                        html: `
                            <div class="text-start">
                                <div class="mb-3">
                                    <label class="form-label">Team Name <span class="text-danger">*</span></label>
                                    <input type="text" id="editTeamName" class="form-control" value="${team.name}">
                                </div>
                                <p class="text-muted small mb-0">Players: ${team.player_count}</p>
                            </div>
                        `,
                        showCancelButton: true,
                        showDenyButton: true,
                        confirmButtonText: 'Save Changes',
                        denyButtonText: 'Delete Team',
                        denyButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : 'var(--ecs-danger)',
                        cancelButtonText: 'Cancel',
                        preConfirm: () => {
                            const name = document.getElementById('editTeamName').value;
                            if (!name) {
                                Swal.showValidationMessage('Team name is required');
                                return false;
                            }
                            return { name: name };
                        }
                    }).then((result) => {
                        if (result.isConfirmed) {
                            const formData = new FormData();
                            formData.append('name', result.value.name);

                            fetch(`/admin-panel/match-operations/teams/${teamId}/update`, {
                                method: 'POST',
                                headers: {
                                    'X-CSRFToken': this.getCSRFToken()
                                },
                                body: formData
                            })
                            .then(response => response.json())
                            .then(data => {
                                if (data.success) {
                                    Swal.fire('Success', data.message, 'success').then(() => location.reload());
                                } else {
                                    Swal.fire('Error', data.message, 'error');
                                }
                            })
                            .catch(() => Swal.fire('Error', 'Failed to update team', 'error'));
                        } else if (result.isDenied) {
                            this.deleteTeam(teamId, team.name);
                        }
                    });
                } else {
                    Swal.fire('Error', data.message, 'error');
                }
            })
            .catch(() => Swal.fire('Error', 'Failed to load team details', 'error'));
    }

    deleteTeam(teamId, teamName) {
        Swal.fire({
            title: 'Delete Team?',
            text: `Are you sure you want to delete "${teamName}"? This cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, delete',
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : 'var(--ecs-danger)',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                fetch(`/admin-panel/match-operations/teams/${teamId}/delete`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': this.getCSRFToken()
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire('Deleted', data.message, 'success').then(() => location.reload());
                    } else {
                        Swal.fire('Error', data.message, 'error');
                    }
                })
                .catch(() => Swal.fire('Error', 'Failed to delete team', 'error'));
            }
        });
    }

    manageRoster(teamId) {
        const rostersUrl = window.MATCH_OPS_CONFIG?.teamRostersUrl || '/admin-panel/match-operations/team-rosters';
        window.location.href = `${rostersUrl}?team_id=${teamId}`;
    }

    // Match Scheduling Methods
    scheduleMatch(matchId) {
        Swal.fire({
            title: 'Schedule Match',
            html: `
                <form id="scheduleForm" class="text-start">
                    <div class="mb-3">
                        <label class="form-label">Date</label>
                        <input type="date" class="form-control" id="matchDate" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Time</label>
                        <input type="time" class="form-control" id="matchTime" required>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Location</label>
                        <input type="text" class="form-control" id="matchLocation" placeholder="e.g., North Field">
                    </div>
                </form>
            `,
            showCancelButton: true,
            confirmButtonText: 'Schedule Match',
            cancelButtonText: 'Cancel',
            preConfirm: () => {
                const date = document.getElementById('matchDate').value;
                const time = document.getElementById('matchTime').value;
                const location = document.getElementById('matchLocation').value;

                if (!date || !time) {
                    Swal.showValidationMessage('Please enter both date and time');
                    return false;
                }

                return { date, time, location };
            }
        }).then((result) => {
            if (result.isConfirmed) {
                const formData = new FormData();
                formData.append('match_id', matchId);
                formData.append('date', result.value.date);
                formData.append('time', result.value.time);
                formData.append('location', result.value.location);

                const url = window.SCHEDULE_CONFIG?.updateMatchScheduleUrl || '/admin-panel/match-operations/update-schedule';
                fetch(url, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-CSRFToken': this.getCSRFToken()
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire('Scheduled!', 'Match has been scheduled.', 'success').then(() => {
                            location.reload();
                        });
                    } else {
                        Swal.fire('Error', data.message || 'Failed to schedule match', 'error');
                    }
                })
                .catch(() => {
                    Swal.fire('Error', 'Failed to schedule match', 'error');
                });
            }
        });
    }

    quickSchedule() {
        Swal.fire({
            title: 'Quick Schedule',
            text: 'This will automatically schedule all unscheduled matches. Continue?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, Schedule All',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                Swal.fire({
                    title: 'Scheduling...',
                    text: 'Please wait while matches are being scheduled.',
                    allowOutsideClick: false,
                    showConfirmButton: false,
                    didOpen: () => {
                        Swal.showLoading();
                    }
                });

                const url = window.SCHEDULE_CONFIG?.autoScheduleMatchesUrl || '/admin-panel/match-operations/auto-schedule';
                fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCSRFToken()
                    },
                    body: JSON.stringify({})
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire({
                            title: 'Schedule Created!',
                            text: data.message,
                            icon: 'success'
                        }).then(() => location.reload());
                    } else {
                        Swal.fire('Error', data.message, 'error');
                    }
                })
                .catch(error => {
                    console.error('[AdminMatchOperationsManager] Error:', error);
                    Swal.fire('Error', 'Failed to create schedule', 'error');
                });
            }
        });
    }

    createNewMatch() {
        const teamsData = window.SCHEDULE_CONFIG?.teamsData || [];
        let teamOptions = teamsData.map(t => `<option value="${t.id}">${t.name}</option>`).join('');

        Swal.fire({
            title: 'Create New Match',
            html: `
                <form id="newMatchForm" class="text-start">
                    <div class="mb-3">
                        <label class="form-label">Home Team</label>
                        <select class="form-select" id="homeTeam" required>
                            <option value="">Select Home Team</option>
                            ${teamOptions}
                        </select>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Away Team</label>
                        <select class="form-select" id="awayTeam" required>
                            <option value="">Select Away Team</option>
                            ${teamOptions}
                        </select>
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Date (Optional)</label>
                        <input type="date" class="form-control" id="newMatchDate">
                    </div>
                    <div class="mb-3">
                        <label class="form-label">Time (Optional)</label>
                        <input type="time" class="form-control" id="newMatchTime">
                    </div>
                </form>
            `,
            showCancelButton: true,
            confirmButtonText: 'Create Match',
            cancelButtonText: 'Cancel',
            preConfirm: () => {
                const homeTeam = document.getElementById('homeTeam').value;
                const awayTeam = document.getElementById('awayTeam').value;

                if (!homeTeam || !awayTeam) {
                    Swal.showValidationMessage('Please select both teams');
                    return false;
                }

                if (homeTeam === awayTeam) {
                    Swal.showValidationMessage('Home and Away teams must be different');
                    return false;
                }

                return {
                    homeTeam,
                    awayTeam,
                    date: document.getElementById('newMatchDate').value,
                    time: document.getElementById('newMatchTime').value
                };
            }
        }).then((result) => {
            if (result.isConfirmed) {
                const url = window.SCHEDULE_CONFIG?.createMatchUrl || '/admin-panel/match-operations/create-match';
                fetch(url, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCSRFToken()
                    },
                    body: JSON.stringify({
                        home_team_id: parseInt(result.value.homeTeam),
                        away_team_id: parseInt(result.value.awayTeam),
                        date: result.value.date || null,
                        time: result.value.time || null
                    })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        Swal.fire({
                            title: 'Match Created!',
                            text: data.message,
                            icon: 'success'
                        }).then(() => location.reload());
                    } else {
                        Swal.fire('Error', data.message, 'error');
                    }
                })
                .catch(error => {
                    console.error('[AdminMatchOperationsManager] Error:', error);
                    Swal.fire('Error', 'Failed to create match', 'error');
                });
            }
        });
    }

    viewMatch(matchId) {
        Swal.fire({
            title: 'Match Details',
            text: 'Match details functionality coming soon!',
            icon: 'info'
        });
    }

    editMatch(matchId) {
        Swal.fire({
            title: 'Edit Match',
            text: 'Match editing functionality coming soon!',
            icon: 'info'
        });
    }

    enterResult(matchId) {
        Swal.fire({
            title: 'Enter Match Result',
            text: 'Result entry feature will be implemented here',
            icon: 'info'
        });
    }

    // Transfer Methods
    approveTransfer(requestId) {
        Swal.fire({
            title: 'Approve Transfer?',
            text: 'This will complete the player transfer.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, approve',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                Swal.fire({
                    title: 'Transfer Approved',
                    text: 'Transfer approval functionality coming soon!',
                    icon: 'success'
                });
            }
        });
    }

    rejectTransfer(requestId) {
        Swal.fire({
            title: 'Reject Transfer?',
            text: 'This will reject the player transfer request.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, reject',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                Swal.fire({
                    title: 'Transfer Rejected',
                    text: 'Transfer rejection functionality coming soon!',
                    icon: 'info'
                });
            }
        });
    }

    exportTransferHistory() {
        Swal.fire({
            title: 'Export Transfer History',
            text: 'Export functionality coming soon!',
            icon: 'info'
        });
    }

    // Team Roster Methods
    managePlayerAssignments() {
        Swal.fire({
            title: 'Assign Players',
            text: 'Player assignment functionality coming soon!',
            icon: 'info'
        });
    }

    viewTeamRoster(teamId) {
        Swal.fire({
            title: 'View Team Roster',
            text: 'Team roster details functionality coming soon!',
            icon: 'info'
        });
    }

    editTeamRoster(teamId) {
        Swal.fire({
            title: 'Edit Team Roster',
            text: 'Team roster editing functionality coming soon!',
            icon: 'info'
        });
    }

    showTeamsWithoutPlayers() {
        const teamsWithoutPlayers = window.TEAM_ROSTERS_CONFIG?.teamsWithoutPlayers || [];

        if (teamsWithoutPlayers.length > 0) {
            Swal.fire({
                title: 'Teams Without Players',
                html: '<ul class="text-start">' + teamsWithoutPlayers.map(team => '<li>' + team + '</li>').join('') + '</ul>',
                icon: 'warning',
                confirmButtonText: 'Assign Players'
            }).then((result) => {
                if (result.isConfirmed) {
                    this.managePlayerAssignments();
                }
            });
        }
    }
}

// Create singleton instance
let matchOperationsManager = null;

/**
 * Get or create manager instance
 */
function getManager() {
    if (!matchOperationsManager) {
        matchOperationsManager = new AdminMatchOperationsManager();
    }
    return matchOperationsManager;
}

/**
 * Initialize function
 */
function init() {
    if (_initialized) return;
    _initialized = true;

    const manager = getManager();
    manager.init();

    // Expose methods globally for backward compatibility
    window.createTeam = () => manager.createTeam();
    window.viewTeam = (teamId) => manager.viewTeam(teamId);
    window.editTeam = (teamId) => manager.editTeam(teamId);
    window.deleteTeam = (teamId, teamName) => manager.deleteTeam(teamId, teamName);
    window.manageRoster = (teamId) => manager.manageRoster(teamId);
    window.scheduleMatch = (matchId) => manager.scheduleMatch(matchId);
    window.quickSchedule = () => manager.quickSchedule();
    window.createNewMatch = () => manager.createNewMatch();
    window.viewMatch = (matchId) => manager.viewMatch(matchId);
    window.editMatch = (matchId) => manager.editMatch(matchId);
    window.enterResult = (matchId) => manager.enterResult(matchId);
}

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('admin-match-operations', init, {
        priority: 40,
        reinitializable: false,
        description: 'Admin match operations management'
    });
}

// Fallback for direct script loading
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Export for ES modules
export { AdminMatchOperationsManager, getManager, init };
