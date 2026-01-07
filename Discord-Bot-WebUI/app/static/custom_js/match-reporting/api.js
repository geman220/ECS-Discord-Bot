/**
 * Match Reporting - API
 * Handles server communication for match reporting
 *
 * @module match-reporting/api
 */

import { getCurrentMatchData } from './state.js';
import { getVerificationStatus, validateVerification } from './verification.js';

/**
 * Fetch match data from the server
 * @param {string|number} matchId - Match ID
 * @returns {Promise<Object>} Match data
 */
export async function fetchMatchData(matchId) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 15000);

    try {
        const response = await fetch(`/teams/report_match/${matchId}`, {
            method: 'GET',
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            signal: controller.signal
        });

        clearTimeout(timeoutId);
        return await response.json();
    } catch (error) {
        clearTimeout(timeoutId);
        throw error;
    }
}

/**
 * Submit match report to server
 * @param {string|number} matchId - Match ID
 * @param {Object} changes - Event changes (add/remove arrays)
 */
export async function submitMatchReport(matchId, changes) {
    const {
        goalsToAdd, goalsToRemove,
        assistsToAdd, assistsToRemove,
        yellowCardsToAdd, yellowCardsToRemove,
        redCardsToAdd, redCardsToRemove,
        ownGoalsToAdd, ownGoalsToRemove
    } = changes;

    const homeTeamScore = window.$('#home_team_score-' + matchId).val();
    const awayTeamScore = window.$('#away_team_score-' + matchId).val();
    const notes = window.$('#match_notes-' + matchId).val();

    // Get the version for optimistic locking
    const currentMatchData = getCurrentMatchData();
    const version = currentMatchData ? currentMatchData.version : null;

    // Get verification status
    const verificationStatus = getVerificationStatus(matchId);

    // Validate verification if required
    const validation = validateVerification(matchId);
    if (!validation.isValid) {
        window.Swal.fire({
            icon: 'warning',
            title: 'Verification Required',
            text: validation.message,
            confirmButtonText: 'OK'
        });
        return;
    }

    try {
        const response = await fetch(`/teams/report_match/${matchId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                home_team_score: homeTeamScore,
                away_team_score: awayTeamScore,
                notes: notes,
                goals_to_add: goalsToAdd,
                goals_to_remove: goalsToRemove,
                assists_to_add: assistsToAdd,
                assists_to_remove: assistsToRemove,
                yellow_cards_to_add: yellowCardsToAdd,
                yellow_cards_to_remove: yellowCardsToRemove,
                red_cards_to_add: redCardsToAdd,
                red_cards_to_remove: redCardsToRemove,
                own_goals_to_add: ownGoalsToAdd,
                own_goals_to_remove: ownGoalsToRemove,
                verify_home_team: verificationStatus.verifyHomeTeam,
                verify_away_team: verificationStatus.verifyAwayTeam,
                version: version
            })
        });

        const data = await response.json();

        if (response.status === 409) {
            handleConflictError(matchId, data);
            return;
        }

        if (!response.ok) {
            throw new Error(data.message || 'There was an error submitting your report.');
        }

        if (data.success) {
            handleSuccessResponse(matchId, data, verificationStatus);
        } else {
            handleErrorResponse(matchId, data);
        }
    } catch (error) {
        window.Swal.fire({
            icon: 'warning',
            title: 'Error!',
            text: error.message || 'An unexpected error occurred while submitting your report.'
        }).then(() => {
            const submitBtn = document.getElementById(`submitBtn-${matchId}`);
            if (submitBtn) submitBtn.disabled = false;
        });
    }
}

/**
 * Handle version conflict error
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Error data
 */
function handleConflictError(matchId, data) {
    let errorTitle = 'Error!';
    let errorMessage = 'An unexpected error occurred while submitting your report.';
    let showRefreshOption = false;

    if (data.error_type === 'version_conflict') {
        errorTitle = 'Match Updated by Another User';
        errorMessage = 'This match was modified by another user while you were editing. Please refresh to get the latest data and try again.';
        showRefreshOption = true;
    }

    const swalOptions = {
        icon: 'warning',
        title: errorTitle,
        text: errorMessage
    };

    if (showRefreshOption) {
        swalOptions.showCancelButton = true;
        swalOptions.confirmButtonText = 'Refresh Page';
        swalOptions.cancelButtonText = 'Cancel';
    }

    window.Swal.fire(swalOptions).then((result) => {
        if (result.isConfirmed && showRefreshOption) {
            location.reload();
        } else {
            const submitBtn = document.getElementById(`submitBtn-${matchId}`);
            if (submitBtn) submitBtn.disabled = false;
        }
    });
}

/**
 * Handle successful submission
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Response data
 * @param {Object} verificationStatus - Verification status
 */
function handleSuccessResponse(matchId, data, verificationStatus) {
    let successMessage = 'Your match report has been submitted successfully.';

    if (data.home_team_verified && data.away_team_verified) {
        successMessage = 'Match report submitted and fully verified by both teams.';
    } else if (data.home_team_verified || data.away_team_verified) {
        successMessage = 'Match report submitted and verified by one team.';

        if (verificationStatus.verifyHomeTeam || verificationStatus.verifyAwayTeam) {
            successMessage += ' Thank you for verifying!';
        } else {
            successMessage += ' The other team still needs to verify.';
        }
    }

    window.Swal.fire({
        icon: 'success',
        title: 'Success!',
        text: successMessage
    }).then(() => {
        closeModal(matchId);
        location.reload();
    });
}

/**
 * Handle error response
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Response data
 */
function handleErrorResponse(matchId, data) {
    window.Swal.fire({
        icon: 'error',
        title: 'Error!',
        text: data.message || 'There was an error submitting your report.'
    }).then(() => {
        const submitBtn = document.getElementById(`submitBtn-${matchId}`);
        if (submitBtn) submitBtn.disabled = false;
    });
}

/**
 * Close the match modal
 * @param {string|number} matchId - Match ID
 */
function closeModal(matchId) {
    try {
        const modalElem = document.getElementById(`reportMatchModal-${matchId}`);
        if (modalElem) {
            const bsModal = window.bootstrap.Modal.getInstance(modalElem);
            if (bsModal) {
                bsModal.hide();
            } else {
                modalElem.classList.remove('show');
                modalElem.style.display = 'none';
            }
        }
    } catch (e) {
        // Error closing modal
    }
}

// Legacy function for backward compatibility
export function reportMatchUpdateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove,
    yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove, ownGoalsToAdd, ownGoalsToRemove) {
    submitMatchReport(matchId, {
        goalsToAdd, goalsToRemove,
        assistsToAdd, assistsToRemove,
        yellowCardsToAdd, yellowCardsToRemove,
        redCardsToAdd, redCardsToRemove,
        ownGoalsToAdd, ownGoalsToRemove
    });
}

// Backward compatibility
window.reportMatchUpdateStats = reportMatchUpdateStats;

export default {
    fetchMatchData,
    submitMatchReport,
    reportMatchUpdateStats
};
