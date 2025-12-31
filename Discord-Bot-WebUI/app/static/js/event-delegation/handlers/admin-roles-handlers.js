'use strict';

/**
 * Admin Roles Handlers
 *
 * Event delegation handlers for admin panel role management:
 * - roles/manage_roles.html
 *
 * @version 1.0.0
 */

import { EventDelegation } from '../core.js';

// Store references for modal management
let roleModal = null;
let roleDetailsModal = null;
let assignRoleModal = null;

/**
 * Initialize role management modals
 */
function initRoleModals() {
    if (typeof window.ModalManager !== 'undefined') {
        if (!roleModal) roleModal = window.ModalManager.getInstance('roleModal');
        if (!roleDetailsModal) roleDetailsModal = window.ModalManager.getInstance('roleDetailsModal');
        if (!assignRoleModal) assignRoleModal = window.ModalManager.getInstance('assignRoleModal');
    }
}

// ============================================================================
// ROLE CREATION & EDITING
// ============================================================================

/**
 * Create Role
 * Opens modal to create a new role
 */
EventDelegation.register('create-role', function(element, e) {
    e.preventDefault();
    initRoleModals();

    const roleForm = document.getElementById('roleForm');
    if (!roleForm) {
        console.error('[create-role] Role form not found');
        return;
    }

    // Reset form
    roleForm.reset();
    document.getElementById('roleId').value = '';

    const modalLabel = document.getElementById('roleModalLabel');
    if (modalLabel) {
        modalLabel.innerHTML = '<i class="ti ti-shield-plus me-2"></i>Create Role';
    }

    // Set the create action URL - we need to construct this from the page
    const createUrl = roleForm.dataset.createUrl || '/admin-panel/users/roles/create';
    roleForm.action = createUrl;

    if (roleModal) {
        roleModal.show();
    } else {
        // Fallback to Bootstrap modal
        const modalEl = document.getElementById('roleModal');
        if (modalEl && typeof bootstrap !== 'undefined') {
            const bsModal = new bootstrap.Modal(modalEl);
            bsModal.show();
        }
    }
});

/**
 * Edit Role
 * Loads role data and opens edit modal
 */
EventDelegation.register('edit-role', function(element, e) {
    e.preventDefault();
    initRoleModals();

    const roleId = element.dataset.roleId;
    if (!roleId) {
        console.error('[edit-role] Missing role ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[edit-role] SweetAlert2 not available');
        return;
    }

    // Show loading
    window.Swal.fire({
        title: 'Loading Role Data',
        html: '<div class="text-center"><div class="spinner-border text-primary" role="status" data-spinner></div></div>',
        allowOutsideClick: false,
        showConfirmButton: false
    });

    // Get the API URL from data attribute or construct it
    const apiUrl = element.dataset.apiUrl || `/admin-panel/users/roles/${roleId}/details`;

    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const roleForm = document.getElementById('roleForm');
                if (!roleForm) {
                    throw new Error('Role form not found');
                }

                // Populate form
                document.getElementById('roleId').value = data.role.id;
                document.getElementById('roleName').value = data.role.name;
                document.getElementById('roleDescription').value = data.role.description || '';

                const modalLabel = document.getElementById('roleModalLabel');
                if (modalLabel) {
                    modalLabel.innerHTML = '<i class="ti ti-edit me-2"></i>Edit Role';
                }

                // Set edit action URL
                const editUrl = roleForm.dataset.editUrl || `/admin-panel/users/roles/${roleId}/edit`;
                roleForm.action = editUrl.replace('0', roleId);

                window.Swal.close();

                if (roleModal) {
                    roleModal.show();
                }
            } else {
                throw new Error(data.message || 'Failed to load role data');
            }
        })
        .catch(error => {
            window.Swal.close();
            window.Swal.fire('Error', error.message || 'Failed to load role data', 'error');
        });
});

/**
 * View Role Details
 * Shows detailed role information in modal
 */
EventDelegation.register('view-role-details', function(element, e) {
    e.preventDefault();
    initRoleModals();

    const roleId = element.dataset.roleId;
    if (!roleId) {
        console.error('[view-role-details] Missing role ID');
        return;
    }

    const detailsContent = document.getElementById('roleDetailsContent');
    if (detailsContent) {
        detailsContent.innerHTML = '<div class="text-center"><div class="spinner-border text-primary" role="status" data-spinner></div></div>';
    }

    if (roleDetailsModal) {
        roleDetailsModal.show();
    }

    // Get the API URL from data attribute or construct it
    const apiUrl = element.dataset.apiUrl || `/admin-panel/users/roles/${roleId}/details`;

    fetch(apiUrl)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const role = data.role;
                let content = `
                    <div class="row">
                        <div class="col-md-6">
                            <h6>Role Information</h6>
                            <table class="c-table c-table--compact" data-table data-mobile-table data-table-type="roles">
                                <tr><td><strong>Name:</strong></td><td>${role.name}</td></tr>
                                <tr><td><strong>Description:</strong></td><td>${role.description || 'No description'}</td></tr>
                                <tr><td><strong>Users:</strong></td><td>${role.user_count}</td></tr>
                                <tr><td><strong>Created:</strong></td><td>${role.created_at ? new Date(role.created_at).toLocaleDateString() : '-'}</td></tr>
                            </table>
                        </div>
                        <div class="col-md-6">
                            <h6>Users with this Role</h6>
                            <div class="u-overflow-y-auto u-max-h-200">
                `;

                if (role.users && role.users.length > 0) {
                    role.users.forEach(user => {
                        content += `
                            <div class="d-flex justify-content-between align-items-center mb-2">
                                <div>
                                    <strong>${user.username}</strong>
                                    <br><small class="text-muted">${user.email}</small>
                                </div>
                                <div>
                                    <span class="badge bg-label-${user.is_approved ? 'success' : 'warning'}" data-badge>${user.is_approved ? 'Approved' : 'Pending'}</span>
                                    <span class="badge bg-label-${user.is_active ? 'success' : 'danger'}" data-badge>${user.is_active ? 'Active' : 'Inactive'}</span>
                                </div>
                            </div>
                        `;
                    });
                } else {
                    content += '<p class="text-muted">No users have this role</p>';
                }

                content += `
                            </div>
                        </div>
                    </div>
                `;

                if (detailsContent) {
                    detailsContent.innerHTML = content;
                }
            } else {
                throw new Error(data.message || 'Failed to load role details');
            }
        })
        .catch(error => {
            if (detailsContent) {
                detailsContent.innerHTML = `<div class="alert alert-danger" data-alert>Error: ${error.message}</div>`;
            }
        });
});

/**
 * View Role Users
 * Navigates to role users page
 */
EventDelegation.register('view-role-users', function(element, e) {
    e.preventDefault();

    const roleId = element.dataset.roleId;
    if (!roleId) {
        console.error('[view-role-users] Missing role ID');
        return;
    }

    // Navigate to role users page
    const usersUrl = element.dataset.usersUrl || `/admin-panel/users/roles/${roleId}/users`;
    window.location.href = usersUrl;
});

/**
 * Assign Role
 * Opens modal to assign role to a user
 */
EventDelegation.register('assign-role', function(element, e) {
    e.preventDefault();
    initRoleModals();

    const roleId = element.dataset.roleId;
    if (!roleId) {
        console.error('[assign-role] Missing role ID');
        return;
    }

    const assignRoleForm = document.getElementById('assignRoleForm');
    if (!assignRoleForm) {
        console.error('[assign-role] Assign role form not found');
        return;
    }

    document.getElementById('assignRoleId').value = roleId;
    document.getElementById('assigningRoleName').textContent = 'Loading...';

    // Set form action
    const assignUrl = assignRoleForm.dataset.assignUrl || `/admin-panel/users/roles/${roleId}/assign`;
    assignRoleForm.action = assignUrl.replace('0', roleId);

    // Clear and show loading in user select
    const userSelect = document.getElementById('selectUser');
    if (userSelect) {
        userSelect.innerHTML = '<option value="">Loading users...</option>';
    }

    // Get the API URLs from data attributes or construct them
    const roleApiUrl = element.dataset.roleApiUrl || `/admin-panel/users/roles/${roleId}/details`;
    const usersApiUrl = element.dataset.usersApiUrl || `/admin-panel/users/roles/${roleId}/available-users`;

    Promise.all([
        fetch(roleApiUrl).then(r => r.json()),
        fetch(usersApiUrl).then(r => r.json())
    ]).then(([roleData, usersData]) => {
        // Set role name
        if (roleData.success) {
            document.getElementById('assigningRoleName').textContent = roleData.role.name;
        }

        // Populate user dropdown
        if (userSelect) {
            userSelect.innerHTML = '<option value="">Choose a user...</option>';
            if (usersData.success && usersData.users && usersData.users.length > 0) {
                usersData.users.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.id;
                    option.textContent = `${user.username} (${user.email})`;
                    if (!user.is_active) {
                        option.textContent += ' [Inactive]';
                        option.classList.add('text-muted');
                    }
                    userSelect.appendChild(option);
                });
            } else {
                userSelect.innerHTML = '<option value="">No available users (all have this role)</option>';
            }
        }
    }).catch(error => {
        console.error('Error loading data:', error);
        if (userSelect) {
            userSelect.innerHTML = '<option value="">Error loading users</option>';
        }
    });

    if (assignRoleModal) {
        assignRoleModal.show();
    }
});

/**
 * Delete Role
 * Deletes a role with confirmation
 */
EventDelegation.register('delete-role', function(element, e) {
    e.preventDefault();

    const roleId = element.dataset.roleId;
    const roleName = element.dataset.roleName || 'this role';

    if (!roleId) {
        console.error('[delete-role] Missing role ID');
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[delete-role] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Delete Role?',
        text: `This will permanently delete the role "${roleName}". This action cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, Delete',
        cancelButtonText: 'Cancel',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
    }).then((result) => {
        if (result.isConfirmed) {
            const deleteUrl = element.dataset.deleteUrl || `/admin-panel/users/roles/${roleId}/delete`;
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            fetch(deleteUrl, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Deleted!', data.message || 'Role deleted successfully', 'success').then(() => {
                        location.reload();
                    });
                } else {
                    window.Swal.fire('Error', data.message || 'Failed to delete role', 'error');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                window.Swal.fire('Error', 'Failed to delete role', 'error');
            });
        }
    });
});

/**
 * Export Roles
 * Exports role data
 */
EventDelegation.register('export-roles', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire('Feature Coming Soon', 'Role export functionality will be added soon.', 'info');
    }
});

// ============================================================================
// FORM SUBMISSION HANDLERS
// ============================================================================

/**
 * Submit Role Form
 * Handles role creation/edit form submission
 */
EventDelegation.register('submit-role-form', function(element, e) {
    e.preventDefault();
    initRoleModals();

    const roleForm = document.getElementById('roleForm');
    if (!roleForm) {
        console.error('[submit-role-form] Role form not found');
        return;
    }

    const formData = new FormData(roleForm);

    fetch(roleForm.action, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (roleModal) {
                roleModal.hide();
            }
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Success', data.message || 'Role saved successfully', 'success').then(() => {
                    location.reload();
                });
            } else {
                location.reload();
            }
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message || 'Failed to save role', 'error');
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to save role', 'error');
        }
    });
});

/**
 * Submit Assign Role Form
 * Handles role assignment form submission
 */
EventDelegation.register('submit-assign-role-form', function(element, e) {
    e.preventDefault();
    initRoleModals();

    const assignRoleForm = document.getElementById('assignRoleForm');
    if (!assignRoleForm) {
        console.error('[submit-assign-role-form] Assign role form not found');
        return;
    }

    const formData = new FormData(assignRoleForm);

    fetch(assignRoleForm.action, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (assignRoleModal) {
                assignRoleModal.hide();
            }
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Success', data.message || 'Role assigned successfully', 'success').then(() => {
                    location.reload();
                });
            } else {
                location.reload();
            }
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message || 'Failed to assign role', 'error');
            }
        }
    })
    .catch(error => {
        console.error('Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to assign role', 'error');
        }
    });
});

console.log('[EventDelegation] Admin roles handlers loaded');
