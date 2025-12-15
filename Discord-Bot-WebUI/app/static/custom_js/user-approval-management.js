/**
 * User Approval Management JavaScript
 * Handles user approval and denial functionality for league placement
 */

// Global variables
let currentUserId = null;
let approvalModal = null;
let denialModal = null;
let playerDetailsModal = null;

// Initialize when document is ready
document.addEventListener('DOMContentLoaded', function() {
    initializeModals();
    initializeEventListeners();
});

/**
 * Initialize Bootstrap modals
 */
function initializeModals() {
    const approvalModalElement = document.getElementById('approvalModal');
    const denialModalElement = document.getElementById('denialModal');
    const playerDetailsModalElement = document.getElementById('playerDetailsModal');
    
    if (approvalModalElement) {
        approvalModal = new bootstrap.Modal(approvalModalElement);
    }
    
    if (denialModalElement) {
        denialModal = new bootstrap.Modal(denialModalElement);
    }
    
    if (playerDetailsModalElement) {
        playerDetailsModal = new bootstrap.Modal(playerDetailsModalElement);
    }
}

/**
 * Initialize event listeners
 */
function initializeEventListeners() {
    // Close modals when clicking outside or on close button
    document.addEventListener('click', function(event) {
        if (event.target.classList.contains('btn-close')) {
            if (approvalModal) approvalModal.hide();
            if (denialModal) denialModal.hide();
        }
    });
    
    // Handle form submissions
    const approvalForm = document.getElementById('approvalForm');
    const denialForm = document.getElementById('denialForm');
    
    if (approvalForm) {
        approvalForm.addEventListener('submit', function(e) {
            e.preventDefault();
            submitApproval();
        });
    }
    
    if (denialForm) {
        denialForm.addEventListener('submit', function(e) {
            e.preventDefault();
            submitDenial();
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
    
    // Disable submit button
    const submitButton = document.querySelector('#approvalModal .btn-approve');
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
            updateStats();
            
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
    
    // Disable submit button
    const submitButton = document.querySelector('#denialModal .btn-deny');
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
            updateStats();
            
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
    const table = document.querySelector('.table tbody');
    if (!table) return;
    
    const rows = table.querySelectorAll('tr');
    rows.forEach(row => {
        const approveButton = row.querySelector(`button[onclick="showApprovalModal(${userId})"]`);
        if (approveButton) {
            // Add fade out animation
            row.style.transition = 'opacity 0.3s ease';
            row.style.opacity = '0';
            
            // Remove after animation
            setTimeout(() => {
                row.remove();
                
                // Check if table is empty
                const remainingRows = table.querySelectorAll('tr');
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
    const cardBody = document.querySelector('.card-body');
    if (cardBody) {
        cardBody.innerHTML = `
            <div class="text-center py-4">
                <i class="ti ti-users" style="font-size: 3rem; color: var(--ecs-secondary);"></i>
                <h6 class="mt-3">No pending approvals</h6>
                <p class="text-muted">All users have been processed</p>
            </div>
        `;
    }
}

/**
 * Update statistics display
 */
function updateStats() {
    fetch('/admin/user-approvals/stats')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const stats = data.stats;
                
                // Update stats cards
                const pendingCard = document.querySelector('.stats-card.pending .stats-number');
                const approvedCard = document.querySelector('.stats-card.approved .stats-number');
                const deniedCard = document.querySelector('.stats-card.denied .stats-number');
                const totalCard = document.querySelector('.stats-card:not(.pending):not(.approved):not(.denied) .stats-number');
                
                if (pendingCard) pendingCard.textContent = stats.pending;
                if (approvedCard) approvedCard.textContent = stats.approved;
                if (deniedCard) deniedCard.textContent = stats.denied;
                if (totalCard) totalCard.textContent = stats.total;
                
                // Update badge in card header
                const pendingBadge = document.querySelector('.card-header .badge');
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
    const refreshButton = document.querySelector('button[onclick="refreshStats()"]');
    if (refreshButton) {
        const originalText = refreshButton.innerHTML;
        refreshButton.innerHTML = '<i class="ti ti-loader"></i> Refreshing...';
        refreshButton.disabled = true;
        
        setTimeout(() => {
            updateStats();
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
    // Try to get from meta tag first
    const metaTag = document.querySelector('meta[name="csrf-token"]');
    if (metaTag) {
        return metaTag.getAttribute('content');
    }
    
    // Try to get from cookie
    const cookieValue = document.cookie
        .split('; ')
        .find(row => row.startsWith('csrf_token='))
        ?.split('=')[1];
    
    return cookieValue || '';
}

/**
 * Show success alert
 * @param {string} message - Success message
 */
function showSuccessAlert(message) {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
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
    if (typeof Swal !== 'undefined') {
        Swal.fire({
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
    if (typeof Swal !== 'undefined') {
        Swal.fire({
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
    if (typeof Swal !== 'undefined') {
        Swal.fire({
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
                detailsHtml += '<div class="info-value"><span class="badge bg-warning">Pending Approval</span></div>';
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
                detailsHtml += user.roles.map(role => `<span class="badge bg-primary me-1">${role}</span>`).join('');
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
                        detailsHtml += `<div class="info-value">${player.is_current_player ? '<span class="badge bg-success">Active</span>' : '<span class="badge bg-secondary">Inactive</span>'}</div>`;
                        detailsHtml += '</div>';
                        
                        if (player.is_coach) {
                            detailsHtml += '<div class="info-item">';
                            detailsHtml += '<div class="info-label">Coach Status</div>';
                            detailsHtml += '<div class="info-value"><span class="badge bg-info">Coach</span></div>';
                            detailsHtml += '</div>';
                        }
                        
                        if (player.is_sub) {
                            detailsHtml += '<div class="info-item">';
                            detailsHtml += '<div class="info-label">Substitute Status</div>';
                            detailsHtml += '<div class="info-value"><span class="badge bg-info">Substitute</span></div>';
                            detailsHtml += '</div>';
                        }
                    } else {
                        // For pending users, show that they're awaiting approval
                        detailsHtml += '<div class="info-item">';
                        detailsHtml += '<div class="info-label">Player Status</div>';
                        detailsHtml += '<div class="info-value"><span class="badge bg-warning">Awaiting Approval</span></div>';
                        detailsHtml += '</div>';
                    }
                    
                    detailsHtml += '</div>';
                    detailsHtml += '</div>';
                }
                
                document.getElementById('playerDetailsContent').innerHTML = detailsHtml;
                
                // Update profile link
                if (player) {
                    document.getElementById('profileLink').href = `/players/profile/${player.id}`;
                    document.getElementById('profileLink').style.display = 'inline-block';
                } else {
                    document.getElementById('profileLink').style.display = 'none';
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