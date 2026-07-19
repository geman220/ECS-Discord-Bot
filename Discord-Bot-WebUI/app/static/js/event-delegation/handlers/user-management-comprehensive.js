import { EventDelegation } from '../core.js';
import { InitSystem } from '../../init-system.js';

let _initialized = false;

/**
 * Comprehensive User Management — Single Source of Truth
 * ======================================================
 * All user-management logic lives here. The template provides only
 * window.USER_MGMT_CONFIG (Jinja URLs/CSRF) and markup.
 */

// ============================================================================
// MODULE STATE
// ============================================================================

let editUserModalEl = null;

// ============================================================================
// CONFIGURATION HELPERS
// ============================================================================

// Escape user-controlled text before it goes into a SweetAlert `html:` block.
// Player names (and, more loosely, team names) are user/admin-editable and end up
// in these dialogs — without escaping, a name like `<img src=x onerror=...>` is
// stored XSS that fires in the admin's session. Attribute-context Jinja `|e` does
// NOT protect the innerHTML sink SweetAlert uses.
function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getCsrfToken() {
    const metaToken = document.querySelector('meta[name="csrf-token"]');
    if (metaToken) return metaToken.getAttribute('content');

    const inputToken = document.querySelector('input[name="csrf_token"]');
    if (inputToken) return inputToken.value;

    if (typeof window.USER_MGMT_CONFIG !== 'undefined' && window.USER_MGMT_CONFIG.csrfToken) {
        return window.USER_MGMT_CONFIG.csrfToken;
    }

    return '';
}

function getUrl(key, userId = null) {
    const config = window.USER_MGMT_CONFIG || {};
    let url = config[key] || '';
    if (userId && url) {
        url = url.replace('/0', '/' + userId);
    }
    return url;
}

function isDarkMode() {
    return document.documentElement.classList.contains('dark');
}

// ============================================================================
// MODAL HELPERS
// ============================================================================

function openModal(modal) {
    if (!modal) return;
    modal.classList.remove('hidden');
    modal.classList.add('flex');
    modal.setAttribute('aria-hidden', 'false');
    document.body.classList.add('overflow-hidden');
}

function closeModal(modal) {
    if (!modal) return;
    modal.classList.add('hidden');
    modal.classList.remove('flex');
    modal.setAttribute('aria-hidden', 'true');
    document.body.classList.remove('overflow-hidden');

    // Clean up lingering Flowbite backdrop elements
    document.querySelectorAll('body > div.fixed.inset-0[class*="z-4"]').forEach(backdrop => {
        if (backdrop.children.length === 0 || backdrop.classList.contains('bg-gray-900/50') ||
            backdrop.classList.contains('bg-dark-backdrop/70') || backdrop.classList.contains('bg-gray-900/80')) {
            backdrop.remove();
        }
    });

    if (typeof window.Swal !== 'undefined' && window.Swal.isVisible()) {
        window.Swal.close();
    }
}

// ============================================================================
// UI HELPERS
// ============================================================================

function showLoading(title = 'Loading...') {
    if (typeof window.Swal !== 'undefined') {
        const dark = isDarkMode();
        window.Swal.fire({
            title: title,
            html: '<div class="flex justify-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status" data-spinner></div></div>',
            allowOutsideClick: false,
            showConfirmButton: false,
            background: dark ? '#1f2937' : '#ffffff',
            color: dark ? '#f3f4f6' : '#111827'
        });
    }
}

function showNotification(title, message, type = 'info') {
    if (typeof window.Swal !== 'undefined') {
        const dark = isDarkMode();
        window.Swal.fire({
            title,
            text: message,
            icon: type,
            confirmButtonColor: '#1a472a',
            background: dark ? '#1f2937' : '#ffffff',
            color: dark ? '#f3f4f6' : '#111827'
        });
    }
}

// ============================================================================
// LEAGUE TIER HELPERS
// ============================================================================

function getLeagueTypeFromName(leagueName) {
    if (!leagueName) return '';
    if (leagueName.includes('ECS FC')) return 'ecsfc';
    if (leagueName.toLowerCase().includes('classic')) return 'classic';
    if (leagueName.toLowerCase().includes('premier')) return 'premier';
    return '';
}

function resetAllLeagueTiers() {
    ['primary', 'secondary', 'tertiary'].forEach(tier => {
        const cap = tier.charAt(0).toUpperCase() + tier.slice(1);
        const typeSelect = document.getElementById(`edit${cap}LeagueType`);
        if (typeSelect) typeSelect.value = '';

        const singleTeam = document.getElementById(`${tier}SingleTeam`);
        const ecsfcTeams = document.getElementById(`${tier}EcsFcTeams`);
        if (singleTeam) singleTeam.classList.add('hidden');
        if (ecsfcTeams) ecsfcTeams.classList.add('hidden');

        const teamSelect = document.getElementById(`edit${cap}Team`);
        if (teamSelect) {
            teamSelect.value = '';
            teamSelect.disabled = true;
        }

        document.querySelectorAll(`#${tier}EcsFcTeams input[type="checkbox"]`).forEach(cb => {
            cb.checked = false;
            cb.disabled = true;
        });
    });
}

function handleLeagueTypeChange(tier, leagueType) {
    const cap = tier.charAt(0).toUpperCase() + tier.slice(1);
    const singleTeam = document.getElementById(`${tier}SingleTeam`);
    const ecsfcTeams = document.getElementById(`${tier}EcsFcTeams`);
    const teamSelect = document.getElementById(`edit${cap}Team`);

    if (singleTeam) singleTeam.classList.add('hidden');
    if (ecsfcTeams) ecsfcTeams.classList.add('hidden');

    // Reset and disable all team elements for this tier.
    // Disabled elements are excluded from form submission per HTML spec.
    if (teamSelect) {
        teamSelect.value = '';
        teamSelect.disabled = true;
    }
    if (ecsfcTeams) {
        ecsfcTeams.querySelectorAll('input[type="checkbox"]').forEach(cb => {
            cb.checked = false;
            cb.disabled = true;
        });
    }

    if (!leagueType) return;

    if (leagueType === 'classic' || leagueType === 'premier') {
        if (singleTeam) singleTeam.classList.remove('hidden');
        if (teamSelect) {
            teamSelect.disabled = false;
            teamSelect.querySelectorAll('option[data-league-name]').forEach(opt => {
                const optType = getLeagueTypeFromName(opt.dataset.leagueName);
                opt.style.display = optType === leagueType ? '' : 'none';
            });
        }
    } else if (leagueType === 'ecsfc') {
        if (ecsfcTeams) {
            ecsfcTeams.classList.remove('hidden');
            ecsfcTeams.querySelectorAll('input[type="checkbox"]').forEach(cb => {
                cb.disabled = false;
            });
        }
    }
}

function setLeagueTier(tier, leagueType, teamData) {
    const cap = tier.charAt(0).toUpperCase() + tier.slice(1);
    const typeSelect = document.getElementById(`edit${cap}LeagueType`);
    if (!typeSelect) return;

    typeSelect.value = leagueType;
    handleLeagueTypeChange(tier, leagueType);

    if (leagueType === 'ecsfc' && Array.isArray(teamData)) {
        teamData.forEach(teamId => {
            if (teamId) {
                const checkbox = document.querySelector(`#${tier}EcsFcTeams input[data-team-id="${teamId}"]`);
                if (checkbox) checkbox.checked = true;
            }
        });
    } else if (teamData) {
        const teamSelect = document.getElementById(`edit${cap}Team`);
        if (teamSelect) {
            teamSelect.value = teamData;
            // Pre-check the per-tier "Coach of this team" box from the stored
            // per-team coach map, and keep it in sync if the admin changes the team.
            const coachCb = document.getElementById(`edit${cap}TeamCoach`);
            if (coachCb) {
                coachCb.checked = !!(window._teamCoachMap && window._teamCoachMap[String(teamData)]);
            }
            if (!teamSelect.dataset.coachSyncBound) {
                teamSelect.dataset.coachSyncBound = '1';
                teamSelect.addEventListener('change', function () {
                    const cb = document.getElementById(`edit${cap}TeamCoach`);
                    if (cb) cb.checked = !!(window._teamCoachMap && window._teamCoachMap[String(this.value)]);
                });
            }
        }
    }
}

function populateLeagueTiers(player) {
    // Store per-team coach status for the per-tier coach checkboxes, and reset the
    // boxes so stale state from a previously-edited user never carries over.
    window._teamCoachMap = (player && player.team_coach_map) || {};
    ['Primary', 'Secondary', 'Tertiary'].forEach(function (cap) {
        const cb = document.getElementById('edit' + cap + 'TeamCoach');
        if (cb) cb.checked = false;
    });

    const allTeamIds = player.team_ids || [];

    // Build team info map from DOM options
    const teamOptions = document.querySelectorAll('#editPrimaryTeam option[data-league-name]');
    const teamInfo = {};
    teamOptions.forEach(opt => {
        teamInfo[opt.value] = {
            leagueName: opt.dataset.leagueName,
            leagueId: opt.dataset.league
        };
    });

    // Group teams by league type
    const classicTeams = [];
    const premierTeams = [];
    const ecsfcTeams = [];

    allTeamIds.forEach(teamId => {
        const info = teamInfo[teamId];
        if (info) {
            const lt = getLeagueTypeFromName(info.leagueName);
            if (lt === 'classic') classicTeams.push(teamId);
            else if (lt === 'premier') premierTeams.push(teamId);
            else if (lt === 'ecsfc') ecsfcTeams.push(teamId);
        }
    });

    // Primary tier from league name
    const primaryLeagueType = player.primary_league_name
        ? getLeagueTypeFromName(player.primary_league_name)
        : '';

    if (primaryLeagueType === 'classic') {
        setLeagueTier('primary', 'classic', classicTeams[0] || null);
    } else if (primaryLeagueType === 'premier') {
        setLeagueTier('primary', 'premier', premierTeams[0] || null);
    } else if (primaryLeagueType === 'ecsfc') {
        setLeagueTier('primary', 'ecsfc', ecsfcTeams.length > 0 ? ecsfcTeams : []);
    }

    // Other leagues from API
    const otherLeagueTypes = (player.other_league_names || []).map(n => getLeagueTypeFromName(n));

    const remainingLeagues = [];

    otherLeagueTypes.forEach(lt => {
        if (lt && lt !== primaryLeagueType && !remainingLeagues.find(l => l.type === lt)) {
            if (lt === 'classic') remainingLeagues.push({ type: 'classic', teams: classicTeams });
            else if (lt === 'premier') remainingLeagues.push({ type: 'premier', teams: premierTeams });
            else if (lt === 'ecsfc') remainingLeagues.push({ type: 'ecsfc', teams: ecsfcTeams });
        }
    });

    // Also detect from team assignments
    if (premierTeams.length > 0 && primaryLeagueType !== 'premier' && !remainingLeagues.find(l => l.type === 'premier')) {
        remainingLeagues.push({ type: 'premier', teams: premierTeams });
    }
    if (classicTeams.length > 0 && primaryLeagueType !== 'classic' && !remainingLeagues.find(l => l.type === 'classic')) {
        remainingLeagues.push({ type: 'classic', teams: classicTeams });
    }
    if (ecsfcTeams.length > 0 && primaryLeagueType !== 'ecsfc' && !remainingLeagues.find(l => l.type === 'ecsfc')) {
        remainingLeagues.push({ type: 'ecsfc', teams: ecsfcTeams });
    }

    remainingLeagues.forEach((league, idx) => {
        const tier = idx === 0 ? 'secondary' : 'tertiary';
        if (league.type === 'ecsfc') {
            setLeagueTier(tier, 'ecsfc', league.teams);
        } else {
            setLeagueTier(tier, league.type, league.teams[0] || null);
        }
    });
}

// ============================================================================
// POPULATE EDIT FORM
// ============================================================================

function populateEditForm(user) {
    const editForm = document.getElementById('editUserForm');
    if (editForm) {
        editForm.action = getUrl('editUserUrl', user.id);
    }

    document.getElementById('editUserId').value = user.id;
    document.getElementById('editUsername').value = user.username || '';
    document.getElementById('editEmail').value = user.email || '';
    document.getElementById('editRealName').value = user.real_name || '';
    document.getElementById('editIsApproved').checked = user.is_approved;
    document.getElementById('editIsActive').checked = user.is_active;

    // Roles — API returns 'roles' as array of role IDs
    const userRoleIds = user.roles || [];
    document.querySelectorAll('#editRolesContainer input[type="checkbox"]').forEach(cb => {
        cb.checked = userRoleIds.includes(parseInt(cb.value));
    });

    // Player profile
    const playerFields = document.getElementById('playerFields');
    const noPlayerMessage = document.getElementById('noPlayerMessage');
    const isCurrentPlayerCb = document.getElementById('editIsCurrentPlayer');

    if (user.player) {
        if (noPlayerMessage) noPlayerMessage.classList.add('hidden');
        if (playerFields) playerFields.classList.remove('hidden');
        if (isCurrentPlayerCb) {
            isCurrentPlayerCb.checked = user.player.is_current_player;
            isCurrentPlayerCb.disabled = false;
        }

        resetAllLeagueTiers();
        populateLeagueTiers(user.player);
    } else {
        if (noPlayerMessage) noPlayerMessage.classList.remove('hidden');
        if (playerFields) playerFields.classList.add('hidden');
        if (isCurrentPlayerCb) {
            isCurrentPlayerCb.checked = false;
            isCurrentPlayerCb.disabled = true;
        }
        resetAllLeagueTiers();
    }
}

// ============================================================================
// LOAD USER DETAILS & OPEN MODAL
// ============================================================================

function loadUserDetails(userId) {
    const url = getUrl('userDetailsUrl', userId);
    if (!url) {
        showNotification('Error', 'User details URL not configured', 'error');
        return;
    }

    fetch(url)
        .then(response => {
            if (!response.ok) throw new Error(`Server error: ${response.status}`);
            const ct = response.headers.get('content-type');
            if (!ct || !ct.includes('application/json')) throw new Error('Invalid response format');
            return response.json();
        })
        .then(data => {
            if (data.success) {
                populateEditForm(data.user);
                openModal(editUserModalEl);
            } else {
                throw new Error(data.error || 'Failed to load user');
            }
        })
        .catch(error => {
            console.error('Error loading user details:', error);
            showNotification('Error', error.message || 'Failed to load user details', 'error');
        });
}

// ============================================================================
// EDIT USER
// ============================================================================

window.EventDelegation.register('edit-user', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[edit-user] Missing user ID');
        return;
    }
    loadUserDetails(userId);
}, { preventDefault: true });

// ============================================================================
// FORM SUBMISSION
// ============================================================================

function handleEditUserSubmit(e, confirmConflicts) {
    if (e && e.preventDefault) e.preventDefault();

    const form = document.getElementById('editUserForm');
    if (!form) return;

    const formData = new FormData(form);
    // On the second pass (admin confirmed the roster-conflict popup) tell the
    // server to skip the guard and apply the change as-is.
    if (confirmConflicts) formData.append('confirm_conflicts', 'true');

    showLoading('Saving...');

    fetch(form.action, {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (response.redirected) {
            throw new Error('Session expired or request was redirected. Please refresh and try again.');
        }
        const ct = response.headers.get('content-type');
        if (ct && ct.includes('application/json')) {
            return response.json();
        }
        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }
        throw new Error('Unexpected response format from server. Please refresh and try again.');
    })
    .then(data => {
        // Roster-conflict guard: explain the change and let the admin override.
        if (data && data.needs_confirmation) {
            if (window.Swal && window.Swal.isVisible()) window.Swal.close();
            // Escape: conflict strings embed team/league names (admin-editable).
            const items = (data.conflicts || []).map(c => '<li>' + escapeHtml(c) + '</li>').join('');
            window.Swal.fire({
                title: 'Confirm roster change?',
                html: '<div style="text-align:left"><p>Saving will create:</p>' +
                      '<ul style="text-align:left;margin:.25rem 0 0 1.1rem;list-style:disc">' + items + '</ul>' +
                      '<p style="margin-top:.5rem;font-size:.85em;opacity:.75">This can misassign Discord roles and standings. Save anyway only if you intend it.</p></div>',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Save anyway',
                cancelButtonText: 'Go back',
                confirmButtonColor: '#b45309',
                background: isDarkMode() ? '#1f2937' : '#ffffff',
                color: isDarkMode() ? '#f3f4f6' : '#111827'
            }).then(r => { if (r.isConfirmed) handleEditUserSubmit(null, true); });
            return;
        }
        if (data && data.success) {
            closeModal(editUserModalEl);
            showNotification('Success', data.message || 'User updated successfully', 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            throw new Error((data && data.message) || 'Failed to update user');
        }
    })
    .catch(error => {
        showNotification('Error', error.message || 'Failed to update user', 'error');
    });
}

// ============================================================================
// RESET USER PASSWORD (for manage_users.html)
// ============================================================================

window.EventDelegation.register('reset-user-password', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    const username = element.dataset.username;
    if (!userId) return;

    if (typeof window.setUserForResetPassword === 'function') {
        window.setUserForResetPassword(userId, username);
    }
}, { preventDefault: true });

// ============================================================================
// APPROVE USER STATUS (for manage_users.html)
// ============================================================================

window.EventDelegation.register('approve-user-status', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) return;

    if (typeof window.handleApproveUserClick === 'function') {
        window.handleApproveUserClick(userId);
    }
}, { preventDefault: true });

// ============================================================================
// REMOVE USER (for manage_users.html)
// ============================================================================

window.EventDelegation.register('remove-user', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) return;

    if (typeof window.handleRemoveUserClick === 'function') {
        window.handleRemoveUserClick(userId);
    }
}, { preventDefault: true });

// ============================================================================
// APPROVE / DEACTIVATE / ACTIVATE / DELETE USER
// ============================================================================

window.EventDelegation.register('approve-user', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) return;

    window.Swal.fire({
        title: 'Approve User?',
        text: 'This will approve the user account.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, Approve',
        confirmButtonColor: '#1a472a',
        background: isDarkMode() ? '#1f2937' : '#ffffff',
        color: isDarkMode() ? '#f3f4f6' : '#111827'
    }).then(result => {
        if (result.isConfirmed) performUserAction(userId, 'approve');
    });
}, { preventDefault: true });

window.EventDelegation.register('deactivate-user', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) return;

    window.Swal.fire({
        title: 'Deactivate User?',
        text: 'This will prevent the user from accessing the system.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, Deactivate',
        confirmButtonColor: '#1a472a',
        background: isDarkMode() ? '#1f2937' : '#ffffff',
        color: isDarkMode() ? '#f3f4f6' : '#111827'
    }).then(result => {
        if (result.isConfirmed) performUserAction(userId, 'deactivate');
    });
}, { preventDefault: true });

window.EventDelegation.register('activate-user', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) return;

    window.Swal.fire({
        title: 'Activate User?',
        text: 'This will allow the user to access the system.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, Activate',
        confirmButtonColor: '#1a472a',
        background: isDarkMode() ? '#1f2937' : '#ffffff',
        color: isDarkMode() ? '#f3f4f6' : '#111827'
    }).then(result => {
        if (result.isConfirmed) performUserAction(userId, 'activate');
    });
}, { preventDefault: true });

window.EventDelegation.register('delete-user', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) return;

    window.Swal.fire({
        title: 'Delete User?',
        html: '<div style="text-align:left">' +
              '<p>This <strong>permanently</strong> deletes the user account and its player profile. It will also:</p>' +
              '<ul style="text-align:left;margin:.25rem 0 0 1.1rem;list-style:disc">' +
              '<li>Remove them from all teams and sub pools</li>' +
              '<li>Delete their career/season stats and history</li>' +
              '<li>Strip their Discord roles</li></ul>' +
              '<p style="margin-top:.5rem;font-size:.85em;opacity:.75">Matches they refereed are kept (the referee link is cleared, not the match). This cannot be undone.</p></div>',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, Delete',
        cancelButtonText: 'Cancel',
        confirmButtonColor: '#dc2626',
        background: isDarkMode() ? '#1f2937' : '#ffffff',
        color: isDarkMode() ? '#f3f4f6' : '#111827'
    }).then(result => {
        if (result.isConfirmed) performUserAction(userId, 'delete');
    });
}, { preventDefault: true });

// Remove a rostered player's conflicting Pub League sub status. The popup spells
// out exactly what will change so the admin is making an informed override.
window.EventDelegation.register('remove-sub-status', function(element, e) {
    e.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) return;
    const name = escapeHtml(element.dataset.playerName || 'This player');
    const team = escapeHtml(element.dataset.teamName || 'their team');
    const division = escapeHtml(element.dataset.division || 'their division');
    const subList = escapeHtml(element.dataset.divisions || 'a sub list');

    window.Swal.fire({
        title: 'Remove from sub list?',
        html: '<div style="text-align:left">' +
              '<p><strong>' + name + '</strong> is rostered on <strong>' + team + '</strong> (' + division +
              ') but is still on the <strong>' + subList + '</strong> sub list.</p>' +
              '<p style="margin-top:.5rem">This will:</p>' +
              '<ul style="text-align:left;margin:.25rem 0 0 1.1rem;list-style:disc">' +
              '<li>Take them off the ' + subList + ' sub list</li>' +
              '<li>Remove the matching sub role on Discord</li></ul>' +
              '<p style="margin-top:.5rem;font-size:.85em;opacity:.75">ECS FC sub status is kept. ' +
              'You can re-add them to a sub pool later if needed.</p></div>',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, remove sub status',
        cancelButtonText: 'Keep as is',
        confirmButtonColor: '#b45309',
        background: isDarkMode() ? '#1f2937' : '#ffffff',
        color: isDarkMode() ? '#f3f4f6' : '#111827'
    }).then(result => {
        if (result.isConfirmed) removeSubStatus(userId);
    });
}, { preventDefault: true });

function removeSubStatus(userId) {
    const url = getUrl('removeSubStatusUrl', userId);
    if (!url) {
        showNotification('Error', 'URL not configured for remove-sub-status', 'error');
        return;
    }
    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() }
    })
    .then(response => {
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        return response.json();
    })
    .then(data => {
        if (data.success) {
            showNotification('Done', data.message, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            throw new Error(data.message || 'Action failed');
        }
    })
    .catch(error => {
        console.error('Error removing sub status:', error);
        showNotification('Error', error.message || 'Action failed', 'error');
    });
}

function performUserAction(userId, action) {
    const url = getUrl(`${action}UserUrl`, userId);
    if (!url) {
        showNotification('Error', `URL not configured for action: ${action}`, 'error');
        return;
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        }
    })
    .then(response => {
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        const ct = response.headers.get('content-type');
        if (!ct || !ct.includes('application/json')) throw new Error('Invalid response format');
        return response.json();
    })
    .then(data => {
        if (data.success) {
            showNotification('Success', data.message, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            throw new Error(data.message || 'Action failed');
        }
    })
    .catch(error => {
        console.error('Error performing user action:', error);
        showNotification('Error', error.message || 'Action failed', 'error');
    });
}

// ============================================================================
// BULK ACTIONS
// ============================================================================

function getSelectedUserIds() {
    return Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);
}

window.EventDelegation.register('bulk-action', function(element, e) {
    e.preventDefault();

    const action = element.dataset.bulkAction;
    if (!action) return;

    const selectedUsers = getSelectedUserIds();
    if (selectedUsers.length === 0) {
        showNotification('No Selection', 'Please select users to perform bulk actions on.', 'warning');
        return;
    }

    const actionText = action.charAt(0).toUpperCase() + action.slice(1);
    // Spell out the downstream effect so a bulk action isn't a mystery click.
    const bulkConsequence = {
        'delete': 'Permanently deletes these accounts, their player profiles, stats, and Discord roles. Cannot be undone.',
        'deactivate': 'Blocks these users from accessing the app and strips their Discord roles. Their roster/stats are kept.',
        'activate': 'Restores app access and re-syncs their Discord roles.',
        'approve': 'Approves these users and grants their league/Discord roles.'
    }[action] || '';

    window.Swal.fire({
        title: `${actionText} ${selectedUsers.length} users?`,
        html: bulkConsequence
            ? '<p style="text-align:left;font-size:.9em">' + bulkConsequence + '</p>'
            : undefined,
        icon: action === 'delete' ? 'warning' : 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes',
        cancelButtonText: 'Cancel',
        confirmButtonColor: action === 'delete' ? '#dc2626' : '#1a472a',
        background: isDarkMode() ? '#1f2937' : '#ffffff',
        color: isDarkMode() ? '#f3f4f6' : '#111827'
    }).then(result => {
        if (result.isConfirmed) performBulkAction(action, selectedUsers);
    });
}, { preventDefault: true });

window.EventDelegation.register('bulk-approve-users', function(element, e) {
    e.preventDefault();

    const selectedUsers = getSelectedUserIds();
    if (selectedUsers.length === 0) {
        showNotification('No Selection', 'Please select users to approve.', 'warning');
        return;
    }

    window.Swal.fire({
        title: `Approve ${selectedUsers.length} selected users?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, Approve',
        confirmButtonColor: '#1a472a',
        background: isDarkMode() ? '#1f2937' : '#ffffff',
        color: isDarkMode() ? '#f3f4f6' : '#111827'
    }).then(result => {
        if (result.isConfirmed) performBulkAction('approve', selectedUsers);
    });
}, { preventDefault: true });

function performBulkAction(action, selectedUsers) {
    const url = getUrl('bulkActionsUrl');
    if (!url) {
        showNotification('Error', 'Bulk actions URL not configured', 'error');
        return;
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({ action: action, user_ids: selectedUsers })
    })
    .then(response => {
        if (!response.ok) throw new Error(`Server error: ${response.status}`);
        const ct = response.headers.get('content-type');
        if (!ct || !ct.includes('application/json')) throw new Error('Invalid response format');
        return response.json();
    })
    .then(data => {
        if (data.success) {
            showNotification('Success', data.message, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            throw new Error(data.message || 'Bulk action failed');
        }
    })
    .catch(error => {
        console.error('Error performing bulk action:', error);
        showNotification('Error', error.message || 'Bulk action failed', 'error');
    });
}

// ============================================================================
// CREATE / EXPORT / SYNC USERS
// ============================================================================

window.EventDelegation.register('create-user', function(element, e) {
    e.preventDefault();
    showNotification('Create User', 'Users are created automatically when they register. Use the approval system to manage new users.', 'info');
}, { preventDefault: true });

window.EventDelegation.register('export-users', function(element, e) {
    e.preventDefault();
    const exportType = element.dataset.exportType || 'users';
    const dark = isDarkMode();

    window.Swal.fire({
        title: 'Export User Data',
        html: `
            <div class="mb-4">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Export Type</label>
                <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="userExportType" data-form-select>
                    <option value="users" ${exportType === 'users' ? 'selected' : ''}>All Users</option>
                    <option value="roles" ${exportType === 'roles' ? 'selected' : ''}>User Roles</option>
                    <option value="activity" ${exportType === 'activity' ? 'selected' : ''}>Activity Data</option>
                </select>
            </div>
            <div class="mb-4">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Date Range</label>
                <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="userExportDateRange" data-form-select>
                    <option value="all">All Time</option>
                    <option value="7_days">Last 7 Days</option>
                    <option value="30_days">Last 30 Days</option>
                    <option value="90_days">Last 90 Days</option>
                </select>
            </div>
        `,
        background: dark ? '#1f2937' : '#ffffff',
        color: dark ? '#f3f4f6' : '#111827',
        showCancelButton: true,
        confirmButtonText: 'Export',
        preConfirm: () => ({
            type: document.getElementById('userExportType').value,
            date_range: document.getElementById('userExportDateRange').value,
            format: 'json'
        })
    }).then(result => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Exporting Users...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/users/analytics/export', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(result.value)
                    })
                    .then(response => {
                        if (!response.ok) throw new Error(`Server error: ${response.status}`);
                        const ct = response.headers.get('content-type');
                        if (!ct || !ct.includes('application/json')) throw new Error('Invalid response format');
                        return response.json();
                    })
                    .then(data => {
                        if (data.success) {
                            const blob = new Blob([JSON.stringify(data.export_data, null, 2)], { type: 'application/json' });
                            const url = window.URL.createObjectURL(blob);
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = data.filename || 'user-export.json';
                            document.body.appendChild(a);
                            a.click();
                            window.URL.revokeObjectURL(url);
                            document.body.removeChild(a);

                            window.Swal.fire({
                                title: 'Export Complete!',
                                html: `<p>${data.message}</p><p class="text-muted small mt-2">File: ${data.filename}</p>`,
                                icon: 'success'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to export users', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[export-users] Error:', error);
                        window.Swal.fire('Error', 'Failed to export users. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
}, { preventDefault: true });

window.EventDelegation.register('sync-users', function(element, e) {
    e.preventDefault();
    showNotification('Sync Users', 'WooCommerce sync is not currently enabled. User data syncs automatically through Discord.', 'info');
}, { preventDefault: true });

// ============================================================================
// INITIALIZATION
// ============================================================================

function initUserManagementComprehensive() {
    if (_initialized) return;

    // Page guard
    const modalEl = document.getElementById('editUserModal');
    const userTable = document.querySelector('.user-checkbox');
    if (!modalEl && !userTable) return;

    _initialized = true;
    editUserModalEl = modalEl;

    // Form submit handler
    const form = document.getElementById('editUserForm');
    if (form) {
        form.addEventListener('submit', handleEditUserSubmit);
    }

    // Modal close buttons
    if (editUserModalEl) {
        document.querySelectorAll('[data-modal-hide="editUserModal"]').forEach(btn => {
            btn.addEventListener('click', () => closeModal(editUserModalEl));
        });

        // Backdrop click
        editUserModalEl.addEventListener('click', (e) => {
            if (e.target === editUserModalEl) closeModal(editUserModalEl);
        });
    }

    // Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && editUserModalEl && !editUserModalEl.classList.contains('hidden')) {
            closeModal(editUserModalEl);
        }
    });

    // Select all checkbox
    const selectAll = document.getElementById('selectAll');
    if (selectAll) {
        selectAll.addEventListener('change', function() {
            document.querySelectorAll('.user-checkbox').forEach(cb => {
                cb.checked = this.checked;
            });
        });
    }

    // League type dropdown change handlers
    ['Primary', 'Secondary', 'Tertiary'].forEach(tier => {
        const select = document.getElementById(`edit${tier}LeagueType`);
        if (select) {
            select.addEventListener('change', function() {
                handleLeagueTypeChange(tier.toLowerCase(), this.value);
            });
        }
    });

    // Real-time search
    const searchInput = document.getElementById('search');
    if (searchInput) {
        let searchTimeout;
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                document.getElementById('filterForm').submit();
            }, 500);
        });
    }

    console.log('[UserManagement] Comprehensive module initialized');
}

// Register with InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('user-management-comprehensive', initUserManagementComprehensive, {
        priority: 50,
        reinitializable: false,
        description: 'Comprehensive user management handlers'
    });
}
