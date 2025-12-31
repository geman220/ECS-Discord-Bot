/**
 * ============================================================================
 * ADMIN NOTIFICATION GROUPS - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles notification groups page interactions using data-attribute hooks
 * Follows event delegation pattern with InitSystem registration
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';
import { ModalManager } from './modal-manager.js';

// CSRF Token
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

// Module state
let currentMemberGroupId = null;
let searchTimeout = null;

// Store config from data attributes
let baseUrl = '/admin-panel';

/**
 * Initialize notification groups module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-notification-groups-config]');
    if (configEl) {
        baseUrl = configEl.dataset.baseUrl || '/admin-panel';
    }

    initializeEventDelegation();
    initializeFormHandlers();
}

/**
 * Initialize event delegation
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch (action) {
            case 'go-back':
                window.history.back();
                break;
            case 'view-group':
                viewGroup(target.dataset.groupId);
                break;
            case 'edit-group':
                editGroup(target.dataset.groupId);
                break;
            case 'manage-members':
                manageMembers(target.dataset.groupId, target.dataset.groupName);
                break;
            case 'send-to-group':
                sendToGroup(target.dataset.groupId, target.dataset.groupName);
                break;
            case 'delete-group':
                deleteGroup(target.dataset.groupId, target.dataset.groupName);
                break;
            case 'add-member':
                addMember(target.dataset.userId);
                break;
            case 'remove-member':
                removeMember(target.dataset.memberId);
                break;
        }
    });

    // Handle select changes
    document.addEventListener('change', function(e) {
        if (e.target.classList.contains('js-group-type-select')) {
            toggleGroupTypeOptions();
        }
        if (e.target.classList.contains('js-criteria-target-type')) {
            toggleCriteriaOptions();
        }
    });

    // Member search
    document.querySelector('.js-member-search')?.addEventListener('keyup', searchUsers);
}

/**
 * Initialize form handlers
 */
function initializeFormHandlers() {
    // Create group form
    document.querySelector('.js-create-group-form')?.addEventListener('submit', submitCreateGroup);

    // Edit group form
    document.querySelector('.js-edit-group-form')?.addEventListener('submit', submitEditGroup);
}

/**
 * Toggle group type options (dynamic vs static)
 */
function toggleGroupTypeOptions() {
    const groupType = document.getElementById('group_type')?.value;
    const dynamicOptions = document.getElementById('dynamicGroupOptions');
    const staticOptions = document.getElementById('staticGroupOptions');

    if (!dynamicOptions || !staticOptions) return;

    if (groupType === 'dynamic') {
        dynamicOptions.classList.remove('d-none');
        staticOptions.classList.add('d-none');
    } else {
        dynamicOptions.classList.add('d-none');
        staticOptions.classList.remove('d-none');
    }
}

/**
 * Toggle criteria sub-options
 */
function toggleCriteriaOptions() {
    const targetType = document.getElementById('criteria_target_type')?.value;

    // Hide all
    ['Team', 'League', 'Role', 'Pool'].forEach(type => {
        const container = document.getElementById(`criteria${type}Container`);
        if (container) container.classList.add('d-none');
    });

    // Show selected
    switch (targetType) {
        case 'team':
            document.getElementById('criteriaTeamContainer')?.classList.remove('d-none');
            break;
        case 'league':
            document.getElementById('criteriaLeagueContainer')?.classList.remove('d-none');
            break;
        case 'role':
            document.getElementById('criteriaRoleContainer')?.classList.remove('d-none');
            break;
        case 'pool':
            document.getElementById('criteriaPoolContainer')?.classList.remove('d-none');
            break;
    }
}

/**
 * Submit create group form
 */
async function submitCreateGroup(event) {
    event.preventDefault();

    const form = document.getElementById('createGroupForm');
    const formData = new FormData(form);

    // Build criteria object for dynamic groups
    const groupType = formData.get('group_type');
    let criteria = null;

    if (groupType === 'dynamic') {
        criteria = {
            target_type: formData.get('criteria_target_type'),
            platform: formData.get('criteria_platform')
        };

        const targetType = criteria.target_type;
        if (targetType === 'team') {
            criteria.team_ids = Array.from(document.getElementById('criteria_teams').selectedOptions).map(opt => opt.value);
        } else if (targetType === 'league') {
            criteria.league_ids = Array.from(document.getElementById('criteria_leagues').selectedOptions).map(opt => opt.value);
        } else if (targetType === 'role') {
            criteria.role_names = Array.from(document.getElementById('criteria_roles').selectedOptions).map(opt => opt.value);
        } else if (targetType === 'pool') {
            criteria.pool_type = formData.get('criteria_pool');
        }
    }

    const data = {
        name: formData.get('name'),
        description: formData.get('description'),
        group_type: groupType,
        criteria: criteria
    };

    try {
        const response = await fetch(`${baseUrl}/communication/notification-groups`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (result.success) {
            showSuccess('Notification group created successfully!', () => location.reload());
        } else {
            showError(result.error || 'Failed to create group');
        }
    } catch (error) {
        console.error('Error creating group:', error);
        showError('Failed to create group. Please try again.');
    }

    return false;
}

/**
 * View group details
 */
async function viewGroup(groupId) {
    ModalManager.show('viewGroupModal');

    const content = document.getElementById('viewGroupContent');
    content.innerHTML = '<div class="text-center py-4"><div class="spinner-border" role="status" data-spinner></div></div>';

    try {
        const response = await fetch(`${baseUrl}/communication/notification-groups/${groupId}`);
        const data = await response.json();

        if (data.success) {
            const group = data.group;
            document.getElementById('viewGroupTitle').textContent = group.name;

            let criteriaHtml = '';
            if (group.group_type === 'dynamic' && group.criteria) {
                criteriaHtml = `
                    <h6 class="mt-3">Targeting Criteria</h6>
                    <ul class="list-unstyled">
                        <li><strong>Target Type:</strong> ${group.criteria.target_type || 'All'}</li>
                        <li><strong>Platform:</strong> ${group.criteria.platform || 'All'}</li>
                        ${group.criteria.team_ids ? `<li><strong>Team IDs:</strong> ${group.criteria.team_ids.join(', ')}</li>` : ''}
                        ${group.criteria.league_ids ? `<li><strong>League IDs:</strong> ${group.criteria.league_ids.join(', ')}</li>` : ''}
                        ${group.criteria.role_names ? `<li><strong>Roles:</strong> ${group.criteria.role_names.join(', ')}</li>` : ''}
                        ${group.criteria.pool_type ? `<li><strong>Pool:</strong> ${group.criteria.pool_type}</li>` : ''}
                    </ul>
                `;
            }

            content.innerHTML = `
                <div class="row">
                    <div class="col-md-6">
                        <p><strong>Name:</strong> ${escapeHtml(group.name)}</p>
                        <p><strong>Type:</strong> <span class="badge bg-${group.group_type === 'dynamic' ? 'success' : 'info'}" data-badge>${group.group_type}</span></p>
                        <p><strong>Status:</strong> <span class="badge bg-${group.is_active ? 'success' : 'danger'}" data-badge>${group.is_active ? 'Active' : 'Inactive'}</span></p>
                    </div>
                    <div class="col-md-6">
                        <p><strong>Created:</strong> ${group.created_at || 'N/A'}</p>
                        <p><strong>Updated:</strong> ${group.updated_at || 'N/A'}</p>
                        <p><strong>Members:</strong> ${group.member_count || 0}</p>
                    </div>
                </div>
                ${group.description ? `<p><strong>Description:</strong> ${escapeHtml(group.description)}</p>` : ''}
                ${criteriaHtml}
            `;
        } else {
            content.innerHTML = '<div class="alert alert-danger" data-alert>Failed to load group details</div>';
        }
    } catch (error) {
        console.error('Error loading group:', error);
        content.innerHTML = '<div class="alert alert-danger" data-alert>Failed to load group details</div>';
    }
}

/**
 * Edit group
 */
async function editGroup(groupId) {
    try {
        const response = await fetch(`${baseUrl}/communication/notification-groups/${groupId}`);
        const data = await response.json();

        if (data.success) {
            const group = data.group;

            document.getElementById('edit_group_id').value = group.id;
            document.getElementById('edit_group_name').value = group.name;
            document.getElementById('edit_group_type').value = group.group_type;
            document.getElementById('edit_group_description').value = group.description || '';
            document.getElementById('edit_group_active').checked = group.is_active;

            // Show/hide dynamic criteria editor
            const dynamicCriteria = document.getElementById('editDynamicCriteria');
            if (group.group_type === 'dynamic') {
                dynamicCriteria.classList.remove('d-none');
                document.getElementById('editCriteriaContent').innerHTML = `
                    <p><strong>Current Criteria:</strong></p>
                    <pre class="bg-light p-2 rounded">${JSON.stringify(group.criteria, null, 2)}</pre>
                `;
            } else {
                dynamicCriteria.classList.add('d-none');
            }

            ModalManager.show('editGroupModal');
        } else {
            showError('Failed to load group data');
        }
    } catch (error) {
        console.error('Error loading group:', error);
        showError('Failed to load group data');
    }
}

/**
 * Submit edit group form
 */
async function submitEditGroup(event) {
    event.preventDefault();

    const groupId = document.getElementById('edit_group_id').value;
    const data = {
        name: document.getElementById('edit_group_name').value,
        description: document.getElementById('edit_group_description').value,
        is_active: document.getElementById('edit_group_active').checked
    };

    try {
        const response = await fetch(`${baseUrl}/communication/notification-groups/${groupId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(data)
        });

        const result = await response.json();

        if (result.success) {
            showSuccess('Group updated successfully!', () => location.reload());
        } else {
            showError(result.error || 'Failed to update group');
        }
    } catch (error) {
        console.error('Error updating group:', error);
        showError('Failed to update group. Please try again.');
    }

    return false;
}

/**
 * Delete group
 */
function deleteGroup(groupId, groupName) {
    if (typeof Swal === 'undefined') {
        if (!confirm(`Are you sure you want to delete "${groupName}"? This action cannot be undone.`)) return;
        performDeleteGroup(groupId);
        return;
    }

    Swal.fire({
        title: 'Delete Group?',
        text: `Are you sure you want to delete "${groupName}"? This action cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
        confirmButtonText: 'Yes, delete it!'
    }).then((result) => {
        if (result.isConfirmed) {
            performDeleteGroup(groupId);
        }
    });
}

/**
 * Perform group deletion
 */
async function performDeleteGroup(groupId) {
    try {
        const response = await fetch(`${baseUrl}/communication/notification-groups/${groupId}`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': csrfToken
            }
        });

        const data = await response.json();

        if (data.success) {
            showSuccess('The group has been deleted.', () => location.reload());
        } else {
            showError(data.error || 'Failed to delete group');
        }
    } catch (error) {
        console.error('Error deleting group:', error);
        showError('Failed to delete group. Please try again.');
    }
}

/**
 * Send notification to group
 */
function sendToGroup(groupId, groupName) {
    // Redirect to push notifications page with group pre-selected
    const pushUrl = window.notificationGroupsConfig?.pushNotificationsUrl || '/admin-panel/push-notifications';
    window.location.href = `${pushUrl}?target_type=group&group_id=${groupId}`;
}

/**
 * Manage members (for static groups)
 */
async function manageMembers(groupId, groupName) {
    currentMemberGroupId = groupId;
    document.getElementById('manage_members_group_id').value = groupId;
    document.getElementById('memberGroupName').textContent = groupName;

    ModalManager.show('manageMembersModal');

    // Load current members
    await loadMembers();
}

/**
 * Load current members
 */
async function loadMembers() {
    const groupId = currentMemberGroupId;

    try {
        const response = await fetch(`${baseUrl}/communication/notification-groups/${groupId}/members`);
        const data = await response.json();

        if (data.success) {
            const membersContainer = document.getElementById('currentMembers');
            document.getElementById('memberCount').textContent = data.members.length;

            if (data.members.length === 0) {
                membersContainer.innerHTML = '<div class="text-center text-muted py-3">No members yet</div>';
            } else {
                membersContainer.innerHTML = data.members.map(member => `
                    <div class="list-group-item member-item">
                        <div>
                            <strong>${escapeHtml(member.name || 'Unknown')}</strong>
                            <br><small class="text-muted">${escapeHtml(member.email || '')}</small>
                        </div>
                        <button class="c-btn c-btn--sm c-btn--outline-danger" data-action="remove-member" data-member-id="${member.id}" aria-label="Remove member"><i class="ti ti-x"></i></button>
                    </div>
                `).join('');
            }
        }
    } catch (error) {
        console.error('Error loading members:', error);
    }
}

/**
 * Search users for adding to group
 */
async function searchUsers() {
    const query = document.getElementById('memberSearch')?.value;

    if (!query || query.length < 2) {
        document.getElementById('searchResults').innerHTML = '<div class="text-center text-muted py-3">Type at least 2 characters</div>';
        return;
    }

    // Debounce search
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
        try {
            const response = await fetch(`${baseUrl}/communication/notification-groups/${currentMemberGroupId}/members/search?q=${encodeURIComponent(query)}`);
            const data = await response.json();

            if (data.success) {
                const resultsContainer = document.getElementById('searchResults');

                if (data.users.length === 0) {
                    resultsContainer.innerHTML = '<div class="text-center text-muted py-3">No users found</div>';
                } else {
                    resultsContainer.innerHTML = data.users.map(user => `
                        <button class="list-group-item list-group-item-action d-flex justify-content-between align-items-center"
                                data-action="add-member" data-user-id="${user.id}">
                            <div>
                                <strong>${escapeHtml(user.name || 'Unknown')}</strong>
                                <br><small class="text-muted">${escapeHtml(user.email || '')}</small>
                            </div>
                            <i class="ti ti-plus text-success"></i>
                        </button>
                    `).join('');
                }
            }
        } catch (error) {
            console.error('Error searching users:', error);
        }
    }, 300);
}

/**
 * Add member to group
 */
async function addMember(userId) {
    try {
        const response = await fetch(`${baseUrl}/communication/notification-groups/${currentMemberGroupId}/members`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ user_id: userId })
        });

        const data = await response.json();

        if (data.success) {
            await loadMembers();
            document.getElementById('memberSearch').value = '';
            document.getElementById('searchResults').innerHTML = '';
        } else {
            showError(data.error || 'Failed to add member');
        }
    } catch (error) {
        console.error('Error adding member:', error);
    }
}

/**
 * Remove member from group
 */
async function removeMember(userId) {
    try {
        const response = await fetch(`${baseUrl}/communication/notification-groups/${currentMemberGroupId}/members/${userId}`, {
            method: 'DELETE',
            headers: {
                'X-CSRFToken': csrfToken
            }
        });

        const data = await response.json();

        if (data.success) {
            await loadMembers();
        } else {
            showError(data.error || 'Failed to remove member');
        }
    } catch (error) {
        console.error('Error removing member:', error);
    }
}

/**
 * Escape HTML to prevent XSS
 */
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * Show success message
 */
function showSuccess(message, callback) {
    if (typeof Swal !== 'undefined') {
        Swal.fire('Success', message, 'success').then(() => {
            if (callback) callback();
        });
    } else {
        alert(message);
        if (callback) callback();
    }
}

/**
 * Show error message
 */
function showError(message) {
    if (typeof Swal !== 'undefined') {
        Swal.fire('Error', message, 'error');
    } else {
        alert(message);
    }
}

/**
 * Cleanup function
 */
function cleanup() {
    currentMemberGroupId = null;
    if (searchTimeout) {
        clearTimeout(searchTimeout);
        searchTimeout = null;
    }
}

// Register with InitSystem
InitSystem.register('admin-notification-groups', init, {
    priority: 30,
    reinitializable: true,
    cleanup: cleanup,
    description: 'Admin notification groups page functionality'
});

// Fallback for non-module usage
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Export for ES modules
export {
    init,
    cleanup,
    toggleGroupTypeOptions,
    toggleCriteriaOptions,
    submitCreateGroup,
    viewGroup,
    editGroup,
    submitEditGroup,
    deleteGroup,
    sendToGroup,
    manageMembers,
    loadMembers,
    searchUsers,
    addMember,
    removeMember
};

// Backward compatibility
window.adminNotificationGroupsInit = init;
window.toggleGroupTypeOptions = toggleGroupTypeOptions;
window.toggleCriteriaOptions = toggleCriteriaOptions;
window.submitCreateGroup = submitCreateGroup;
window.viewGroup = viewGroup;
window.editGroup = editGroup;
window.submitEditGroup = submitEditGroup;
window.deleteGroup = deleteGroup;
window.sendToGroup = sendToGroup;
window.manageMembers = manageMembers;
window.loadMembers = loadMembers;
window.searchUsers = searchUsers;
window.addMember = addMember;
window.removeMember = removeMember;
