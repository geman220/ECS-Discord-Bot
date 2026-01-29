/**
 * Match Reporting - Verification Section
 * Handles match verification UI for home and away teams
 *
 * @module match-reporting/verification
 */

/**
 * Update or create the verification section in a modal
 * @param {Element} modal - Modal element
 * @param {string|number} matchId - Match ID
 * @param {Object} data - Match data containing verification status
 */
export function updateVerificationSection(modal, matchId, data) {
    try {
        // Look for existing verification section, create if not found
        let verificationSection = modal.querySelector(`#verificationSection-${matchId}`);

        if (!verificationSection) {
            const modalBody = modal.querySelector('.modal-body');
            if (!modalBody) return;

            verificationSection = document.createElement('div');
            verificationSection.id = `verificationSection-${matchId}`;
            verificationSection.className = 'mb-4 verification-section border-top pt-4 mt-4';
            modalBody.appendChild(verificationSection);
        }

        // Get verification data from match data
        const homeTeamVerified = data.home_team_verified || false;
        const awayTeamVerified = data.away_team_verified || false;
        const canVerifyHome = data.can_verify_home || false;
        const canVerifyAway = data.can_verify_away || false;

        // Build verification HTML
        const verificationHTML = buildVerificationHTML({
            matchId,
            homeTeamVerified,
            awayTeamVerified,
            canVerifyHome,
            canVerifyAway,
            homeTeamName: data.home_team_name || 'Home Team',
            awayTeamName: data.away_team_name || 'Away Team',
            homeVerifier: data.home_verifier,
            awayVerifier: data.away_verifier,
            homeVerifiedAt: data.home_team_verified_at,
            awayVerifiedAt: data.away_team_verified_at
        });

        verificationSection.innerHTML = verificationHTML;
    } catch (error) {
        // Error updating verification section
    }
}

/**
 * Build verification section HTML
 * @param {Object} config - Verification configuration
 * @returns {string} HTML string
 */
function buildVerificationHTML(config) {
    const {
        matchId,
        homeTeamVerified,
        awayTeamVerified,
        canVerifyHome,
        canVerifyAway,
        homeTeamName,
        awayTeamName,
        homeVerifier,
        awayVerifier,
        homeVerifiedAt,
        awayVerifiedAt
    } = config;

    const bothVerified = homeTeamVerified && awayTeamVerified;
    const alertClass = bothVerified
        ? 'text-green-800 bg-green-50 dark:bg-gray-800 dark:text-green-400'
        : 'text-yellow-800 bg-yellow-50 dark:bg-gray-800 dark:text-yellow-400';

    return `
        <h5 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">Match Verification</h5>
        <div class="p-4 rounded-lg mb-3 ${alertClass}" role="alert" data-status="${bothVerified ? 'complete' : 'pending'}">
            <div class="flex items-center">
                <i class="ti ${bothVerified ? 'ti-circle-check' : 'ti-alert-circle'} mr-2 text-xl"></i>
                <div>
                    <p class="text-sm">
                        ${bothVerified
                            ? 'This match has been verified by both teams.'
                            : 'This match requires verification from both teams to be complete.'}
                    </p>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
                ${buildTeamVerificationCard({
                    matchId,
                    teamType: 'home',
                    teamName: homeTeamName,
                    isVerified: homeTeamVerified,
                    canVerify: canVerifyHome,
                    verifier: homeVerifier,
                    verifiedAt: homeVerifiedAt
                })}
            </div>
            <div>
                ${buildTeamVerificationCard({
                    matchId,
                    teamType: 'away',
                    teamName: awayTeamName,
                    isVerified: awayTeamVerified,
                    canVerify: canVerifyAway,
                    verifier: awayVerifier,
                    verifiedAt: awayVerifiedAt
                })}
            </div>
        </div>
    `;
}

/**
 * Build verification card for a single team
 * @param {Object} config - Team verification config
 * @returns {string} HTML string
 */
function buildTeamVerificationCard(config) {
    const {
        matchId,
        teamType,
        teamName,
        isVerified,
        canVerify,
        verifier,
        verifiedAt
    } = config;

    const inputId = teamType === 'home' ? `verifyHomeTeam-${matchId}` : `verifyAwayTeam-${matchId}`;
    const inputName = teamType === 'home' ? 'verify_home_team' : 'verify_away_team';
    const borderClass = isVerified
        ? 'border-green-500 dark:border-green-400'
        : 'border-yellow-500 dark:border-yellow-400';

    return `
        <div class="mb-2 p-4 bg-white border rounded-lg dark:bg-gray-800 ${borderClass}" data-verification="${teamType}" data-verified="${isVerified}">
            <h6 class="text-sm font-medium text-gray-900 dark:text-white flex items-center mb-2">
                <i class="ti ${isVerified ? 'ti-check text-green-600' : 'ti-clock text-yellow-500'} mr-2"></i>
                ${teamName}
            </h6>
            <p class="text-xs text-gray-500 dark:text-gray-400 mb-2">
                ${isVerified
                    ? `Verified by ${verifier || 'Unknown'}${verifiedAt ? ' on ' + new Date(verifiedAt).toLocaleString() : ''}`
                    : 'Not verified yet'}
            </p>
            ${!isVerified && canVerify ? `
                <div class="flex items-start">
                    <div class="flex items-center h-5">
                        <input type="checkbox" value="true" id="${inputId}" name="${inputName}" data-verification-input="${teamType}"
                               class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                    </div>
                    <div class="ml-2">
                        <label for="${inputId}" class="text-sm font-medium text-gray-900 dark:text-gray-300">
                            Verify for ${teamName}
                        </label>
                        <p class="text-xs text-gray-500 dark:text-gray-400">Check this box to verify the match results for your team</p>
                    </div>
                </div>
            ` : ''}
        </div>
    `;
}

/**
 * Get verification status from form
 * @param {string|number} matchId - Match ID
 * @returns {Object} Verification status
 */
export function getVerificationStatus(matchId) {
    const verifyHomeTeam = window.$(`#verifyHomeTeam-${matchId}`).is(':checked');
    const verifyAwayTeam = window.$(`#verifyAwayTeam-${matchId}`).is(':checked');

    const homeTeamCheckbox = window.$(`#verifyHomeTeam-${matchId}`);
    const awayTeamCheckbox = window.$(`#verifyAwayTeam-${matchId}`);

    return {
        verifyHomeTeam,
        verifyAwayTeam,
        hasHomeCheckbox: homeTeamCheckbox.length > 0,
        hasAwayCheckbox: awayTeamCheckbox.length > 0
    };
}

/**
 * Validate verification requirements
 * @param {string|number} matchId - Match ID
 * @returns {Object} Validation result with isValid and message
 */
export function validateVerification(matchId) {
    const status = getVerificationStatus(matchId);

    // Check if user can verify but hasn't checked any boxes
    if ((status.hasHomeCheckbox || status.hasAwayCheckbox) &&
        !status.verifyHomeTeam && !status.verifyAwayTeam) {
        return {
            isValid: false,
            message: 'Please verify the match results for your team before submitting.'
        };
    }

    return { isValid: true, message: null };
}

// Backward compatibility
window.updateVerificationSection = updateVerificationSection;

export default {
    updateVerificationSection,
    getVerificationStatus,
    validateVerification
};
