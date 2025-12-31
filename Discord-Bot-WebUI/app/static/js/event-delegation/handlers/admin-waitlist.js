/**
 * Admin Waitlist Management Handlers
 *
 * Event delegation handlers for user waitlist administration:
 * - View player details
 * - Contact users
 * - Remove from waitlist
 * - Auto-refresh stats
 */

import { EventDelegation } from '../core.js';

// ============================================================================
// MODULE STATE
// ============================================================================

let currentUserId = null;

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

/**
 * Get CSRF token from meta tag
 */
function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
}

/**
 * Show notification using Swal if available
 */
function showNotification(title, message, type = 'info') {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: title,
            text: message,
            icon: type
        });
    } else {
        alert(`${title}: ${message}`);
    }
}

/**
 * Show modal using ModalManager or bootstrap
 */
function showModal(modalId) {
    if (typeof ModalManager !== 'undefined') {
        ModalManager.show(modalId);
    } else if (typeof bootstrap !== 'undefined') {
        const modalEl = document.getElementById(modalId);
        if (modalEl) {
            const modal = new bootstrap.Modal(modalEl);
            modal.show();
        }
    }
}

/**
 * Hide modal using bootstrap
 */
function hideModal(modalId) {
    const modalEl = document.getElementById(modalId);
    if (modalEl && typeof bootstrap !== 'undefined') {
        const modal = bootstrap.Modal.getInstance(modalEl);
        if (modal) modal.hide();
    }
}

// ============================================================================
// PAGE REFRESH
// ============================================================================

/**
 * Refresh page action
 */
EventDelegation.register('refresh', (element, event) => {
    event.preventDefault();
    location.reload();
});

// ============================================================================
// VIEW PLAYER DETAILS
// ============================================================================

/**
 * View player details in modal
 */
EventDelegation.register('view-player', (element, event) => {
    event.preventDefault();
    const userId = element.dataset.userId;
    if (!userId) return;

    fetch(`/admin/user-waitlist/user/${userId}`)
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const user = data.user;
                const content = document.getElementById('playerDetailsContent');

                if (content) {
                    content.innerHTML = buildPlayerDetailsHTML(user);
                }

                showModal('playerDetailsModal');
            } else {
                showNotification('Error', data.message, 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Error', 'An error occurred while loading player details', 'error');
        });
});

/**
 * Build HTML for player details modal
 */
function buildPlayerDetailsHTML(user) {
    const preferredLeagueDisplay =
        user.preferred_league === 'pub_league_classic' ? 'Pub League Classic' :
        user.preferred_league === 'pub_league_premier' ? 'Pub League Premier' :
        user.preferred_league === 'ecs_fc' ? 'ECS FC' :
        user.preferred_league || 'Not specified';

    return `
        <div class="row">
            <div class="col-md-6">
                <h6>Basic Information</h6>
                <p><strong>Username:</strong> ${user.username}</p>
                <p><strong>Email:</strong> ${user.email}</p>
                <p><strong>Joined:</strong> ${user.created_at || 'Unknown'}</p>
                <p><strong>Status:</strong> <span class="badge status-${user.approval_status}" data-badge>${user.approval_status}</span></p>
                <p><strong>Preferred League:</strong> ${preferredLeagueDisplay}</p>
                <p><strong>Roles:</strong> ${user.roles.map(role => `<span class="badge bg-label-secondary me-1" data-badge>${role}</span>`).join('')}</p>
            </div>
            <div class="col-md-6">
                <h6>Player Details</h6>
                ${user.player.name ? `<p><strong>Name:</strong> ${user.player.name}</p>` : ''}
                ${user.player.phone ? `<p><strong>Phone:</strong> ${user.player.phone}</p>` : ''}
                ${user.player.pronouns ? `<p><strong>Pronouns:</strong> ${user.player.pronouns}</p>` : ''}
                ${user.player.discord_id ? `<p><strong>Discord:</strong> <span class="text-primary">Linked</span></p>` : '<p><strong>Discord:</strong> <span class="text-muted">Not linked</span></p>'}
                ${user.player.jersey_size ? `<p><strong>Jersey Size:</strong> ${user.player.jersey_size}</p>` : ''}
                ${user.player.jersey_number ? `<p><strong>Jersey Number:</strong> ${user.player.jersey_number}</p>` : ''}
            </div>
        </div>

        <div class="row mt-3">
            <div class="col-md-6">
                <h6>Playing Information</h6>
                ${user.player.favorite_position ? `<p><strong>Favorite Position:</strong> ${user.player.favorite_position}</p>` : ''}
                ${user.player.other_positions ? `<p><strong>Other Positions:</strong> ${user.player.other_positions}</p>` : ''}
                ${user.player.positions_not_to_play ? `<p><strong>Positions NOT to Play:</strong> ${user.player.positions_not_to_play}</p>` : ''}
                ${user.player.frequency_play_goal ? `<p><strong>Frequency Play Goal:</strong> ${user.player.frequency_play_goal}</p>` : ''}
                ${user.player.expected_weeks_available ? `<p><strong>Expected Weeks Available:</strong> ${user.player.expected_weeks_available}</p>` : ''}
                ${user.player.willing_to_referee ? `<p><strong>Willing to Referee:</strong> ${user.player.willing_to_referee}</p>` : ''}
            </div>
            <div class="col-md-6">
                <h6>Substitute Information</h6>
                <p><strong>Interested in Subbing:</strong> ${user.player.interested_in_sub ? '<span class="badge bg-label-success" data-badge>Yes</span>' : '<span class="badge bg-label-secondary" data-badge>No</span>'}</p>
                <p><strong>Available for Subbing:</strong> ${user.player.is_sub ? '<span class="badge bg-label-success" data-badge>Yes</span>' : '<span class="badge bg-label-secondary" data-badge>No</span>'}</p>
                ${user.player.unavailable_dates ? `<p><strong>Unavailable Dates:</strong> ${user.player.unavailable_dates}</p>` : ''}
            </div>
        </div>

        ${user.player.additional_info ? `
            <div class="row mt-3">
                <div class="col-12">
                    <h6>Additional Information</h6>
                    <p>${user.player.additional_info}</p>
                </div>
            </div>
        ` : ''}

        ${user.player.player_notes ? `
            <div class="row mt-3">
                <div class="col-12">
                    <h6>Player Notes</h6>
                    <p>${user.player.player_notes}</p>
                </div>
            </div>
        ` : ''}
    `;
}

// ============================================================================
// CONTACT MODAL
// ============================================================================

/**
 * Open contact modal
 */
EventDelegation.register('contact-modal', (element, event) => {
    event.preventDefault();
    currentUserId = element.dataset.userId;

    const methodSelect = document.getElementById('contact-method');
    const messageInput = document.getElementById('contact-message');

    if (methodSelect) methodSelect.value = 'email';
    if (messageInput) messageInput.value = '';

    showModal('contactModal');
});

/**
 * Submit contact form
 */
EventDelegation.register('submit-contact', (element, event) => {
    event.preventDefault();

    const method = document.getElementById('contact-method')?.value;
    const message = document.getElementById('contact-message')?.value?.trim() || '';

    if (!currentUserId) {
        showNotification('Error', 'No user selected', 'error');
        return;
    }

    fetch(`/admin/user-waitlist/contact/${currentUserId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({
            contact_method: method,
            message: message
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showNotification('Success', data.message, 'success');
        } else {
            showNotification('Error', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error', 'An error occurred while logging the contact', 'error');
    });

    hideModal('contactModal');
});

// ============================================================================
// REMOVAL MODAL
// ============================================================================

/**
 * Open removal modal
 */
EventDelegation.register('removal-modal', (element, event) => {
    event.preventDefault();
    currentUserId = element.dataset.userId;

    const reasonInput = document.getElementById('removal-reason');
    if (reasonInput) reasonInput.value = '';

    showModal('removalModal');
});

/**
 * Submit removal form
 */
EventDelegation.register('submit-removal', (element, event) => {
    event.preventDefault();

    const reason = document.getElementById('removal-reason')?.value?.trim();

    if (!reason) {
        showNotification('Error', 'Please provide a reason for removal', 'error');
        return;
    }

    if (!currentUserId) {
        showNotification('Error', 'No user selected', 'error');
        return;
    }

    fetch(`/admin/user-waitlist/remove/${currentUserId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify({
            reason: reason
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    title: 'Success',
                    text: data.message,
                    icon: 'success'
                }).then(() => {
                    location.reload();
                });
            } else {
                alert(data.message);
                location.reload();
            }
        } else {
            showNotification('Error', data.message, 'error');
        }
    })
    .catch(error => {
        console.error('Error:', error);
        showNotification('Error', 'An error occurred while removing the user', 'error');
    });

    hideModal('removalModal');
});

// ============================================================================
// AUTO-REFRESH STATS
// ============================================================================

/**
 * Initialize auto-refresh for waitlist stats
 * This runs on page load for the waitlist page
 */
function initAutoRefresh() {
    // Only run on waitlist page
    const waitlistCount = document.getElementById('waitlist-count');
    if (!waitlistCount) return;

    setInterval(function() {
        fetch('/admin/user-waitlist/stats')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    const waitlistEl = document.getElementById('waitlist-count');
                    const registeredEl = document.getElementById('total-registered');
                    const approvedEl = document.getElementById('total-approved');

                    if (waitlistEl) waitlistEl.textContent = data.stats.waitlist_count;
                    if (registeredEl) registeredEl.textContent = data.stats.total_registered;
                    if (approvedEl) approvedEl.textContent = data.stats.total_approved;
                }
            })
            .catch(error => {
                console.error('Error refreshing stats:', error);
            });
    }, 30000);
}

// Initialize auto-refresh when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAutoRefresh);
} else {
    initAutoRefresh();
}

console.log('[EventDelegation] Admin waitlist handlers loaded');
