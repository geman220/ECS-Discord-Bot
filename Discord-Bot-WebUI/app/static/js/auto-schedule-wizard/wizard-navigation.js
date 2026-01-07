/**
 * Auto Schedule Wizard - Navigation
 * Step navigation and display management
 *
 * @module auto-schedule-wizard/wizard-navigation
 */

import { getState, getCalendarState } from './state.js';

/**
 * Navigate to next step in wizard
 */
export function nextStep() {
    const state = getState();
    if (state.currentStep < state.maxSteps) {
        if (validateStep(state.currentStep)) {
            updateStepDisplay(state.currentStep + 1);
        }
    }
}

/**
 * Navigate to previous step in wizard
 */
export function previousStep() {
    const state = getState();
    if (state.currentStep > 1) {
        updateStepDisplay(state.currentStep - 1);
    }
}

/**
 * Update the wizard step display
 * @param {number} step - Step number to display
 */
export function updateStepDisplay(step) {
    const state = getState();

    // Hide current step
    const currentStepEl = document.querySelector(`.wizard-step[data-step="${state.currentStep}"]`);
    const currentIndicator = document.querySelector(`.step[data-step="${state.currentStep}"]`);

    if (currentStepEl) currentStepEl.classList.remove('active');
    if (currentIndicator) currentIndicator.classList.remove('active');

    // Update state
    state.currentStep = step;

    // Show new step
    const newStepEl = document.querySelector(`.wizard-step[data-step="${step}"]`);
    const newIndicator = document.querySelector(`.step[data-step="${step}"]`);

    if (newStepEl) newStepEl.classList.add('active');
    if (newIndicator) newIndicator.classList.add('active');

    // Update previous steps as completed
    for (let i = 1; i < step; i++) {
        const indicator = document.querySelector(`.step[data-step="${i}"]`);
        if (indicator) indicator.classList.add('completed');
    }

    // Update buttons
    const prevBtn = document.getElementById('prevBtn');
    const nextBtn = document.getElementById('nextBtn');
    const createBtn = document.getElementById('createBtn');

    if (prevBtn) prevBtn.classList.toggle('wizard-btn--hidden', step === 1);
    if (nextBtn) nextBtn.classList.toggle('wizard-btn--hidden', step === state.maxSteps);
    if (createBtn) createBtn.classList.toggle('d-none', step !== state.maxSteps);

    // Trigger step-specific updates
    triggerStepUpdate(step);
}

/**
 * Trigger step-specific update handlers
 * @param {number} step - Current step number
 */
function triggerStepUpdate(step) {
    // These will call functions that may be defined elsewhere
    // Using window.* for backward compatibility
    switch (step) {
        case 2:
            if (typeof window.updateStructureSections === 'function') {
                window.updateStructureSections();
            }
            break;
        case 3:
            if (typeof window.updateCalendarSections === 'function') {
                window.updateCalendarSections();
            }
            if (typeof window.generateCalendarPreview === 'function') {
                window.generateCalendarPreview();
            }
            break;
        case 5:
            if (typeof window.updateTeamSections === 'function') {
                window.updateTeamSections();
            }
            break;
        case 6:
            if (typeof window.generateSeasonSummary === 'function') {
                window.generateSeasonSummary();
            }
            break;
    }
}

/**
 * Validate current step before proceeding
 * @param {number} step - Step number to validate
 * @returns {boolean} Whether validation passed
 */
export function validateStep(step) {
    // Step-specific validation
    switch (step) {
        case 1:
            return validateStep1();
        case 4:
            return validateWizardStep4();
        default:
            return true;
    }
}

/**
 * Validate step 1 (basic info)
 * @returns {boolean}
 */
function validateStep1() {
    const seasonName = document.getElementById('seasonName')?.value;
    const leagueType = document.getElementById('leagueType')?.value;
    const startDate = document.getElementById('seasonStartDate')?.value;

    if (!seasonName?.trim()) {
        if (typeof window.showErrorModal === 'function') {
            window.showErrorModal('Validation Error', 'Please enter a season name.');
        }
        return false;
    }

    if (!leagueType) {
        if (typeof window.showErrorModal === 'function') {
            window.showErrorModal('Validation Error', 'Please select a league type.');
        }
        return false;
    }

    if (!startDate) {
        if (typeof window.showErrorModal === 'function') {
            window.showErrorModal('Validation Error', 'Please select a start date.');
        }
        return false;
    }

    return true;
}

/**
 * Validate step 4 (schedule configuration)
 * @returns {boolean}
 */
export function validateWizardStep4() {
    const premierTime = document.getElementById('premierStartTime')?.value;
    const classicTime = document.getElementById('classicStartTime')?.value;
    const matchDuration = document.getElementById('matchDuration')?.value;

    if (!premierTime || !classicTime) {
        if (typeof window.showErrorModal === 'function') {
            window.showErrorModal('Configuration Error', 'Both Premier and Classic start times are required.');
        }
        return false;
    }

    if (!matchDuration || matchDuration < 30 || matchDuration > 120) {
        if (typeof window.showErrorModal === 'function') {
            window.showErrorModal('Configuration Error', 'Match duration must be between 30 and 120 minutes.');
        }
        return false;
    }

    // Get field config
    const fieldConfig = typeof window.getWizardFieldConfig === 'function'
        ? window.getWizardFieldConfig()
        : [{ name: 'North' }, { name: 'South' }];

    if (fieldConfig.length < 2) {
        if (typeof window.showErrorModal === 'function') {
            window.showErrorModal('Configuration Error', 'At least 2 fields are required for back-to-back scheduling.');
        }
        return false;
    }

    // Check for duplicate field names
    const fieldNames = fieldConfig.map(f => f.name.toLowerCase());
    const uniqueNames = [...new Set(fieldNames)];
    if (fieldNames.length !== uniqueNames.length) {
        if (typeof window.showErrorModal === 'function') {
            window.showErrorModal('Configuration Error', 'Field names must be unique.');
        }
        return false;
    }

    // Check for empty field names
    if (fieldConfig.some(f => !f.name || f.name.trim() === '')) {
        if (typeof window.showErrorModal === 'function') {
            window.showErrorModal('Configuration Error', 'All fields must have names.');
        }
        return false;
    }

    return true;
}

export default {
    nextStep,
    previousStep,
    updateStepDisplay,
    validateStep,
    validateWizardStep4
};
