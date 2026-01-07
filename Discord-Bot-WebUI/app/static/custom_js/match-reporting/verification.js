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

    return `
        <h5 class="mb-3">Match Verification</h5>
        <div class="alert ${bothVerified ? 'alert-success' : 'alert-warning'} mb-3" data-status="${bothVerified ? 'complete' : 'pending'}">
            <div class="d-flex align-items-center">
                <i class="fa ${bothVerified ? 'fa-check-circle' : 'fa-exclamation-circle'} me-2 fs-3"></i>
                <div>
                    <p class="mb-0">
                        ${bothVerified
                            ? 'This match has been verified by both teams.'
                            : 'This match requires verification from both teams to be complete.'}
                    </p>
                </div>
            </div>
        </div>

        <div class="row">
            <div class="col-md-6">
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
            <div class="col-md-6">
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

    return `
        <div class="card mb-2 ${isVerified ? 'border-success' : 'border-warning'}" data-verification="${teamType}" data-verified="${isVerified}">
            <div class="card-body">
                <h6 class="card-title d-flex align-items-center">
                    <i class="fa ${isVerified ? 'fa-check text-success' : 'fa-clock text-warning'} me-2"></i>
                    ${teamName}
                </h6>
                <p class="card-text small mb-2">
                    ${isVerified
                        ? `Verified by ${verifier || 'Unknown'}${verifiedAt ? ' on ' + new Date(verifiedAt).toLocaleString() : ''}`
                        : 'Not verified yet'}
                </p>
                ${!isVerified && canVerify ? `
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" value="true" id="${inputId}" name="${inputName}" data-verification-input="${teamType}">
                        <label class="form-check-label" for="${inputId}">
                            Verify for ${teamName}
                        </label>
                        <div class="text-muted small">Check this box to verify the match results for your team</div>
                    </div>
                ` : ''}
            </div>
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
