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
                <i class="ti ti-circle-check text-success empty-state-icon"></i>
                <h4 class="text-success mt-3">No Players to Mark Inactive!</h4>
                <p class="text-muted">All currently active players have current WooCommerce memberships.</p>
            </div>
        `;
        return;
    }

    let html = `
        <div class="alert alert-warning border-start border-warning border-3 py-3 px-4 mb-4" data-alert>
            <div class="d-flex align-items-center">
                <i class="ti ti-user-off me-2 fs-4"></i>
                <div>
                    <h6 class="alert-heading mb-1">Players to Mark Inactive</h6>
                    <p class="mb-0">These players are currently active but have no current WooCommerce membership orders. They will be marked as inactive.</p>
                </div>
            </div>
        </div>

        <div class="row mb-3">
            <div class="col-12">
                <div class="d-flex justify-content-between align-items-center">
                    <span class="text-muted">
                        <strong>${remainingInactive.length}</strong> players will be marked inactive
                    </span>
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="confirmInactiveProcess" checked>
                        <label class="form-check-label fw-semibold" for="confirmInactiveProcess">
                            Proceed with marking these players inactive
                        </label>
                    </div>
                </div>
            </div>
        </div>
    `;

    // Show excluded players if any
    const excludedPlayers = syncData.players_to_inactivate ?
        syncData.players_to_inactivate.filter(player => assignedPlayerIds.has(player.player_id)) : [];

    if (excludedPlayers.length > 0) {
        html += `
            <div class="alert alert-info border-start border-info border-3 py-3 px-4 mb-4" data-alert>
                <div class="d-flex align-items-center">
                    <i class="ti ti-info-circle me-2 fs-4"></i>
                    <div>
                        <h6 class="alert-heading mb-1">Players Excluded from Inactive List</h6>
                        <p class="mb-0">${excludedPlayers.length} players were excluded because they were assigned to orders during resolution.</p>
                        <small class="text-muted">These players will remain active: ${excludedPlayers.map(p => p.player_name).join(', ')}</small>
                    </div>
                </div>
            </div>
        `;
    }

    // Add remaining inactive players
    remainingInactive.forEach(player => {
        html += `
            <div class="issue-card inactive-player-card border rounded p-3 mb-3">
                <div class="row align-items-center">
                    <div class="col-md-4">
                        <h6 class="mb-1">
                            <i class="ti ti-user-off text-warning me-2"></i>
                            ${player.player_name}
                        </h6>
                        <small class="text-muted">
                            <i class="ti ti-user me-1"></i>Username: ${player.username}<br>
                            <i class="ti ti-shield me-1"></i>League: ${player.league_name}
                        </small>
                    </div>
                    <div class="col-md-4">
                        <div class="text-center">
                            <span class="badge bg-success" data-badge>Currently Active</span>
                            <div class="mt-2">
                                <i class="ti ti-arrow-down text-warning"></i>
                            </div>
                            <span class="badge bg-warning" data-badge>Will be Inactive</span>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="text-end">
                            <small class="text-muted">
                                <i class="ti ti-info-circle me-1"></i>${player.reason}
                            </small>
                        </div>
                    </div>
                </div>
            </div>
        `;
    });

    cardBody.innerHTML = html;
}
