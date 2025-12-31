/**
 * User Approval Management JavaScript
 * Handles user approval and denial functionality for league placement
 */

(function() {
'use strict';

let _initialized = false;

// Module-level variables
let currentUserId = null;
let approvalModal = null;
let denialModal = null;
let playerDetailsModal = null;

// Initialize function
function init() {
    if (_initialized) return;
    _initialized = true;

    initializeModals();
    initializeFormSubmitListeners();
}

/**
 * Initialize Bootstrap modals
 */
function initializeModals() {
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
function initializeFormSubmitListeners() {
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
function showApprovalModal(userId) {
    if (!approvalModal) {
        showErrorAlert('Modal not initialized');
        return;
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
function showDenialModal(userId) {
    if (!denialModal) {
        showErrorAlert('Modal not initialized');
        return;
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
function submitApproval() {
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
function submitDenial() {
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
function removeUserFromTable(userId) {
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
function showEmptyTableMessage() {
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
function userApprovalUpdateStats() {
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
function refreshStats() {
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

/**
 * Get CSRF token from meta tag or cookie
 * @returns {string} CSRF token
 */
function getCSRFToken() {
    // Try to get from meta tag first (vanilla JS pattern)
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    // If not found in meta tag, try cookie as fallback
    if (!csrfToken) {
        const cookieValue = document.cookie
            .split('; ')
            .find(row => row.startsWith('csrf_token='))
            ?.split('=')[1];
        return cookieValue || '';
    }

    return csrfToken;
}

/**
 * Show success alert
 * @param {string} message - Success message
 */
function showSuccessAlert(message) {
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
function showErrorAlert(message) {
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
function showWarningAlert(message) {
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
function showInfoAlert(message) {
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
function showPlayerDetails(userId) {
    if (!playerDetailsModal) {
        showErrorAlert('Details modal not initialized');
        return;
    }

    // Show loading state
    document.getElementById('playerDetailsContent').innerHTML = '<div class="text-center py-4"><i class="ti ti-loader ti-spin"></i> Loading player details...</div>';

    // Show modal
    playerDetailsModal.show();

    // Fetch user details
    fetch(`/admin/user-approvals/user/${userId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const user = data.user;
                const player = user.player;

                let detailsHtml = '<div class="player-details-header">';

                // Profile image or avatar
                if (player && player.profile_picture_url) {
                    detailsHtml += `<img src="${player.profile_picture_url}" alt="${player.name}" class="player-details-image">`;
                } else {
                    detailsHtml += `<div class="player-details-avatar">${user.username.charAt(0).toUpperCase()}</div>`;
                }

                // Basic info
                detailsHtml += '<div class="player-details-info">';
                detailsHtml += `<h3>${user.username}</h3>`;
                if (player) {
                    detailsHtml += `<p class="text-muted mb-2">${player.name}</p>`;
                }
                detailsHtml += `<p class="mb-0">${user.email}</p>`;
                detailsHtml += '</div>';
                detailsHtml += '</div>';

                // Account Information Section
                detailsHtml += '<div class="player-details-section">';
                detailsHtml += '<h5>Account Information</h5>';
                detailsHtml += '<div class="info-grid">';

                detailsHtml += '<div class="info-item">';
                detailsHtml += '<div class="info-label">Registration Date</div>';
                detailsHtml += `<div class="info-value">${user.created_at ? new Date(user.created_at).toLocaleDateString() : 'Unknown'}</div>`;
                detailsHtml += '</div>';

                detailsHtml += '<div class="info-item">';
                detailsHtml += '<div class="info-label">Status</div>';
                detailsHtml += '<div class="info-value"><span data-badge data-status="pending">Pending Approval</span></div>';
                detailsHtml += '</div>';

                if (player && player.discord_id) {
                    detailsHtml += '<div class="info-item">';
                    detailsHtml += '<div class="info-label">Discord ID</div>';
                    detailsHtml += `<div class="info-value"><code>${player.discord_id}</code></div>`;
                    detailsHtml += '</div>';
                }

                detailsHtml += '<div class="info-item">';
                detailsHtml += '<div class="info-label">Current Roles</div>';
                detailsHtml += '<div class="info-value">';
                detailsHtml += user.roles.map(role => `<span data-badge data-role="user-role">${role}</span>`).join('');
                detailsHtml += '</div>';
                detailsHtml += '</div>';

                detailsHtml += '</div>';
                detailsHtml += '</div>';

                // Player Information Section (if exists)
                if (player) {
                    detailsHtml += '<div class="player-details-section">';
                    detailsHtml += '<h5>Player Information</h5>';
                    detailsHtml += '<div class="info-grid">';

                    if (player.pronouns) {
                        detailsHtml += '<div class="info-item">';
                        detailsHtml += '<div class="info-label">Pronouns</div>';
                        detailsHtml += `<div class="info-value">${player.pronouns}</div>`;
                        detailsHtml += '</div>';
                    }

                    if (player.phone) {
                        detailsHtml += '<div class="info-item">';
                        detailsHtml += '<div class="info-label">Phone</div>';
                        detailsHtml += `<div class="info-value">${player.phone}</div>`;
                        detailsHtml += '</div>';
                    }

                    if (player.jersey_size) {
                        detailsHtml += '<div class="info-item">';
                        detailsHtml += '<div class="info-label">Jersey Size</div>';
                        detailsHtml += `<div class="info-value">${player.jersey_size}</div>`;
                        detailsHtml += '</div>';
                    }

                    if (player.favorite_position) {
                        detailsHtml += '<div class="info-item">';
                        detailsHtml += '<div class="info-label">Favorite Position</div>';
                        detailsHtml += `<div class="info-value">${player.favorite_position}</div>`;
                        detailsHtml += '</div>';
                    }

                    // Only show player status if user is approved
                    if (user.approval_status === 'approved') {
                        detailsHtml += '<div class="info-item">';
                        detailsHtml += '<div class="info-label">Player Status</div>';
                        detailsHtml += `<div class="info-value">${player.is_current_player ? '<span data-badge data-status="active">Active</span>' : '<span data-badge data-status="inactive">Inactive</span>'}</div>`;
                        detailsHtml += '</div>';

                        if (player.is_coach) {
                            detailsHtml += '<div class="info-item">';
                            detailsHtml += '<div class="info-label">Coach Status</div>';
                            detailsHtml += '<div class="info-value"><span data-badge data-role="coach">Coach</span></div>';
                            detailsHtml += '</div>';
                        }

                        if (player.is_sub) {
                            detailsHtml += '<div class="info-item">';
                            detailsHtml += '<div class="info-label">Substitute Status</div>';
                            detailsHtml += '<div class="info-value"><span data-badge data-role="substitute">Substitute</span></div>';
                            detailsHtml += '</div>';
                        }
                    } else {
                        // For pending users, show that they're awaiting approval
                        detailsHtml += '<div class="info-item">';
                        detailsHtml += '<div class="info-label">Player Status</div>';
                        detailsHtml += '<div class="info-value"><span data-badge data-status="pending">Awaiting Approval</span></div>';
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
                    profileLink.classList.remove('profile-link-hidden');
                    profileLink.classList.add('profile-link-visible');
                } else {
                    profileLink.classList.remove('profile-link-visible');
                    profileLink.classList.add('profile-link-hidden');
                }
            } else {
                document.getElementById('playerDetailsContent').innerHTML = '<div class="text-center text-danger py-4">Error loading player details</div>';
            }
        })
        .catch(error => {
            console.error('Error loading details:', error);
            document.getElementById('playerDetailsContent').innerHTML = '<div class="text-center text-danger py-4">Error loading player details</div>';
        });
}

// Export functions for global use
window.showApprovalModal = showApprovalModal;
window.showDenialModal = showDenialModal;
window.submitApproval = submitApproval;
window.submitDenial = submitDenial;
window.refreshStats = refreshStats;
window.showPlayerDetails = showPlayerDetails;

// Register with InitSystem (primary)
if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('user-approval-management', init, {
        priority: 30,
        reinitializable: true,
        description: 'User approval management page'
    });
}

// Fallback
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

})();
