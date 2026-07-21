import { EventDelegation } from '../core.js';
import { escapeHtml } from '../../utils/sanitize.js';

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
    return `/admin-panel/users/waitlist/user/${userId}`;
}

/**
 * Get URL for processing waitlist users
 */
function getProcessWaitlistUrl() {
    if (typeof window.WAITLIST_CONFIG !== 'undefined' && window.WAITLIST_CONFIG.processWaitlistUrl) {
        return window.WAITLIST_CONFIG.processWaitlistUrl;
    }
    return '/admin-panel/users/waitlist/process';
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
window.EventDelegation.register('view-user', function(element, e) {
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
        contentElement.innerHTML = '<div class="flex justify-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status" data-spinner></div></div>';
    }

    // Show the modal
    window.ModalManager.show('waitlistUserModal');

    // Load user details via AJAX (route returns { success, user } JSON)
    fetch(getUserDetailsUrl(userId))
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (contentElement) {
                    contentElement.innerHTML = renderUserDetails(data.user || {});
                }
            } else {
                if (contentElement) {
                    contentElement.innerHTML = '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading user details</div>';
                }
            }
        })
        .catch(error => {
            console.error('[view-user] Error loading user details:', error);
            if (contentElement) {
                contentElement.innerHTML = '<div class="p-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400" role="alert" data-alert>Error loading user details</div>';
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
window.EventDelegation.register('process-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    const userName = element.dataset.userName || 'this user';

    if (!userId) {
        console.error('[process-user] Missing user ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
    }
}, { preventDefault: true });

// ============================================================================
// REMOVE USER FROM WAITLIST
// ============================================================================

/**
 * Handle Remove User button click
 * Shows confirmation dialog and removes user from waitlist
 */
window.EventDelegation.register('remove-waitlist-user', function(element, e) {
    e.preventDefault();

    const userId = element.dataset.userId;
    const userName = element.dataset.userName || 'this user';

    if (!userId) {
        console.error('[remove-waitlist-user] Missing user ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
    }
}, { preventDefault: true });

// ============================================================================
// PROCESS ALL FROM WAITLIST
// ============================================================================

/**
 * Handle Process All button click
 * Processes all selected users or all users if none selected
 */
window.EventDelegation.register('process-all', function(element, e) {
    e.preventDefault();

    const checkboxes = document.querySelectorAll('.js-user-checkbox:checked');
    const selectedCount = checkboxes.length;

    if (typeof window.Swal !== 'undefined') {
        if (selectedCount === 0) {
            // Process all users
            window.Swal.fire({
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
            window.Swal.fire({
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
    }
}, { preventDefault: true });

// ============================================================================
// PROCESS FROM MODAL
// ============================================================================

/**
 * Handle Process From Modal button click
 * Processes the currently selected user from within the modal
 */
window.EventDelegation.register('process-from-modal', function(element, e) {
    e.preventDefault();

    if (selectedUserId && typeof window.Swal !== 'undefined') {
        window.Swal.fire({
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
 * Render user details HTML from the JSON returned by
 * /admin-panel/users/waitlist/user/<id> ({ success, user }).
 */
function renderUserDetails(user) {
    const player = user.player || {};
    const rows = [
        ['Username', user.username],
        ['Email', user.email],
        ['Registered', user.created_at],
        ['Status', user.approval_status],
        ['Roles', (user.roles || []).join(', ')],
        ['Player Name', player.name],
        ['Phone', player.phone],
        ['Preferred Position', player.favorite_position],
        ['Jersey Size', player.jersey_size]
    ];

    const rowsHtml = rows
        .filter(([, value]) => value !== null && value !== undefined && value !== '')
        .map(([label, value]) => `
            <div class="flex gap-2">
                <span class="font-semibold text-gray-900 dark:text-white">${escapeHtml(label)}:</span>
                <span class="text-gray-700 dark:text-gray-300">${escapeHtml(String(value))}</span>
            </div>`)
        .join('');

    return `<div class="text-start space-y-1">${rowsHtml}</div>`;
}

/**
 * Show an error dialog (falls back to alert if Swal unavailable)
 */
function showWaitlistError(message) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire('Error', message, 'error');
    } else {
        alert(message);
    }
}

/**
 * Submit a single-user waitlist action.
 * - 'remove'  -> POST /admin-panel/users/waitlist/remove/<id> (JSON)
 * - 'process' -> POST /admin-panel/users/bulk-operations/waitlist-process (JSON, one id)
 * @param {string} userId - User ID to process
 * @param {string} action - Action to perform (process, remove)
 */
function submitWaitlistAction(userId, action) {
    let url;
    let body;

    if (action === 'remove') {
        url = `/admin-panel/users/waitlist/remove/${userId}`;
        body = JSON.stringify({ reason: 'Removed via waitlist management' });
    } else {
        url = '/admin-panel/users/bulk-operations/waitlist-process';
        body = JSON.stringify({ user_ids: [parseInt(userId, 10)], action: 'move_to_pending' });
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: body
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.location.reload();
            } else {
                showWaitlistError(data.message || 'Failed to update waitlist user');
            }
        })
        .catch(error => {
            console.error('[waitlist-management] Action failed:', error);
            showWaitlistError('Failed to update waitlist user');
        });
}

/**
 * Submit bulk waitlist action.
 * - 'process_all'      -> form POST /admin-panel/users/waitlist/process (processes everyone, redirects)
 * - 'process_selected' -> POST /admin-panel/users/bulk-operations/waitlist-process (JSON)
 * @param {string} action - Action to perform (process_all, process_selected)
 * @param {Array} selectedIds - Array of selected user IDs
 */
function submitBulkWaitlistAction(action, selectedIds) {
    if (action === 'process_all') {
        // Legacy bulk route: processes the whole waitlist and redirects with a flash
        const form = document.createElement('form');
        form.method = 'POST';
        form.action = getProcessWaitlistUrl();

        const csrfToken = document.createElement('input');
        csrfToken.type = 'hidden';
        csrfToken.name = 'csrf_token';
        csrfToken.value = getCsrfToken();

        // Backend requires action=process_all or it silently no-ops
        const actionField = document.createElement('input');
        actionField.type = 'hidden';
        actionField.name = 'action';
        actionField.value = 'process_all';

        form.appendChild(csrfToken);
        form.appendChild(actionField);
        document.body.appendChild(form);
        form.submit();
        return;
    }

    fetch('/admin-panel/users/bulk-operations/waitlist-process', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
            user_ids: selectedIds.map(id => parseInt(id, 10)),
            action: 'move_to_pending'
        })
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                window.location.reload();
            } else {
                showWaitlistError(data.message || 'Failed to process selected users');
            }
        })
        .catch(error => {
            console.error('[waitlist-management] Bulk action failed:', error);
            showWaitlistError('Failed to process selected users');
        });
}

// Handlers loaded
