/**
 * Auto Schedule Wizard - Structure Manager
 * Season structure configuration and calculations
 *
 * @module auto-schedule-wizard/structure-manager
 */

/**
 * Update season structure sections based on league type
 */
export function updateStructureSections() {
    const leagueType = document.getElementById('leagueType')?.value;
    const pubLeagueStructure = document.getElementById('pubLeagueStructure');
    const ecsFcStructure = document.getElementById('ecsFcStructure');

    if (leagueType === 'Pub League') {
        if (pubLeagueStructure) pubLeagueStructure.classList.remove('d-none');
        if (ecsFcStructure) ecsFcStructure.classList.add('d-none');
        updateTotalWeeks('premier');
        updateTotalWeeks('classic');
    } else if (leagueType === 'ECS FC') {
        if (pubLeagueStructure) pubLeagueStructure.classList.add('d-none');
        if (ecsFcStructure) ecsFcStructure.classList.remove('d-none');
        updateTotalWeeks('ecsFc');
    }
}

/**
 * Update total weeks calculation for a division
 * @param {string} divisionType - 'premier', 'classic', or 'ecsFc'
 */
export function updateTotalWeeks(divisionType) {
    // Get shared special weeks
    const sharedFunEl = document.getElementById('includeFunWeek');
    const sharedTstEl = document.getElementById('includeTstWeek');
    const sharedByeEl = document.getElementById('includeByeWeek');
    const funWeeks = (sharedFunEl && sharedFunEl.checked) ? 1 : 0;
    const tstWeeks = (sharedTstEl && sharedTstEl.checked) ? 1 : 0;
    const byeWeeks = (sharedByeEl && sharedByeEl.checked) ? 1 : 0;

    if (divisionType === 'premier') {
        const regularEl = document.getElementById('premierRegularWeeks');
        const playoffEl = document.getElementById('premierPlayoffWeeks');
        const bonusWeekEl = document.getElementById('premierHasBonusWeek');
        const totalEl = document.getElementById('premierTotalWeeks');

        if (regularEl && playoffEl && bonusWeekEl && totalEl) {
            const regular = parseInt(regularEl.value) || 0;
            const playoff = parseInt(playoffEl.value) || 0;
            const bonus = bonusWeekEl.checked ? 1 : 0;
            const total = regular + playoff + funWeeks + tstWeeks + byeWeeks + bonus;
            totalEl.textContent = total;
        }
    } else if (divisionType === 'classic') {
        const regularEl = document.getElementById('classicRegularWeeks');
        const playoffEl = document.getElementById('classicPlayoffWeeks');
        const bonusWeekEl = document.getElementById('classicHasBonusWeek');
        const totalEl = document.getElementById('classicTotalWeeks');

        if (regularEl && playoffEl && bonusWeekEl && totalEl) {
            const regular = parseInt(regularEl.value) || 0;
            const playoff = parseInt(playoffEl.value) || 0;
            const bonus = bonusWeekEl.checked ? 1 : 0;
            const total = regular + playoff + funWeeks + tstWeeks + byeWeeks + bonus;
            totalEl.textContent = total;
        }
    } else if (divisionType === 'ecsFc') {
        const regularEl = document.getElementById('ecsFcRegularWeeks');
        const playoffEl = document.getElementById('ecsFcPlayoffWeeks');
        const totalEl = document.getElementById('ecsFcTotalWeeks');

        if (regularEl && playoffEl && totalEl) {
            const regular = parseInt(regularEl.value) || 0;
            const playoff = parseInt(playoffEl.value) || 0;
            const total = regular + playoff;
            totalEl.textContent = total;
        }
    }
}

/**
 * Toggle practice configuration display
 */
export function togglePracticeConfig() {
    const practiceCheckbox = document.getElementById('classicHasPractice');
    const practiceConfig = document.querySelector('.classic-practice-config');

    if (practiceConfig && practiceCheckbox) {
        practiceConfig.classList.toggle('wizard-config--visible', practiceCheckbox.checked);
    }
}

/**
 * Update season structure breakdown based on total weeks
 */
export function updateSeasonStructure() {
    const totalWeeksEl = document.getElementById('totalSeasonWeeks');
    const breakdown = document.getElementById('seasonBreakdown');

    if (!totalWeeksEl || !breakdown) return;

    const totalWeeks = parseInt(totalWeeksEl.value);

    // Fixed playoff weeks
    const premierPlayoffs = 2;
    const classicPlayoffs = 1;
    const specialWeeksCount = getEnabledSpecialWeeksCount();

    // Calculate regular weeks based on total season length
    const premierRegular = totalWeeks - premierPlayoffs - specialWeeksCount;
    const classicRegular = totalWeeks - classicPlayoffs - specialWeeksCount;

    // Update the form inputs
    const premierRegularInput = document.getElementById('premierRegularWeeks');
    const classicRegularInput = document.getElementById('classicRegularWeeks');

    if (premierRegularInput) {
        premierRegularInput.value = premierRegular;
    }
    if (classicRegularInput) {
        classicRegularInput.value = classicRegular;
    }

    // Update the breakdown display
    breakdown.innerHTML = `
        <div><strong>Premier:</strong> ${premierRegular} regular + ${premierPlayoffs} playoff weeks</div>
        <div><strong>Classic:</strong> ${classicRegular} regular + ${classicPlayoffs} playoff week</div>
        <div class="text-muted"><small>Plus ${specialWeeksCount} shared special weeks</small></div>
        <div class="text-muted"><small>Total season length: ${totalWeeks} weeks</small></div>
    `;

    // Regenerate calendar if on step 3
    if (typeof window.generateCalendarPreview === 'function') {
        const currentStep = window._autoScheduleWizardState?.currentStep;
        if (currentStep === 3) {
            window.generateCalendarPreview(true);
        }
    }
}

/**
 * Count enabled special weeks
 * @returns {number} Number of enabled special weeks
 */
export function getEnabledSpecialWeeksCount() {
    let count = 0;
    if (document.getElementById('includeTstWeek')?.checked) count++;
    if (document.getElementById('includeFunWeek')?.checked) count++;
    if (document.getElementById('includeByeWeek')?.checked) count++;
    return count;
}

/**
 * Update practice week options based on season length
 */
export function updateWizardPracticeWeekOptions() {
    // Try to get season length from various sources
    let weekCount = 7; // default

    // Check if we're in structure configuration step
    const premierWeeks = document.getElementById('premierRegularWeeks');
    const classicWeeks = document.getElementById('classicRegularWeeks');
    const totalWeeks = document.getElementById('totalSeasonWeeks');

    if (premierWeeks && classicWeeks) {
        weekCount = Math.max(parseInt(premierWeeks.value) || 7, parseInt(classicWeeks.value) || 8);
    } else if (totalWeeks) {
        weekCount = Math.min(8, parseInt(totalWeeks.value || 11) - 3);
    }

    // Handle classic practice week container
    const container = document.getElementById('classicPracticeWeekCheckboxes');

    if (container) {
        container.innerHTML = '';

        for (let i = 1; i <= weekCount; i++) {
            const div = document.createElement('div');
            div.className = 'form-check form-check-inline';
            const checked = (i === 1 || i === 3) ? 'checked' : '';

            div.innerHTML = `
                <input class="form-check-input" type="checkbox" id="practice-week-${i}" value="${i}" ${checked}>
                <label class="form-check-label" for="practice-week-${i}">Week ${i}</label>
            `;
            container.appendChild(div);
        }
    }
}

export default {
    updateStructureSections,
    updateTotalWeeks,
    togglePracticeConfig,
    updateSeasonStructure,
    getEnabledSpecialWeeksCount,
    updateWizardPracticeWeekOptions
};
