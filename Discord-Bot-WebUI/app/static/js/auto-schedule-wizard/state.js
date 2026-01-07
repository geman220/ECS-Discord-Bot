/**
 * Auto Schedule Wizard - Shared State
 * Centralized state management for the wizard
 *
 * @module auto-schedule-wizard/state
 */

// Global wizard state (using window to prevent redeclaration errors if script loads twice)
if (typeof window._autoScheduleWizardState === 'undefined') {
    window._autoScheduleWizardState = {
        currentStep: 1,
        maxSteps: 6,
        calendarState: {
            weeks: [],
            startDate: null,
            regularWeeks: 7,
            includeTST: false,
            includeFUN: false,
            byeWeeks: 0
        },
        calendarDraggedElement: null,
        draggedIndex: null
    };
}

/**
 * Get the wizard state object
 * @returns {Object} The wizard state
 */
export function getState() {
    return window._autoScheduleWizardState;
}

/**
 * Get the calendar state object
 * @returns {Object} The calendar state
 */
export function getCalendarState() {
    return window._autoScheduleWizardState.calendarState;
}

/**
 * Get current step
 * @returns {number}
 */
export function getCurrentStep() {
    return window._autoScheduleWizardState.currentStep;
}

/**
 * Set current step
 * @param {number} step
 */
export function setCurrentStep(step) {
    window._autoScheduleWizardState.currentStep = step;
}

/**
 * Get max steps
 * @returns {number}
 */
export function getMaxSteps() {
    return window._autoScheduleWizardState.maxSteps;
}

/**
 * Get dragged element reference
 * @returns {HTMLElement|null}
 */
export function getDraggedElement() {
    return window._autoScheduleWizardState.calendarDraggedElement;
}

/**
 * Set dragged element reference
 * @param {HTMLElement|null} element
 */
export function setDraggedElement(element) {
    window._autoScheduleWizardState.calendarDraggedElement = element;
}

/**
 * Get dragged index
 * @returns {number|null}
 */
export function getDraggedIndex() {
    return window._autoScheduleWizardState.draggedIndex;
}

/**
 * Set dragged index
 * @param {number|null} index
 */
export function setDraggedIndex(index) {
    window._autoScheduleWizardState.draggedIndex = index;
}

/**
 * Reset calendar state to defaults
 */
export function resetCalendarState() {
    const state = getCalendarState();
    state.weeks = [];
    state.startDate = null;
    state.regularWeeks = 7;
    state.includeTST = false;
    state.includeFUN = false;
    state.byeWeeks = 0;
}

/**
 * Update calendar state properties
 * @param {Object} updates - Properties to update
 */
export function updateCalendarState(updates) {
    const state = getCalendarState();
    Object.assign(state, updates);
}

export default {
    getState,
    getCalendarState,
    getCurrentStep,
    setCurrentStep,
    getMaxSteps,
    getDraggedElement,
    setDraggedElement,
    getDraggedIndex,
    setDraggedIndex,
    resetCalendarState,
    updateCalendarState
};
