import { EventDelegation } from '../core.js';
import { InitSystem } from '../../init-system.js';

let _initialized = false;

/**
 * Comprehensive User Management Action Handlers
 * ==============================================
 * Handles all user management actions for the comprehensive user management page:
 * - Edit user (modal)
 * - Approve/deactivate/activate/delete user
 * - Bulk actions (approve, activate, deactivate, delete)
 * - Create user, export users, sync users
 * - Select all checkbox toggle
 *
 * Migrated from inline scripts in manage_users_comprehensive.html
 *
 * @version 1.0.0
 */

// ============================================================================
// CONFIGURATION
// ============================================================================

/**
 * Get CSRF token from the page
 */
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

/**
 * Get URL config from window object or generate from pattern
 */
function getUrl(key, userId = null) {
    const config = window.USER_MGMT_CONFIG || {};
    let url = config[key] || '';

    // If userId provided, replace placeholder
    if (userId && url) {
        url = url.replace('/0', '/' + userId).replace('0', userId);
    }

    return url;
}

// ============================================================================
// MODAL STATE
// ============================================================================

let editUserModal = null;
let editUserForm = null;

/**
 * Initialize modal references when DOM is ready
 */
function initModalReferences() {
    if (typeof ModalManager !== 'undefined') {
        editUserModal = ModalManager.getInstance('editUserModal');
    }
    editUserForm = document.getElementById('editUserForm');
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Filter teams by league in a select element
 */
function filterTeamsByLeague(leagueId, teamSelect, showLeagueName = false) {
    const currentValue = teamSelect.value;
    const allOptions = teamSelect.querySelectorAll('option[data-league]');

    allOptions.forEach(option => {
        if (!leagueId || option.dataset.league === leagueId) {
            option.style.display = '';
        } else {
            option.style.display = 'none';
        }
    });

    // Reset selection if current selection is now hidden
    const currentOption = teamSelect.querySelector(`option[value="${currentValue}"]`);
    if (currentOption && currentOption.style.display === 'none') {
        teamSelect.value = '';
    }
}

/**
 * Show loading dialog
 */
function showLoading(title = 'Loading...') {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: title,
            html: '<div class="text-center"><div class="spinner-border text-primary" role="status" data-spinner></div></div>',
            allowOutsideClick: false,
            showConfirmButton: false
        });
    }
}

/**
 * Close any open Swal dialog
 */
function closeLoading() {
    if (typeof Swal !== 'undefined') {
        Swal.close();
    }
}

/**
 * Show notification
 */
function showNotification(title, message, type = 'info') {
    if (typeof Swal !== 'undefined') {
        Swal.fire(title, message, type);
    } else {
        alert(`${title}: ${message}`);
    }
}

/**
 * Populate the edit user form with user data
 */
function populateEditForm(user) {
    // Basic user info
    document.getElementById('editUserId').value = user.id;
    document.getElementById('editUsername').value = user.username || '';
    document.getElementById('editEmail').value = user.email || '';
    document.getElementById('editRealName').value = user.real_name || '';
    document.getElementById('editIsApproved').checked = user.is_approved;
    document.getElementById('editIsActive').checked = user.is_active;

    // Set selected roles - pre-select user's current roles using checkboxes
    const rolesContainer = document.getElementById('editRolesContainer');
    const userRoleIds = user.roles || [];
    if (rolesContainer) {
        rolesContainer.querySelectorAll('[data-role-checkbox]').forEach(checkbox => {
            checkbox.checked = userRoleIds.includes(parseInt(checkbox.value));
        });
    }

    // Player profile section
    const playerFields = document.getElementById('playerFields');
    const noPlayerMessage = document.getElementById('noPlayerMessage');
    const isCurrentPlayerCheckbox = document.getElementById('editIsCurrentPlayer');

    if (user.has_player && user.player) {
        // Show player fields, hide no-player message
        if (playerFields) playerFields.classList.remove('d-none');
        if (noPlayerMessage) noPlayerMessage.classList.add('d-none');

        // Set active player status
        if (isCurrentPlayerCheckbox) {
            isCurrentPlayerCheckbox.checked = user.player.is_current_player || false;
            isCurrentPlayerCheckbox.disabled = false;
        }

        // Primary league and team
        const leagueSelect = document.getElementById('editLeague');
        const teamSelect = document.getElementById('editTeam');

        if (leagueSelect) {
            leagueSelect.value = user.player.league_id || '';
            leagueSelect.disabled = false;
        }

        // Filter teams first, then set value
        if (teamSelect) {
            filterTeamsByLeague(user.player.league_id ? user.player.league_id.toString() : '', teamSelect);
            teamSelect.value = user.player.team_id || '';
            teamSelect.disabled = false;
        }

        // Secondary league and team
        const secondaryLeagueSelect = document.getElementById('editSecondaryLeague');
        const secondaryTeamSelect = document.getElementById('editSecondaryTeam');

        if (secondaryLeagueSelect) {
            secondaryLeagueSelect.value = user.player.secondary_league_id || '';
            secondaryLeagueSelect.disabled = false;
        }

        if (secondaryTeamSelect) {
            filterTeamsByLeague(user.player.secondary_league_id ? user.player.secondary_league_id.toString() : '', secondaryTeamSelect, true);
            secondaryTeamSelect.value = user.player.secondary_team_id || '';
            secondaryTeamSelect.disabled = false;
        }
    } else {
        // Hide player fields, show no-player message
        if (playerFields) playerFields.classList.add('d-none');
        if (noPlayerMessage) noPlayerMessage.classList.remove('d-none');

        // Disable all player-related fields
        if (isCurrentPlayerCheckbox) {
            isCurrentPlayerCheckbox.checked = false;
            isCurrentPlayerCheckbox.disabled = true;
        }

        ['editLeague', 'editTeam', 'editSecondaryLeague', 'editSecondaryTeam'].forEach(id => {
            const el = document.getElementById(id);
            if (el) {
                el.value = '';
                el.disabled = true;
            }
        });
    }

    // Set form action
    if (editUserForm) {
        editUserForm.action = getUrl('editUserUrl', user.id);
    }
}

/**
 * Get selected user IDs from checkboxes
 */
function getSelectedUserIds() {
    return Array.from(document.querySelectorAll('.user-checkbox:checked')).map(cb => cb.value);
}

// ============================================================================
// RESET USER PASSWORD
// ============================================================================

/**
 * Handle Reset Password button click
 * Opens the reset password modal for a user
 */
EventDelegation.register('reset-user-password', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    const username = element.dataset.username;

    if (!userId) {
        console.error('[reset-user-password] Missing user ID');
        return;
    }

    // Call the global handler function defined in manage_users.html
    if (typeof window.setUserForResetPassword === 'function') {
        window.setUserForResetPassword(userId, username);
    } else {
        console.error('[reset-user-password] setUserForResetPassword function not found');
    }
}, { preventDefault: true });

// ============================================================================
// APPROVE USER STATUS (for manage_users.html)
// ============================================================================

/**
 * Handle Approve User button click (manage_users.html variant)
 * Approves a pending user via global handler
 */
EventDelegation.register('approve-user-status', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[approve-user-status] Missing user ID');
        return;
    }

    // Call the global handler function defined in manage_users.html
    if (typeof window.handleApproveUserClick === 'function') {
        window.handleApproveUserClick(userId);
    } else {
        console.error('[approve-user-status] handleApproveUserClick function not found');
    }
}, { preventDefault: true });

// ============================================================================
// REMOVE USER (for manage_users.html)
// ============================================================================

/**
 * Handle Remove User button click
 * Removes a user via global handler
 */
EventDelegation.register('remove-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[remove-user] Missing user ID');
        return;
    }

    // Call the global handler function defined in manage_users.html
    if (typeof window.handleRemoveUserClick === 'function') {
        window.handleRemoveUserClick(userId);
    } else {
        console.error('[remove-user] handleRemoveUserClick function not found');
    }
}, { preventDefault: true });

// ============================================================================
// EDIT USER
// ============================================================================

/**
 * Handle Edit User button click
 * Loads user data and opens the edit modal
 */
EventDelegation.register('edit-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[edit-user] Missing user ID');
        return;
    }

    showLoading('Loading User Data');

    // Fetch user data
    fetch(getUrl('userDetailsUrl', userId))
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                populateEditForm(data.user);
                closeLoading();
                if (editUserModal) {
                    editUserModal.show();
                } else {
                    // Fallback to bootstrap modal
                    const modalEl = document.getElementById('editUserModal');
                    if (modalEl && typeof bootstrap !== 'undefined') {
                        const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
                        modal.show();
                    }
                }
            } else {
                throw new Error(data.error || 'Failed to load user');
            }
        })
        .catch(error => {
            closeLoading();
            showNotification('Error', error.message || 'Failed to load user data', 'error');
        });
}, { preventDefault: true });

// ============================================================================
// APPROVE USER
// ============================================================================

EventDelegation.register('approve-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[approve-user] Missing user ID');
        return;
    }

    if (typeof Swal === 'undefined') {
        if (confirm('Approve this user? This will allow them to access the system.')) {
            performUserAction(userId, 'approve');
        }
        return;
    }

    Swal.fire({
        title: 'Approve User?',
        text: 'This will approve the user and allow them to access the system.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, Approve',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            performUserAction(userId, 'approve');
        }
    });
}, { preventDefault: true });

// ============================================================================
// DEACTIVATE USER
// ============================================================================

EventDelegation.register('deactivate-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[deactivate-user] Missing user ID');
        return;
    }

    if (typeof Swal === 'undefined') {
        if (confirm('Deactivate this user? This will prevent them from accessing the system.')) {
            performUserAction(userId, 'deactivate');
        }
        return;
    }

    Swal.fire({
        title: 'Deactivate User?',
        text: 'This will prevent the user from accessing the system.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, Deactivate',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            performUserAction(userId, 'deactivate');
        }
    });
}, { preventDefault: true });

// ============================================================================
// ACTIVATE USER
// ============================================================================

EventDelegation.register('activate-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[activate-user] Missing user ID');
        return;
    }

    if (typeof Swal === 'undefined') {
        if (confirm('Activate this user? This will allow them to access the system.')) {
            performUserAction(userId, 'activate');
        }
        return;
    }

    Swal.fire({
        title: 'Activate User?',
        text: 'This will allow the user to access the system.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, Activate',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            performUserAction(userId, 'activate');
        }
    });
}, { preventDefault: true });

// ============================================================================
// DELETE USER
// ============================================================================

EventDelegation.register('delete-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[delete-user] Missing user ID');
        return;
    }

    if (typeof Swal === 'undefined') {
        if (confirm('DELETE this user? This action cannot be undone!')) {
            performUserAction(userId, 'delete');
        }
        return;
    }

    Swal.fire({
        title: 'Delete User?',
        text: 'This will permanently delete the user. This action cannot be undone!',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, Delete',
        cancelButtonText: 'Cancel',
        confirmButtonColor: '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            performUserAction(userId, 'delete');
        }
    });
}, { preventDefault: true });

/**
 * Perform a user action (approve, deactivate, activate, delete)
 */
function performUserAction(userId, action) {
    const urlKey = `${action}UserUrl`;
    const url = getUrl(urlKey, userId);

    if (!url) {
        showNotification('Error', `URL not configured for action: ${action}`, 'error');
        return;
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRFToken': getCsrfToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Success', data.message, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showNotification('Error', data.message, 'error');
        }
    })
    .catch(error => {
        showNotification('Error', error.message || 'Action failed', 'error');
    });
}

// ============================================================================
// TOGGLE SELECT ALL
// ============================================================================
// Note: toggle-select-all is handled by form-actions.js (generic implementation)
// Use data-target=".user-checkbox" in the HTML to specify checkbox selector

// ============================================================================
// BULK ACTIONS
// ============================================================================

EventDelegation.register('bulk-action', function(element, e) {
    e.preventDefault();

    const action = element.dataset.bulkAction;
    if (!action) {
        console.error('[bulk-action] Missing bulk action type');
        return;
    }

    const selectedUsers = getSelectedUserIds();

    if (selectedUsers.length === 0) {
        showNotification('No Selection', 'Please select users to perform bulk actions on.', 'warning');
        return;
    }

    const actionText = action.charAt(0).toUpperCase() + action.slice(1);

    if (typeof Swal === 'undefined') {
        if (confirm(`${actionText} ${selectedUsers.length} selected users?`)) {
            performBulkAction(action, selectedUsers);
        }
        return;
    }

    Swal.fire({
        title: `${actionText} Selected Users?`,
        text: `This will ${action} ${selectedUsers.length} selected users.`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: `Yes, ${actionText}`,
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            performBulkAction(action, selectedUsers);
        }
    });
}, { preventDefault: true });

/**
 * Handle bulk approve button (convenience action)
 */
EventDelegation.register('bulk-approve-users', function(element, e) {
    e.preventDefault();

    const selectedUsers = getSelectedUserIds();

    if (selectedUsers.length === 0) {
        showNotification('No Selection', 'Please select users to approve.', 'warning');
        return;
    }

    if (typeof Swal === 'undefined') {
        if (confirm(`Approve ${selectedUsers.length} selected users?`)) {
            performBulkAction('approve', selectedUsers);
        }
        return;
    }

    Swal.fire({
        title: 'Approve Selected Users?',
        text: `This will approve ${selectedUsers.length} selected users.`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, Approve',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            performBulkAction('approve', selectedUsers);
        }
    });
}, { preventDefault: true });

/**
 * Perform bulk action on selected users
 */
function performBulkAction(action, selectedUsers) {
    const url = getUrl('bulkActionsUrl');

    if (!url) {
        showNotification('Error', 'Bulk actions URL not configured', 'error');
        return;
    }

    const formData = new FormData();
    formData.append('action', action);
    formData.append('csrf_token', getCsrfToken());
    selectedUsers.forEach(userId => {
        formData.append('user_ids', userId);
    });

    fetch(url, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Success', data.message, 'success');
            setTimeout(() => location.reload(), 1500);
        } else {
            showNotification('Error', data.message, 'error');
        }
    })
    .catch(error => {
        showNotification('Error', error.message || 'Bulk action failed', 'error');
    });
}

// ============================================================================
// CREATE USER
// ============================================================================

EventDelegation.register('create-user', function(element, e) {
    e.preventDefault();
    showNotification('Feature Coming Soon', 'User creation functionality will be added soon.', 'info');
}, { preventDefault: true });

// ============================================================================
// EXPORT USERS
// ============================================================================

EventDelegation.register('export-users', function(element, e) {
    e.preventDefault();
    const exportType = element.dataset.exportType || 'all';
    showNotification('Feature Coming Soon', `User export (${exportType}) functionality will be added soon.`, 'info');
}, { preventDefault: true });

// ============================================================================
// SYNC USERS
// ============================================================================

EventDelegation.register('sync-users', function(element, e) {
    e.preventDefault();
    showNotification('Feature Coming Soon', 'WooCommerce sync functionality will be added soon.', 'info');
}, { preventDefault: true });

// ============================================================================
// SETUP LEAGUE-TEAM FILTERING
// ============================================================================

/**
 * Setup league-team filtering for the edit form
 */
function setupLeagueTeamFiltering() {
    const leagueSelect = document.getElementById('editLeague');
    const teamSelect = document.getElementById('editTeam');
    const secondaryLeagueSelect = document.getElementById('editSecondaryLeague');
    const secondaryTeamSelect = document.getElementById('editSecondaryTeam');

    // Filter primary teams when primary league changes
    if (leagueSelect && teamSelect) {
        leagueSelect.addEventListener('change', function() {
            filterTeamsByLeague(this.value, teamSelect);
        });
    }

    // Filter secondary teams when secondary league changes
    if (secondaryLeagueSelect && secondaryTeamSelect) {
        secondaryLeagueSelect.addEventListener('change', function() {
            filterTeamsByLeague(this.value, secondaryTeamSelect, true);
        });
    }
}

// ============================================================================
// FORM SUBMISSION HANDLER
// ============================================================================

/**
 * Handle edit user form submission
 */
function handleEditUserSubmit(e) {
    e.preventDefault();

    if (!editUserForm) return;

    const formData = new FormData(editUserForm);

    showLoading('Saving...');

    fetch(editUserForm.action, {
        method: 'POST',
        body: formData
    })
    .then(response => {
        const contentType = response.headers.get('content-type');
        if (contentType && contentType.includes('application/json')) {
            return response.json();
        }
        if (response.redirected || response.ok) {
            return { success: true, message: 'User updated successfully' };
        }
        throw new Error('Update failed');
    })
    .then(data => {
        if (editUserModal) {
            editUserModal.hide();
        } else {
            const modalEl = document.getElementById('editUserModal');
            if (modalEl && typeof bootstrap !== 'undefined') {
                const modal = bootstrap.Modal.getInstance(modalEl);
                if (modal) modal.hide();
            }
        }
        showNotification('Success', data.message || 'User updated successfully', 'success');
        setTimeout(() => location.reload(), 1500);
    })
    .catch(error => {
        showNotification('Error', error.message || 'Failed to update user', 'error');
    });
}

// ============================================================================
// INITIALIZATION
// ============================================================================

/**
 * Initialize the comprehensive user management module
 */
function init() {
    if (_initialized) return;

    // Page guard - only initialize on user management page
    const editUserModal = document.getElementById('editUserModal');
    const userTable = document.querySelector('.user-checkbox');
    if (!editUserModal && !userTable) return;

    _initialized = true;

    // Initialize modal references
    initModalReferences();

    // Setup league-team filtering
    setupLeagueTeamFiltering();

    // Attach form submit handler
    const form = document.getElementById('editUserForm');
    if (form) {
        form.addEventListener('submit', handleEditUserSubmit);
    }

    console.log('[EventDelegation] User management comprehensive initialized');
}

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('user-management-comprehensive', init, {
        priority: 50,
        reinitializable: false,
        description: 'Comprehensive user management handlers'
    });
}

// Fallback
// InitSystem handles initialization

console.log('[EventDelegation] User management comprehensive handlers loaded');
