'use strict';

/**
 * Admin Reports Handlers
 *
 * Event delegation handlers for admin panel report pages:
 * - feedback_list.html
 * - rsvp_status.html
 *
 * @version 1.0.0
 */

import { EventDelegation } from '../core.js';

// ============================================================================
// FEEDBACK MANAGEMENT HANDLERS
// ============================================================================

/**
 * Close Feedback
 * Closes a feedback item
 */
window.EventDelegation.register('close-feedback', function(element, e) {
    e.preventDefault();

    const feedbackId = element.dataset.feedbackId;

    if (!feedbackId) {
        console.error('[close-feedback] Missing feedback ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Close Feedback?',
            text: 'Are you sure you want to close this feedback?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, Close',
            cancelButtonText: 'Cancel'
        }).then((result) => {
            if (result.isConfirmed) {
                performCloseFeedback(element, feedbackId);
            }
        });
    }
    return;
});

function performCloseFeedback(element, feedbackId) {

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/reports/feedback/${feedbackId}/close`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast(data.message || 'Feedback closed', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.message || 'Failed to close feedback');
        }
    })
    .catch(error => {
        if (typeof window.AdminPanel !== 'undefined') {
            window.AdminPanel.showMobileToast('Error closing feedback', 'danger');
        }
        console.error('Error closing feedback:', error);
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
}

/**
 * Delete Feedback
 * Deletes a feedback item with confirmation
 */
window.EventDelegation.register('delete-feedback', function(element, e) {
    e.preventDefault();

    const feedbackId = element.dataset.feedbackId;

    if (!feedbackId) {
        console.error('[delete-feedback] Missing feedback ID');
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Delete Feedback?',
            text: 'This cannot be undone.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonText: 'Yes, Delete',
            cancelButtonText: 'Cancel',
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#dc3545'
        }).then((result) => {
            if (result.isConfirmed) {
                performDeleteFeedback(element, feedbackId);
            }
        });
    }
    return;
});

function performDeleteFeedback(element, feedbackId) {

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/admin-panel/reports/feedback/${feedbackId}/delete`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast(data.message || 'Feedback deleted', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.message || 'Failed to delete feedback');
        }
    })
    .catch(error => {
        if (typeof window.AdminPanel !== 'undefined') {
            window.AdminPanel.showMobileToast('Error deleting feedback', 'danger');
        }
        console.error('Error deleting feedback:', error);
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
}

/**
 * Filter by Priority
 * Changes the priority filter for feedback list
 */
window.EventDelegation.register('filter-feedback-priority', function(element, e) {
    const priority = element.value;
    const url = new URL(window.location.href);

    if (priority) {
        url.searchParams.set('priority', priority);
    } else {
        url.searchParams.delete('priority');
    }

    window.location.href = url.toString();
});

// ============================================================================
// RSVP STATUS HANDLERS
// ============================================================================

/**
 * Update RSVP
 * Updates RSVP status for a player
 */
window.EventDelegation.register('update-rsvp', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const response = element.dataset.response;

    if (!playerId || !response) {
        console.error('[update-rsvp] Missing player ID or response');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    // Disable all RSVP buttons for this player
    const allButtons = document.querySelectorAll(`[data-player-id="${playerId}"]`);
    allButtons.forEach(btn => btn.disabled = true);

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    // Get match ID from container data attribute or form
    const container = element.closest('[data-match-id]');
    const matchId = container?.dataset.matchId ||
                    document.querySelector('[data-match-id]')?.dataset.matchId ||
                    document.querySelector('[name="match_id"]')?.value;

    // Build form data for POST
    const formData = new FormData();
    formData.append('player_id', playerId);
    formData.append('match_id', matchId);
    formData.append('response', response);

    fetch('/admin-panel/reports/rsvp/update', {
        method: 'POST',
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrfToken
        },
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast(data.message || 'RSVP updated', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.message || 'Failed to update RSVP');
        }
    })
    .catch(error => {
        if (typeof window.AdminPanel !== 'undefined') {
            window.AdminPanel.showMobileToast('Error updating RSVP', 'danger');
        }
        console.error('Error updating RSVP:', error);
        // Re-enable buttons on error
        allButtons.forEach(btn => btn.disabled = false);
    })
    .finally(() => {
        element.innerHTML = originalText;
    });
});

/**
 * Bulk RSVP Update
 * Updates multiple RSVP statuses at once
 */
window.EventDelegation.register('bulk-rsvp-update', function(element, e) {
    e.preventDefault();

    const action = element.dataset.action;
    const response = element.dataset.response;

    if (!action || !response) {
        console.error('[bulk-rsvp-update] Missing action or response');
        return;
    }

    const selectedPlayers = [];
    document.querySelectorAll('input[name="selected_players"]:checked').forEach(cb => {
        selectedPlayers.push(cb.value);
    });

    if (selectedPlayers.length === 0) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Warning', 'Please select at least one player', 'warning');
        }
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i>Updating...';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
    const matchId = document.querySelector('[name="match_id"]')?.value;

    fetch('/admin-panel/reports/rsvp/bulk-update', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            player_ids: selectedPlayers,
            response: response,
            match_id: matchId
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.AdminPanel !== 'undefined') {
                window.AdminPanel.showMobileToast(data.message || 'RSVPs updated', 'success');
            }
            location.reload();
        } else {
            throw new Error(data.message || 'Failed to update RSVPs');
        }
    })
    .catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Error', error.message, 'error');
        }
        console.error('Error updating RSVPs:', error);
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

// Handlers loaded
