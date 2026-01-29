'use strict';

/**
 * User Approvals Module
 * Extracted from admin_panel/users/approvals.html
 * Handles user approval, rejection, and viewing functionality
 * @module user-approvals
 */

// Module configuration - set from template
const config = {
    getUserDetailsUrl: '',
    processApprovalUrl: '',
    csrfToken: '',
    pendingUsersCount: 0
};

/**
 * Initialize User Approvals module
 * @param {Object} options - Configuration options
 */
export function init(options) {
    Object.assign(config, options);
    console.log('[UserApprovals] Initialized');
}

/**
 * View user details in modal
 * @param {string|number} userId - The user ID
 * @param {string} userName - The user name for display
 */
export function viewUserDetails(userId, userName) {
    const titleEl = document.getElementById('user_details_title');
    const contentEl = document.getElementById('user_details_content');

    if (titleEl) {
        titleEl.textContent = `Details for ${userName}`;
    }
    if (contentEl) {
        contentEl.innerHTML = '<div class="flex justify-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status" data-spinner></div></div>';
    }

    // Show modal using ModalManager if available
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('userDetailsModal');
    } else if (typeof window.Modal !== 'undefined') {
        const modalEl = document.getElementById('userDetailsModal');
        if (modalEl) {
            modalEl._flowbiteModal = modalEl._flowbiteModal || new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
            modalEl._flowbiteModal.show();
        }
    }

    // Load user details via AJAX
    const url = config.getUserDetailsUrl ?
        `${config.getUserDetailsUrl}?user_id=${userId}` :
        `/admin-panel/users/details?user_id=${userId}`;

    fetch(url)
        .then(response => response.json())
        .then(data => {
            if (data.success && contentEl) {
                contentEl.innerHTML = data.html;
            } else if (contentEl) {
                contentEl.innerHTML = '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading user details</div>';
            }
        })
        .catch(error => {
            console.error('[UserApprovals] Error loading user details:', error);
            if (contentEl) {
                contentEl.innerHTML = '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading user details</div>';
            }
        });
}

/**
 * Approve a user
 * @param {string|number} userId - The user ID
 * @param {string} userName - The user name for confirmation
 */
export function approveUser(userId, userName) {
    const confirmColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28a745';
    const cancelColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d';

    if (typeof window.Swal === 'undefined') return;

    window.Swal.fire({
        title: 'Approve User?',
        text: `Are you sure you want to approve "${userName}"?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: confirmColor,
        cancelButtonColor: cancelColor,
        confirmButtonText: 'Yes, approve!'
    }).then((result) => {
        if (result.isConfirmed) {
            submitUserAction('approve', userId);
        }
    });
}

/**
 * Reject a user
 * @param {string|number} userId - The user ID
 * @param {string} userName - The user name for confirmation
 */
export function rejectUser(userId, userName) {
    const confirmColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545';
    const cancelColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d';

    if (typeof window.Swal === 'undefined') return;

    window.Swal.fire({
        title: 'Reject User?',
        text: `Are you sure you want to reject "${userName}"?`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: confirmColor,
        cancelButtonColor: cancelColor,
        confirmButtonText: 'Yes, reject!'
    }).then((result) => {
        if (result.isConfirmed) {
            submitUserAction('reject', userId);
        }
    });
}

/**
 * Approve all pending users
 */
export function approveAllPending() {
    const pendingCount = config.pendingUsersCount;
    const confirmColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28a745';
    const cancelColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d';

    if (typeof window.Swal === 'undefined') return;

    window.Swal.fire({
        title: 'Approve All Pending Users?',
        text: `This will approve ${pendingCount} pending users. This action cannot be undone.`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: confirmColor,
        cancelButtonColor: cancelColor,
        confirmButtonText: 'Yes, approve all!'
    }).then((result) => {
        if (result.isConfirmed) {
            submitUserAction('approve_all', null);
        }
    });
}

/**
 * Submit user action via form
 * @param {string} action - The action to perform
 * @param {string|number|null} userId - The user ID (null for bulk actions)
 */
export function submitUserAction(action, userId) {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = config.processApprovalUrl || '/admin-panel/users/approvals/process';

    const csrfToken = document.createElement('input');
    csrfToken.type = 'hidden';
    csrfToken.name = 'csrf_token';
    csrfToken.value = config.csrfToken || document.querySelector('meta[name="csrf-token"]')?.content || '';

    const actionInput = document.createElement('input');
    actionInput.type = 'hidden';
    actionInput.name = 'action';
    actionInput.value = action;

    form.appendChild(csrfToken);
    form.appendChild(actionInput);

    if (userId) {
        const userIdInput = document.createElement('input');
        userIdInput.type = 'hidden';
        userIdInput.name = 'user_id';
        userIdInput.value = userId;
        form.appendChild(userIdInput);
    }

    document.body.appendChild(form);
    form.submit();
}

/**
 * Go back to previous page
 */
export function goBack() {
    window.history.back();
}

// Register with InitSystem if available
if (typeof window.InitSystem !== 'undefined') {
    window.InitSystem.register('userApprovals', function() {
        console.log('[UserApprovals] Module loaded via InitSystem');
    }, { requires: [], priority: 10 });
}

// Window exports for backward compatibility
window.UserApprovals = {
    init: init,
    viewUserDetails: viewUserDetails,
    approveUser: approveUser,
    rejectUser: rejectUser,
    approveAllPending: approveAllPending,
    submitUserAction: submitUserAction
};
