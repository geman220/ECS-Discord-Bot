/**
 * Auto Schedule Wizard - Team Manager
 * Team setup and preview functionality
 *
 * @module auto-schedule-wizard/team-manager
 */

/**
 * Update team sections based on league type
 */
export function updateTeamSections() {
    const leagueType = document.getElementById('leagueType')?.value;
    const pubLeagueSection = document.getElementById('pubLeagueTeams');
    const ecsFcSection = document.getElementById('ecsFcTeams');

    if (leagueType === 'Pub League') {
        if (pubLeagueSection) pubLeagueSection.classList.remove('hidden');
        if (ecsFcSection) ecsFcSection.classList.add('hidden');
        updateTeamPreview('premier');
        updateTeamPreview('classic');
    } else if (leagueType === 'ECS FC') {
        if (pubLeagueSection) pubLeagueSection.classList.add('hidden');
        if (ecsFcSection) ecsFcSection.classList.remove('hidden');
        updateTeamPreview('ecsFc');
    }
}

/**
 * Update team preview display for a specific league type
 * @param {string} leagueType - 'premier', 'classic', or 'ecsFc'
 */
export function updateTeamPreview(leagueType) {
    let count, previewId, startingLetterOffset = 0;

    if (leagueType === 'premier') {
        count = parseInt(document.getElementById('premierTeamCount')?.value) || 8;
        previewId = 'premierTeamPreview';
        startingLetterOffset = 0; // Premier starts at A
    } else if (leagueType === 'classic') {
        count = parseInt(document.getElementById('classicTeamCount')?.value) || 4;
        previewId = 'classicTeamPreview';
        // Classic starts after Premier teams
        const premierCount = parseInt(document.getElementById('premierTeamCount')?.value) || 0;
        startingLetterOffset = premierCount;
    } else if (leagueType === 'ecsFc') {
        count = parseInt(document.getElementById('ecsFcTeamCount')?.value) || 8;
        previewId = 'ecsFcTeamPreview';
        startingLetterOffset = 0; // ECS FC is standalone, starts at A
    }

    const previewDiv = document.getElementById(previewId);
    if (!previewDiv) return;

    const teamLabels = [];

    // Generate team names with proper letter sequence
    for (let i = 0; i < count; i++) {
        const letter = String.fromCharCode(65 + startingLetterOffset + i);
        teamLabels.push(`Team ${letter}`);
    }

    // Show starting letter range for clarity
    const startLetter = String.fromCharCode(65 + startingLetterOffset);
    const endLetter = String.fromCharCode(65 + startingLetterOffset + count - 1);
    const rangeText = count > 1 ? `Teams ${startLetter}-${endLetter}` : `Team ${startLetter}`;

    previewDiv.innerHTML = `
        <div class="small text-muted mb-2">${rangeText} to be created:</div>
        <div class="d-flex flex-wrap gap-1">
            ${teamLabels.map(name => `<span class="badge bg-light text-dark border">${name}</span>`).join('')}
        </div>
    `;
}

/**
 * Get team configuration for a specific league type
 * @param {string} leagueType - 'premier', 'classic', or 'ecsFc'
 * @returns {Object} Team configuration
 */
export function getTeamConfig(leagueType) {
    if (leagueType === 'premier') {
        return {
            count: parseInt(document.getElementById('premierTeamCount')?.value) || 8,
            startLetter: 'A'
        };
    } else if (leagueType === 'classic') {
        const premierCount = parseInt(document.getElementById('premierTeamCount')?.value) || 8;
        return {
            count: parseInt(document.getElementById('classicTeamCount')?.value) || 4,
            startLetter: String.fromCharCode(65 + premierCount)
        };
    } else if (leagueType === 'ecsFc') {
        return {
            count: parseInt(document.getElementById('ecsFcTeamCount')?.value) || 8,
            startLetter: 'A'
        };
    }

    return { count: 0, startLetter: 'A' };
}

/**
 * Generate team letter range string
 * @param {number} count - Number of teams
 * @param {number} offset - Starting letter offset (0 = A)
 * @returns {string} Range string like "Teams A-H"
 */
export function getTeamRange(count, offset = 0) {
    if (count === 0) return '';

    const startLetter = String.fromCharCode(65 + offset);
    const endLetter = String.fromCharCode(65 + offset + count - 1);

    return count > 1 ? `Teams ${startLetter}-${endLetter}` : `Team ${startLetter}`;
}

export default {
    updateTeamSections,
    updateTeamPreview,
    getTeamConfig,
    getTeamRange
};
