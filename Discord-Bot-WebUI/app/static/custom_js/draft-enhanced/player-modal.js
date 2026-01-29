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
        <div class="p-4">
            <!-- Player Header Info -->
            <div class="text-center mb-6">
                <img src="${data.profile_picture_url || '/static/img/default_player.png'}"
                     alt="${data.name}"
                     class="w-24 h-24 rounded-full border-4 border-white dark:border-gray-700 shadow-lg mx-auto mb-3 object-cover js-player-image"
                     data-fallback="/static/img/default_player.png">
                <h4 class="text-xl font-bold text-gray-900 dark:text-white mb-1">${data.name}</h4>
                <p class="text-gray-500 dark:text-gray-400">${formatPosition(data.favorite_position) || 'Any Position'}</p>

                <!-- Career Stats Row -->
                <div class="grid grid-cols-4 gap-4 mt-4">
                    <div class="text-center">
                        <div class="text-xl font-bold text-green-600 dark:text-green-400">${data.goals}</div>
                        <small class="text-xs text-gray-500 dark:text-gray-400">Goals</small>
                    </div>
                    <div class="text-center">
                        <div class="text-xl font-bold text-cyan-600 dark:text-cyan-400">${data.assists}</div>
                        <small class="text-xs text-gray-500 dark:text-gray-400">Assists</small>
                    </div>
                    <div class="text-center">
                        <div class="text-xl font-bold text-yellow-600 dark:text-yellow-400">${data.yellow_cards}</div>
                        <small class="text-xs text-gray-500 dark:text-gray-400">Yellow</small>
                    </div>
                    <div class="text-center">
                        <div class="text-xl font-bold text-red-600 dark:text-red-400">${data.red_cards}</div>
                        <small class="text-xs text-gray-500 dark:text-gray-400">Red</small>
                    </div>
                </div>
            </div>

            <!-- Playing Information Section -->
            <div class="mb-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <h5 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">
                    <i class="ti ti-info-circle mr-2"></i>Playing Information
                </h5>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div class="space-y-2">
                        <div class="text-sm">
                            <span class="font-medium text-gray-700 dark:text-gray-300">Preferred Position:</span>
                            <span class="px-2 py-0.5 text-xs font-medium bg-ecs-green text-white rounded ml-1">${formatPosition(data.favorite_position) || 'Any'}</span>
                        </div>
                        ${data.other_positions ? `
                        <div class="text-sm">
                            <span class="font-medium text-gray-700 dark:text-gray-300">Other Positions:</span>
                            <span class="text-gray-900 dark:text-white ml-1">${Array.isArray(data.other_positions) ? data.other_positions.map(pos => formatPosition(pos)).join(', ') : data.other_positions}</span>
                        </div>
                        ` : ''}
                        ${data.positions_to_avoid ? `
                        <div class="text-sm">
                            <span class="font-medium text-gray-700 dark:text-gray-300">Positions to Avoid:</span>
                            <span class="text-gray-900 dark:text-white ml-1">${data.positions_to_avoid}</span>
                        </div>
                        ` : ''}
                    </div>
                    <div class="space-y-2">
                        ${data.goal_frequency ? `
                        <div class="text-sm">
                            <span class="font-medium text-gray-700 dark:text-gray-300">Goal Frequency:</span>
                            <span class="text-gray-900 dark:text-white ml-1">${data.goal_frequency}</span>
                        </div>
                        ` : ''}
                        ${data.expected_availability ? `
                        <div class="text-sm">
                            <span class="font-medium text-gray-700 dark:text-gray-300">Expected Availability:</span>
                            <span class="text-gray-900 dark:text-white ml-1">${data.expected_availability}</span>
                        </div>
                        ` : ''}
                    </div>
                </div>
            </div>

            <!-- Player Notes -->
            ${data.player_notes ? `
            <div class="mb-4 pt-4 border-t border-gray-200 dark:border-gray-700">
                <h5 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">
                    <i class="ti ti-notes mr-2"></i>Player Notes
                </h5>
                <p class="text-sm text-gray-700 dark:text-gray-300">${data.player_notes}</p>
            </div>
            ` : ''}

            <!-- Admin Notes -->
            ${data.admin_notes ? `
            <div class="pt-4 border-t border-gray-200 dark:border-gray-700">
                <h5 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">
                    <i class="ti ti-shield mr-2"></i>Admin Notes
                </h5>
                <p class="text-sm text-gray-700 dark:text-gray-300">${data.admin_notes}</p>
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
