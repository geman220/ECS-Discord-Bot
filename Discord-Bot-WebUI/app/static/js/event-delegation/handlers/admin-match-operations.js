import { EventDelegation } from '../core.js';

/**
 * Admin Match Operations Action Handlers
 * Handles match scheduling, results, teams, transfers, and rosters
 */

// MANAGE TEAMS
// ============================================================================

/**
 * Show Create Team Modal Action
 * Opens the modal to create a new team
 */
window.EventDelegation.register('show-create-team-modal', function(element, e) {
    e.preventDefault();

    if (typeof showCreateTeamModal === 'function') {
        showCreateTeamModal();
    } else {
        // Reset form
        const form = document.getElementById('createTeamForm');
        if (form) form.reset();

        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('createTeamModal');
        } else {
            const modalEl = document.getElementById('createTeamModal');
            if (modalEl && typeof window.bootstrap !== 'undefined') {
                window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
            }
        }
    }
});

/**
 * Show Edit Team Modal Action
 * Opens modal to edit a team
 */
window.EventDelegation.register('show-edit-team-modal', function(element, e) {
    e.preventDefault();

    const teamId = element.dataset.teamId;
    const teamName = element.dataset.teamName;
    const leagueId = element.dataset.leagueId;

    if (typeof showEditTeamModal === 'function') {
        showEditTeamModal(teamId, teamName, leagueId);
    } else {
        const editTeamId = document.getElementById('editTeamId');
        const editTeamName = document.getElementById('editTeamName');
        const editLeagueId = document.getElementById('editLeagueId');

        if (editTeamId) editTeamId.value = teamId || '';
        if (editTeamName) editTeamName.value = teamName || '';
        if (editLeagueId) editLeagueId.value = leagueId || '';

        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('editTeamModal');
        } else {
            const modalEl = document.getElementById('editTeamModal');
            if (modalEl && typeof window.bootstrap !== 'undefined') {
                window.bootstrap.Modal.getOrCreateInstance(modalEl).show();
            }
        }
    }
});

/**
 * Submit Create Team Action
 * Submits the create team form
 */
window.EventDelegation.register('submit-create-team', function(element, e) {
    e.preventDefault();

    if (typeof submitCreateTeam === 'function') {
        submitCreateTeam();
    } else {
        const form = document.getElementById('createTeamForm');
        if (form) {
            form.submit();
        }
    }
});

/**
 * Submit Edit Team Action
 * Submits the edit team form
 */
window.EventDelegation.register('submit-edit-team', function(element, e) {
    e.preventDefault();

    if (typeof submitEditTeam === 'function') {
        submitEditTeam();
    } else {
        const form = document.getElementById('editTeamForm');
        if (form) {
            form.submit();
        }
    }
});

/**
 * Confirm Delete Team Action (match operations version)
 * Shows confirmation before deleting team
 */
window.EventDelegation.register('confirm-delete-team', function(element, e) {
    e.preventDefault();

    const teamId = element.dataset.teamId;
    const teamName = element.dataset.teamName;

    if (typeof confirmDeleteTeam === 'function') {
        confirmDeleteTeam(teamId, teamName);
    } else {
        const confirmMessage = `Are you sure you want to delete "${teamName}"? This cannot be undone.`;

        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Delete Team?',
                text: confirmMessage,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, Delete',
                confirmButtonColor: '#dc3545'
            }).then((result) => {
                if (result.isConfirmed) {
                    deleteTeamById(teamId);
                }
            });
        }
    }
});

/**
 * Helper: Delete team by ID
 */
function deleteTeamById(teamId) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
    const url = window.MATCH_OPS_CONFIG?.deleteTeamUrl || `/admin-panel/match-operations/teams/${teamId}/delete`;

    fetch(url, {
        method: 'DELETE',
        headers: { 'X-CSRFToken': csrfToken }
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Deleted!', result.message, 'success').then(() => window.location.reload());
            }
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', result.message, 'error');
            }
        }
    })
    .catch(error => {
        console.error('[confirm-delete-team] Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to delete team', 'error');
        }
    });
}

// SCHEDULE MATCHES
// ============================================================================

/**
 * Preview Schedule Action
 * Previews the schedule before committing
 */
window.EventDelegation.register('preview-schedule', function(element, e) {
    e.preventDefault();

    if (typeof previewSchedule === 'function') {
        previewSchedule();
    } else {
        console.error('[preview-schedule] previewSchedule function not found');
    }
});

/**
 * Generate Schedule Action
 * Generates a new match schedule
 */
window.EventDelegation.register('generate-schedule', function(element, e) {
    e.preventDefault();

    if (typeof generateSchedule === 'function') {
        generateSchedule();
    } else {
        console.error('[generate-schedule] generateSchedule function not found');
    }
});

/**
 * Create Single Match Action
 * Opens modal to create a single match
 */
window.EventDelegation.register('create-single-match', function(element, e) {
    e.preventDefault();

    if (typeof showCreateMatchModal === 'function') {
        showCreateMatchModal();
    } else {
        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('createMatchModal');
        }
    }
});

/**
 * Submit Single Match Action
 * Submits the single match creation form
 */
window.EventDelegation.register('submit-single-match', function(element, e) {
    e.preventDefault();

    if (typeof submitSingleMatch === 'function') {
        submitSingleMatch();
    } else {
        const form = document.getElementById('createMatchForm');
        if (form) {
            form.submit();
        }
    }
});

// MATCH RESULTS
// ============================================================================

/**
 * Enter Match Result Action
 * Opens modal to enter match result
 */
window.EventDelegation.register('enter-match-result', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const homeTeam = element.dataset.homeTeam;
    const awayTeam = element.dataset.awayTeam;

    if (typeof enterMatchResult === 'function') {
        enterMatchResult(matchId, homeTeam, awayTeam);
    } else {
        const resultMatchId = document.getElementById('resultMatchId');
        const resultHomeTeam = document.getElementById('resultHomeTeam');
        const resultAwayTeam = document.getElementById('resultAwayTeam');
        const resultHomeScore = document.getElementById('resultHomeScore');
        const resultAwayScore = document.getElementById('resultAwayScore');

        if (resultMatchId) resultMatchId.value = matchId;
        if (resultHomeTeam) resultHomeTeam.textContent = homeTeam || 'Home';
        if (resultAwayTeam) resultAwayTeam.textContent = awayTeam || 'Away';
        if (resultHomeScore) resultHomeScore.value = '';
        if (resultAwayScore) resultAwayScore.value = '';

        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('matchResultModal');
        }
    }
});

/**
 * Submit Match Result Action
 * Submits match result
 */
window.EventDelegation.register('submit-match-result', function(element, e) {
    e.preventDefault();

    if (typeof submitMatchResult === 'function') {
        submitMatchResult();
    } else {
        const matchId = document.getElementById('resultMatchId')?.value;
        const homeScore = parseInt(document.getElementById('resultHomeScore')?.value) || 0;
        const awayScore = parseInt(document.getElementById('resultAwayScore')?.value) || 0;
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

        const url = window.MATCH_OPS_CONFIG?.submitResultUrl || `/admin-panel/match-operations/results/${matchId}/submit`;

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ home_score: homeScore, away_score: awayScore })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Success', result.message, 'success').then(() => window.location.reload());
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', result.message, 'error');
                }
            }
        })
        .catch(error => {
            console.error('[submit-match-result] Error:', error);
        });
    }
});

/**
 * View Match Details Action
 * Opens modal with match details
 */
window.EventDelegation.register('view-match-details', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (typeof viewMatchDetails === 'function') {
        viewMatchDetails(matchId);
    } else {
        // Fetch match details and show in modal
        const url = window.MATCH_OPS_CONFIG?.matchDetailsUrl || `/admin-panel/match-operations/matches/${matchId}/details`;

        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (typeof window.Swal !== 'undefined') {
                        window.Swal.fire({
                            title: 'Match Details',
                            html: data.html || `<pre>${JSON.stringify(data.match, null, 2)}</pre>`,
                            width: '600px'
                        });
                    }
                }
            })
            .catch(error => {
                console.error('[view-match-details] Error:', error);
            });
    }
});

// PLAYER TRANSFERS
// ============================================================================

/**
 * Show Transfer Player Modal Action
 * Opens modal to transfer a player
 */
window.EventDelegation.register('show-transfer-modal', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;
    const currentTeam = element.dataset.currentTeam;

    if (typeof showTransferModal === 'function') {
        showTransferModal(playerId, playerName, currentTeam);
    } else {
        const transferPlayerId = document.getElementById('transferPlayerId');
        const transferPlayerName = document.getElementById('transferPlayerName');
        const transferCurrentTeam = document.getElementById('transferCurrentTeam');
        const transferTargetTeam = document.getElementById('transferTargetTeam');

        if (transferPlayerId) transferPlayerId.value = playerId;
        if (transferPlayerName) transferPlayerName.textContent = playerName || '';
        if (transferCurrentTeam) transferCurrentTeam.textContent = currentTeam || 'No Team';
        if (transferTargetTeam) transferTargetTeam.value = '';

        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('transferModal');
        }
    }
});

/**
 * Submit Transfer Action
 * Submits player transfer
 */
window.EventDelegation.register('submit-transfer', function(element, e) {
    e.preventDefault();

    if (typeof submitTransfer === 'function') {
        submitTransfer();
    } else {
        const playerId = document.getElementById('transferPlayerId')?.value;
        const targetTeamId = document.getElementById('transferTargetTeam')?.value;
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

        if (!targetTeamId) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Please select a target team', 'warning');
            }
            return;
        }

        const url = window.MATCH_OPS_CONFIG?.transferUrl || '/admin-panel/match-operations/transfers/submit';

        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ player_id: playerId, target_team_id: targetTeamId })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Success', result.message, 'success').then(() => window.location.reload());
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', result.message, 'error');
                }
            }
        })
        .catch(error => {
            console.error('[submit-transfer] Error:', error);
        });
    }
});

/**
 * Bulk Transfer Action
 * Opens bulk transfer interface
 */
window.EventDelegation.register('bulk-transfer', function(element, e) {
    e.preventDefault();

    if (typeof showBulkTransferModal === 'function') {
        showBulkTransferModal();
    } else {
        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('bulkTransferModal');
        }
    }
});

// TEAM ROSTERS
// ============================================================================

/**
 * Manage Player Assignments Action
 * Opens player assignment interface
 */
window.EventDelegation.register('manage-player-assignments', function(element, e) {
    e.preventDefault();

    if (typeof managePlayerAssignments === 'function') {
        managePlayerAssignments();
    } else {
        // Navigate to teams page for player management
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Manage Player Assignments',
                text: 'Navigate to a team page to manage player assignments.',
                icon: 'info',
                confirmButtonText: 'Go to Teams',
                showCancelButton: true
            }).then((result) => {
                if (result.isConfirmed) {
                    window.location.href = '/teams';
                }
            });
        }
    }
});

/**
 * View Team Roster Action
 * Shows detailed team roster - navigates to team page
 */
window.EventDelegation.register('view-team-roster', function(element, e) {
    e.preventDefault();

    const teamId = element.dataset.teamId;

    if (typeof viewTeamRoster === 'function') {
        viewTeamRoster(teamId);
    } else {
        // Navigate directly to team page
        if (teamId) {
            window.location.href = `/teams/${teamId}`;
        } else {
            window.location.href = '/teams';
        }
    }
});

/**
 * Edit Team Roster Action
 * Opens team roster editing interface - navigates to team page
 */
window.EventDelegation.register('edit-team-roster', function(element, e) {
    e.preventDefault();

    const teamId = element.dataset.teamId;

    if (typeof editTeamRoster === 'function') {
        editTeamRoster(teamId);
    } else {
        // Navigate directly to team page for editing
        if (teamId) {
            window.location.href = `/teams/${teamId}`;
        } else {
            window.location.href = '/teams';
        }
    }
});

/**
 * Show Teams Without Players Action
 * Shows list of teams without assigned players
 */
window.EventDelegation.register('show-teams-without-players', function(element, e) {
    e.preventDefault();

    if (typeof showTeamsWithoutPlayers === 'function') {
        showTeamsWithoutPlayers();
    } else {
        // Try to get teams from data attribute or global variable
        const teamsWithoutPlayers = window.ROSTER_CONFIG?.teamsWithoutPlayers || [];

        if (teamsWithoutPlayers.length > 0) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Teams Without Players',
                    html: '<ul class="text-start">' + teamsWithoutPlayers.map(team => '<li>' + team + '</li>').join('') + '</ul>',
                    icon: 'warning',
                    confirmButtonText: 'Assign Players'
                }).then((result) => {
                    if (result.isConfirmed) {
                        const btn = document.querySelector('[data-action="manage-player-assignments"]');
                        if (btn) btn.click();
                    }
                });
            }
        }
    }
});

// UPCOMING MATCHES
// ============================================================================

/**
 * View Match Action (Upcoming Matches)
 * Shows match details - uses report match modal or navigates
 */
window.EventDelegation.register('view-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (typeof viewMatch === 'function') {
        viewMatch(matchId);
    } else if (typeof window.handleEditButtonClick === 'function') {
        // Use report match modal to view/edit
        window.handleEditButtonClick(matchId);
    } else {
        // Fallback - navigate to teams page
        window.location.href = '/teams';
    }
});

/**
 * Edit Match Action (Upcoming Matches)
 * Opens match editing interface - delegates to report_match.js handleEditButtonClick
 */
window.EventDelegation.register('edit-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    // Try report_match.js handler (primary method for match reporting)
    if (typeof window.handleEditButtonClick === 'function') {
        window.handleEditButtonClick(matchId);
    } else {
        // Handler not yet loaded - show loading and retry after short delay
        console.warn('[edit-match] handleEditButtonClick not ready, retrying...');
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Loading...',
                text: 'Please wait...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();
                    // Retry after a short delay for async module loading
                    setTimeout(() => {
                        if (typeof window.handleEditButtonClick === 'function') {
                            window.Swal.close();
                            window.handleEditButtonClick(matchId);
                        } else {
                            window.Swal.fire({
                                title: 'Error',
                                text: 'Match editing is not available. Please refresh the page.',
                                icon: 'error'
                            });
                        }
                    }, 500);
                }
            });
        }
    }
});

/**
 * Schedule Match Action (Upcoming Matches)
 * Opens match scheduling interface - navigates to season management
 */
window.EventDelegation.register('schedule-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;

    if (typeof scheduleMatch === 'function') {
        scheduleMatch(matchId);
    } else {
        // Navigate to season management for scheduling
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Schedule Match',
                text: 'Match scheduling is done through Season Management.',
                icon: 'info',
                confirmButtonText: 'Go to Seasons',
                showCancelButton: true
            }).then((result) => {
                if (result.isConfirmed) {
                    window.location.href = '/admin/season_management';
                }
            });
        }
    }
});

// ============================================================================

// Handlers loaded
