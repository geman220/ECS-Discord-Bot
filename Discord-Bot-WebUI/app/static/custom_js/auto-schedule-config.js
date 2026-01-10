'use strict';

/**
 * Auto Schedule Config Module
 * Extracted from auto_schedule_config.html
 * Handles schedule configuration, templates, and week/field management
 * @module auto-schedule-config
 */

import { InitSystem } from '../js/init-system.js';

// Module state
let weekConfigCount = 0;
let fieldCount = 2; // Start with North and South
let draggedElement = null;

/**
 * Initialize Auto Schedule Config module
 */
export function init() {
    // Initialize field counter based on existing fields
    fieldCount = document.querySelectorAll('.field-config-item').length || 2;

    // Generate practice week checkboxes based on weeks count
    updatePracticeWeekOptions();

    // Generate a default schedule on page load
    generateDefaultWeeks();

    // Show practice config for Classic if applicable
    updatePracticeConfigVisibility();

    setupEventListeners();

    console.log('[AutoScheduleConfig] Initialized');
}

/**
 * Setup event listeners using event delegation
 */
function setupEventListeners() {
    // Delegated input handler for weeks count
    document.addEventListener('input', function(e) {
        if (e.target.id === 'weeks_count') {
            updatePracticeWeekOptions();
            generateDefaultWeeks();
        }
    });

    // Delegated change handler for practice weeks checkbox
    document.addEventListener('change', function(e) {
        if (e.target.id === 'enable-practice-weeks') {
            const practiceWeeksSelection = document.getElementById('practice-weeks-selection');
            if (practiceWeeksSelection) {
                if (e.target.checked) {
                    practiceWeeksSelection.classList.remove('u-hidden');
                } else {
                    practiceWeeksSelection.classList.add('u-hidden');
                }
            }
        }
    });

    // Drag end handler for week cards
    document.addEventListener('dragend', function(e) {
        if (e.target.classList.contains('week-card')) {
            e.target.classList.remove('dragging');
        }
    });

    // Delegated drag handlers for week cards
    document.addEventListener('dragstart', function(e) {
        if (e.target.matches('.week-card')) {
            handleDragStart.call(e.target, e);
        }
    });

    document.addEventListener('dragover', function(e) {
        if (e.target.closest('.week-card')) {
            handleDragOver(e);
        }
    });

    document.addEventListener('drop', function(e) {
        const weekCard = e.target.closest('.week-card');
        if (weekCard) {
            handleDrop.call(weekCard, e);
        }
    });
}

/**
 * Apply schedule template
 * @param {string} templateType - Template type (premier-standard, classic-practice, custom)
 */
export function applyTemplate(templateType) {
    clearWeeks();

    switch(templateType) {
        case 'premier-standard':
            // Premier: 8 weeks regular, no practice
            setFormValue('weeks_count', 8);
            setFormValue('premier_start_time', '08:20');
            setFormValue('enable_time_rotation', true, true);
            setFormValue('enable-practice-weeks', false, true);
            generateRegularWeeks(8);
            break;

        case 'classic-practice':
            // Classic: 7 weeks with practice weeks 1 and 3
            setFormValue('weeks_count', 7);
            setFormValue('classic_start_time', '13:10');
            setFormValue('enable-practice-weeks', true, true);
            updatePracticeWeekOptions();

            // Check weeks 1 and 3 for practice
            setTimeout(() => {
                setFormValue('practice-week-1', true, true);
                setFormValue('practice-week-3', true, true);
                const practiceWeeksSelection = document.getElementById('practice-weeks-selection');
                if (practiceWeeksSelection) practiceWeeksSelection.classList.remove('u-hidden');
            }, 100);

            generateRegularWeeks(7);
            break;

        case 'custom':
            // Just clear and let user configure
            setFormValue('weeks_count', 6);
            addWeekConfig('REGULAR');
            addWeekConfig('REGULAR');
            addWeekConfig('TST');
            addWeekConfig('REGULAR');
            addWeekConfig('FUN');
            addWeekConfig('REGULAR');
            break;
    }
}

/**
 * Helper to set form values
 */
function setFormValue(id, value, isCheckbox = false) {
    const element = document.getElementById(id);
    if (element) {
        if (isCheckbox) {
            element.checked = value;
        } else {
            element.value = value;
        }
    }
}

/**
 * Generate regular weeks
 * @param {number} count - Number of weeks to generate
 */
function generateRegularWeeks(count) {
    clearWeeks();
    for (let i = 0; i < count; i++) {
        addWeekConfig('REGULAR');
    }
}

/**
 * Update practice week options
 */
function updatePracticeWeekOptions() {
    const weeksInput = document.getElementById('weeks_count');
    const weekCount = weeksInput ? parseInt(weeksInput.value) || 7 : 7;
    const container = document.getElementById('practice-week-checkboxes');

    if (!container) return;

    container.innerHTML = '';

    for (let i = 1; i <= weekCount; i++) {
        const div = document.createElement('div');
        div.className = 'flex items-center mr-4';
        div.innerHTML = `
            <input class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600" type="checkbox" id="practice-week-${i}" name="practice_weeks" value="${i}">
            <label class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300" for="practice-week-${i}">Week ${i}</label>
        `;
        container.appendChild(div);
    }
}

/**
 * Update practice config visibility
 */
function updatePracticeConfigVisibility() {
    const practiceConfig = document.getElementById('practice-config');
    if (practiceConfig) practiceConfig.classList.remove('u-hidden');
}

/**
 * Add a new field configuration
 */
export function addField() {
    const container = document.getElementById('field-configurations');
    if (!container) return;

    const fieldItem = document.createElement('div');
    fieldItem.className = 'field-config-item mb-2';
    fieldItem.setAttribute('data-field-index', fieldCount);

    fieldItem.innerHTML = `
        <div class="flex gap-2" data-input-group>
            <input type="text" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white field-name"
                   name="field_name_${fieldCount}"
                   placeholder="Field name" required data-form-control aria-label="Field name">
            <input type="number" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white field-capacity"
                   name="field_capacity_${fieldCount}"
                   value="20" min="1" max="50"
                   placeholder="Capacity" title="Field capacity" data-form-control aria-label="Capacity">
            <button type="button" class="c-btn c-btn--outline-danger remove-field js-remove-field"
                    data-action="remove-field" aria-label="Close"><i class="fas fa-times"></i></button>
        </div>
    `;

    container.appendChild(fieldItem);
    fieldCount++;
}

/**
 * Remove a field configuration
 * @param {HTMLElement} button - The remove button clicked
 */
export function removeField(button) {
    const fieldItems = document.querySelectorAll('.field-config-item');
    if (fieldItems.length > 2) { // Keep at least 2 fields
        button.closest('.field-config-item').remove();
    }
}

/**
 * Get theme color helper
 * @param {string} colorName - Color name
 * @param {string} fallback - Fallback color
 */
function getThemeColor(colorName, fallback) {
    if (typeof ECSTheme !== 'undefined') {
        return ECSTheme.getColor(colorName) || fallback;
    }
    const cssVar = getComputedStyle(document.documentElement).getPropertyValue(`--ecs-${colorName}`);
    return cssVar.trim() || fallback;
}

/**
 * Add a week configuration card
 * @param {string} weekType - Week type (REGULAR, PRACTICE, FUN, TST, BYE, PLAYOFF)
 */
export function addWeekConfig(weekType = 'REGULAR') {
    const container = document.getElementById('week-configurations');
    if (!container) return;

    const weekCard = document.createElement('div');
    weekCard.className = `week-card ${weekType.toLowerCase()}`;
    weekCard.draggable = true;
    weekCard.setAttribute('data-week-type', weekType);
    weekCard.setAttribute('data-week-order', weekConfigCount + 1);

    weekCard.innerHTML = `
        <div class="week-header">Week ${weekConfigCount + 1}</div>
        <div class="week-type">
            ${weekType}
        </div>
        <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white mt-2 week-type-select"
                name="week_type_${weekConfigCount}"
                data-action="update-week-card" data-form-select>
            <option value="REGULAR" ${weekType === 'REGULAR' ? 'selected' : ''}>Regular</option>
            <option value="PRACTICE" ${weekType === 'PRACTICE' ? 'selected' : ''}>Practice</option>
            <option value="FUN" ${weekType === 'FUN' ? 'selected' : ''}>Fun Week</option>
            <option value="TST" ${weekType === 'TST' ? 'selected' : ''}>TST</option>
            <option value="BYE" ${weekType === 'BYE' ? 'selected' : ''}>BYE</option>
            <option value="PLAYOFF" ${weekType === 'PLAYOFF' ? 'selected' : ''}>Playoff</option>
        </select>
        <button type="button" class="c-btn c-btn--sm c-btn--outline-danger mt-1 js-remove-week-card"
                data-action="remove-week-card" aria-label="Close"><i class="fas fa-times"></i></button>
        <input type="hidden" name="week_order_${weekConfigCount}" value="${weekConfigCount + 1}">
    `;

    // Drag events handled by delegated listeners in setupEventListeners()

    container.appendChild(weekCard);
    weekConfigCount++;
}

/**
 * Update a week card after type change
 * @param {HTMLElement} select - The select element that changed
 */
export function updateWeekCard(select) {
    const weekCard = select.closest('.week-card');
    if (!weekCard) return;

    const weekType = select.value;
    const weekTypeDisplay = weekCard.querySelector('.week-type');

    // Update visual styling
    weekCard.className = `week-card ${weekType.toLowerCase()}`;
    weekTypeDisplay.textContent = weekType;
    weekCard.setAttribute('data-week-type', weekType);
}

/**
 * Remove a week card
 * @param {HTMLElement} button - The remove button clicked
 */
export function removeWeekCard(button) {
    button.closest('.week-card').remove();
    renumberWeeks();
}

/**
 * Clear all weeks
 */
export function clearWeeks() {
    const container = document.getElementById('week-configurations');
    if (container) {
        container.innerHTML = '';
    }
    weekConfigCount = 0;
}

/**
 * Generate default weeks based on weeks_count input
 */
export function generateDefaultWeeks() {
    const weeksInput = document.getElementById('weeks_count');
    const weekCount = weeksInput ? parseInt(weeksInput.value) || 7 : 7;
    clearWeeks();

    for (let i = 0; i < weekCount; i++) {
        addWeekConfig('REGULAR');
    }
}

/**
 * Renumber all weeks after drag/drop or removal
 */
function renumberWeeks() {
    const weekCards = document.querySelectorAll('.week-card');
    weekCards.forEach((card, index) => {
        const weekHeader = card.querySelector('.week-header');
        if (weekHeader) {
            weekHeader.textContent = `Week ${index + 1}`;
        }
        card.setAttribute('data-week-order', index + 1);

        // Update hidden input
        const hiddenInput = card.querySelector('input[type="hidden"]');
        if (hiddenInput) {
            hiddenInput.value = index + 1;
        }
    });
    weekConfigCount = weekCards.length;
}

// Drag and drop handlers
function handleDragStart(e) {
    draggedElement = this;
    this.classList.add('dragging');
}

function handleDragOver(e) {
    e.preventDefault();
}

function handleDrop(e) {
    e.preventDefault();

    if (draggedElement && draggedElement !== this) {
        const container = document.getElementById('week-configurations');
        const draggedIndex = Array.from(container.children).indexOf(draggedElement);
        const targetIndex = Array.from(container.children).indexOf(this);

        if (draggedIndex < targetIndex) {
            container.insertBefore(draggedElement, this.nextSibling);
        } else {
            container.insertBefore(draggedElement, this);
        }

        renumberWeeks();
    }

    if (draggedElement) {
        draggedElement.classList.remove('dragging');
    }
    draggedElement = null;
}

// Event delegation handler
document.addEventListener('click', function(e) {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.dataset.action;

    switch(action) {
        case 'add-config-field':
            addField();
            break;
        case 'remove-field':
            removeField(target);
            break;
        case 'apply-template':
            applyTemplate(target.dataset.template);
            break;
        case 'add-week-config':
            addWeekConfig();
            break;
        case 'generate-default-weeks':
            generateDefaultWeeks();
            break;
        case 'clear-weeks':
            clearWeeks();
            break;
        case 'remove-week-card':
            removeWeekCard(target);
            break;
    }
});

// Handle select changes for week type updates
document.addEventListener('change', function(e) {
    const target = e.target.closest('[data-action="update-week-card"]');
    if (target) {
        updateWeekCard(target);
    }
});

// Register with InitSystem
if (typeof InitSystem !== 'undefined' && InitSystem.register) {
    InitSystem.register('auto-schedule-config', init, {
        priority: 30,
        description: 'Auto schedule configuration module'
    });
} else if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('auto-schedule-config', init, {
        priority: 30,
        description: 'Auto schedule configuration module'
    });
}

// Window exports for backward compatibility
window.AutoScheduleConfig = {
    init: init,
    applyTemplate: applyTemplate,
    addField: addField,
    removeField: removeField,
    addWeekConfig: addWeekConfig,
    updateWeekCard: updateWeekCard,
    removeWeekCard: removeWeekCard,
    clearWeeks: clearWeeks,
    generateDefaultWeeks: generateDefaultWeeks
};
