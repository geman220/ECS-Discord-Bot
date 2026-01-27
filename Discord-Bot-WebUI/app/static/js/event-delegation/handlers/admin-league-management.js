import { EventDelegation } from '../core.js';

/**
 * Admin League Management Action Handlers
 * Handles seasons, teams, and league management in admin panel
 */

// LEAGUE MANAGEMENT DASHBOARD
// ============================================================================

/**
 * Refresh Dashboard Stats Action
 * Auto-refresh stats on desktop
 */
let dashboardRefreshInterval = null;

window.EventDelegation.register('refresh-dashboard-stats', function(element, e) {
    e.preventDefault();

    if (typeof refreshDashboardStats === 'function') {
        refreshDashboardStats();
    } else {
        // Fallback implementation
        const url = window.LEAGUE_MANAGEMENT_CONFIG?.dashboardStatsUrl || '/admin-panel/league-management/api/dashboard-stats';
        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('[Dashboard] Stats refreshed');
                }
            })
            .catch(error => {
                console.error('[Dashboard] Error refreshing stats:', error);
            });
    }
});

// SEASON MANAGEMENT
// ============================================================================

/**
 * Set Current Season Action
 * Opens modal to set a season as current
 */
window.EventDelegation.register('set-current-season', function(element, e) {
    e.preventDefault();

    const seasonId = element.dataset.seasonId;
    const seasonName = element.dataset.seasonName;

    if (!seasonId) {
        console.error('[set-current-season] Missing season ID');
        return;
    }

    if (typeof setCurrentSeason === 'function') {
        setCurrentSeason(seasonId, seasonName);
    } else {
        // Fallback: Open modal directly
        const setCurrentSeasonId = document.getElementById('setCurrentSeasonId');
        const setCurrentSeasonName = document.getElementById('setCurrentSeasonName');
        const performRollover = document.getElementById('performRollover');
        const rolloverPreview = document.getElementById('rolloverPreview');

        if (setCurrentSeasonId) setCurrentSeasonId.value = seasonId;
        if (setCurrentSeasonName) setCurrentSeasonName.textContent = seasonName;
        if (performRollover) performRollover.checked = false;
        if (rolloverPreview) rolloverPreview.classList.add('hidden');

        // Only show modal if element exists on page
        if (document.getElementById('setCurrentModal') && typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('setCurrentModal');
        }
    }
});

/**
 * Confirm Set Current Season Action
 * Confirms setting a season as current with optional rollover
 */
window.EventDelegation.register('confirm-set-current', function(element, e) {
    e.preventDefault();

    if (typeof confirmSetCurrent === 'function') {
        confirmSetCurrent();
    } else {
        const seasonId = document.getElementById('setCurrentSeasonId')?.value;
        const performRollover = document.getElementById('performRollover')?.checked || false;
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

        if (!seasonId) {
            console.error('[confirm-set-current] Missing season ID');
            return;
        }

        fetch(`/admin-panel/league-management/seasons/api/${seasonId}/set-current`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ perform_rollover: performRollover })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'success');
                }
                setTimeout(() => window.location.reload(), 1000);
            } else {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'danger');
                }
            }
        })
        .catch(error => {
            console.error('[confirm-set-current] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to set current season', 'danger');
            }
        });
    }
});

/**
 * Delete Season Action
 * Deletes a season with confirmation
 */
window.EventDelegation.register('delete-season', function(element, e) {
    e.preventDefault();

    const seasonId = element.dataset.seasonId;
    const seasonName = element.dataset.seasonName;

    if (!seasonId) {
        console.error('[delete-season] Missing season ID');
        return;
    }

    if (typeof deleteSeason === 'function') {
        deleteSeason(seasonId, seasonName);
    } else {
        const confirmMessage = `Are you sure you want to delete "${seasonName}"? This will remove all associated leagues, teams, and matches. This cannot be undone.`;

        if (typeof AdminPanel !== 'undefined' && AdminPanel.confirmAction) {
            AdminPanel.confirmAction(confirmMessage, () => {
                performDeleteSeason(seasonId);
            });
        } else if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Delete Season?',
                text: confirmMessage,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, delete',
                confirmButtonColor: '#dc3545'
            }).then((result) => {
                if (result.isConfirmed) {
                    performDeleteSeason(seasonId);
                }
            });
        }
    }
});

/**
 * Helper: Perform season deletion
 */
function performDeleteSeason(seasonId) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

    fetch(`/admin-panel/league-management/seasons/api/${seasonId}/delete`, {
        method: 'DELETE',
        headers: { 'X-CSRFToken': csrfToken }
    })
    .then(response => response.json())
    .then(result => {
        if (result.success) {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast(result.message, 'success');
            }
            setTimeout(() => window.location.reload(), 1000);
        } else {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast(result.message, 'danger');
            }
        }
    })
    .catch(error => {
        console.error('[delete-season] Error:', error);
        if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
            AdminPanel.showMobileToast('Failed to delete season', 'danger');
        }
    });
}

/**
 * Save Season Action
 * Saves changes to a season
 */
window.EventDelegation.register('save-season', function(element, e) {
    e.preventDefault();

    if (typeof saveSeasonChanges === 'function') {
        saveSeasonChanges();
    } else {
        const seasonId = document.getElementById('editSeasonId')?.value;
        const name = document.getElementById('editSeasonName')?.value?.trim();
        const startDate = document.getElementById('editSeasonStartDate')?.value;
        const endDate = document.getElementById('editSeasonEndDate')?.value;

        if (!name) {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Please enter a season name', 'warning');
            }
            return;
        }

        fetch(`/admin-panel/league-management/seasons/api/${seasonId}/update`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: name,
                start_date: startDate || null,
                end_date: endDate || null
            })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'success');
                }
                setTimeout(() => window.location.reload(), 1000);
            } else {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'danger');
                }
            }
        })
        .catch(error => {
            console.error('[save-season] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to update season', 'danger');
            }
        });
    }
});

// TEAM MANAGEMENT
// ============================================================================

/**
 * Create Team Action
 * Creates a new team
 */
window.EventDelegation.register('create-team', function(element, e) {
    e.preventDefault();

    if (typeof createTeam === 'function') {
        createTeam();
    } else {
        const name = document.getElementById('newTeamName')?.value?.trim();
        const leagueId = document.getElementById('newTeamLeague')?.value;
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

        if (!name || !leagueId) {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Please fill in all required fields', 'warning');
            }
            return;
        }

        const url = window.LEAGUE_MANAGEMENT_CONFIG?.createTeamUrl || '/admin-panel/league-management/teams/api/create';
        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ name: name, league_id: parseInt(leagueId) })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'success');
                }
                setTimeout(() => window.location.reload(), 1000);
            } else {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'danger');
                }
            }
        })
        .catch(error => {
            console.error('[create-team] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to create team', 'danger');
            }
        });
    }
});

/**
 * Edit Team Action
 * Opens modal to edit a team
 */
window.EventDelegation.register('edit-team', function(element, e) {
    e.preventDefault();

    const teamId = element.dataset.teamId;
    const teamName = element.dataset.teamName;

    if (!teamId) {
        console.error('[edit-team] Missing team ID');
        return;
    }

    if (typeof editTeam === 'function') {
        editTeam(teamId, teamName);
    } else {
        const editTeamId = document.getElementById('editTeamId');
        const editTeamName = document.getElementById('editTeamName');

        if (editTeamId) editTeamId.value = teamId;
        if (editTeamName) editTeamName.value = teamName || '';

        // Only show modal if element exists on page
        if (document.getElementById('editTeamModal') && typeof window.ModalManager !== 'undefined') {
            window.ModalManager.show('editTeamModal');
        }
    }
});

/**
 * Save Team Edit Action
 * Saves team name changes
 */
window.EventDelegation.register('save-team-edit', function(element, e) {
    e.preventDefault();

    if (typeof saveTeamEdit === 'function') {
        saveTeamEdit();
    } else {
        const teamId = document.getElementById('editTeamId')?.value;
        const newName = document.getElementById('editTeamName')?.value?.trim();
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

        if (!newName) {
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Please enter a team name', 'warning');
            }
            return;
        }

        fetch(`/admin-panel/league-management/teams/api/${teamId}/update`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ name: newName })
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'success');
                }
                setTimeout(() => window.location.reload(), 1000);
            } else {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'danger');
                }
            }
        })
        .catch(error => {
            console.error('[save-team-edit] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to update team', 'danger');
            }
        });
    }
});

/**
 * Sync Discord Action
 * Syncs Discord resources for a team
 */
window.EventDelegation.register('sync-discord', function(element, e) {
    e.preventDefault();

    const teamId = element.dataset.teamId;

    if (!teamId) {
        console.error('[sync-discord] Missing team ID');
        return;
    }

    if (typeof syncTeamDiscord === 'function') {
        syncTeamDiscord(teamId);
    } else {
        const doSync = () => {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

            fetch(`/admin-panel/league-management/teams/api/${teamId}/sync-discord`, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken }
            })
            .then(response => response.json())
            .then(result => {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, result.success ? 'success' : 'warning');
                }
                if (result.success) {
                    setTimeout(() => window.location.reload(), 1500);
                }
            })
            .catch(error => {
                console.error('[sync-discord] Error:', error);
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast('Failed to sync Discord', 'danger');
                }
            });
        };

        if (typeof AdminPanel !== 'undefined' && AdminPanel.confirmAction) {
            AdminPanel.confirmAction('This will sync Discord resources for this team. Continue?', doSync);
        } else if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Sync Discord?',
                text: 'This will sync Discord resources for this team. Continue?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Yes, sync',
                confirmButtonColor: '#3085d6'
            }).then((result) => {
                if (result.isConfirmed) {
                    doSync();
                }
            });
        }
    }
});

/**
 * Delete Team Action
 * Deletes a team with confirmation
 */
window.EventDelegation.register('delete-team', function(element, e) {
    e.preventDefault();

    const teamId = element.dataset.teamId;
    const teamName = element.dataset.teamName;

    if (!teamId) {
        console.error('[delete-team] Missing team ID');
        return;
    }

    if (typeof deleteTeam === 'function') {
        deleteTeam(teamId, teamName);
    } else {
        const confirmMessage = `Are you sure you want to delete "${teamName}"? This will also remove Discord resources.`;

        const doDelete = () => {
            const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

            fetch(`/admin-panel/league-management/teams/api/${teamId}/delete`, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': csrfToken }
            })
            .then(response => response.json())
            .then(result => {
                if (result.success) {
                    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                        AdminPanel.showMobileToast(result.message, 'success');
                    }
                    setTimeout(() => window.location.reload(), 1000);
                } else {
                    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                        AdminPanel.showMobileToast(result.message, 'danger');
                    }
                }
            })
            .catch(error => {
                console.error('[delete-team] Error:', error);
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast('Failed to delete team', 'danger');
                }
            });
        };

        if (typeof AdminPanel !== 'undefined' && AdminPanel.confirmAction) {
            AdminPanel.confirmAction(confirmMessage, doDelete);
        } else if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Delete Team?',
                text: confirmMessage,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, delete',
                confirmButtonColor: '#dc3545'
            }).then((result) => {
                if (result.isConfirmed) {
                    doDelete();
                }
            });
        }
    }
});

// PLAYOFF MANAGEMENT
// ============================================================================

/**
 * Auto-Assign Playoffs Action
 * Automatically assigns playoff teams based on standings
 */
window.EventDelegation.register('auto-assign-playoffs', function(element, e) {
    e.preventDefault();

    const leagueId = element.dataset.leagueId;

    if (!leagueId) {
        console.error('[auto-assign-playoffs] Missing league ID');
        return;
    }

    const doAssign = () => {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content ||
                          document.querySelector('input[name="csrf_token"]')?.value || '';

        // Show loading state
        element.disabled = true;
        const originalText = element.innerHTML;
        element.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Assigning...';

        fetch(`/admin/playoffs/league/${leagueId}/auto-assign`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire({
                        title: 'Success!',
                        text: 'Playoff teams have been auto-assigned based on standings!',
                        icon: 'success',
                        confirmButtonText: 'OK'
                    }).then(() => {
                        location.reload();
                    });
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', data.error || 'Failed to auto-assign playoffs', 'error');
                }
            }
        })
        .catch(error => {
            console.error('[auto-assign-playoffs] Error:', error);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'An error occurred while auto-assigning playoffs', 'error');
            }
        })
        .finally(() => {
            element.disabled = false;
            element.innerHTML = originalText;
        });
    };

    // Show confirmation dialog
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Auto-Assign Playoff Teams?',
            text: 'This will automatically assign playoff teams based on current standings.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, assign',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                doAssign();
            }
        });
    }
});

// HISTORY PAGE - PLAYER LOOKUP
// ============================================================================

/**
 * Select Player Action (from search results)
 * Selects a player from search results for history lookup
 */
window.EventDelegation.register('select-player', function(element, e) {
    e.preventDefault();

    const playerIndex = parseInt(element.dataset.playerIndex, 10);

    if (typeof selectPlayer === 'function' && typeof searchResults !== 'undefined' && searchResults[playerIndex]) {
        selectPlayer(searchResults[playerIndex]);
    } else {
        console.error('[select-player] selectPlayer function or searchResults not available');
    }
});

/**
 * Lookup Player History Action
 * Looks up player team history
 */
window.EventDelegation.register('lookup-player-history', function(element, e) {
    e.preventDefault();

    if (typeof lookupPlayerHistory === 'function') {
        lookupPlayerHistory();
    } else {
        console.error('[lookup-player-history] lookupPlayerHistory function not found');
    }
});

// ============================================================================

// Handlers loaded
