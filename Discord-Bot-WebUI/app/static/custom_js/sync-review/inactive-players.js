'use strict';

/**
 * Sync Review Inactive Players
 * Inactive player count and display updates
 * @module sync-review/inactive-players
 */

import { getSyncData, getResolutions } from './state.js';

/**
 * Update inactive player count based on assignments
 */
export function updateInactivePlayerCount() {
    const syncData = getSyncData();
    const resolutions = getResolutions();

    // Get all players assigned to existing orders
    let assignedPlayerIds = new Set();

    // Add players from multi-order assignments
    Object.values(resolutions.multiOrders).forEach(assignments => {
        assignments.forEach(assignment => {
            if (assignment.playerId) {
                assignedPlayerIds.add(assignment.playerId);
            }
        });
    });

    // Filter out assigned players from the inactive list
    const remainingInactive = syncData.players_to_inactivate ?
        syncData.players_to_inactivate.filter(player => !assignedPlayerIds.has(player.player_id)) : [];

    // Update the badge count
    const inactiveBadge = document.getElementById('inactivePlayersBadge');
    if (inactiveBadge) {
        inactiveBadge.textContent = remainingInactive.length;
    }

    // Update the count in the stats card
    const inactiveCount = document.getElementById('potentialInactiveCount');
    if (inactiveCount) {
        inactiveCount.textContent = remainingInactive.length;
    }

    // Update the display in the inactive players tab
    updateInactivePlayersDisplay(remainingInactive, assignedPlayerIds);
}

/**
 * Update inactive players display
 * @param {Array} remainingInactive
 * @param {Set} assignedPlayerIds
 */
export function updateInactivePlayersDisplay(remainingInactive, assignedPlayerIds) {
    const syncData = getSyncData();
    const inactiveTab = document.getElementById('inactive-players');
    if (!inactiveTab) return;

    const cardBody = inactiveTab.querySelector('.card-body');
    if (!cardBody) return;

    if (remainingInactive.length === 0) {
        cardBody.innerHTML = `
            <div class="text-center py-5">
                <i class="ti ti-circle-check text-green-600 dark:text-green-400 text-6xl"></i>
                <h4 class="text-green-600 dark:text-green-400 mt-3 text-lg font-semibold">No Players to Mark Inactive!</h4>
                <p class="text-gray-500 dark:text-gray-400">All currently active players have current WooCommerce memberships.</p>
            </div>
        `;
        return;
    }

    let html = `
        <div class="flex items-center p-4 mb-4 text-yellow-800 rounded-lg bg-yellow-50 border-l-4 border-yellow-500 dark:bg-gray-800 dark:text-yellow-400" role="alert" data-alert>
            <i class="ti ti-user-off mr-2 text-xl"></i>
            <div>
                <h6 class="font-semibold mb-1">Players to Mark Inactive</h6>
                <p class="text-sm">These players are currently active but have no current WooCommerce membership orders. They will be marked as inactive.</p>
            </div>
        </div>

        <div class="mb-4">
            <div class="flex justify-between items-center">
                <span class="text-gray-500 dark:text-gray-400 text-sm">
                    <strong class="font-semibold">${remainingInactive.length}</strong> players will be marked inactive
                </span>
                <div class="flex items-center">
                    <input type="checkbox" id="confirmInactiveProcess" checked class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                    <label for="confirmInactiveProcess" class="ml-2 text-sm font-semibold text-gray-900 dark:text-gray-300">
                        Proceed with marking these players inactive
                    </label>
                </div>
            </div>
        </div>
    `;

    // Show excluded players if any
    const excludedPlayers = syncData.players_to_inactivate ?
        syncData.players_to_inactivate.filter(player => assignedPlayerIds.has(player.player_id)) : [];

    if (excludedPlayers.length > 0) {
        html += `
            <div class="flex items-center p-4 mb-4 text-blue-800 rounded-lg bg-blue-50 border-l-4 border-blue-500 dark:bg-gray-800 dark:text-blue-400" role="alert" data-alert>
                <i class="ti ti-info-circle mr-2 text-xl"></i>
                <div>
                    <h6 class="font-semibold mb-1">Players Excluded from Inactive List</h6>
                    <p class="text-sm mb-1">${excludedPlayers.length} players were excluded because they were assigned to orders during resolution.</p>
                    <p class="text-xs text-gray-500 dark:text-gray-400">These players will remain active: ${excludedPlayers.map(p => p.player_name).join(', ')}</p>
                </div>
            </div>
        `;
    }

    // Add remaining inactive players
    remainingInactive.forEach(player => {
        html += `
            <div class="issue-card inactive-player-card border border-gray-200 dark:border-gray-700 rounded-lg p-4 mb-3">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4 items-center">
                    <div>
                        <h6 class="text-sm font-semibold text-gray-900 dark:text-white mb-1">
                            <i class="ti ti-user-off text-yellow-500 mr-2"></i>
                            ${player.player_name}
                        </h6>
                        <p class="text-xs text-gray-500 dark:text-gray-400">
                            <i class="ti ti-user mr-1"></i>Username: ${player.username}<br>
                            <i class="ti ti-shield mr-1"></i>League: ${player.league_name}
                        </p>
                    </div>
                    <div class="text-center">
                        <span class="px-2 py-0.5 text-xs font-medium rounded bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300" data-badge>Currently Active</span>
                        <div class="my-2">
                            <i class="ti ti-arrow-down text-yellow-500"></i>
                        </div>
                        <span class="px-2 py-0.5 text-xs font-medium rounded bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300" data-badge>Will be Inactive</span>
                    </div>
                    <div class="text-right">
                        <p class="text-xs text-gray-500 dark:text-gray-400">
                            <i class="ti ti-info-circle mr-1"></i>${player.reason}
                        </p>
                    </div>
                </div>
            </div>
        `;
    });

    cardBody.innerHTML = html;
}
