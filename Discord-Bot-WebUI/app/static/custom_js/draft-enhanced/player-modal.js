'use strict';

/**
 * Draft Enhanced Player Modal
 * Player profile modal functionality
 * @module draft-enhanced/player-modal
 */

import { formatPosition } from './state.js';
import { setupImageErrorHandlers } from './image-handlers.js';
import { confirmDraftPlayer } from './draft-confirmation.js';

/**
 * Open player profile modal
 * @param {string} playerId
 */
export function openPlayerModal(playerId) {
    // Check if modal exists on this page
    const modalElement = document.getElementById('playerProfileModal');
    if (!modalElement) {
        console.warn('[draft-enhanced] playerProfileModal not found on this page');
        return;
    }

    // Show loading state
    const profileLoading = document.getElementById('profileLoading');
    profileLoading.classList.add('block');
    profileLoading.classList.remove('hidden');
    // Use Flowbite's hidden class pattern instead of is-visible
    document.getElementById('profileData').classList.add('hidden');
    document.getElementById('draftFromModal').classList.add('hidden');

    // Open modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('playerProfileModal');
    } else if (typeof window.Modal !== 'undefined') {
        const flowbiteModal = modalElement._flowbiteModal || (modalElement._flowbiteModal = new window.Modal(modalElement, { backdrop: 'dynamic', closable: true }));
        flowbiteModal.show();
    }

    // Fetch player data
    fetch(`/players/api/player_profile/${playerId}`)
        .then(response => response.json())
        .then(data => {
            displayPlayerProfile(data, playerId);
        })
        .catch(error => {
            console.error('Error loading player profile:', error);
            document.getElementById('profileLoading').innerHTML = `
                <div class="text-center py-5">
                    <i class="ti ti-exclamation-triangle text-warning mb-3 draft-error-icon"></i>
                    <h5>Error Loading Profile</h5>
                    <p class="text-muted">Unable to load player information. Please try again.</p>
                </div>
            `;
        });
}

/**
 * Display player profile in modal
 * @param {Object} data
 * @param {string} playerId
 */
export function displayPlayerProfile(data, playerId) {
    const profileLoading = document.getElementById('profileLoading');
    profileLoading.classList.add('hidden');
    profileLoading.classList.remove('block');

    const profileHtml = `
        <div class="p-4 draft-profile-container">
            <!-- Player Header Info -->
            <div class="text-center mb-4">
                <img src="${data.profile_picture_url || '/static/img/default_player.png'}"
                     alt="${data.name}"
                     class="rounded-circle border border-3 border-white mb-3 draft-profile-avatar js-player-image"
                     data-fallback="/static/img/default_player.png">
                <h4 class="fw-bold mb-1 draft-profile-name">${data.name}</h4>
                <p class="mb-2 draft-profile-position">${formatPosition(data.favorite_position) || 'Any Position'}</p>

                <!-- Career Stats Row -->
                <div class="row text-center mb-4">
                    <div class="col-3">
                        <div class="fw-bold text-success fs-5">${data.goals}</div>
                        <small class="draft-profile-stat-label">Goals</small>
                    </div>
                    <div class="col-3">
                        <div class="fw-bold text-info fs-5">${data.assists}</div>
                        <small class="draft-profile-stat-label">Assists</small>
                    </div>
                    <div class="col-3">
                        <div class="fw-bold text-warning fs-5">${data.yellow_cards}</div>
                        <small class="draft-profile-stat-label">Yellow</small>
                    </div>
                    <div class="col-3">
                        <div class="fw-bold text-danger fs-5">${data.red_cards}</div>
                        <small class="draft-profile-stat-label">Red</small>
                    </div>
                </div>
            </div>

            <!-- Playing Information Section -->
            <div class="mb-4">
                <h5 class="pb-2 mb-3 draft-profile-section-header">
                    <i class="ti ti-info-circle me-2"></i>Playing Information
                </h5>
                <div class="row">
                    <div class="col-md-6">
                        <div class="mb-2">
                            <strong class="draft-profile-label">Preferred Position:</strong>
                            <span class="badge bg-primary ms-1">${formatPosition(data.favorite_position) || 'Any'}</span>
                        </div>
                        ${data.other_positions ? `
                        <div class="mb-2">
                            <strong class="draft-profile-label">Other Positions:</strong>
                            <small class="draft-profile-value">${Array.isArray(data.other_positions) ? data.other_positions.map(pos => formatPosition(pos)).join(', ') : data.other_positions}</small>
                        </div>
                        ` : ''}
                        ${data.positions_to_avoid ? `
                        <div class="mb-2">
                            <strong class="draft-profile-label">Positions to Avoid:</strong>
                            <small class="draft-profile-value">${data.positions_to_avoid}</small>
                        </div>
                        ` : ''}
                    </div>
                    <div class="col-md-6">
                        ${data.goal_frequency ? `
                        <div class="mb-2">
                            <strong class="draft-profile-label">Goal Frequency:</strong>
                            <small class="draft-profile-value">${data.goal_frequency}</small>
                        </div>
                        ` : ''}
                        ${data.expected_availability ? `
                        <div class="mb-2">
                            <strong class="draft-profile-label">Expected Availability:</strong>
                            <small class="draft-profile-value">${data.expected_availability}</small>
                        </div>
                        ` : ''}
                    </div>
                </div>
            </div>

            <!-- Player Notes -->
            ${data.player_notes ? `
            <div class="mb-4">
                <h5 class="pb-2 mb-3 draft-profile-section-header">
                    <i class="ti ti-notes me-2"></i>Player Notes
                </h5>
                <p class="draft-profile-notes">${data.player_notes}</p>
            </div>
            ` : ''}

            <!-- Admin Notes -->
            ${data.admin_notes ? `
            <div class="mb-3">
                <h5 class="pb-2 mb-3 draft-profile-section-header">
                    <i class="ti ti-shield me-2"></i>Admin Notes
                </h5>
                <p class="draft-profile-notes">${data.admin_notes}</p>
            </div>
            ` : ''}
        </div>
    `;

    document.getElementById('profileData').innerHTML = profileHtml;
    // Use Flowbite's hidden class pattern instead of is-visible
    document.getElementById('profileData').classList.remove('hidden');

    // Re-setup image error handlers for dynamically added images
    setupImageErrorHandlers();

    // Show draft button and set up click handler
    const draftButton = document.getElementById('draftFromModal');
    // Use Flowbite's hidden class pattern instead of is-visible
    draftButton.classList.remove('hidden');
    draftButton.onclick = () => {
        // Close modal and trigger draft using ModalManager
        if (typeof window.ModalManager !== 'undefined') {
            window.ModalManager.hide('playerProfileModal');
        } else {
            // Fallback to direct Flowbite instance
            const modalEl = document.getElementById('playerProfileModal');
            modalEl?._flowbiteModal?.hide();
        }
        confirmDraftPlayer(playerId, data.name);
    };
}
