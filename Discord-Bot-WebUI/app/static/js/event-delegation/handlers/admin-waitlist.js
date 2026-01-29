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
import { InitSystem } from '../../init-system.js';
import { escapeHtml } from '../../utils/sanitize.js';

let _initialized = false;

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
 * Show notification using window.Swal if available
 */
function showNotification(title, message, type = 'info') {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: title,
            text: message,
            icon: type
        });
    }
}

/**
 * Show modal using window.ModalManager or Flowbite
 */
function showModal(modalId) {
    // Guard: Check if modal element exists on this page
    const modalEl = document.getElementById(modalId);
    if (!modalEl) {
        console.warn(`[admin-waitlist] Modal ${modalId} not found on this page`);
        return;
    }

    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show(modalId);
    } else if (typeof window.Modal !== 'undefined') {
        const modal = modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
        modal.show();
    }
}

/**
 * Hide modal using Flowbite
 */
function hideModal(modalId) {
    const modalEl = document.getElementById(modalId);
    if (modalEl && modalEl._flowbiteModal) {
        modalEl._flowbiteModal.hide();
    }
}

// ============================================================================
// PAGE REFRESH
// ============================================================================

/**
 * Refresh page action
 */
window.EventDelegation.register('refresh', (element, event) => {
    event.preventDefault();
    location.reload();
});

// ============================================================================
// VIEW PLAYER DETAILS
// ============================================================================

/**
 * View player details in modal
 */
window.EventDelegation.register('view-player', (element, event) => {
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
 * Uses escapeHtml to prevent XSS from user data
 */
function buildPlayerDetailsHTML(user) {
    const preferredLeagueDisplay =
        user.preferred_league === 'pub_league_classic' ? 'Pub League Classic' :
        user.preferred_league === 'pub_league_premier' ? 'Pub League Premier' :
        user.preferred_league === 'ecs_fc' ? 'ECS FC' :
        escapeHtml(user.preferred_league) || 'Not specified';

    const safeStatus = escapeHtml(user.approval_status);
    const statusBadgeClass = safeStatus === 'approved' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' :
                             safeStatus === 'denied' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300' :
                             'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';

    return `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div>
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Basic Information</h6>
                <div class="space-y-2">
                    <p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Username:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.username)}</span></p>
                    <p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Email:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.email)}</span></p>
                    <p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Joined:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.created_at) || 'Unknown'}</span></p>
                    <p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Status:</span> <span class="px-2 py-0.5 text-xs font-medium ${statusBadgeClass} rounded ml-1">${safeStatus}</span></p>
                    <p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Preferred League:</span> <span class="text-gray-900 dark:text-white">${preferredLeagueDisplay}</span></p>
                    <p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Roles:</span> ${user.roles.map(role => `<span class="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300 rounded ml-1">${escapeHtml(role)}</span>`).join('')}</p>
                </div>
            </div>
            <div>
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Player Details</h6>
                <div class="space-y-2">
                    ${user.player.name ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Name:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.name)}</span></p>` : ''}
                    ${user.player.phone ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Phone:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.phone)}</span></p>` : ''}
                    ${user.player.pronouns ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Pronouns:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.pronouns)}</span></p>` : ''}
                    ${user.player.discord_id ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Discord:</span> <span class="text-ecs-green">Linked</span></p>` : '<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Discord:</span> <span class="text-gray-500 dark:text-gray-400">Not linked</span></p>'}
                    ${user.player.jersey_size ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Jersey Size:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.jersey_size)}</span></p>` : ''}
                    ${user.player.jersey_number ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Jersey Number:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.jersey_number)}</span></p>` : ''}
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
            <div>
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Playing Information</h6>
                <div class="space-y-2">
                    ${user.player.favorite_position ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Favorite Position:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.favorite_position)}</span></p>` : ''}
                    ${user.player.other_positions ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Other Positions:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.other_positions)}</span></p>` : ''}
                    ${user.player.positions_not_to_play ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Positions NOT to Play:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.positions_not_to_play)}</span></p>` : ''}
                    ${user.player.frequency_play_goal ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Frequency Play Goal:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.frequency_play_goal)}</span></p>` : ''}
                    ${user.player.expected_weeks_available ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Expected Weeks Available:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.expected_weeks_available)}</span></p>` : ''}
                    ${user.player.willing_to_referee ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Willing to Referee:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.willing_to_referee)}</span></p>` : ''}
                </div>
            </div>
            <div>
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Substitute Information</h6>
                <div class="space-y-2">
                    <p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Interested in Subbing:</span> ${user.player.interested_in_sub ? '<span class="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300 rounded ml-1">Yes</span>' : '<span class="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300 rounded ml-1">No</span>'}</p>
                    <p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Available for Subbing:</span> ${user.player.is_sub ? '<span class="px-2 py-0.5 text-xs font-medium bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300 rounded ml-1">Yes</span>' : '<span class="px-2 py-0.5 text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300 rounded ml-1">No</span>'}</p>
                    ${user.player.unavailable_dates ? `<p class="text-sm"><span class="font-medium text-gray-700 dark:text-gray-300">Unavailable Dates:</span> <span class="text-gray-900 dark:text-white">${escapeHtml(user.player.unavailable_dates)}</span></p>` : ''}
                </div>
            </div>
        </div>

        ${user.player.additional_info ? `
            <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">Additional Information</h6>
                <p class="text-sm text-gray-700 dark:text-gray-300">${escapeHtml(user.player.additional_info)}</p>
            </div>
        ` : ''}

        ${user.player.player_notes ? `
            <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-2">Player Notes</h6>
                <p class="text-sm text-gray-700 dark:text-gray-300">${escapeHtml(user.player.player_notes)}</p>
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
window.EventDelegation.register('contact-modal', (element, event) => {
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
window.EventDelegation.register('submit-contact', (element, event) => {
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
window.EventDelegation.register('removal-modal', (element, event) => {
    event.preventDefault();
    currentUserId = element.dataset.userId;

    const reasonInput = document.getElementById('removal-reason');
    if (reasonInput) reasonInput.value = '';

    showModal('removalModal');
});

/**
 * Submit removal form
 */
window.EventDelegation.register('submit-removal', (element, event) => {
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
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    title: 'Success',
                    text: data.message,
                    icon: 'success'
                }).then(() => {
                    location.reload();
                });
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
    if (_initialized) return;

    // Only run on waitlist page
    const waitlistCount = document.getElementById('waitlist-count');
    if (!waitlistCount) return;

    _initialized = true;

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

    console.log('[window.EventDelegation] Admin waitlist auto-refresh initialized');
}

// Register with window.InitSystem
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('admin-waitlist', initAutoRefresh, {
        priority: 50,
        reinitializable: false,
        description: 'Admin waitlist auto-refresh stats'
    });
}

// Fallback
// window.InitSystem handles initialization

// Handlers loaded
