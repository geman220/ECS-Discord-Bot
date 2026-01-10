/**
 * Draft System - Position Highlighting
 * Position analysis and player highlighting based on team needs
 *
 * @module draft-system/position-highlighting
 */

import { getLeagueName } from './state.js';

/**
 * Fetch position analysis from backend API
 * @param {string} teamId - Team ID to analyze
 * @returns {Promise<Object|null>} Position analysis data
 */
export async function fetchPositionAnalysis(teamId) {
    try {
        const leagueName = getLeagueName();
        const response = await fetch(`/draft/api/${leagueName}/position-analysis/${teamId}`);
        if (response.ok) {
            return await response.json();
        } else {
            console.error('Failed to fetch position analysis:', response.status);
            return null;
        }
    } catch (error) {
        console.error('Error fetching position analysis:', error);
        return null;
    }
}

/**
 * Update player highlighting based on position fit for active team
 * @param {string|null} activeTeamId - Active team ID or null to clear
 */
export async function updatePositionHighlighting(activeTeamId) {
    if (!activeTeamId) {
        clearAllHighlighting();
        return;
    }

    // Fetch position analysis for this team
    const analysis = await fetchPositionAnalysis(activeTeamId);
    if (!analysis || !analysis.player_fit_scores) {
        return;
    }

    // Apply highlighting to player cards
    applyHighlighting(analysis.player_fit_scores);
}

/**
 * Clear all position highlighting from player cards
 */
export function clearAllHighlighting() {
    document.querySelectorAll('[data-component="player-card"]').forEach(card => {
        card.classList.remove('highlight-strong', 'highlight-moderate');
        const badge = card.querySelector('[data-component="position-fit-badge"]');
        if (badge) badge.remove();
    });
}

/**
 * Apply highlighting based on fit scores
 * @param {Object} playerFitScores - Fit scores by player ID
 */
export function applyHighlighting(playerFitScores) {
    document.querySelectorAll('[data-component="player-card"]').forEach(card => {
        const playerId = parseInt(card.dataset.playerId);
        if (!playerId) return;

        // Remove existing highlighting
        card.classList.remove('highlight-strong', 'highlight-moderate');
        const existingBadge = card.querySelector('[data-component="position-fit-badge"]');
        if (existingBadge) existingBadge.remove();

        // Get fit score for this player
        const fitData = playerFitScores[playerId];
        if (!fitData) return;

        // Apply highlighting based on fit category
        if (fitData.fit_category === 'strong') {
            card.classList.add('highlight-strong');
            addPositionBadge(card, 'strong', fitData.favorite_position);
        } else if (fitData.fit_category === 'moderate') {
            card.classList.add('highlight-moderate');
            addPositionBadge(card, 'moderate');
        }
    });
}

/**
 * Add position fit badge to card
 * @param {HTMLElement} card - Player card element
 * @param {string} type - Badge type (strong or moderate)
 * @param {string} position - Position name (for strong fit)
 */
function addPositionBadge(card, type, position = null) {
    const badge = document.createElement('span');
    badge.setAttribute('data-component', 'position-fit-badge');

    if (type === 'strong') {
        badge.className = 'badge-strong';
        badge.innerHTML = '<i class="ti ti-star-filled me-1"></i>Position Fit';
        badge.title = `${position} - Perfect match for team needs`;
    } else {
        badge.className = 'badge-moderate';
        badge.innerHTML = '<i class="ti ti-check me-1"></i>Can Play';
        badge.title = 'Can play needed position';
    }

    card.appendChild(badge);
}

/**
 * Set up team tab highlighting event listeners
 */
export function setupTeamTabHighlighting() {
    // Find all team tabs/sections (Flowbite accordion pattern)
    const teamTabs = document.querySelectorAll('[data-accordion-target][data-team-id], [data-collapse-toggle][data-team-id]');
    teamTabs.forEach(tab => {
        tab.addEventListener('click', (e) => {
            const teamId = parseInt(e.currentTarget.dataset.teamId);
            if (teamId) {
                // Delay slightly to allow accordion to open
                setTimeout(() => updatePositionHighlighting(teamId), 100);
            }
        });
    });

    // Check if a team accordion is already open on page load
    const openAccordion = document.querySelector('[data-component="team-collapse"].show[data-team-id]');
    if (openAccordion) {
        const teamId = parseInt(openAccordion.dataset.teamId);
        if (teamId) {
            updatePositionHighlighting(teamId);
        }
    }
}

export default {
    fetchPositionAnalysis,
    updatePositionHighlighting,
    clearAllHighlighting,
    applyHighlighting,
    setupTeamTabHighlighting
};
