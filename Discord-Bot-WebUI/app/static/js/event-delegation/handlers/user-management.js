import { EventDelegation } from '../../event-delegation/core.js';

/**
 * User Management Action Handlers
 * ================================
 * Handles user management actions (edit, delete, approve, remove, reset password)
 * using centralized event delegation.
 *
 * This replaces the inline event listeners in manage_users.html that were
 * causing duplicate handler accumulation on AJAX updates.
 *
 * @version 1.0.0
 * @created 2025-12-27
 */

// Uses global EventDelegation from core.js

// ============================================================================
// EDIT USER ACTION
// ============================================================================

/**
 * Handle Edit User button click
 * Opens the edit user modal with user data
 */
EventDelegation.register('edit-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    if (!userId) {
        console.error('[edit-user] Missing user ID');
        return;
    }

    // Call the global handler function defined in manage_users.html
    if (typeof window.handleEditUserClick === 'function') {
        window.handleEditUserClick(userId);
    } else {
        console.error('[edit-user] handleEditUserClick function not found');
    }
}, { preventDefault: true });

// ============================================================================
// RESET PASSWORD ACTION
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
// APPROVE USER ACTION
// ============================================================================

/**
 * Handle Approve User button click
 * Approves a pending user
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
// REMOVE USER ACTION
// ============================================================================

/**
 * Handle Remove User button click
 * Removes a user from the system
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
// DELETE USER ACTION
// ============================================================================

/**
 * Handle Delete User button click
 * Permanently deletes a user
 */
EventDelegation.register('delete-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    const username = element.dataset.username;

    if (!userId) {
        console.error('[delete-user] Missing user ID');
        return;
    }

    // Call the global handler function defined in manage_users.html
    if (typeof window.handleDeleteUserClick === 'function') {
        window.handleDeleteUserClick(userId, username);
    } else {
        console.error('[delete-user] handleDeleteUserClick function not found');
    }
}, { preventDefault: true });

// ============================================================================
// BULK APPROVE ACTION
// ============================================================================

EventDelegation.register('bulk-approve-users', function(element, e) {
    e.preventDefault();
    if (typeof window.bulkApprove === 'function') {
        window.bulkApprove();
    } else {
        console.error('[bulk-approve-users] bulkApprove function not found');
    }
}, { preventDefault: true });

// ============================================================================
// EXPORT USERS ACTION
// ============================================================================

EventDelegation.register('export-users', function(element, e) {
    e.preventDefault();
    const exportType = element.dataset.exportType || 'all';
    if (typeof window.exportUsers === 'function') {
        window.exportUsers(exportType);
    } else {
        console.error('[export-users] exportUsers function not found');
    }
}, { preventDefault: true });

// ============================================================================
// SYNC USERS ACTION
// ============================================================================

EventDelegation.register('sync-users', function(element, e) {
    e.preventDefault();
    if (typeof window.syncUsers === 'function') {
        window.syncUsers();
    } else {
        console.error('[sync-users] syncUsers function not found');
    }
}, { preventDefault: true });

// ============================================================================
// CREATE USER ACTION
// ============================================================================

EventDelegation.register('create-user', function(element, e) {
    e.preventDefault();
    if (typeof window.createUser === 'function') {
        window.createUser();
    } else {
        console.error('[create-user] createUser function not found');
    }
}, { preventDefault: true });

// ============================================================================
// BULK ACTION (approve, activate, deactivate, delete)
// ============================================================================

EventDelegation.register('bulk-action', function(element, e) {
    e.preventDefault();
    const action = element.dataset.bulkAction;
    if (!action) {
        console.error('[bulk-action] Missing bulk action type');
        return;
    }
    if (typeof window.bulkAction === 'function') {
        window.bulkAction(action);
    } else {
        console.error('[bulk-action] bulkAction function not found');
    }
}, { preventDefault: true });

console.log('[EventDelegation] User management handlers loaded');
