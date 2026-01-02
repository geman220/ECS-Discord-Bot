import { EventDelegation } from '../core.js';
import { ModalManager } from '../../modal-manager.js';

/**
 * Discord Management Action Handlers
 * Handles Discord integration and player management
 */

// DISCORD MANAGEMENT ACTIONS
// ============================================================================

/**
 * Change Per Page Action (triggered by change event)
 * Updates the number of items displayed per page
 */
window.EventDelegation.register('change-per-page', function(element, e) {
    const perPage = element.value;
    const url = new URL(window.location);
    url.searchParams.set('per_page', perPage);
    url.searchParams.set('page', '1'); // Reset to first page
    window.location.href = url.toString();
});

/**
 * Refresh All Discord Status Action
 * Refreshes Discord status for all players
 */
window.EventDelegation.register('refresh-all-discord-status', function(element, e) {
    e.preventDefault();

    const btn = element;

    if (typeof window.Swal === 'undefined') {
        console.error('[refresh-all-discord-status] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Refresh All Discord Status',
        text: 'This will refresh Discord status for all players. This may take a moment. Continue?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, refresh all',
        cancelButtonText: 'Cancel',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('success') : '#28c76f',
        cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#ea5455'
    }).then((result) => {
        if (result.isConfirmed) {
            // Show loading state
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i>Refreshing...';
            btn.disabled = true;

            // Get CSRF token
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            // Refresh all Discord status
            fetch('/admin/refresh_all_discord_status', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            }).then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Status Updated',
                        text: `Refreshed Discord status for ${data.success_count} players`,
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => {
                        location.reload();
                    });
                } else {
                    throw new Error(data.message || 'Failed to refresh status');
                }
            }).catch(error => {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Failed to refresh status: ' + error.message,
                    confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#ea5455'
                });
            }).finally(() => {
                btn.innerHTML = originalText;
                btn.disabled = false;
            });
        }
    });
});

/**
 * Refresh Unknown Discord Status Action
 * Checks Discord status for all players with unknown status
 */
window.EventDelegation.register('refresh-unknown-discord-status', function(element, e) {
    e.preventDefault();

    const btn = element;

    if (typeof window.Swal === 'undefined') {
        console.error('[refresh-unknown-discord-status] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Check Unknown Discord Status',
        text: 'This will check Discord status for all players with unknown status. Continue?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Yes, check unknown',
        cancelButtonText: 'Cancel',
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('warning') : '#ffab00',
        cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#ea5455'
    }).then((result) => {
        if (result.isConfirmed) {
            // Show loading state
            const originalText = btn.innerHTML;
            btn.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i>Checking...';
            btn.disabled = true;

            // Get CSRF token
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

            // Check unknown Discord status
            fetch('/admin/refresh_unknown_discord_status', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            }).then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'Status Checked',
                        text: `Checked Discord status for ${data.success_count} players with unknown status`,
                        timer: 2000,
                        showConfirmButton: false
                    }).then(() => {
                        location.reload();
                    });
                } else {
                    throw new Error(data.message || 'Failed to check unknown status');
                }
            }).catch(error => {
                window.Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Failed to check unknown status: ' + error.message,
                    confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#ea5455'
                });
            }).finally(() => {
                btn.innerHTML = originalText;
                btn.disabled = false;
            });
        }
    });
});

/**
 * Refresh Player Status Action
 * Refreshes Discord status for individual player
 */
window.EventDelegation.register('refresh-player-status', function(element, e) {
    e.preventDefault();

    const playerId = element.dataset.playerId;
    const playerName = element.dataset.playerName;

    if (!playerId) {
        console.error('[refresh-player-status] Missing player ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i><span>Checking...</span>';
    element.disabled = true;

    // Get CSRF token
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/teams/player/${playerId}/refresh-discord-status`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    }).then(response => response.json())
    .then(data => {
        if (data.success) {
            // Show success message and reload
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Status Updated',
                    text: `Discord status refreshed for ${playerName}`,
                    timer: 2000,
                    showConfirmButton: false
                }).then(() => {
                    location.reload();
                });
            } else {
                location.reload();
            }
        } else {
            throw new Error(data.message || 'Failed to refresh status');
        }
    }).catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to refresh status: ' + error.message,
                confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#ea5455'
            });
        } else {
            console.error('[refresh-player-status] Error:', error);
        }
    }).finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

/**
 * Send Discord DM Action
 * Opens modal to send Discord direct message
 */
window.EventDelegation.register('send-discord-dm', function(element, e) {
    e.preventDefault();

    const discordId = element.dataset.discordId;
    const playerName = element.dataset.playerName;

    if (!discordId) {
        console.error('[send-discord-dm] Missing Discord ID');
        return;
    }

    const dmDiscordIdInput = document.getElementById('dmDiscordId');
    const modalTitle = document.querySelector('#discordDMModal .modal-title');
    const dmMessageTextarea = document.getElementById('dmMessage');

    if (dmDiscordIdInput) dmDiscordIdInput.value = discordId;
    if (modalTitle) modalTitle.textContent = `Send Discord DM to ${playerName}`;

    // Set default message
    const defaultMessage = `Hi ${playerName}! 👋

We noticed you haven't joined our ECS FC Discord server yet.

Join us to:
• Get match updates and announcements
• Connect with your teammates
• Participate in league discussions

Join here: https://discord.gg/weareecs

See you there!
- ECS FC Admin Team`;

    if (dmMessageTextarea) dmMessageTextarea.value = defaultMessage;

    // Show modal
    const modalElement = document.getElementById('discordDMModal');
    if (modalElement) {
        window.ModalManager.show('discordDMModal');
    }
});

/**
 * Submit Discord DM Action
 * Sends the Discord direct message
 */
window.EventDelegation.register('submit-discord-dm', function(element, e) {
    e.preventDefault();

    const discordId = document.getElementById('dmDiscordId')?.value;
    const message = document.getElementById('dmMessage')?.value;

    if (!message || !message.trim()) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'warning',
                title: 'Message Required',
                text: 'Please enter a message before sending',
                confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('warning') : '#ffab00'
            });
        }
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i>Sending...';
    element.disabled = true;

    // Get CSRF token
    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch('/admin/send_discord_dm', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            discord_id: discordId,
            message: message
        })
    }).then(response => response.json())
    .then(data => {
        if (data.success) {
            const modalElement = document.getElementById('discordDMModal');
            if (modalElement && window.bootstrap) {
                const modalInstance = window.bootstrap.Modal.getInstance(modalElement);
                if (modalInstance) modalInstance.hide();
            }

            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Message Sent',
                    text: 'Discord message sent successfully!',
                    timer: 2000,
                    showConfirmButton: false
                });
            }
        } else {
            throw new Error(data.message || 'Failed to send message');
        }
    }).catch(error => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to send Discord message: ' + error.message,
                confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('danger') : '#ea5455'
            });
        } else {
            console.error('[submit-discord-dm] Error:', error);
        }
    }).finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

// ============================================================================

console.log('[window.EventDelegation] Discord management handlers loaded');
