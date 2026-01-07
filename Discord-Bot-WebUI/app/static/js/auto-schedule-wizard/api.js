/**
 * Auto Schedule Wizard - API
 * Form data handling and server communication
 *
 * @module auto-schedule-wizard/api
 */

import { getCalendarState } from './state.js';
import { showLoadingModal, hideLoadingModal, showSuccessModal, showErrorModal } from './ui-helpers.js';

/**
 * Get form data for season creation
 * @returns {Object} Form data object
 */
export function getFormData() {
    const leagueType = document.getElementById('leagueType')?.value;
    const calendarState = getCalendarState();

    const getId = id => document.getElementById(id);
    const getVal = id => getId(id)?.value;
    const getChecked = id => getId(id)?.checked;

    const baseData = {
        season_name: getVal('seasonName'),
        league_type: leagueType,
        set_as_current: getChecked('setAsCurrent'),
        season_start_date: calendarState.startDate?.toISOString().split('T')[0] || '',
        regular_weeks: parseInt(getVal('premierRegularWeeks')) || 7,
        total_weeks: parseInt(getVal('totalSeasonWeeks')) || 11,
        week_configs: getUniqueWeekConfigs(),
        premier_start_time: getVal('premierStartTime') || '08:20',
        classic_start_time: getVal('classicStartTime') || '13:10',
        match_duration: parseInt(getVal('matchDuration')) || 60,
        fields: getWizardFieldConfig().map(f => f.name).join(',') || 'North,South',
        enable_time_rotation: getChecked('enableTimeRotation') ?? true,
        break_duration: parseInt(getVal('breakDuration')) || 10,
        enable_practice_weeks: getChecked('classicHasPractice') || false,
        practice_weeks: getClassicPracticeWeeks() || ''
    };

    if (leagueType === 'Pub League') {
        return {
            ...baseData,
            premier_teams: parseInt(getVal('premierTeamCount')) || 8,
            classic_teams: parseInt(getVal('classicTeamCount')) || 4,
            premier_regular_weeks: parseInt(getVal('premierRegularWeeks')) || 7,
            premier_playoff_weeks: parseInt(getVal('premierPlayoffWeeks')) || 2,
            classic_regular_weeks: parseInt(getVal('classicRegularWeeks')) || 8,
            classic_playoff_weeks: parseInt(getVal('classicPlayoffWeeks')) || 1,
            premier_has_fun_week: getChecked('includeFunWeek') || false,
            premier_has_tst_week: getChecked('includeTstWeek') || false,
            premier_has_bonus_week: getChecked('includeByeWeek') || false,
            classic_has_practice_sessions: getChecked('classicHasPractice') || false,
            classic_practice_weeks: getClassicPracticeWeeks() || '',
            classic_practice_game_number: 1
        };
    }

    // ECS FC
    return {
        ...baseData,
        ecs_fc_teams: parseInt(getVal('ecsFcTeamCount')) || 8,
        ecs_fc_regular_weeks: parseInt(getVal('ecsFcRegularWeeks')) || 7,
        ecs_fc_playoff_weeks: parseInt(getVal('ecsFcPlayoffWeeks')) || 1
    };
}

/**
 * Get unique week configurations for both divisions
 * @returns {Array} Array of week configuration objects
 */
export function getUniqueWeekConfigs() {
    const calendarState = getCalendarState();
    const uniqueWeeks = new Map();

    if (!calendarState.weeks) return [];

    // Process all weeks and create entries for both divisions where appropriate
    calendarState.weeks.forEach(w => {
        const weekKey = `${w.weekNumber}-${w.division}`;

        if (!uniqueWeeks.has(weekKey)) {
            uniqueWeeks.set(weekKey, {
                date: w.date.toISOString().split('T')[0],
                type: w.type.toUpperCase(),
                week_number: w.weekNumber,
                division: w.division,
                is_practice: w.isPractice || false
            });
        }
    });

    // Convert to array and sort by week number, then by division
    return Array.from(uniqueWeeks.values()).sort((a, b) => {
        if (a.week_number !== b.week_number) {
            return a.week_number - b.week_number;
        }
        return a.division.localeCompare(b.division);
    });
}

/**
 * Get wizard field configuration data
 * @returns {Array} Array of field configuration objects
 */
export function getWizardFieldConfig() {
    const fieldItems = document.querySelectorAll('.wizard-field-item');
    if (fieldItems.length === 0) {
        // Return default fields if no wizard fields found
        return [{ name: 'North' }, { name: 'South' }];
    }

    const fieldConfig = [];

    fieldItems.forEach(item => {
        const name = item.querySelector('.wizard-field-name')?.value?.trim();

        if (name) {
            fieldConfig.push({ name });
        }
    });

    // If no valid fields found, return defaults
    return fieldConfig.length > 0 ? fieldConfig : [{ name: 'North' }, { name: 'South' }];
}

/**
 * Get classic practice weeks configuration
 * @returns {string|null} Comma-separated practice week numbers
 */
export function getClassicPracticeWeeks() {
    const enablePractice = document.getElementById('classicHasPractice');
    if (!enablePractice || !enablePractice.checked) {
        return null;
    }

    const checkboxes = document.querySelectorAll('#classicPracticeWeekCheckboxes input[type="checkbox"]:checked');
    const practiceWeeks = Array.from(checkboxes).map(cb => cb.value);

    return practiceWeeks.length > 0 ? practiceWeeks.join(',') : null;
}

/**
 * Create season using wizard data
 * @returns {Promise<void>}
 */
export async function createSeason() {
    const calendarState = getCalendarState();

    if (!calendarState?.weeks?.length) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Calendar Required', 'Please ensure the calendar is generated.', 'warning');
        }
        return;
    }

    // Disable create button
    const createButton = document.querySelector('[data-action="create-season"]');
    if (createButton) {
        createButton.disabled = true;
        createButton.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Creating Season...';
    }

    showLoadingModal('Creating Season', 'Please wait...');

    const formData = getFormData();
    console.log('Sending season data:', formData);

    try {
        const response = await fetch(window.autoScheduleUrls?.createSeasonWizard || '/auto-schedule/create-season', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || ''
            },
            body: JSON.stringify(formData)
        });

        const data = await response.json();
        hideLoadingModal();

        if (data.success) {
            showSuccessModal('Season Created!', 'Redirecting...', () => {
                window.location.href = data.redirect_url || '/auto-schedule/';
            });
        } else {
            if (createButton) {
                createButton.disabled = false;
                createButton.innerHTML = '<i class="fas fa-check me-2"></i>Create Season';
            }
            showErrorModal('Error', data.error || 'An error occurred.');
        }
    } catch (error) {
        console.error('Season creation error:', error);
        hideLoadingModal();

        if (createButton) {
            createButton.disabled = false;
            createButton.innerHTML = '<i class="fas fa-check me-2"></i>Create Season';
        }
        showErrorModal('Network Error', 'Failed to create season.');
    }
}

/**
 * Set a season as active
 * @param {number} seasonId - Season ID
 * @param {string} leagueType - League type
 */
export async function setActiveSeason(seasonId, leagueType) {
    if (typeof window.Swal === 'undefined') return;

    const result = await window.Swal.fire({
        title: 'Set Active Season',
        text: `Are you sure you want to set this season as the current ${leagueType} season?`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#6c757d',
        confirmButtonText: 'Yes, set it!'
    });

    if (!result.isConfirmed) return;

    try {
        const response = await fetch(window.autoScheduleUrls?.setActiveSeason || '/auto-schedule/set-active-season', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || ''
            },
            body: JSON.stringify({
                season_id: seasonId,
                league_type: leagueType
            })
        });

        const data = await response.json();

        if (data.success) {
            // Refresh the page to show updated season status
            location.reload();
        } else {
            window.Swal.fire('Error', 'Error: ' + data.error, 'error');
        }
    } catch (error) {
        window.Swal.fire('Error', 'An error occurred while updating the active season', 'error');
    }
}

export default {
    getFormData,
    getUniqueWeekConfigs,
    getWizardFieldConfig,
    getClassicPracticeWeeks,
    createSeason,
    setActiveSeason
};
