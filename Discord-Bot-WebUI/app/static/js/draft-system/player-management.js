/**
 * Draft System - Player Management
 * Player card creation, addition, and removal
 *
 * @module draft-system/player-management
 */

import { updateTeamCount, updatePlayerCounts } from './ui-helpers.js';
import { applyCurrentFilters, handleSort, cleanupEmptyColumns } from './search.js';

/**
 * Format position name for display
 * @param {string} position - Raw position name
 * @returns {string} Formatted position name
 */
export function formatPosition(position) {
    if (!position) return position;
    return position.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

/**
 * Add player to team roster
 * @param {Object} player - Player data
 * @param {string} teamId - Team ID
 * @param {string} teamName - Team name
 */
export function addPlayerToTeam(player, teamId, teamName) {
    const teamSection = document.getElementById(`teamPlayers${teamId}`);
    if (!teamSection) {
        return;
    }

    const playerCard = document.createElement('div');
    playerCard.className = 'md:w-1/2 lg:w-1/3 p-2';
    playerCard.setAttribute('data-component', 'team-player-card');
    playerCard.setAttribute('data-player-id', player.id);

    const profilePictureUrl = player.profile_picture_url || '/static/img/default_player.png';

    playerCard.innerHTML = `
        <div class="card border-0 shadow-sm position-relative draft-card-grabable"
             draggable="true"
             data-drag-player-id="${player.id}">
            ${player.is_ref ? `
            <div class="position-absolute top-0 start-0 z-2">
                <div class="bg-danger text-white draft-referee-badge" title="Referee">
                    REF
                </div>
            </div>
            ` : ''}
            <div class="card-body p-2">
                <div class="flex items-center mb-2">
                    <img src="${profilePictureUrl}"
                         alt="${player.name}"
                         class="rounded-circle me-2 avatar-40"
                         loading="lazy"
                         data-fallback-src="/static/img/default_player.png">
                    <div class="flex-grow-1 min-width-0">
                        <div class="fw-semibold text-truncate small">${player.name}</div>
                        <div class="text-gray-500 dark:text-gray-400 text-xs-75">
                            ${formatPosition(player.favorite_position) || 'Any'}
                        </div>
                    </div>
                    <button class="text-red-600 bg-transparent border border-red-600 hover:bg-red-600 hover:text-white focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-xs p-1"
                            data-action="remove-player"
                            data-player-id="${player.id}"
                            data-team-id="${teamId}"
                            data-player-name="${player.name}"
                            data-team-name="${teamName}"
                            title="Remove ${player.name}">
                        <i class="ti ti-x text-xs-75"></i>
                    </button>
                </div>
                <div class="flex justify-between text-center small">
                    <div>
                        <div class="fw-bold text-green-500 dark:text-green-400">${player.career_goals || 0}</div>
                        <div class="text-gray-500 dark:text-gray-400 text-xs-70">Goals</div>
                    </div>
                    <div>
                        <div class="fw-bold text-blue-500 dark:text-blue-400">${player.career_assists || 0}</div>
                        <div class="text-gray-500 dark:text-gray-400 text-xs-70">Assists</div>
                    </div>
                    <div>
                        <div class="fw-bold">
                            <span class="text-yellow-500 dark:text-yellow-400">${player.career_yellow_cards || 0}</span>/<span class="text-red-500 dark:text-red-400">${player.career_red_cards || 0}</span>
                        </div>
                        <div class="text-gray-500 dark:text-gray-400 text-xs-70">Cards</div>
                    </div>
                </div>
            </div>
        </div>
    `;

    playerCard.classList.add('draft-card-enter');
    teamSection.appendChild(playerCard);

    // Animate in
    setTimeout(() => {
        playerCard.classList.remove('draft-card-enter');
        playerCard.classList.add('draft-card-enter-active');
    }, 10);

    updateTeamCount(teamId);
}

/**
 * Add player back to available pool
 * @param {Object} player - Player data
 */
export function addPlayerToAvailable(player) {
    const availableContainer = document.getElementById('available-players');
    if (!availableContainer) {
        return;
    }

    const playerCard = document.createElement('div');
    playerCard.className = 'xl:w-1/4 lg:w-1/3 md:w-1/2 sm:w-1/2 p-2';
    playerCard.setAttribute('data-component', 'player-column');

    const profilePictureUrl = player.profile_picture_url || '/static/img/default_player.png';
    const experienceLevel = player.experience_level || player.league_experience_seasons || 'Unknown';
    const position = formatPosition(player.favorite_position || player.position) || 'Any';

    const mediumPictureUrl = player.profile_picture_medium || player.profile_picture_webp || profilePictureUrl;
    const experienceSeasons = player.league_experience_seasons || 0;
    const attendanceEstimate = player.attendance_estimate || 75;
    const expectedAvailability = player.expected_weeks_available || 'All weeks';

    // Get experience badge color
    let experienceBadgeColor = 'secondary';
    if (experienceLevel === 'Veteran') experienceBadgeColor = 'success';
    else if (experienceLevel === 'Experienced') experienceBadgeColor = 'warning';

    // Get attendance color and display
    let attendanceColor = 'muted';
    let attendanceDisplay = 'No data';
    if (attendanceEstimate !== null && attendanceEstimate !== undefined) {
        attendanceDisplay = `${Math.round(attendanceEstimate)}%`;
        if (attendanceEstimate >= 80) attendanceColor = 'success';
        else if (attendanceEstimate >= 60) attendanceColor = 'warning';
        else attendanceColor = 'danger';
    }

    playerCard.innerHTML = `
        <div id="player-${player.id}" class="card border-0 shadow-sm h-100 draft-card-grabable-lg"
             data-component="player-card"
             data-player-id="${player.id}"
             data-player-name="${player.name.toLowerCase()}"
             data-position="${position.toLowerCase()}"
             data-experience="${experienceSeasons}"
             data-attendance="${attendanceEstimate}"
             data-goals="${player.career_goals || 0}"
             draggable="true"
             data-drag-player-id="${player.id}">

            <!-- Player Image Header -->
            <div class="position-relative overflow-hidden draft-card-image-header">
                <img src="${mediumPictureUrl}"
                     alt="${player.name}"
                     class="player-face-crop draft-img-cover"
                     loading="eager"
                     data-fallback-src="/static/img/default_player.png">

                <div class="position-absolute w-100 h-100 draft-dark-overlay"></div>

                <div class="position-absolute top-0 end-0 z-2">
                    <div class="experience-corner-tag bg-${experienceBadgeColor}"
                         title="${experienceLevel}">
                        <span class="experience-initial">
                            ${experienceLevel[0] || 'N'}
                        </span>
                    </div>
                </div>

                <div class="position-absolute bottom-0 start-0 p-2 z-2">
                    <h6 class="text-white fw-bold mb-0 text-shadow-sm">${player.name}</h6>
                </div>
            </div>

            <!-- Player Info Body -->
            <div class="card-body p-3 text-center">
                <div class="mb-2">
                    ${position !== 'Any' ?
                        `<span class="px-2.5 py-0.5 text-xs font-medium rounded-full bg-ecs-green text-white">${position}</span>` :
                        `<span class="px-2.5 py-0.5 text-xs font-medium rounded-full bg-gray-500 text-white dark:bg-gray-600">Any Position</span>`
                    }
                </div>

                <div class="row text-center mb-2 small">
                    <div class="col-6">
                        <div class="fw-bold text-green-500 dark:text-green-400">${player.career_goals || 0}</div>
                        <div class="text-gray-500 dark:text-gray-400">Goals</div>
                    </div>
                    <div class="col-6">
                        <div class="fw-bold text-blue-500 dark:text-blue-400">${player.career_assists || 0}</div>
                        <div class="text-gray-500 dark:text-gray-400">Assists</div>
                    </div>
                </div>

                <div class="row text-center mb-3 small">
                    <div class="col-6">
                        <div class="fw-bold">
                            <span class="text-yellow-500 dark:text-yellow-400">${player.career_yellow_cards || 0}</span>/<span class="text-red-500 dark:text-red-400">${player.career_red_cards || 0}</span>
                        </div>
                        <div class="text-gray-500 dark:text-gray-400">Y/R Cards</div>
                    </div>
                    <div class="col-6">
                        <div class="fw-bold text-${attendanceColor}">
                            ${attendanceDisplay}
                        </div>
                        <div class="text-gray-500 dark:text-gray-400">Attendance</div>
                    </div>
                </div>

                <div class="small text-gray-500 dark:text-gray-400 mb-2">
                    ${experienceSeasons} season${experienceSeasons !== 1 ? 's' : ''}
                </div>

                ${expectedAvailability !== 'All weeks' ?
                    `<div class="small text-blue-500 dark:text-blue-400 mb-3">
                        <i class="ti ti-calendar-event me-1"></i><strong>Expected:</strong> ${expectedAvailability}
                    </div>` :
                    `<div class="small text-green-500 dark:text-green-400 mb-3">
                        <i class="ti ti-calendar-check me-1"></i><strong>Available:</strong> All weeks
                    </div>`
                }
            </div>

            <!-- Action Buttons -->
            <div class="card-footer bg-transparent border-0 p-2">
                <div class="d-grid gap-1">
                    <button class="text-white bg-green-600 hover:bg-green-700 focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-3 py-1.5 fw-bold bg-success-gradient"
                            data-action="draft-player"
                            data-player-id="${player.id}"
                            data-player-name="${player.name}">
                        <i class="ti ti-user-plus me-1"></i>Draft Player
                    </button>
                    <button class="text-cyan-600 bg-transparent border border-cyan-600 hover:bg-cyan-600 hover:text-white focus:ring-4 focus:ring-cyan-300 font-medium rounded-lg text-sm px-3 py-1.5"
                            data-action="view-player-profile"
                            data-player-id="${player.id}">
                        <i class="ti ti-user me-1"></i>View Profile
                    </button>
                </div>
            </div>
        </div>
    `;

    playerCard.classList.add('draft-card-enter');
    availableContainer.appendChild(playerCard);

    cleanupEmptyColumns(availableContainer);

    // Apply filters and sorting after short delay
    setTimeout(() => {
        const sortSelect = document.getElementById('sortPlayers');
        if (sortSelect && sortSelect.value && sortSelect.value !== 'default') {
            handleSort({ target: sortSelect });
        }

        applyCurrentFilters(playerCard);
    }, 50);

    // Animate in
    setTimeout(() => {
        playerCard.classList.remove('draft-card-enter');
        playerCard.classList.add('draft-card-enter-active');
    }, 10);

    updatePlayerCounts();
}

/**
 * Remove player from team roster with animation
 * @param {string} playerId - Player ID
 * @param {string} teamId - Team ID
 */
export function removePlayerFromTeam(playerId, teamId) {
    const playerCard = document.querySelector(`#teamPlayers${teamId} [data-player-id="${playerId}"]`);
    if (playerCard) {
        playerCard.classList.add('team-player-exit');
        setTimeout(() => {
            playerCard.remove();
            updateTeamCount(teamId);
        }, 300);
    }
}

/**
 * Remove player from available pool with animation
 * @param {string} playerId - Player ID
 */
export function removePlayerFromAvailable(playerId) {
    const availableContainer = document.getElementById('available-players');
    if (!availableContainer) return;

    const playerColumn = availableContainer.querySelector(`[data-player-id="${playerId}"]`)?.closest('[data-component="player-column"]');
    if (playerColumn) {
        const currentHeight = playerColumn.offsetHeight;
        playerColumn.style.maxHeight = currentHeight + 'px';

        playerColumn.classList.add('transition-all', 'duration-300', 'ease-in-out');

        requestAnimationFrame(() => {
            playerColumn.classList.add('opacity-0');
            playerColumn.classList.add('scale-90');
            playerColumn.style.transform = 'scale(0.8) translateY(-10px)';

            setTimeout(() => {
                playerColumn.classList.add('max-h-0', 'mb-0-important', 'pt-0-important', 'pb-0-important', 'overflow-hidden');
                playerColumn.style.maxHeight = '0';
            }, 100);
        });

        setTimeout(() => {
            playerColumn.remove();
            updatePlayerCounts();
        }, 400);
    }
}

export default {
    formatPosition,
    addPlayerToTeam,
    addPlayerToAvailable,
    removePlayerFromTeam,
    removePlayerFromAvailable
};
