'use strict';

/**
 * Draft Enhanced Confirmation
 * Draft confirmation modal and team selection
 * @module draft-enhanced/draft-confirmation
 */

import { getLeagueName } from './state.js';

/**
 * Custom Draft Confirmation Modal
 * @param {string} playerId - The player's ID
 * @param {string} playerName - The player's name
 * @param {boolean} isMultiTeam - Whether this player is already on an ECS FC team
 * @param {string} existingTeams - Comma-separated list of teams the player is already on
 */
export function confirmDraftPlayer(playerId, playerName, isMultiTeam = false, existingTeams = '') {
    // For multi-team players, show confirmation first
    if (isMultiTeam && existingTeams) {
        // Use SweetAlert2 for the confirmation if available
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Add to Another ECS FC Team?',
                html: `<p>This player is already on:</p>
                       <p class="fw-bold text-info">${existingTeams}</p>
                       <p>Add <strong>${playerName}</strong> to an additional team?</p>`,
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Yes, Continue',
                cancelButtonText: 'Cancel',
                confirmButtonColor: '#0066FF',
                cancelButtonColor: '#6c757d'
            }).then((result) => {
                if (result.isConfirmed) {
                    showDraftTeamSelection(playerId, playerName, existingTeams);
                }
            });
        }
        return;
    }

    // Standard draft flow - show team selection directly
    showDraftTeamSelection(playerId, playerName, existingTeams);
}

/**
 * Show the team selection modal for drafting
 * @param {string} playerId
 * @param {string} playerName
 * @param {string} existingTeams
 */
export function showDraftTeamSelection(playerId, playerName, existingTeams = '') {
    // Check if modal exists on this page
    const modalElement = document.getElementById('draftConfirmModal');
    if (!modalElement) {
        console.warn('[draft-confirmation] draftConfirmModal not found on this page');
        return;
    }

    // Populate the message
    let message = `Select a team for <strong>${playerName}</strong>:`;
    if (existingTeams) {
        message = `Select an additional team for <strong>${playerName}</strong>:<br><small class="text-muted">Already on: ${existingTeams}</small>`;
    }
    document.getElementById('draftPlayerMessage').innerHTML = message;

    // Populate team options
    const teamSelect = document.getElementById('teamSelect');
    teamSelect.innerHTML = '<option value="">Choose a team...</option>';

    // Get all teams and their player counts
    document.querySelectorAll('[id^="teamCount"]').forEach(badge => {
        const teamId = badge.id.replace('teamCount', '');
        const teamName = badge.parentElement.querySelector('.fw-bold').textContent;
        const playerCount = badge.textContent.replace(' players', '');

        const option = document.createElement('option');
        option.value = teamId;
        option.textContent = `${teamName} (${playerCount})`;
        teamSelect.appendChild(option);
    });

    // Set up the confirm button
    const confirmBtn = document.getElementById('confirmDraftBtn');
    confirmBtn.onclick = function() {
        const selectedTeamId = teamSelect.value;
        if (!selectedTeamId) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Selection Required', 'Please select a team!', 'warning');
            }
            return;
        }

        // Close modal
        const modalEl = document.getElementById('draftConfirmModal');
        modalEl?._flowbiteModal?.hide();

        const leagueName = getLeagueName();

        // Execute the draft via socket or API
        const socket = window.draftEnhancedSocket || window.socket;
        if (socket && socket.connected) {
            socket.emit('draft_player_enhanced', {
                player_id: parseInt(playerId),
                team_id: parseInt(selectedTeamId),
                league_name: leagueName
            });
        }

        console.log(`Drafting player ${playerId} to team ${selectedTeamId}`);
    };

    // Show the modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('draftConfirmModal');
    } else if (typeof window.Modal !== 'undefined') {
        const flowbiteModal = modalElement._flowbiteModal || (modalElement._flowbiteModal = new window.Modal(modalElement, { backdrop: 'dynamic', closable: true }));
        flowbiteModal.show();
    }
}
