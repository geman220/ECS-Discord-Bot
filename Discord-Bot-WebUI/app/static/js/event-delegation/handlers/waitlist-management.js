import { EventDelegation } from '../core.js';

/**
 * Waitlist Management Action Handlers
 * ====================================
 * Handles waitlist management actions (view user, process, remove, process all)
 * using centralized event delegation.
 *
 * Migrated from inline scripts in waitlist.html
 *
 * @version 1.0.0
 */

// ============================================================================
// CONFIGURATION - URLs injected from template via data attributes or globals
// ============================================================================

/**
 * Get URL for fetching user details
 */
function getUserDetailsUrl(userId) {
    if (typeof window.WAITLIST_CONFIG !== 'undefined' && window.WAITLIST_CONFIG.userDetailsUrl) {
        return `${window.WAITLIST_CONFIG.userDetailsUrl}?user_id=${userId}`;
    }
    return `/admin-panel/api/user-details?user_id=${userId}`;
}

/**
 * Get URL for processing waitlist users
 */
function getProcessWaitlistUrl() {
    if (typeof window.WAITLIST_CONFIG !== 'undefined' && window.WAITLIST_CONFIG.processWaitlistUrl) {
        return window.WAITLIST_CONFIG.processWaitlistUrl;
    }
    return '/admin-panel/user-management/waitlist/process';
}

/**
 * Get CSRF token from the page
 */
function getCsrfToken() {
    // Try to find CSRF token from meta tag
    const metaToken = document.querySelector('meta[name="csrf-token"]');
    if (metaToken) {
        return metaToken.getAttribute('content');
    }

    // Try to find from hidden input
    const inputToken = document.querySelector('input[name="csrf_token"]');
    if (inputToken) {
        return inputToken.value;
    }

    // Try global config
    if (typeof window.WAITLIST_CONFIG !== 'undefined' && window.WAITLIST_CONFIG.csrfToken) {
        return window.WAITLIST_CONFIG.csrfToken;
    }

    return '';
}

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

// Track selected user for modal actions
let selectedUserId = null;

// ============================================================================
// VIEW WAITLIST USER
// ============================================================================

/**
 * Handle View User button click
 * Opens the user details modal and loads user information via AJAX
 */
EventDelegation.register('view-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    const userName = element.dataset.userName;

    if (!userId) {
        console.error('[view-user] Missing user ID');
        return;
    }

    // Store selected user ID for modal actions
    selectedUserId = userId;

    // Update modal title
    const titleElement = document.getElementById('waitlist_user_title');
    if (titleElement) {
        titleElement.textContent = `Details for ${userName || 'User'}`;
    }

    // Show loading state in modal content
    const contentElement = document.getElementById('waitlist_user_content');
    if (contentElement) {
        contentElement.innerHTML = '<div class="text-center"><div class="spinner-border" role="status" data-spinner></div></div>';
    }

    // Show the modal
    if (typeof ModalManager !== 'undefined') {
        ModalManager.show('waitlistUserModal');
    } else {
        const modalEl = document.getElementById('waitlistUserModal');
        if (modalEl && typeof bootstrap !== 'undefined') {
            const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
            modal.show();
        }
    }

    // Load user details via AJAX
    fetch(getUserDetailsUrl(userId))
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (contentElement) {
                    contentElement.innerHTML = data.html;
                }
            } else {
                if (contentElement) {
                    contentElement.innerHTML = '<div class="alert alert-danger" data-alert>Error loading user details</div>';
                }
            }
        })
        .catch(error => {
            console.error('[view-user] Error loading user details:', error);
            if (contentElement) {
                contentElement.innerHTML = '<div class="alert alert-danger" data-alert>Error loading user details</div>';
            }
        });
}, { preventDefault: true });

// ============================================================================
// PROCESS USER FROM WAITLIST
// ============================================================================

/**
 * Handle Process User button click
 * Shows confirmation dialog and processes user from waitlist
 */
EventDelegation.register('process-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    const userName = element.dataset.userName || 'this user';

    if (!userId) {
        console.error('[process-user] Missing user ID');
        return;
    }

    // Check if Swal is available
    if (typeof Swal === 'undefined') {
        if (confirm(`Process "${userName}" from the waitlist and approve their registration?`)) {
            submitWaitlistAction(userId, 'process');
        }
        return;
    }

    Swal.fire({
        title: 'Process User from Waitlist?',
        text: `Process "${userName}" from the waitlist and approve their registration?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28a745',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
        confirmButtonText: 'Yes, process user!'
    }).then((result) => {
        if (result.isConfirmed) {
            submitWaitlistAction(userId, 'process');
        }
    });
}, { preventDefault: true });

// ============================================================================
// REMOVE USER FROM WAITLIST
// ============================================================================

/**
 * Handle Remove User button click
 * Shows confirmation dialog and removes user from waitlist
 */
EventDelegation.register('remove-waitlist-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    const userName = element.dataset.userName || 'this user';

    if (!userId) {
        console.error('[remove-waitlist-user] Missing user ID');
        return;
    }

    // Check if Swal is available
    if (typeof Swal === 'undefined') {
        if (confirm(`Remove "${userName}" from the waitlist? This action cannot be undone.`)) {
            submitWaitlistAction(userId, 'remove');
        }
        return;
    }

    Swal.fire({
        title: 'Remove from Waitlist?',
        text: `Remove "${userName}" from the waitlist? This action cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
        confirmButtonText: 'Yes, remove!'
    }).then((result) => {
        if (result.isConfirmed) {
            submitWaitlistAction(userId, 'remove');
        }
    });
}, { preventDefault: true });

// ============================================================================
// PROCESS ALL FROM WAITLIST
// ============================================================================

/**
 * Handle Process All button click
 * Processes all selected users or all users if none selected
 */
EventDelegation.register('process-all', function(element, e) {
    e.preventDefault();

    const checkboxes = document.querySelectorAll('.js-user-checkbox:checked');
    const selectedCount = checkboxes.length;

    if (typeof Swal === 'undefined') {
        // Fallback without SweetAlert
        if (selectedCount === 0) {
            if (confirm('Process all users from the waitlist and approve their registrations?')) {
                submitBulkWaitlistAction('process_all', []);
            }
        } else {
            if (confirm(`Process ${selectedCount} selected users from the waitlist?`)) {
                const selectedIds = Array.from(checkboxes).map(cb => cb.value);
                submitBulkWaitlistAction('process_selected', selectedIds);
            }
        }
        return;
    }

    if (selectedCount === 0) {
        // Process all users
        Swal.fire({
            title: 'Process All Users?',
            text: 'Process all users from the waitlist and approve their registrations?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28a745',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: 'Yes, process all!'
        }).then((result) => {
            if (result.isConfirmed) {
                submitBulkWaitlistAction('process_all', []);
            }
        });
    } else {
        // Process selected users
        Swal.fire({
            title: `Process ${selectedCount} Selected Users?`,
            text: `Process ${selectedCount} selected users from the waitlist?`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28a745',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: 'Yes, process selected!'
        }).then((result) => {
            if (result.isConfirmed) {
                const selectedIds = Array.from(checkboxes).map(cb => cb.value);
                submitBulkWaitlistAction('process_selected', selectedIds);
            }
        });
    }
}, { preventDefault: true });

// ============================================================================
// PROCESS FROM MODAL
// ============================================================================

/**
 * Handle Process From Modal button click
 * Processes the currently selected user from within the modal
 */
EventDelegation.register('process-from-modal', function(element, e) {
    e.preventDefault();

    if (selectedUserId) {
        // Check if Swal is available
        if (typeof Swal === 'undefined') {
            if (confirm('Process this user from the waitlist and approve their registration?')) {
                submitWaitlistAction(selectedUserId, 'process');
            }
            return;
        }

        Swal.fire({
            title: 'Process User from Waitlist?',
            text: 'Process this user from the waitlist and approve their registration?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('success') : '#28a745',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('secondary') : '#6c757d',
            confirmButtonText: 'Yes, process user!'
        }).then((result) => {
            if (result.isConfirmed) {
                submitWaitlistAction(selectedUserId, 'process');
            }
        });
    }
}, { preventDefault: true });

// ============================================================================
// TOGGLE SELECT ALL
// ============================================================================
// Note: toggle-select-all is handled by form-actions.js (generic implementation)
// Use data-target=".js-user-checkbox" in the HTML to specify checkbox selector

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Submit waitlist action via form POST
 * @param {string} userId - User ID to process
 * @param {string} action - Action to perform (process, remove)
 */
function submitWaitlistAction(userId, action) {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = getProcessWaitlistUrl();

    const csrfToken = document.createElement('input');
    csrfToken.type = 'hidden';
    csrfToken.name = 'csrf_token';
    csrfToken.value = getCsrfToken();

    const userIdInput = document.createElement('input');
    userIdInput.type = 'hidden';
    userIdInput.name = 'user_id';
    userIdInput.value = userId;

    const actionInput = document.createElement('input');
    actionInput.type = 'hidden';
    actionInput.name = 'action';
    actionInput.value = action;

    form.appendChild(csrfToken);
    form.appendChild(userIdInput);
    form.appendChild(actionInput);
    document.body.appendChild(form);
    form.submit();
}

/**
 * Submit bulk waitlist action via form POST
 * @param {string} action - Action to perform (process_all, process_selected)
 * @param {Array} selectedIds - Array of selected user IDs
 */
function submitBulkWaitlistAction(action, selectedIds) {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = getProcessWaitlistUrl();

    const csrfToken = document.createElement('input');
    csrfToken.type = 'hidden';
    csrfToken.name = 'csrf_token';
    csrfToken.value = getCsrfToken();

    const actionInput = document.createElement('input');
    actionInput.type = 'hidden';
    actionInput.name = 'action';
    actionInput.value = action;

    form.appendChild(csrfToken);
    form.appendChild(actionInput);

    // Add selected user IDs
    selectedIds.forEach(id => {
        const userIdInput = document.createElement('input');
        userIdInput.type = 'hidden';
        userIdInput.name = 'selected_users';
        userIdInput.value = id;
        form.appendChild(userIdInput);
    });

    document.body.appendChild(form);
    form.submit();
}

console.log('[EventDelegation] Waitlist management handlers loaded');
