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
    // Only replace '/0' pattern to avoid corrupting IDs that contain '0'
    if (userId && url) {
        url = url.replace('/0', '/' + userId);
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
    if (typeof window.ModalManager !== 'undefined') {
        editUserModal = window.ModalManager.getInstance('editUserModal');
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
    if (typeof window.Swal !== 'undefined') {
        const isDark = document.documentElement.classList.contains('dark');
        window.Swal.fire({
            title: title,
            html: '<div class="flex justify-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status" data-spinner></div></div>',
            allowOutsideClick: false,
            showConfirmButton: false,
            background: isDark ? '#1f2937' : '#ffffff',
            color: isDark ? '#f3f4f6' : '#111827'
        });
    }
}

/**
 * Close any open window.Swal dialog
 */
function closeLoading() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.close();
    }
}

/**
 * Show notification
 */
function showNotification(title, message, type = 'info') {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire(title, message, type);
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
        if (playerFields) playerFields.classList.remove('hidden');
        if (noPlayerMessage) noPlayerMessage.classList.add('hidden');
        if (isCurrentPlayerCheckbox) {
            isCurrentPlayerCheckbox.checked = user.player.is_current_player || false;
            isCurrentPlayerCheckbox.disabled = false;
        }
        // League/team fields are managed by the template's three-tier system
    } else {
        if (playerFields) playerFields.classList.add('hidden');
        if (noPlayerMessage) noPlayerMessage.classList.remove('hidden');
        if (isCurrentPlayerCheckbox) {
            isCurrentPlayerCheckbox.checked = false;
            isCurrentPlayerCheckbox.disabled = true;
        }
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
window.EventDelegation.register('reset-user-password', function(element, e) {
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
window.EventDelegation.register('approve-user-status', function(element, e) {
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
window.EventDelegation.register('remove-user', function(element, e) {
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
// EDIT USER - handled by the template's inline three-tier system
// ============================================================================

// ============================================================================
// APPROVE USER
// ============================================================================

window.EventDelegation.register('approve-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[approve-user] Missing user ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
    }
}, { preventDefault: true });

// ============================================================================
// DEACTIVATE USER
// ============================================================================

window.EventDelegation.register('deactivate-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[deactivate-user] Missing user ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
    }
}, { preventDefault: true });

// ============================================================================
// ACTIVATE USER
// ============================================================================

window.EventDelegation.register('activate-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[activate-user] Missing user ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
    }
}, { preventDefault: true });

// ============================================================================
// DELETE USER
// ============================================================================

window.EventDelegation.register('delete-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[delete-user] Missing user ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
    }
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
    .then(response => {
        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Invalid response format - expected JSON');
        }
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
// TOGGLE SELECT ALL
// ============================================================================
// Note: toggle-select-all is handled by form-actions.js (generic implementation)
// Use data-target=".user-checkbox" in the HTML to specify checkbox selector

// ============================================================================
// BULK ACTIONS
// ============================================================================

window.EventDelegation.register('bulk-action', function(element, e) {
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

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
    }
}, { preventDefault: true });

/**
 * Handle bulk approve button (convenience action)
 */
window.EventDelegation.register('bulk-approve-users', function(element, e) {
    e.preventDefault();

    const selectedUsers = getSelectedUserIds();

    if (selectedUsers.length === 0) {
        showNotification('No Selection', 'Please select users to approve.', 'warning');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
    }
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
    .then(response => {
        if (!response.ok) {
            throw new Error(`Server error: ${response.status}`);
        }
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            throw new Error('Invalid response format - expected JSON');
        }
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
// CREATE USER
// ============================================================================

window.EventDelegation.register('create-user', function(element, e) {
    e.preventDefault();
    showNotification('Create User', 'Users are created automatically when they register. Use the approval system to manage new users.', 'info');
}, { preventDefault: true });

// ============================================================================
// EXPORT USERS
// ============================================================================

window.EventDelegation.register('export-users', function(element, e) {
    e.preventDefault();
    const exportType = element.dataset.exportType || 'users';

    if (typeof window.Swal === 'undefined') {
        console.error('[export-users] SweetAlert2 not available');
        return;
    }

    const isDark = document.documentElement.classList.contains('dark');
    window.Swal.fire({
        title: 'Export User Data',
        html: `
            <div class="mb-4">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Export Type</label>
                <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="userExportType" data-form-select>
                    <option value="users" ${exportType === 'users' ? 'selected' : ''}>All Users</option>
                    <option value="roles" ${exportType === 'roles' ? 'selected' : ''}>User Roles</option>
                    <option value="activity" ${exportType === 'activity' ? 'selected' : ''}>Activity Data</option>
                </select>
            </div>
            <div class="mb-4">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Date Range</label>
                <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="userExportDateRange" data-form-select>
                    <option value="all">All Time</option>
                    <option value="7_days">Last 7 Days</option>
                    <option value="30_days">Last 30 Days</option>
                    <option value="90_days">Last 90 Days</option>
                </select>
            </div>
        `,
        background: isDark ? '#1f2937' : '#ffffff',
        color: isDark ? '#f3f4f6' : '#111827',
        showCancelButton: true,
        confirmButtonText: 'Export',
        preConfirm: () => {
            return {
                type: document.getElementById('userExportType').value,
                date_range: document.getElementById('userExportDateRange').value,
                format: 'json'
            };
        }
    }).then((result) => {
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
                        if (!response.ok) {
                            throw new Error(`Server error: ${response.status}`);
                        }
                        const contentType = response.headers.get('content-type');
                        if (!contentType || !contentType.includes('application/json')) {
                            throw new Error('Invalid response format');
                        }
                        return response.json();
                    })
                    .then(data => {
                        if (data.success) {
                            // Create download link
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

// ============================================================================
// SYNC USERS
// ============================================================================

window.EventDelegation.register('sync-users', function(element, e) {
    e.preventDefault();
    showNotification('Sync Users', 'WooCommerce sync is not currently enabled. User data syncs automatically through Discord.', 'info');
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
            if (modalEl && modalEl._flowbiteModal) {
                modalEl._flowbiteModal.hide();
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
function initUserManagementComprehensive() {
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

    console.log('[window.EventDelegation] User management comprehensive initialized');
}

// Register with window.InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('user-management-comprehensive', initUserManagementComprehensive, {
        priority: 50,
        reinitializable: false,
        description: 'Comprehensive user management handlers'
    });
}

// Fallback
// window.InitSystem handles initialization

// Handlers loaded
