/**
 * User Approval Management JavaScript
 * Handles user approval and denial functionality for league placement
 */
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';

let _initialized = false;

// Module-level variables
let currentUserId = null;
let approvalModal = null;
let denialModal = null;
let playerDetailsModal = null;

// Initialize function
export function initUserApprovalManagement() {
    if (_initialized) return;

    // Page-specific guard: Only initialize on user approvals page
    // Check for page-specific elements that only exist on this page
    const isUserApprovalsPage = document.getElementById('approvalModal') ||
                                 document.getElementById('approvalForm') ||
                                 document.querySelector('[data-role="approval-table"]');

    if (!isUserApprovalsPage) {
        return; // Not the user approvals page, don't initialize
    }

    _initialized = true;

    initializeModals();
    initializeFormSubmitListeners();
}

/**
 * Initialize Bootstrap modals
 */
export function initializeModals() {
    const approvalModalElement = document.getElementById('approvalModal');
    const denialModalElement = document.getElementById('denialModal');
    const playerDetailsModalElement = document.getElementById('playerDetailsModal');

    if (approvalModalElement) {
        approvalModal = window.ModalManager.getInstance('approvalModal');
    }

    if (denialModalElement) {
        denialModal = window.ModalManager.getInstance('denialModal');
    }

    if (playerDetailsModalElement) {
        playerDetailsModal = window.ModalManager.getInstance('playerDetailsModal');
    }
}

/**
 * Initialize form submit event listeners
 * Note: Click handlers are managed by centralized event delegation
 */
export function initializeFormSubmitListeners() {
    // Handle form submissions
    const approvalForm = document.getElementById('approvalForm');
    const denialForm = document.getElementById('denialForm');

    if (approvalForm) {
        approvalForm.addEventListener('submit', function(e) {
            e.preventDefault();
            window.submitApproval();
        });
    }

    if (denialForm) {
        denialForm.addEventListener('submit', function(e) {
            e.preventDefault();
            window.submitDenial();
        });
    }
}

/**
 * Show approval modal for a user
 * @param {number} userId - The user ID to approve
 */
export function showApprovalModal(userId) {
    // Check if we're on the right page - silently return if not
    if (!document.getElementById('approvalModal')) {
        console.warn('[user-approval] approvalModal not found on this page');
        return;
    }

    if (!approvalModal) {
        // Try to initialize the modal now
        const modalElement = document.getElementById('approvalModal');
        if (modalElement && window.ModalManager) {
            approvalModal = window.ModalManager.getInstance('approvalModal');
        }
        if (!approvalModal) {
            showErrorAlert('Modal not initialized');
            return;
        }
    }

    currentUserId = userId;

    // Reset form
    document.getElementById('approvalForm').reset();
    document.getElementById('approvalUserId').value = userId;

    // Show modal
    approvalModal.show();

    // Focus on league select
    setTimeout(() => {
        document.getElementById('leagueSelect').focus();
    }, 300);
}

/**
 * Show denial modal for a user
 * @param {number} userId - The user ID to deny
 */
export function showDenialModal(userId) {
    // Check if we're on the right page - silently return if not
    if (!document.getElementById('denialModal')) {
        console.warn('[user-approval] denialModal not found on this page');
        return;
    }

    if (!denialModal) {
        // Try to initialize the modal now
        const modalElement = document.getElementById('denialModal');
        if (modalElement && window.ModalManager) {
            denialModal = window.ModalManager.getInstance('denialModal');
        }
        if (!denialModal) {
            showErrorAlert('Modal not initialized');
            return;
        }
    }

    currentUserId = userId;

    // Reset form
    document.getElementById('denialForm').reset();
    document.getElementById('denialUserId').value = userId;

    // Show modal
    denialModal.show();

    // Focus on notes textarea
    setTimeout(() => {
        document.getElementById('denialNotes').focus();
    }, 300);
}

/**
 * Submit user approval
 */
export function submitApproval() {
    const form = document.getElementById('approvalForm');
    const formData = new FormData(form);
    const userId = document.getElementById('approvalUserId').value;

    if (!userId) {
        showErrorAlert('User ID is required');
        return;
    }

    // Validate league selection
    const leagueType = formData.get('league_type');
    if (!leagueType) {
        showErrorAlert('Please select a league');
        return;
    }

    // Disable submit button using data attribute selector
    const submitButton = document.querySelector('[data-action="approve-user"]');
    const originalText = submitButton.innerHTML;
    submitButton.disabled = true;
    submitButton.innerHTML = '<i class="ti ti-loader"></i> Processing...';

    // Submit request
    fetch(`/admin/user-approvals/approve/${userId}`, {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessAlert(data.message);

            // Remove the user row from the table
            removeUserFromTable(userId);

            // Update stats
            userApprovalUpdateStats();

            // Hide modal
            approvalModal.hide();
        } else {
            showErrorAlert(data.message || 'Error processing approval');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showErrorAlert('Network error occurred');
    })
    .finally(() => {
        // Re-enable submit button
        submitButton.disabled = false;
        submitButton.innerHTML = originalText;
    });
}

/**
 * Submit user denial
 */
export function submitDenial() {
    const form = document.getElementById('denialForm');
    const formData = new FormData(form);
    const userId = document.getElementById('denialUserId').value;

    if (!userId) {
        showErrorAlert('User ID is required');
        return;
    }

    // Validate notes
    const notes = formData.get('notes');
    if (!notes || notes.trim().length < 10) {
        showErrorAlert('Please provide a detailed reason for denial (at least 10 characters)');
        return;
    }

    // Disable submit button using data attribute selector
    const submitButton = document.querySelector('[data-action="deny-user"]');
    const originalText = submitButton.innerHTML;
    submitButton.disabled = true;
    submitButton.innerHTML = '<i class="ti ti-loader"></i> Processing...';

    // Submit request
    fetch(`/admin/user-approvals/deny/${userId}`, {
        method: 'POST',
        body: formData,
        headers: {
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showSuccessAlert(data.message);

            // Remove the user row from the table
            removeUserFromTable(userId);

            // Update stats
            userApprovalUpdateStats();

            // Hide modal
            denialModal.hide();
        } else {
            showErrorAlert(data.message || 'Error processing denial');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showErrorAlert('Network error occurred');
    })
    .finally(() => {
        // Re-enable submit button
        submitButton.disabled = false;
        submitButton.innerHTML = originalText;
    });
}

/**
 * Remove user row from the table
 * @param {number} userId - The user ID to remove
 */
export function removeUserFromTable(userId) {
    const table = document.querySelector('[data-role="approval-table"]');
    if (!table) return;

    const rows = table.querySelectorAll('[data-role="user-row"]');
    rows.forEach(row => {
        const rowUserId = row.getAttribute('data-user-id');
        if (rowUserId && parseInt(rowUserId) === parseInt(userId)) {
            // Add fade out animation using CSS class
            row.classList.add('fade-out');

            // Remove after animation
            setTimeout(() => {
                row.remove();

                // Check if table is empty
                const remainingRows = table.querySelectorAll('[data-role="user-row"]');
                if (remainingRows.length === 0) {
                    showEmptyTableMessage();
                }
            }, 300);
        }
    });
}

/**
 * Show empty table message
 */
export function showEmptyTableMessage() {
    const container = document.querySelector('[data-role="table-container"]');
    if (container) {
        container.innerHTML = `
            <div class="text-center py-4">
                <i class="ti ti-users empty-table-icon"></i>
                <h6 class="mt-3">No pending approvals</h6>
                <p class="text-muted">All users have been processed</p>
            </div>
        `;
    }
}

/**
 * Update statistics display
 */
export function userApprovalUpdateStats() {
    fetch('/admin/user-approvals/stats')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const stats = data.stats;

                // Update stats cards using data attributes
                const pendingCard = document.querySelector('[data-role="stats-card"][data-status="pending"]');
                const approvedCard = document.querySelector('[data-role="stats-card"][data-status="approved"]');
                const deniedCard = document.querySelector('[data-role="stats-card"][data-status="denied"]');
                const totalCard = document.querySelector('[data-role="stats-card"][data-status="total"]');

                if (pendingCard) {
                    const numberEl = pendingCard.querySelector('[data-role="stats-number"]');
                    if (numberEl) numberEl.textContent = stats.pending;
                }
                if (approvedCard) {
                    const numberEl = approvedCard.querySelector('[data-role="stats-number"]');
                    if (numberEl) numberEl.textContent = stats.approved;
                }
                if (deniedCard) {
                    const numberEl = deniedCard.querySelector('[data-role="stats-number"]');
                    if (numberEl) numberEl.textContent = stats.denied;
                }
                if (totalCard) {
                    const numberEl = totalCard.querySelector('[data-role="stats-number"]');
                    if (numberEl) numberEl.textContent = stats.total;
                }

                // Update badge in card header
                const pendingBadge = document.querySelector('[data-role="pending-count-badge"]');
                if (pendingBadge) {
                    pendingBadge.textContent = `${stats.pending} pending`;
                }
            }
        })
        .catch(error => {
            console.error('Error updating stats:', error);
        });
}

/**
 * Refresh stats manually
 */
export function refreshStats() {
    const refreshButton = document.querySelector('[data-action="refresh-stats"]');
    if (refreshButton) {
        const originalText = refreshButton.innerHTML;
        refreshButton.innerHTML = '<i class="ti ti-loader"></i> Refreshing...';
        refreshButton.disabled = true;

        setTimeout(() => {
            userApprovalUpdateStats();
            refreshButton.innerHTML = originalText;
            refreshButton.disabled = false;
        }, 1000);
    }
}

// getCSRFToken is provided globally by csrf-fetch.js
export const getCSRFToken = window.getCSRFToken;

/**
 * Show success alert
 * @param {string} message - Success message
 */
export function showSuccessAlert(message) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'success',
            title: 'Success!',
            text: message,
            showConfirmButton: false,
            timer: 3000,
            toast: true,
            position: 'top-end'
        });
    } else {
        alert(message);
    }
}

/**
 * Show error alert
 * @param {string} message - Error message
 */
export function showErrorAlert(message) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'error',
            title: 'Error!',
            text: message,
            showConfirmButton: true
        });
    } else {
        alert('Error: ' + message);
    }
}

/**
 * Show warning alert
 * @param {string} message - Warning message
 */
export function showWarningAlert(message) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'warning',
            title: 'Warning!',
            text: message,
            showConfirmButton: true
        });
    } else {
        alert('Warning: ' + message);
    }
}

/**
 * Show info alert
 * @param {string} message - Info message
 */
export function showInfoAlert(message) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'info',
            title: 'Info',
            text: message,
            showConfirmButton: true
        });
    } else {
        alert('Info: ' + message);
    }
}

/**
 * Show player details modal
 * @param {number} userId - The user ID to show details for
 */
export function showPlayerDetails(userId) {
    // Check if we're on the right page - silently return if not
    if (!document.getElementById('playerDetailsModal')) {
        console.warn('[user-approval] playerDetailsModal not found on this page');
        return;
    }

    if (!playerDetailsModal) {
        // Try to initialize the modal now
        const modalElement = document.getElementById('playerDetailsModal');
        if (modalElement && window.ModalManager) {
            playerDetailsModal = window.ModalManager.getInstance('playerDetailsModal');
        }
        if (!playerDetailsModal) {
            showErrorAlert('Details modal not initialized');
            return;
        }
    }

    // Show loading state
    document.getElementById('playerDetailsContent').innerHTML = `
        <div class="flex items-center justify-center py-8">
            <i class="ti ti-loader ti-spin text-2xl text-gray-500 dark:text-gray-400"></i>
            <span class="ml-2 text-gray-500 dark:text-gray-400">Loading player details...</span>
        </div>`;

    // Show modal
    playerDetailsModal.show();

    // Fetch user details
    fetch(`/admin/user-approvals/user/${userId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const user = data.user;
                const player = user.player;

                let detailsHtml = '';

                // Header with avatar and basic info
                detailsHtml += '<div class="flex items-center gap-4 pb-4 border-b border-gray-200 dark:border-gray-700">';

                // Profile image or avatar
                if (player && player.profile_picture_url) {
                    detailsHtml += `<img src="${player.profile_picture_url}" alt="${player.name}" class="w-16 h-16 rounded-full object-cover">`;
                } else {
                    detailsHtml += `<div class="w-16 h-16 rounded-full bg-ecs-green flex items-center justify-center text-white text-2xl font-bold">${user.username.charAt(0).toUpperCase()}</div>`;
                }

                // Basic info
                detailsHtml += '<div class="flex-1">';
                detailsHtml += `<h3 class="text-lg font-semibold text-gray-900 dark:text-white">${user.username}</h3>`;
                if (player) {
                    detailsHtml += `<p class="text-sm text-gray-500 dark:text-gray-400">${player.name}</p>`;
                }
                detailsHtml += `<p class="text-sm text-gray-500 dark:text-gray-400">${user.email}</p>`;
                detailsHtml += '</div>';
                detailsHtml += '</div>';

                // Account Information Section
                detailsHtml += '<div class="mt-4">';
                detailsHtml += '<h5 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Account Information</h5>';
                detailsHtml += '<div class="grid grid-cols-2 gap-3">';

                detailsHtml += '<div>';
                detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Registration Date</div>';
                detailsHtml += `<div class="text-sm text-gray-900 dark:text-white">${user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unknown'}</div>`;
                detailsHtml += '</div>';

                detailsHtml += '<div>';
                detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Status</div>';
                detailsHtml += '<div class="text-sm"><span class="px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300 rounded">Pending Approval</span></div>';
                detailsHtml += '</div>';

                if (player && player.discord_id) {
                    detailsHtml += '<div>';
                    detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Discord ID</div>';
                    detailsHtml += `<div class="text-sm"><code class="px-1 py-0.5 text-xs bg-gray-100 dark:bg-gray-700 text-gray-800 dark:text-gray-200 rounded">${player.discord_id}</code></div>`;
                    detailsHtml += '</div>';
                }

                detailsHtml += '<div>';
                detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Current Roles</div>';
                detailsHtml += '<div class="text-sm flex flex-wrap gap-1">';
                detailsHtml += user.roles.map(role => `<span class="px-2 py-0.5 text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300 rounded">${role}</span>`).join('');
                detailsHtml += '</div>';
                detailsHtml += '</div>';

                detailsHtml += '</div>';
                detailsHtml += '</div>';

                // Player Information Section (if exists)
                if (player) {
                    detailsHtml += '<div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">';
                    detailsHtml += '<h5 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Player Information</h5>';
                    detailsHtml += '<div class="grid grid-cols-2 gap-3">';

                    if (player.pronouns) {
                        detailsHtml += '<div>';
                        detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Pronouns</div>';
                        detailsHtml += `<div class="text-sm text-gray-900 dark:text-white">${player.pronouns}</div>`;
                        detailsHtml += '</div>';
                    }

                    if (player.phone) {
                        detailsHtml += '<div>';
                        detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Phone</div>';
                        detailsHtml += `<div class="text-sm text-gray-900 dark:text-white">${player.phone}</div>`;
                        detailsHtml += '</div>';
                    }

                    if (player.jersey_size) {
                        detailsHtml += '<div>';
                        detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Jersey Size</div>';
                        detailsHtml += `<div class="text-sm text-gray-900 dark:text-white">${player.jersey_size}</div>`;
                        detailsHtml += '</div>';
                    }

                    if (player.favorite_position) {
                        detailsHtml += '<div>';
                        detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Favorite Position</div>';
                        detailsHtml += `<div class="text-sm text-gray-900 dark:text-white">${player.favorite_position}</div>`;
                        detailsHtml += '</div>';
                    }

                    // Only show player status if user is approved
                    if (user.approval_status === 'approved') {
                        detailsHtml += '<div>';
                        detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Player Status</div>';
                        detailsHtml += `<div class="text-sm">${player.is_current_player ? '<span class="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300 rounded">Active</span>' : '<span class="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300 rounded">Inactive</span>'}</div>`;
                        detailsHtml += '</div>';

                        if (player.is_coach) {
                            detailsHtml += '<div>';
                            detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Coach Status</div>';
                            detailsHtml += '<div class="text-sm"><span class="px-2 py-0.5 text-xs font-medium bg-purple-100 text-purple-800 dark:bg-purple-900 dark:text-purple-300 rounded">Coach</span></div>';
                            detailsHtml += '</div>';
                        }

                        if (player.is_sub) {
                            detailsHtml += '<div>';
                            detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Substitute Status</div>';
                            detailsHtml += '<div class="text-sm"><span class="px-2 py-0.5 text-xs font-medium bg-orange-100 text-orange-800 dark:bg-orange-900 dark:text-orange-300 rounded">Substitute</span></div>';
                            detailsHtml += '</div>';
                        }
                    } else {
                        // For pending users, show that they're awaiting approval
                        detailsHtml += '<div>';
                        detailsHtml += '<div class="text-xs text-gray-500 dark:text-gray-400 mb-1">Player Status</div>';
                        detailsHtml += '<div class="text-sm"><span class="px-2 py-0.5 text-xs font-medium bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300 rounded">Awaiting Approval</span></div>';
                        detailsHtml += '</div>';
                    }

                    detailsHtml += '</div>';
                    detailsHtml += '</div>';
                }

                document.getElementById('playerDetailsContent').innerHTML = detailsHtml;

                // Update profile link
                const profileLink = document.getElementById('profileLink');
                if (player) {
                    profileLink.href = `/players/profile/${player.id}`;
                    profileLink.classList.remove('hidden');
                } else {
                    profileLink.classList.add('hidden');
                }
            } else {
                document.getElementById('playerDetailsContent').innerHTML = '<div class="text-center text-red-500 dark:text-red-400 py-4">Error loading player details</div>';
            }
        })
        .catch(error => {
            console.error('Error loading details:', error);
            document.getElementById('playerDetailsContent').innerHTML = '<div class="text-center text-red-500 dark:text-red-400 py-4">Error loading player details</div>';
        });
}

// Register with window.InitSystem (primary)
if (window.InitSystem.register) {
    window.InitSystem.register('user-approval-management', initUserApprovalManagement, {
        priority: 30,
        reinitializable: true,
        description: 'User approval management page'
    });
}

// Fallback
// window.InitSystem handles initialization

// Window exports - only functions used by event delegation handlers (user-approval.js)
window.showApprovalModal = showApprovalModal;
window.showDenialModal = showDenialModal;
window.submitApproval = submitApproval;
window.submitDenial = submitDenial;
window.refreshStats = refreshStats;
window.showPlayerDetails = showPlayerDetails;
