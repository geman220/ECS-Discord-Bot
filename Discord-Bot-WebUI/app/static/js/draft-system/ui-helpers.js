/**
 * Draft System - UI Helpers
 * Toast notifications, loading overlays, and modal helpers
 *
 * @module draft-system/ui-helpers
 */

/**
 * Update connection status indicator
 * @param {boolean} connected - Connection status
 * @param {string|null} message - Optional status message
 */
export function updateConnectionStatus(connected, message = null) {
    const statusElement = document.getElementById('connectionStatus');
    if (statusElement) {
        if (connected) {
            statusElement.className = 'connection-status status-connected';
            statusElement.innerHTML = '<i class="ti ti-wifi me-1"></i>Connected';
        } else {
            statusElement.className = 'connection-status status-disconnected';
            const safeMessage = message || 'Disconnected';
            statusElement.innerHTML = '<i class="ti ti-wifi-off me-1"></i>';
            statusElement.appendChild(document.createTextNode(safeMessage));
        }
    }
}

/**
 * Show loading overlay
 */
export function showLoading() {
    const overlay = document.querySelector('[data-component="draft-loading-overlay"]');
    if (overlay) {
        overlay.classList.add('is-visible');
        overlay.classList.remove('is-hidden');
    }
}

/**
 * Hide loading overlay
 */
export function hideLoading() {
    const overlay = document.querySelector('[data-component="draft-loading-overlay"]');
    if (overlay) {
        overlay.classList.add('is-hidden');
        overlay.classList.remove('is-visible');
    }
}

/**
 * Show toast notification
 * @param {string} message - Toast message
 * @param {string} type - Toast type (success, error, warning, info)
 */
export function showToast(message, type = 'info') {
    if (window.Swal) {
        const iconMap = {
            'success': 'success',
            'error': 'error',
            'warning': 'warning',
            'info': 'info'
        };

        window.Swal.fire({
            title: message,
            icon: iconMap[type] || 'info',
            toast: true,
            position: 'top-end',
            showConfirmButton: false,
            timer: 3000,
            timerProgressBar: true
        });
    } else if (window.showToast) {
        window.showToast(message, type);
    }
}

/**
 * Show drafting indicator
 * @param {string} playerName - Player being drafted
 * @param {string} teamName - Target team name
 */
export function showDraftingIndicator(playerName, teamName) {
    hideDraftingIndicator();

    const indicator = document.createElement('div');
    indicator.id = 'currentDraftIndicator';
    indicator.className = 'drafting-indicator';
    indicator.innerHTML = `
        <div class="d-flex align-items-center gap-3">
            <div class="spinner-border spinner-border-sm text-primary" role="status">
                <span class="visually-hidden">Drafting...</span>
            </div>
            <div>
                <strong>Drafting ${playerName}</strong>
                <div class="small text-muted">to ${teamName}</div>
            </div>
        </div>
    `;
    document.body.appendChild(indicator);
}

/**
 * Hide drafting indicator
 */
export function hideDraftingIndicator() {
    const indicator = document.getElementById('currentDraftIndicator');
    if (indicator) {
        indicator.classList.add('animate-slide-out-right');
        setTimeout(() => indicator.remove(), 300);
    }
}

/**
 * Show user activity notification
 * @param {string} username - User performing action
 * @param {string} playerName - Player being drafted
 * @param {string} teamName - Target team name
 */
export function showUserActivity(username, playerName, teamName) {
    let activityContainer = document.getElementById('draftActivity');
    if (!activityContainer) {
        activityContainer = document.createElement('div');
        activityContainer.id = 'draftActivity';
        activityContainer.className = 'draft-activity-container';
        document.body.appendChild(activityContainer);
    }

    const activity = document.createElement('div');
    activity.className = 'user-activity-toast';
    activity.innerHTML = `
        <i class="ti ti-user-check text-primary me-2"></i>
        <div>
            <strong>${username}</strong> is drafting <strong>${playerName}</strong>
            ${teamName ? `<div class="small text-muted">to ${teamName}</div>` : ''}
        </div>
    `;

    activityContainer.appendChild(activity);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        activity.classList.add('animate-fade-out');
        setTimeout(() => activity.remove(), 300);
    }, 5000);
}

/**
 * Toggle empty state visibility
 * @param {boolean} show - Whether to show empty state
 */
export function toggleEmptyState(show) {
    const emptyState = document.getElementById('emptyState');
    const playersContainer = document.getElementById('playersContainer');

    if (emptyState) {
        if (show) {
            emptyState.classList.add('d-block');
            emptyState.classList.remove('d-none');
        } else {
            emptyState.classList.add('d-none');
            emptyState.classList.remove('d-block');
        }
    }
    if (playersContainer) {
        if (show) {
            playersContainer.classList.add('d-none');
            playersContainer.classList.remove('d-block');
        } else {
            playersContainer.classList.add('d-block');
            playersContainer.classList.remove('d-none');
        }
    }
}

/**
 * Update available player count display
 * @param {number} count - Number of available players
 */
export function updateAvailableCount(count) {
    const countElement = document.getElementById('availableCount');
    if (countElement) {
        countElement.textContent = count;
    }
}

/**
 * Update player counts (available and per-team)
 */
export function updatePlayerCounts() {
    // Update available count
    const availableCount = document.querySelectorAll('[data-component="player-item"]').length;
    const countElement = document.getElementById('availableCount');
    if (countElement) {
        countElement.textContent = availableCount;
    }

    // Update team counts
    document.querySelectorAll('[id^="teamCount"]').forEach(counter => {
        const teamId = counter.id.replace('teamCount', '');
        const playerCount = document.querySelectorAll(`#teamPlayers${teamId} .draft-team-player-card`).length;
        counter.textContent = `${playerCount} players`;
    });
}

/**
 * Update single team count
 * @param {string} teamId - Team ID
 */
export function updateTeamCount(teamId) {
    const teamSection = document.getElementById(`teamPlayers${teamId}`);
    const teamCountBadge = document.getElementById(`teamCount${teamId}`);

    if (teamSection && teamCountBadge) {
        const playerCount = teamSection.querySelectorAll('.draft-team-player-card').length;
        teamCountBadge.textContent = `${playerCount} players`;
    }
}

/**
 * Close all open modals
 */
export function closeModals() {
    const modals = document.querySelectorAll('[data-component="modal"][data-state="open"]');
    modals.forEach(modal => {
        const bsModal = window.bootstrap.Modal.getInstance(modal);
        if (bsModal) bsModal.hide();
    });
}

export default {
    updateConnectionStatus,
    showLoading,
    hideLoading,
    showToast,
    showDraftingIndicator,
    hideDraftingIndicator,
    showUserActivity,
    toggleEmptyState,
    updateAvailableCount,
    updatePlayerCounts,
    updateTeamCount,
    closeModals
};
