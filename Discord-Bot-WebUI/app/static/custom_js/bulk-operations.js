'use strict';

/**
 * Bulk Operations Module
 * Extracted from admin_panel/users/bulk_operations.html
 * Handles bulk user approval, role assignment, and waitlist processing
 * @module bulk-operations
 */

// Module state
let selectedUsers = [];
let selectedRoles = [];
let bulkOperation = '';
let roleDistributionChart = null;

// Configuration - set from template
const config = {
    roleStats: {},
    roles: [],
    bulkStats: { pending_users: 0, waitlist_users: 0 },
    urls: {
        bulkApprove: '/admin-panel/users/bulk-operations/approve',
        bulkRoleAssign: '/admin-panel/users/bulk-operations/role-assign',
        bulkWaitlistProcess: '/admin-panel/users/bulk-operations/waitlist-process',
        userApprovals: '/admin-panel/users/approvals',
        userWaitlist: '/admin-panel/users/waitlist',
        rolesManagement: '/admin-panel/roles'
    }
};

/**
 * Initialize Bulk Operations module
 * @param {Object} options - Configuration options
 */
export function init(options) {
    Object.assign(config, options);
    initializeRoleDistributionChart();
    console.log('[BulkOperations] Initialized');
}

/**
 * Initialize role distribution chart
 */
function initializeRoleDistributionChart() {
    const ctx = document.getElementById('roleDistributionChart');
    if (!ctx || typeof window.Chart === 'undefined') return;

    const roleStats = config.roleStats;
    const labels = Object.keys(roleStats);
    const data = Object.values(roleStats);
    const colors = [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF',
        '#FF9F40', '#FF6384', '#C9CBCF', '#4BC0C0', '#FF6384'
    ];

    roleDistributionChart = new window.Chart(ctx.getContext('2d'), {
        type: 'doughnut',
        data: {
            labels: labels,
            datasets: [{
                data: data,
                backgroundColor: colors.slice(0, labels.length),
                borderWidth: 2
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        padding: 20,
                        usePointStyle: true
                    }
                }
            }
        }
    });
}

/**
 * Show bulk approval modal
 */
export function showBulkApprovalModal() {
    const modalEl = document.getElementById('bulkApprovalModal');
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('bulkApprovalModal');
    } else if (modalEl && typeof window.Modal !== 'undefined') {
        if (!modalEl._flowbiteModal) {
            modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
        }
        modalEl._flowbiteModal.show();
    }
    loadPendingUsersForApproval();
}

/**
 * Show bulk role modal
 */
export function showBulkRoleModal() {
    const modalEl = document.getElementById('bulkRoleModal');
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('bulkRoleModal');
    } else if (modalEl && typeof window.Modal !== 'undefined') {
        if (!modalEl._flowbiteModal) {
            modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
        }
        modalEl._flowbiteModal.show();
    }
    loadRoleAssignmentInterface();
}

/**
 * Show bulk waitlist modal
 */
export function showBulkWaitlistModal() {
    const modalEl = document.getElementById('bulkWaitlistModal');
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('bulkWaitlistModal');
    } else if (modalEl && typeof window.Modal !== 'undefined') {
        if (!modalEl._flowbiteModal) {
            modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
        }
        modalEl._flowbiteModal.show();
    }
    loadWaitlistUsersForProcessing();
}

/**
 * Load pending users for approval interface
 */
function loadPendingUsersForApproval() {
    const pendingCount = config.bulkStats.pending_users;
    const content = `
        <div class="mb-3">
            <label class="form-label">Default League Assignment</label>
            <select class="form-select" id="defaultLeague" data-form-select>
                <option value="classic">Classic League</option>
                <option value="premier">Premier League</option>
                <option value="ecs-fc">ECS FC</option>
                <option value="sub-classic">Classic Sub</option>
                <option value="sub-premier">Premier Sub</option>
                <option value="sub-ecs-fc">ECS FC Sub</option>
            </select>
        </div>
        <div class="mb-3">
            <div class="form-check">
                <input class="form-check-input" type="checkbox" id="sendNotifications" checked>
                <label class="form-check-label" for="sendNotifications">
                    Send approval notifications
                </label>
            </div>
        </div>
        <div class="mb-3">
            <label class="form-label">Select Users to Approve</label>
            <div class="user-selection user-selection-scrollable">
                <div class="list-group">
                    <div class="list-group-item">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" value="select-all" id="selectAllUsers">
                            <label class="form-check-label fw-bold" for="selectAllUsers">
                                Select All Pending Users (${pendingCount})
                            </label>
                        </div>
                    </div>
                    <!-- User list would be populated via AJAX -->
                </div>
            </div>
        </div>
    `;

    document.getElementById('bulkApprovalContent').innerHTML = content;
    document.getElementById('bulkApprovalBtn').disabled = false;
}

/**
 * Load role assignment interface
 */
function loadRoleAssignmentInterface() {
    const roles = config.roles;
    let roleOptions = '';
    roles.forEach(role => {
        roleOptions += `
            <div class="form-check">
                <input class="form-check-input" type="checkbox" value="${role.id}" id="role_${role.id}">
                <label class="form-check-label" for="role_${role.id}">
                    ${role.name} (${role.users ? role.users.length : 0} users)
                </label>
            </div>
        `;
    });

    const content = `
        <div class="row">
            <div class="col-md-6">
                <div class="mb-3">
                    <label class="form-label">Operation Type</label>
                    <select class="form-select" id="roleOperation" data-form-select>
                        <option value="add">Add Roles</option>
                        <option value="remove">Remove Roles</option>
                        <option value="replace">Replace All Roles</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label class="form-label">Select Roles</label>
                    <div class="role-selection-container">
                        ${roleOptions}
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="mb-3">
                    <label class="form-label">Select Users</label>
                    <div class="role-selection-container user-selection-scrollable-lg">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" value="select-all" id="selectAllRoleUsers">
                            <label class="form-check-label fw-bold" for="selectAllRoleUsers">
                                Select All Users
                            </label>
                        </div>
                        <hr>
                        <!-- User list would be populated via AJAX -->
                    </div>
                </div>
            </div>
        </div>
    `;

    document.getElementById('bulkRoleContent').innerHTML = content;
    document.getElementById('bulkRoleBtn').disabled = false;
}

/**
 * Load waitlist users for processing interface
 */
function loadWaitlistUsersForProcessing() {
    const waitlistCount = config.bulkStats.waitlist_users;
    const content = `
        <div class="mb-3">
            <label class="form-label">Processing Action</label>
            <div class="form-check">
                <input class="form-check-input" type="radio" name="waitlistAction" value="move_to_pending" id="moveToPending" checked>
                <label class="form-check-label" for="moveToPending">
                    Move to Pending Approval
                </label>
            </div>
            <div class="form-check">
                <input class="form-check-input" type="radio" name="waitlistAction" value="remove_from_waitlist" id="removeFromWaitlist">
                <label class="form-check-label" for="removeFromWaitlist">
                    Remove from Waitlist
                </label>
            </div>
        </div>
        <div class="mb-3">
            <label class="form-label">Select Waitlist Users</label>
            <div class="user-selection user-selection-scrollable">
                <div class="list-group">
                    <div class="list-group-item">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" value="select-all" id="selectAllWaitlistUsers">
                            <label class="form-check-label fw-bold" for="selectAllWaitlistUsers">
                                Select All Waitlist Users (${waitlistCount})
                            </label>
                        </div>
                    </div>
                    <!-- User list would be populated via AJAX -->
                </div>
            </div>
        </div>
    `;

    document.getElementById('bulkWaitlistContent').innerHTML = content;
    document.getElementById('bulkWaitlistBtn').disabled = false;
}

/**
 * Process bulk approval
 */
export function processBulkApproval() {
    const defaultLeague = document.getElementById('defaultLeague').value;
    const sendNotifications = document.getElementById('sendNotifications').checked;
    const selectedUserIds = []; // Would be populated from checkboxes

    if (selectedUserIds.length === 0) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Warning', 'Please select at least one user to approve', 'warning');
        }
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Confirm Bulk Approval',
            text: `Approve ${selectedUserIds.length} users for ${defaultLeague} league?`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, Approve'
        }).then((result) => {
            if (result.isConfirmed) {
                performBulkApproval(selectedUserIds, defaultLeague, sendNotifications);
            }
        });
    }
}

/**
 * Perform bulk approval request
 */
function performBulkApproval(userIds, league, notifications) {
    fetch(config.urls.bulkApprove, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            user_ids: userIds,
            default_league: league,
            send_notifications: notifications
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Success', data.message, 'success');
            }
            hideModal('bulkApprovalModal');
            location.reload();
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message, 'error');
            }
        }
    })
    .catch(error => {
        console.error('[BulkOperations] Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to process bulk approval', 'error');
        }
    });
}

/**
 * Process bulk role assignment
 */
export function processBulkRoleAssignment() {
    const operation = document.getElementById('roleOperation').value;
    const selectedRoleIds = Array.from(
        document.querySelectorAll('input[type="checkbox"][id^="role_"]:checked')
    ).map(cb => cb.value);
    const selectedUserIds = []; // Would be populated from user checkboxes

    if (selectedRoleIds.length === 0 || selectedUserIds.length === 0) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Warning', 'Please select both roles and users', 'warning');
        }
        return;
    }

    fetch(config.urls.bulkRoleAssign, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            user_ids: selectedUserIds,
            role_ids: selectedRoleIds,
            operation: operation
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Success', data.message, 'success');
            }
            hideModal('bulkRoleModal');
            location.reload();
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message, 'error');
            }
        }
    })
    .catch(error => {
        console.error('[BulkOperations] Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to process bulk role assignment', 'error');
        }
    });
}

/**
 * Process bulk waitlist
 */
export function processBulkWaitlist() {
    const actionRadio = document.querySelector('input[name="waitlistAction"]:checked');
    const action = actionRadio ? actionRadio.value : 'move_to_pending';
    const selectedUserIds = []; // Would be populated from checkboxes

    if (selectedUserIds.length === 0) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Warning', 'Please select at least one user to process', 'warning');
        }
        return;
    }

    fetch(config.urls.bulkWaitlistProcess, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            user_ids: selectedUserIds,
            action: action
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Success', data.message, 'success');
            }
            hideModal('bulkWaitlistModal');
            location.reload();
        } else {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', data.message, 'error');
            }
        }
    })
    .catch(error => {
        console.error('[BulkOperations] Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', 'Failed to process waitlist users', 'error');
        }
    });
}

/**
 * Hide a modal
 */
function hideModal(modalId) {
    const modalEl = document.getElementById(modalId);
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.hide(modalId);
    } else if (modalEl && modalEl._flowbiteModal) {
        modalEl._flowbiteModal.hide();
    }
}

/**
 * Navigation functions
 */
export function refreshOperationHistory() {
    location.reload();
}

export function loadPendingUsers() {
    window.location.href = config.urls.userApprovals;
}

export function loadWaitlistUsers() {
    window.location.href = config.urls.userWaitlist;
}

export function viewRoleDistribution() {
    window.location.href = config.urls.rolesManagement;
}

// Register with EventDelegation if available
if (typeof window.EventDelegation !== 'undefined') {
    window.EventDelegation.register('show-bulk-approval-modal', showBulkApprovalModal);
    window.EventDelegation.register('show-bulk-role-modal', showBulkRoleModal);
    window.EventDelegation.register('show-bulk-waitlist-modal', showBulkWaitlistModal);
    window.EventDelegation.register('load-pending-users', loadPendingUsers);
    window.EventDelegation.register('load-waitlist-users', loadWaitlistUsers);
    window.EventDelegation.register('view-role-distribution', viewRoleDistribution);
    window.EventDelegation.register('refresh-operation-history', refreshOperationHistory);
    window.EventDelegation.register('process-bulk-approval', processBulkApproval);
    window.EventDelegation.register('process-bulk-role-assignment', processBulkRoleAssignment);
    window.EventDelegation.register('process-bulk-waitlist', processBulkWaitlist);
}

// Window exports for backward compatibility
window.BulkOperations = {
    init: init,
    showBulkApprovalModal: showBulkApprovalModal,
    showBulkRoleModal: showBulkRoleModal,
    showBulkWaitlistModal: showBulkWaitlistModal,
    processBulkApproval: processBulkApproval,
    processBulkRoleAssignment: processBulkRoleAssignment,
    processBulkWaitlist: processBulkWaitlist,
    refreshOperationHistory: refreshOperationHistory,
    loadPendingUsers: loadPendingUsers,
    loadWaitlistUsers: loadWaitlistUsers,
    viewRoleDistribution: viewRoleDistribution
};
