/**
 * Auto Schedule Wizard JavaScript
 *
 * This file serves as the main entry point and backward compatibility layer
 * for the auto-schedule wizard. All functionality has been modularized into
 * the auto-schedule-wizard/ directory.
 *
 * Module Structure:
 * - state.js: Shared wizard state management
 * - date-utils.js: Date manipulation utilities
 * - ui-helpers.js: Modals, toasts, CSS helpers
 * - drag-drop.js: Drag and drop handlers
 * - calendar-generator.js: Calendar generation algorithms
 * - wizard-navigation.js: Step navigation
 * - structure-manager.js: Structure configuration
 * - team-manager.js: Team setup
 * - api.js: Form data and API calls
 */

import { ModalManager } from './modal-manager.js';
import { InitSystem } from './init-system.js';

// Import all functionality from submodules
import {
    // State management
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
    updateCalendarState,

    // Date utilities
    getNextSunday,
    formatDate,
    formatDateISO,
    isSunday,
    addDays,
    addWeeks,
    parseDate,
    getWeekNumber,
    isSameDay,

    // UI helpers
    applyThemeColor,
    applyUtilityClasses,
    removeUtilityClasses,
    showModal,
    showLoadingModal,
    hideLoadingModal,
    showSuccessModal,
    showErrorModal,
    showToast,
    addSpinnerCSS,
    addCalendarCSS,

    // Drag and drop
    initializeCalendarDragAndDrop,
    handleCalendarDragStart,
    handleCalendarDragEnter,
    handleCalendarDragLeave,
    handleCalendarDragOver,
    handleCalendarDrop,
    handleCalendarDragEnd,
    clearDropIndicators,
    synchronizeSharedWeek,
    getOtherDivisionContainer,
    updateWeekNumbersAndDates,
    initializeWeekCardDragAndDrop,
    swapWeekPositions,
    updateWeekNumbers,

    // Calendar generator
    generatePubLeagueCalendar,
    generateEcsFcCalendar,
    generateCombinedPubLeagueCalendar,
    createWeekHTML,
    regenerateCalendarHTML,
    generateCalendarHTMLFromState,
    getTotalWeeksCount,

    // Navigation
    nextStep,
    previousStep,
    updateStepDisplay,
    validateStep,
    validateWizardStep4,

    // Structure manager
    updateStructureSections,
    updateTotalWeeks,
    togglePracticeConfig,
    updateSeasonStructure,
    getEnabledSpecialWeeksCount,
    updateWizardPracticeWeekOptions,

    // Team manager
    updateTeamSections,
    updateTeamPreview,
    getTeamConfig,
    getTeamRange,

    // API
    getFormData,
    getUniqueWeekConfigs,
    getWizardFieldConfig,
    getClassicPracticeWeeks,
    createSeason,
    setActiveSeason
} from './auto-schedule-wizard/index.js';

// ========================================
// Additional Wizard Functions
// ========================================

/**
 * Start the season wizard modal
 */
function startSeasonWizard() {
    // Clean up previous state
    cleanupCalendarState();

    const modal = document.getElementById('seasonWizardModal');
    if (modal) {
        modal.classList.add('wizard-modal--visible');
        window.ModalManager.show('seasonWizardModal');
    }

    // Set default start date to next Sunday
    const today = new Date();
    const nextSunday = new Date(today);
    nextSunday.setDate(today.getDate() + (7 - today.getDay()) % 7);

    const startDateEl = document.getElementById('seasonStartDate');
    if (startDateEl) {
        startDateEl.value = nextSunday.toISOString().split('T')[0];
    }

    updateCalendarPreview();
}

/**
 * Clean up calendar state and event listeners
 */
function cleanupCalendarState() {
    const calendarState = getCalendarState();
    calendarState.weeks = [];
    calendarState.startDate = null;

    // Remove all existing event listeners from calendar items
    document.querySelectorAll('.week-item').forEach(item => {
        const newItem = item.cloneNode(true);
        if (item.parentNode) {
            item.parentNode.replaceChild(newItem, item);
        }
    });

    // Reset drag state
    setDraggedElement(null);
    setDraggedIndex(null);
}

/**
 * Show existing seasons section
 */
function showExistingSeasons() {
    const existing = document.getElementById('existingSeasons');
    const mainView = document.querySelector('.row.mb-4:nth-child(2)');
    if (existing) existing.classList.remove('d-none');
    if (mainView) mainView.classList.add('wizard-view--hidden');
}

/**
 * Show main view (hide existing seasons)
 */
function showMainView() {
    const existing = document.getElementById('existingSeasons');
    const mainView = document.querySelector('.row.mb-4:nth-child(2)');
    if (existing) existing.classList.add('d-none');
    if (mainView) mainView.classList.remove('wizard-view--hidden');
}

/**
 * Update calendar sections based on league type
 */
function updateCalendarSections() {
    const leagueType = document.getElementById('leagueType')?.value;
    const pubLeagueCalendar = document.getElementById('pubLeagueCalendar');
    const ecsFcCalendar = document.getElementById('ecsFcCalendar');

    if (leagueType === 'Pub League') {
        if (pubLeagueCalendar) pubLeagueCalendar.classList.remove('d-none');
        if (ecsFcCalendar) ecsFcCalendar.classList.add('d-none');
        updateCalendarSummary();
    } else if (leagueType === 'ECS FC') {
        if (pubLeagueCalendar) pubLeagueCalendar.classList.add('d-none');
        if (ecsFcCalendar) ecsFcCalendar.classList.remove('d-none');
        updateCalendarSummary();
    }
}

/**
 * Update calendar summary display
 */
function updateCalendarSummary() {
    const leagueType = document.getElementById('leagueType')?.value;
    const summaryEl = document.getElementById('calendarSummary');
    if (!summaryEl) return;

    if (leagueType === 'Pub League') {
        const premierRegular = document.getElementById('premierRegularWeeks')?.value || 7;
        const premierPlayoff = document.getElementById('premierPlayoffWeeks')?.value || 2;
        const classicRegular = document.getElementById('classicRegularWeeks')?.value || 8;
        const classicPlayoff = document.getElementById('classicPlayoffWeeks')?.value || 1;

        const hasFun = document.getElementById('includeFunWeek')?.checked || false;
        const hasTst = document.getElementById('includeTstWeek')?.checked || false;
        const hasBye = document.getElementById('includeByeWeek')?.checked || false;
        const hasBonus = document.getElementById('premierHasBonusWeek')?.checked || false;

        let summary = `<strong>Premier:</strong> ${premierRegular} regular + ${premierPlayoff} playoff`;
        if (hasFun || hasTst || hasBye || hasBonus) {
            const specials = [];
            if (hasFun) specials.push('Fun');
            if (hasTst) specials.push('TST');
            if (hasBye) specials.push('BYE');
            if (hasBonus) specials.push('Bonus');
            summary += ' + ' + specials.join(', ');
        }

        summary += `<br><strong>Classic:</strong> ${classicRegular} regular + ${classicPlayoff} playoff`;
        if (hasFun || hasTst || hasBye) {
            const specials = [];
            if (hasFun) specials.push('Fun');
            if (hasTst) specials.push('TST');
            if (hasBye) specials.push('BYE');
            summary += ' + ' + specials.join(', ');
        }

        summaryEl.innerHTML = summary;
    } else if (leagueType === 'ECS FC') {
        const regular = document.getElementById('ecsFcRegularWeeks')?.value || 8;
        const playoff = document.getElementById('ecsFcPlayoffWeeks')?.value || 1;
        summaryEl.innerHTML = `<strong>ECS FC:</strong> ${regular} regular + ${playoff} playoff weeks`;
    }
}

/**
 * Update calendar preview display
 */
function updateCalendarPreview() {
    const calendarState = getCalendarState();

    // Try different preview elements based on league type
    const possibleIds = ['unifiedCalendarPreview', 'calendarPreview', 'pubLeagueCalendar', 'ecsFcCalendarPreview'];
    let preview;

    for (const id of possibleIds) {
        preview = document.getElementById(id);
        if (preview) break;
    }

    if (!preview || !calendarState.weeks || calendarState.weeks.length === 0) return;

    // Group weeks by week number
    const weeksByNumber = {};
    calendarState.weeks.forEach(week => {
        if (!weeksByNumber[week.weekNumber]) {
            weeksByNumber[week.weekNumber] = {
                weekNumber: week.weekNumber,
                date: week.date,
                type: week.type,
                divisions: []
            };
        }
        weeksByNumber[week.weekNumber].divisions.push(week.division);
    });

    // Process unified weeks
    const unifiedWeeks = Object.values(weeksByNumber).map(week => {
        if (week.divisions.length === 2) {
            const weekDetails = calendarState.weeks.filter(w => w.weekNumber === week.weekNumber);
            const premierWeek = weekDetails.find(w => w.division === 'premier');
            const classicWeek = weekDetails.find(w => w.division === 'classic');

            if (premierWeek?.type === classicWeek?.type) {
                return { ...week, divisionsText: 'Premier & Classic' };
            }
            return {
                ...week,
                type: 'MIXED',
                divisionsText: `Premier: ${premierWeek?.type} | Classic: ${classicWeek?.type}`
            };
        }
        return {
            ...week,
            divisionsText: week.divisions[0] === 'premier' ? 'Premier only' : 'Classic only'
        };
    }).sort((a, b) => a.weekNumber - b.weekNumber);

    // Generate HTML
    let html = `
        <div class="mb-3 p-3 bg-light rounded">
            <h6 class="mb-1"><i class="fas fa-calendar-alt me-2"></i>Season Calendar Preview</h6>
            <small class="text-muted">${unifiedWeeks.length} weeks total</small><br>
            <small class="text-info"><i class="fas fa-hand-pointer me-1"></i>Drag any week to swap positions</small>
        </div>
        <div class="calendar-grid">
    `;

    unifiedWeeks.forEach(week => {
        const badgeClass = {
            'TST': 'info', 'FUN': 'warning', 'BYE': 'secondary',
            'PLAYOFF': 'danger', 'MIXED': 'dark'
        }[week.type] || 'primary';

        const iconClass = {
            'TST': 'fas fa-trophy', 'FUN': 'fas fa-star', 'BYE': 'fas fa-pause',
            'PLAYOFF': 'fas fa-medal', 'MIXED': 'fas fa-calendar-week'
        }[week.type] || 'fas fa-calendar';

        html += `
            <div class="week-card draggable-week" data-week-number="${week.weekNumber}" data-week-type="${week.type}" draggable="true">
                <div class="week-header bg-${badgeClass}">
                    <span class="week-number">Week ${week.weekNumber}</span>
                    <i class="fas fa-grip-vertical drag-handle"></i>
                </div>
                <div class="week-body">
                    <div class="week-date">${week.date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</div>
                    <div class="week-type"><i class="${iconClass} me-1"></i>${week.type === 'PLAYOFF' ? 'Playoffs' : week.type}</div>
                    <div class="divisions">${week.divisionsText}</div>
                </div>
            </div>
        `;
    });

    html += '</div>';
    preview.innerHTML = html;

    addCalendarCSS();
    initializeWeekCardDragAndDrop();
}

/**
 * Generate calendar preview
 */
function generateCalendarPreview(forceRegenerate = false) {
    const leagueType = document.getElementById('leagueType')?.value;
    const startDateStr = document.getElementById('seasonStartDate')?.value;

    if (!startDateStr) return;

    // Show/hide appropriate calendar containers
    const pubLeagueCalendar = document.getElementById('pubLeagueCalendar');
    const ecsFcCalendar = document.getElementById('ecsFcCalendar');

    if (leagueType === 'Pub League') {
        if (pubLeagueCalendar) pubLeagueCalendar.classList.remove('d-none');
        if (ecsFcCalendar) ecsFcCalendar.classList.add('d-none');
    } else if (leagueType === 'ECS FC') {
        if (pubLeagueCalendar) pubLeagueCalendar.classList.add('d-none');
        if (ecsFcCalendar) ecsFcCalendar.classList.remove('d-none');
    }

    // Parse date
    const [year, month, day] = startDateStr.split('-').map(num => parseInt(num));
    const startDate = new Date(year, month - 1, day);

    const calendarState = getCalendarState();
    calendarState.startDate = startDate;

    if (leagueType === 'Pub League') {
        generatePubLeagueCalendarLocal(startDate);
    } else if (leagueType === 'ECS FC') {
        generateEcsFcCalendar(startDate);
    }

    updateCalendarPreview();
}

/**
 * Generate Pub League calendar (local version with specific HTML output)
 */
function generatePubLeagueCalendarLocal(startDate) {
    const calendarState = getCalendarState();
    calendarState.weeks = [];

    const totalWeeks = parseInt(document.getElementById('totalSeasonWeeks')?.value) || 11;
    const specialWeeksCount = getEnabledSpecialWeeksCount();

    const premierRegular = totalWeeks - 2 - specialWeeksCount;
    const classicRegular = totalWeeks - 1 - specialWeeksCount;

    const config = {
        premier: { regular: premierRegular, playoff: 2 },
        classic: { regular: classicRegular, playoff: 1 },
        shared: {
            fun: document.getElementById('includeFunWeek')?.checked,
            tst: document.getElementById('includeTstWeek')?.checked,
            bye: document.getElementById('includeByeWeek')?.checked
        },
        totalWeeks: totalWeeks
    };

    let currentDate = new Date(startDate);
    let weekNumber = 1;
    const calendar = { premierHTML: '<div class="calendar-weeks">', classicHTML: '<div class="calendar-weeks">' };

    for (let i = 0; i < totalWeeks; i++) {
        const weekDate = new Date(currentDate);
        let weekType = 'Regular';
        let isPremierWeek = true;
        let isClassicWeek = true;

        if (i >= config.premier.regular && i < config.premier.regular + config.premier.playoff) {
            if (i >= config.classic.regular) {
                weekType = 'PLAYOFF';
            } else {
                weekType = 'MIXED';
            }
        } else if (i >= config.classic.regular && i < config.classic.regular + config.classic.playoff) {
            weekType = 'PLAYOFF';
            isPremierWeek = false;
        } else if (i >= Math.max(config.premier.regular + config.premier.playoff, config.classic.regular + config.classic.playoff)) {
            const specialIndex = i - Math.max(config.premier.regular + config.premier.playoff, config.classic.regular + config.classic.playoff);
            const specialTypes = [];
            if (config.shared.tst) specialTypes.push('TST');
            if (config.shared.fun) specialTypes.push('FUN');
            if (config.shared.bye) specialTypes.push('BYE');

            if (specialIndex < specialTypes.length) {
                weekType = specialTypes[specialIndex];
            }
        }

        if (isPremierWeek) {
            calendarState.weeks.push({
                weekNumber,
                date: new Date(weekDate),
                type: weekType,
                division: 'premier',
                isPractice: false
            });
            calendar.premierHTML += createWeekHTML(weekNumber, weekDate, weekType, false);
        }

        if (isClassicWeek) {
            const isPractice = weekType === 'Regular' && (i === 0 || i === 2);
            calendarState.weeks.push({
                weekNumber,
                date: new Date(weekDate),
                type: weekType,
                division: 'classic',
                isPractice
            });
            calendar.classicHTML += createWeekHTML(weekNumber, weekDate, weekType, isPractice);
        }

        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }

    calendar.premierHTML += '</div>';
    calendar.classicHTML += '</div>';

    const premierPreview = document.getElementById('premierCalendarPreview');
    const classicPreview = document.getElementById('classicCalendarPreview');

    if (premierPreview) premierPreview.innerHTML = calendar.premierHTML;
    if (classicPreview) classicPreview.innerHTML = calendar.classicHTML;

    initializeCalendarDragAndDrop();
}

/**
 * Generate season summary for final step
 */
function generateSeasonSummary() {
    const calendarState = getCalendarState();
    const config = {
        name: document.getElementById('seasonName')?.value,
        type: document.getElementById('leagueType')?.value,
        startDate: document.getElementById('seasonStartDate')?.value,
        current: document.getElementById('setAsCurrent')?.checked
    };

    const summaryElement = document.getElementById('seasonSummary');
    if (!summaryElement) return;

    let summary = `
        <div class="alert alert-info">
            <h5><i class="fas fa-info-circle me-2"></i>Season Creation Summary</h5>
            <p class="mb-0">Review configuration before creating season.</p>
        </div>
        <div class="row mb-4">
            <div class="col-md-6">
                <div class="card border-secondary">
                    <div class="card-header bg-secondary text-white">
                        <h6 class="mb-0"><i class="fas fa-calendar me-2"></i>Season Details</h6>
                    </div>
                    <div class="card-body">
                        <ul class="list-unstyled mb-0">
                            <li><strong>Name:</strong> ${config.name}</li>
                            <li><strong>Type:</strong> ${config.type}</li>
                            <li><strong>Start Date:</strong> ${config.startDate}</li>
                            <li><strong>Set as Current:</strong> ${config.current ? 'Yes' : 'No'}</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    `;

    if (config.type === 'Pub League' && calendarState?.weeks?.length) {
        const premierWeeks = calendarState.weeks.filter(w => w.division === 'premier');
        const classicWeeks = calendarState.weeks.filter(w => w.division === 'classic');

        summary += `
            <div class="row mb-4">
                <div class="col-md-6">
                    <div class="card border-primary">
                        <div class="card-header bg-primary text-white">
                            <h6 class="mb-0"><i class="fas fa-trophy me-2"></i>Premier Division</h6>
                        </div>
                        <div class="card-body">
                            <p><strong>Total Weeks:</strong> ${premierWeeks.length}</p>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card border-success">
                        <div class="card-header bg-success text-white">
                            <h6 class="mb-0"><i class="fas fa-users me-2"></i>Classic Division</h6>
                        </div>
                        <div class="card-body">
                            <p><strong>Total Weeks:</strong> ${classicWeeks.length}</p>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    summary += `
        <div class="alert alert-success">
            <h6><i class="fas fa-check-circle me-2"></i>Ready to Create Season</h6>
            <p class="mb-0">This will create your ${config.type} season.</p>
        </div>
    `;

    summaryElement.innerHTML = summary;
}

/**
 * Apply wizard template
 */
function applyWizardTemplate(templateType) {
    switch(templateType) {
        case 'standard':
            document.getElementById('premierStartTime').value = '08:20';
            document.getElementById('classicStartTime').value = '13:10';
            document.getElementById('matchDuration').value = '70';
            document.getElementById('breakDuration').value = '10';
            document.getElementById('enableTimeRotation').checked = true;
            document.getElementById('classicHasPractice').checked = false;
            document.getElementById('practice-weeks-selection')?.classList.add('d-none');
            break;
        case 'classic-practice':
            document.getElementById('premierStartTime').value = '08:20';
            document.getElementById('classicStartTime').value = '13:10';
            document.getElementById('matchDuration').value = '70';
            document.getElementById('breakDuration').value = '10';
            document.getElementById('enableTimeRotation').checked = true;
            document.getElementById('classicHasPractice').checked = true;
            document.getElementById('practice-weeks-selection')?.classList.remove('d-none');
            setTimeout(() => {
                updateWizardPracticeWeekOptions();
                const week1 = document.getElementById('wizard-practice-week-1');
                const week3 = document.getElementById('wizard-practice-week-3');
                if (week1) week1.checked = true;
                if (week3) week3.checked = true;
            }, 100);
            break;
        case 'custom':
            document.getElementById('classicHasPractice').checked = false;
            document.getElementById('practice-weeks-selection')?.classList.add('d-none');
            break;
    }

    window.showToast?.(`${templateType.charAt(0).toUpperCase() + templateType.slice(1)} template applied!`, 'success');
}

/**
 * Add wizard field
 */
function addWizardField() {
    const container = document.getElementById('wizard-field-configurations');
    if (!container) return;

    const fieldCount = container.children.length;
    const fieldItem = document.createElement('div');
    fieldItem.className = 'wizard-field-item mb-3';

    fieldItem.innerHTML = `
        <div class="row">
            <div class="col-md-8">
                <label class="form-label">Field Name</label>
                <input type="text" class="form-control wizard-field-name" placeholder="Field ${fieldCount + 1}" required>
            </div>
            <div class="col-md-2 d-flex align-items-end">
                <button type="button" class="btn btn-outline-danger" data-action="remove-wizard-field">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        </div>
    `;

    container.appendChild(fieldItem);
    updateWizardFieldRemoveButtons();
}

/**
 * Remove wizard field
 */
function removeWizardField(button) {
    const fieldItems = document.querySelectorAll('.wizard-field-item');
    if (fieldItems.length > 2) {
        button.closest('.wizard-field-item')?.remove();
        updateWizardFieldRemoveButtons();
    }
}

/**
 * Update field remove button states
 */
function updateWizardFieldRemoveButtons() {
    const fieldItems = document.querySelectorAll('.wizard-field-item');
    const removeButtons = document.querySelectorAll('[data-action="remove-field"], [data-action="remove-wizard-field"]');

    removeButtons.forEach(button => {
        button.disabled = fieldItems.length <= 2;
    });
}

// ========================================
// Initialization
// ========================================

let _initialized = false;

function initAutoScheduleWizard() {
    // Page guard
    if (!document.getElementById('totalSeasonWeeks')) return;

    // Guard against multiple initialization
    if (_initialized) return;
    _initialized = true;

    // Initialize CSS
    addSpinnerCSS();

    // Initialize field remove button states
    updateWizardFieldRemoveButtons();

    // Initialize season structure calculations
    updateSeasonStructure();
    updateWizardPracticeWeekOptions();
}

// Register with InitSystem
window.InitSystem.register('auto-schedule-wizard', initAutoScheduleWizard, {
    priority: 30,
    reinitializable: false,
    description: 'Auto schedule wizard functionality'
});

// ========================================
// Window Exports - Only functions used by event delegation handlers
// ========================================

// Wizard control (used by season-wizard.js handler)
window.startSeasonWizard = startSeasonWizard;
window.showExistingSeasons = showExistingSeasons;
window.showMainView = showMainView;
window.nextStep = nextStep;
window.previousStep = previousStep;
window.createSeason = createSeason;
window.setActiveSeason = setActiveSeason;

// Structure (used by season-wizard.js handler)
window.updateSeasonStructure = updateSeasonStructure;

// Enhanced wizard (used by season-wizard.js handler)
window.applyWizardTemplate = applyWizardTemplate;
window.addWizardField = addWizardField;
window.removeWizardField = removeWizardField;
