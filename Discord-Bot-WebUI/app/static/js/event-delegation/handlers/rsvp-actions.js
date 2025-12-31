/**
 * RSVP Action Handlers
 * Handles match RSVP responses and notifications
 */
// Uses global window.EventDelegation from core.js

// RSVP ACTIONS
// ============================================================================

/**
 * RSVP Yes Action
 * Player confirms attendance (admin can set for players)
 */
window.EventDelegation.register('rsvp-yes', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const playerId = element.dataset.playerId;

    if (!matchId) {
        console.error('[rsvp-yes] Missing match ID');
        return;
    }

    // Admin update mode (has playerId) vs player self-RSVP
    if (playerId) {
        // Admin updating player RSVP
        if (typeof updatePlayerRSVP === 'function') {
            updatePlayerRSVP(playerId, matchId, 'yes');
        } else {
            // Fallback: trigger the update-rsvp-btn logic
            const response = 'yes';
            updateRSVPStatus(playerId, matchId, response);
        }
    } else {
        // Player self-RSVP
        if (typeof submitRSVP === 'function') {
            submitRSVP(matchId, 'yes');
        } else {
            console.error('[rsvp-yes] submitRSVP function not found');
        }
    }
});

/**
 * RSVP No Action
 * Player confirms they cannot attend
 */
window.EventDelegation.register('rsvp-no', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const playerId = element.dataset.playerId;

    if (!matchId) {
        console.error('[rsvp-no] Missing match ID');
        return;
    }

    if (playerId) {
        if (typeof updatePlayerRSVP === 'function') {
            updatePlayerRSVP(playerId, matchId, 'no');
        } else {
            updateRSVPStatus(playerId, matchId, 'no');
        }
    } else {
        if (typeof submitRSVP === 'function') {
            submitRSVP(matchId, 'no');
        } else {
            console.error('[rsvp-no] submitRSVP function not found');
        }
    }
});

/**
 * RSVP Maybe Action
 * Player is unsure about attendance
 */
window.EventDelegation.register('rsvp-maybe', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const playerId = element.dataset.playerId;

    if (!matchId) {
        console.error('[rsvp-maybe] Missing match ID');
        return;
    }

    if (playerId) {
        if (typeof updatePlayerRSVP === 'function') {
            updatePlayerRSVP(playerId, matchId, 'maybe');
        } else {
            updateRSVPStatus(playerId, matchId, 'maybe');
        }
    } else {
        if (typeof submitRSVP === 'function') {
            submitRSVP(matchId, 'maybe');
        } else {
            console.error('[rsvp-maybe] submitRSVP function not found');
        }
    }
});

/**
 * Withdraw RSVP Action
 * Player cancels their RSVP
 */
window.EventDelegation.register('rsvp-withdraw', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const playerId = element.dataset.playerId;

    if (!matchId) {
        console.error('[rsvp-withdraw] Missing match ID');
        return;
    }

    if (playerId) {
        // Admin clearing player RSVP
        if (typeof updatePlayerRSVP === 'function') {
            updatePlayerRSVP(playerId, matchId, 'no_response');
        } else {
            updateRSVPStatus(playerId, matchId, 'no_response');
        }
    } else {
        // Player withdrawing own RSVP
        if (typeof withdrawRSVP === 'function') {
            withdrawRSVP(matchId);
        } else {
            console.error('[rsvp-withdraw] withdrawRSVP function not found');
        }
    }
});

/**
 * Send SMS Action
 * Opens modal to send SMS to player
 */
window.EventDelegation.register('rsvp-request-sms', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;
    const phone = element.dataset.phone;

    if (!playerId) {
        console.error('[rsvp-request-sms] Missing player ID');
        return;
    }

    // Use jQuery if available (legacy code uses it)
    if (window.jQuery) {
        const $ = window.jQuery;

        try {
            // Populate modal fields
            $('#smsPlayerName').text(playerName || 'Player');
            $('#smsPlayerId').val(playerId);
            $('#smsPlayerPhone').val(phone || '');

            // Format phone number for display
            if (phone && typeof formatPhoneNumber === 'function') {
                $('#smsPlayerPhoneDisplay').text(formatPhoneNumber(phone));
            } else {
                $('#smsPlayerPhoneDisplay').text(phone || '');
            }

            $('#smsMessage').val('');
            $('#smsCharCount').text('0');

            // Show modal
            const smsModal = document.querySelector('[data-modal="send-sms"]');
            if (smsModal) {
                window.ModalManager.showByElement(smsModal);
            }
        } catch (err) {
            console.error('[rsvp-request-sms] Error opening modal:', err);
        }
    } else {
        // Vanilla JS fallback
        const smsModal = document.querySelector('[data-modal="send-sms"]');
        if (smsModal && window.bootstrap) {
            // Set values directly
            const playerNameEl = document.getElementById('smsPlayerName');
            const playerIdEl = document.getElementById('smsPlayerId');
            const playerPhoneEl = document.getElementById('smsPlayerPhone');
            const messageEl = document.getElementById('smsMessage');
            const charCountEl = document.getElementById('smsCharCount');

            if (playerNameEl) playerNameEl.textContent = playerName || 'Player';
            if (playerIdEl) playerIdEl.value = playerId;
            if (playerPhoneEl) playerPhoneEl.value = phone || '';
            if (messageEl) messageEl.value = '';
            if (charCountEl) charCountEl.textContent = '0';

            window.ModalManager.showByElement(smsModal);
        }
    }
});

/**
 * Send Discord DM Action
 * Opens modal to send Discord direct message
 */
window.EventDelegation.register('rsvp-request-discord-dm', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;
    const discordId = element.dataset.discordId;

    if (!playerId) {
        console.error('[rsvp-request-discord-dm] Missing player ID');
        return;
    }

    // Use jQuery if available (legacy code uses it)
    if (window.jQuery) {
        const $ = window.jQuery;

        try {
            $('#discordPlayerName').text(playerName || 'Player');
            $('#discordPlayerId').val(playerId);
            $('#discordId').val(discordId || '');
            $('#discordMessage').val('');
            $('#discordCharCount').text('0');

            const discordModal = document.querySelector('[data-modal="send-discord-dm"]');
            if (discordModal) {
                window.ModalManager.showByElement(discordModal);
            }
        } catch (err) {
            console.error('[rsvp-request-discord-dm] Error opening modal:', err);
        }
    } else {
        // Vanilla JS fallback
        const discordModal = document.querySelector('[data-modal="send-discord-dm"]');
        if (discordModal && window.bootstrap) {
            const playerNameEl = document.getElementById('discordPlayerName');
            const playerIdEl = document.getElementById('discordPlayerId');
            const discordIdEl = document.getElementById('discordId');
            const messageEl = document.getElementById('discordMessage');
            const charCountEl = document.getElementById('discordCharCount');

            if (playerNameEl) playerNameEl.textContent = playerName || 'Player';
            if (playerIdEl) playerIdEl.value = playerId;
            if (discordIdEl) discordIdEl.value = discordId || '';
            if (messageEl) messageEl.value = '';
            if (charCountEl) charCountEl.textContent = '0';

            window.ModalManager.showByElement(discordModal);
        }
    }
});

/**
 * Update RSVP Status Action (Admin)
 * Admin manually updates player RSVP status
 * This is the main handler that triggers the update via AJAX
 */
window.EventDelegation.register('rsvp-update-status', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const matchId = element.dataset.matchId;
    const response = element.dataset.response;

    if (!playerId || !matchId || !response) {
        console.error('[rsvp-update-status] Missing required data attributes');
        return;
    }

    updateRSVPStatus(playerId, matchId, response);
});

/**
 * Helper function to update RSVP status via AJAX
 * This replaces the inline logic from the jQuery handler
 */
function updateRSVPStatus(playerId, matchId, response) {
    // Use SweetAlert2 for confirmation
    if (typeof Swal === 'undefined') {
        console.error('[updateRSVPStatus] SweetAlert2 not available');
        return;
    }

    Swal.fire({
        title: 'Update RSVP Status?',
        text: 'Are you sure you want to update this player\'s RSVP status?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, update it',
        cancelButtonText: 'Cancel',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('primary') : '#0d6efd',
        customClass: {
            confirmButton: 'swal-btn-confirm',
            cancelButton: 'swal-btn-cancel'
        },
        buttonsStyling: false
    }).then((result) => {
        if (result.isConfirmed) {
            const formData = new FormData();

            // Get CSRF token
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value || '';

            formData.append('csrf_token', csrfToken);
            formData.append('player_id', playerId);
            formData.append('match_id', matchId);
            formData.append('response', response);

            // Show loading state
            Swal.fire({
                title: 'Updating...',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading();
                }
            });

            // Make the AJAX request
            fetch('/admin/update_rsvp', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(function(response) {
                if (!response.ok) {
                    throw new Error('Network response was not ok');
                }
                return response.json();
            })
            .then(function(data) {
                if (data.success) {
                    Swal.fire({
                        title: 'Success!',
                        text: 'RSVP updated successfully.',
                        icon: 'success',
                        timer: 1500,
                        showConfirmButton: false
                    }).then(() => {
                        window.location.reload();
                    });
                } else {
                    Swal.fire({
                        title: 'Error',
                        text: data.message || 'Error updating RSVP.',
                        icon: 'error'
                    });
                }
            })
            .catch(function(error) {
                console.error('[updateRSVPStatus] Error:', error);
                Swal.fire({
                    title: 'Error',
                    text: 'An error occurred while updating RSVP. Please try again.',
                    icon: 'error'
                });
            });
        }
    });
}

// ============================================================================
// ECS FC RSVP PAGE ACTIONS
// ============================================================================

/**
 * Send RSVP Reminder to all players
 */
window.EventDelegation.register('send-rsvp-reminder', function(element, e) {
    e.preventDefault();
    if (typeof window.sendReminder === 'function') {
        window.sendReminder();
    } else {
        console.error('[send-rsvp-reminder] sendReminder function not found');
    }
}, { preventDefault: true });

/**
 * Filter RSVP responses by type
 */
window.EventDelegation.register('filter-rsvp-responses', function(element, e) {
    e.preventDefault();
    const filterType = element.dataset.filterType || 'all';
    if (typeof window.filterResponses === 'function') {
        window.filterResponses(filterType);
    } else {
        console.error('[filter-rsvp-responses] filterResponses function not found');
    }
}, { preventDefault: true });

/**
 * Update player RSVP (admin action)
 */
window.EventDelegation.register('update-player-rsvp-admin', function(element, e) {
    e.preventDefault();
    const playerId = element.dataset.playerId;
    const response = element.dataset.response;
    if (!playerId || !response) {
        console.error('[update-player-rsvp-admin] Missing player ID or response');
        return;
    }
    if (typeof window.updatePlayerRsvp === 'function') {
        window.updatePlayerRsvp(playerId, response);
    } else {
        console.error('[update-player-rsvp-admin] updatePlayerRsvp function not found');
    }
}, { preventDefault: true });

/**
 * Send individual reminder to specific player
 */
window.EventDelegation.register('send-individual-reminder', function(element, e) {
    e.preventDefault();
    const playerId = element.dataset.playerId;
    if (!playerId) {
        console.error('[send-individual-reminder] Missing player ID');
        return;
    }
    if (typeof window.sendIndividualReminder === 'function') {
        window.sendIndividualReminder(playerId);
    } else {
        console.error('[send-individual-reminder] sendIndividualReminder function not found');
    }
}, { preventDefault: true });

// ============================================================================

console.log('[EventDelegation] RSVP handlers loaded');
