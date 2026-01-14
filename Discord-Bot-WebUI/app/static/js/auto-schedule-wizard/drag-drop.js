/**
 * Auto Schedule Wizard - Drag and Drop Handlers
 * Calendar and week card drag/drop functionality
 *
 * @module auto-schedule-wizard/drag-drop
 */

import { getDraggedElement, setDraggedElement, getCalendarState } from './state.js';
import { applyThemeColor } from './ui-helpers.js';
import { formatDate } from './date-utils.js';

/**
 * Initialize calendar drag and drop
 */
export function initializeCalendarDragAndDrop() {
    const weekItems = document.querySelectorAll('.week-item');

    weekItems.forEach(item => {
        item.addEventListener('dragstart', handleCalendarDragStart);
        item.addEventListener('dragover', handleCalendarDragOver);
        item.addEventListener('dragenter', handleCalendarDragEnter);
        item.addEventListener('dragleave', handleCalendarDragLeave);
        item.addEventListener('drop', handleCalendarDrop);
        item.addEventListener('dragend', handleCalendarDragEnd);
    });
}

/**
 * Handle calendar drag start
 * @param {DragEvent} e
 */
export function handleCalendarDragStart(e) {
    setDraggedElement(e.target);
    e.target.classList.add('drag-active');
    e.dataTransfer.effectAllowed = 'move';
}

/**
 * Handle calendar drag enter
 * @param {DragEvent} e
 */
export function handleCalendarDragEnter(e) {
    e.preventDefault();
}

/**
 * Handle calendar drag leave
 * @param {DragEvent} e
 */
export function handleCalendarDragLeave(e) {
    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;
    const weekItem = e.target.closest('.week-item');
    if (weekItem && !weekItem.contains(e.relatedTarget)) {
        clearDropIndicators();
    }
}

/**
 * Handle calendar drag over
 * @param {DragEvent} e
 */
export function handleCalendarDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;

    const calendarDraggedElement = getDraggedElement();
    const weekItem = e.target.closest('.week-item');

    if (weekItem && weekItem !== calendarDraggedElement) {
        clearDropIndicators();

        const rect = weekItem.getBoundingClientRect();
        const midPoint = rect.top + rect.height / 2;

        const highlightColor = (typeof window.ECSTheme !== 'undefined')
            ? window.ECSTheme.getColor('primary')
            : '#0d6efd';
        applyThemeColor(weekItem, highlightColor);

        if (e.clientY < midPoint) {
            weekItem.classList.add('drop-indicator-top');
            weekItem.dataset.dropPosition = 'before';
        } else {
            weekItem.classList.add('drop-indicator-bottom');
            weekItem.dataset.dropPosition = 'after';
        }
    }
}

/**
 * Handle calendar drop
 * @param {DragEvent} e
 */
export function handleCalendarDrop(e) {
    e.preventDefault();

    const calendarDraggedElement = getDraggedElement();

    if (calendarDraggedElement) {
        // Guard: ensure e.target is an Element with closest method
        if (!e.target || typeof e.target.closest !== 'function') return;
        const targetWeekItem = e.target.closest('.week-item');
        const draggedWeekItem = calendarDraggedElement.closest('.week-item');

        if (targetWeekItem && draggedWeekItem && targetWeekItem !== draggedWeekItem) {
            const container = targetWeekItem.closest('.calendar-container');
            const draggedContainer = draggedWeekItem.closest('.calendar-container');

            if (container === draggedContainer) {
                const dropPosition = targetWeekItem.dataset.dropPosition;
                const calendarWeeks = container.querySelector('.calendar-weeks');

                if (calendarWeeks) {
                    const isSharedWeek = draggedWeekItem.classList.contains('shared-week');
                    const sharedType = draggedWeekItem.dataset.sharedType;

                    if (dropPosition === 'before') {
                        calendarWeeks.insertBefore(draggedWeekItem, targetWeekItem);
                    } else if (dropPosition === 'after') {
                        calendarWeeks.insertBefore(draggedWeekItem, targetWeekItem.nextSibling);
                    }

                    if (isSharedWeek && sharedType) {
                        synchronizeSharedWeek(draggedWeekItem, sharedType, dropPosition, targetWeekItem);
                    }

                    updateWeekNumbersAndDates(container);

                    if (isSharedWeek) {
                        const otherContainer = getOtherDivisionContainer(container);
                        if (otherContainer) {
                            updateWeekNumbersAndDates(otherContainer);
                        }
                    }
                }
            }
        }
    }

    clearDropIndicators();
}

/**
 * Handle calendar drag end
 * @param {DragEvent} e
 */
export function handleCalendarDragEnd(e) {
    e.target.classList.remove('drag-active');
    setDraggedElement(null);
    clearDropIndicators();
}

/**
 * Clear all drop indicators
 */
export function clearDropIndicators() {
    const allWeekItems = document.querySelectorAll('.week-item');
    allWeekItems.forEach(item => {
        item.classList.remove('drop-indicator-top', 'drop-indicator-bottom');
        delete item.dataset.dropPosition;
    });
}

/**
 * Synchronize shared week movement to the other division
 * @param {HTMLElement} draggedWeekItem
 * @param {string} sharedType
 * @param {string} dropPosition
 * @param {HTMLElement} targetWeekItem
 */
export function synchronizeSharedWeek(draggedWeekItem, sharedType, dropPosition, targetWeekItem) {
    const otherContainer = getOtherDivisionContainer(draggedWeekItem.closest('.calendar-container'));
    if (!otherContainer) return;

    const otherSharedWeek = otherContainer.querySelector(`[data-shared-type="${sharedType}"]`);
    if (!otherSharedWeek) return;

    const targetWeekNumber = targetWeekItem.dataset.week;
    const otherTargetWeek = otherContainer.querySelector(`[data-week="${targetWeekNumber}"]`);
    if (!otherTargetWeek) return;

    const otherCalendarWeeks = otherContainer.querySelector('.calendar-weeks');
    if (!otherCalendarWeeks) return;

    if (dropPosition === 'before') {
        otherCalendarWeeks.insertBefore(otherSharedWeek, otherTargetWeek);
    } else if (dropPosition === 'after') {
        otherCalendarWeeks.insertBefore(otherSharedWeek, otherTargetWeek.nextSibling);
    }
}

/**
 * Get the other division's container (Premier <-> Classic)
 * @param {HTMLElement} currentContainer
 * @returns {HTMLElement|null}
 */
export function getOtherDivisionContainer(currentContainer) {
    const containerId = currentContainer.id;

    if (containerId.includes('premier')) {
        return document.getElementById('classicCalendarPreview');
    } else if (containerId.includes('classic')) {
        return document.getElementById('premierCalendarPreview');
    }

    return null;
}

/**
 * Update week numbers and dates after reordering
 * @param {HTMLElement} container
 */
export function updateWeekNumbersAndDates(container) {
    const calendarState = getCalendarState();
    const weekItems = container.querySelectorAll('.week-item');
    const startDateStr = document.getElementById('seasonStartDate').value;

    if (!startDateStr) return;

    const [year, month, day] = startDateStr.split('-').map(num => parseInt(num));
    const startDate = new Date(year, month - 1, day);
    let currentDate = new Date(startDate);

    const containerClass = container.className;
    const containerId = container.id;
    let division;

    if (containerClass.includes('premier') || containerId.includes('premier')) {
        division = 'premier';
    } else if (containerClass.includes('classic') || containerId.includes('classic')) {
        division = 'classic';
    } else if (containerClass.includes('ecs') || containerId.includes('ecs')) {
        division = 'ecs_fc';
    } else {
        const parentContainer = container.closest('[id*="premier"], [id*="classic"], [id*="ecs"]');
        if (parentContainer) {
            if (parentContainer.id.includes('premier')) {
                division = 'premier';
            } else if (parentContainer.id.includes('classic')) {
                division = 'classic';
            } else if (parentContainer.id.includes('ecs')) {
                division = 'ecs_fc';
            }
        }
    }

    // Remove old weeks for this division before adding new ones
    calendarState.weeks = calendarState.weeks.filter(w => w.division !== division);

    weekItems.forEach((item, index) => {
        const weekNumber = item.querySelector('.week-number');
        weekNumber.textContent = `Week ${index + 1}`;
        item.dataset.week = index + 1;

        const weekDate = item.querySelector('.week-date');
        if (weekDate) {
            weekDate.textContent = formatDate(currentDate);
        }

        const weekType = item.dataset.type;
        const mappedType = weekType === 'regular' ? 'Regular' :
                          weekType === 'fun' ? 'FUN' :
                          weekType === 'tst' ? 'TST' :
                          weekType === 'playoff' ? 'PLAYOFF' :
                          weekType === 'bonus' ? 'BONUS' : 'Regular';

        const weekTypeText = item.querySelector('.week-type').textContent;
        const isPractice = weekTypeText.includes('Practice Game 1');

        calendarState.weeks.push({
            weekNumber: index + 1,
            date: new Date(currentDate),
            type: mappedType,
            division: division,
            isPractice: isPractice
        });

        currentDate.setDate(currentDate.getDate() + 7);
    });
}

/**
 * Initialize week card drag and drop (for week type cards)
 */
export function initializeWeekCardDragAndDrop() {
    const weekCards = document.querySelectorAll('.week-card[draggable="true"]');

    weekCards.forEach(card => {
        card.addEventListener('dragstart', handleWeekCardDragStart);
        card.addEventListener('dragover', handleWeekCardDragOver);
        card.addEventListener('drop', handleWeekCardDrop);
        card.addEventListener('dragend', handleWeekCardDragEnd);
    });
}

let draggedWeekCard = null;

/**
 * Handle week card drag start
 * @param {DragEvent} e
 */
function handleWeekCardDragStart(e) {
    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;
    draggedWeekCard = e.target.closest('.week-card');
    if (draggedWeekCard) {
        draggedWeekCard.classList.add('drag-active');
        e.dataTransfer.effectAllowed = 'move';
    }
}

/**
 * Handle week card drag over
 * @param {DragEvent} e
 */
function handleWeekCardDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
}

/**
 * Handle week card drop
 * @param {DragEvent} e
 */
function handleWeekCardDrop(e) {
    e.preventDefault();
    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;
    const targetCard = e.target.closest('.week-card');

    if (draggedWeekCard && targetCard && draggedWeekCard !== targetCard) {
        swapWeekPositions(draggedWeekCard, targetCard);
    }
}

/**
 * Handle week card drag end
 * @param {DragEvent} e
 */
function handleWeekCardDragEnd(e) {
    if (draggedWeekCard) {
        draggedWeekCard.classList.remove('drag-active');
        draggedWeekCard = null;
    }
}

/**
 * Swap positions of two week cards
 * @param {HTMLElement} draggedWeek
 * @param {HTMLElement} targetWeek
 */
export function swapWeekPositions(draggedWeek, targetWeek) {
    const container = draggedWeek.parentElement;
    const draggedIndex = Array.from(container.children).indexOf(draggedWeek);
    const targetIndex = Array.from(container.children).indexOf(targetWeek);

    if (draggedIndex < targetIndex) {
        container.insertBefore(draggedWeek, targetWeek.nextSibling);
    } else {
        container.insertBefore(draggedWeek, targetWeek);
    }

    updateWeekNumbers();
}

/**
 * Update week numbers after reordering
 */
export function updateWeekNumbers() {
    const weekCards = document.querySelectorAll('.week-timeline .week-card');
    weekCards.forEach((card, index) => {
        const weekHeader = card.querySelector('.week-header');
        if (weekHeader) {
            weekHeader.textContent = `Week ${index + 1}`;
        }
    });
}

export default {
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
    updateWeekNumbers
};
