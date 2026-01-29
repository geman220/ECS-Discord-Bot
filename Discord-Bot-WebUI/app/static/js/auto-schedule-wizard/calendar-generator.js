/**
 * Auto Schedule Wizard - Calendar Generator
 * Calendar generation algorithms for different league types
 *
 * @module auto-schedule-wizard/calendar-generator
 */

import { getCalendarState, updateCalendarState } from './state.js';
import { formatDate, getNextSunday, addWeeks } from './date-utils.js';

/**
 * Generate Pub League calendar (combined Premier/Classic)
 * @param {Date} startDate - Season start date
 * @returns {Object} Calendar HTML for both divisions
 */
export function generatePubLeagueCalendar(startDate) {
    const calendarState = getCalendarState();

    // Clear calendar state
    calendarState.weeks = [];

    const regularWeeks = parseInt(document.getElementById('pubLeagueRegularWeeks')?.value) || 7;

    let premierHTML = '<div class="calendar-weeks">';
    let classicHTML = '<div class="calendar-weeks">';

    let currentDate = new Date(startDate);

    for (let i = 0; i < regularWeeks; i++) {
        const weekNum = i + 1;
        premierHTML += createWeekHTML(weekNum, currentDate, 'regular', false, false, 'premier');
        classicHTML += createWeekHTML(weekNum, currentDate, 'regular', false, false, 'classic');

        calendarState.weeks.push({
            weekNumber: weekNum,
            date: new Date(currentDate),
            type: 'Regular',
            division: 'premier'
        });
        calendarState.weeks.push({
            weekNumber: weekNum,
            date: new Date(currentDate),
            type: 'Regular',
            division: 'classic'
        });

        currentDate.setDate(currentDate.getDate() + 7);
    }

    premierHTML += '</div>';
    classicHTML += '</div>';

    return { premier: premierHTML, classic: classicHTML };
}

/**
 * Generate ECS FC calendar
 * @param {Date} startDate - Season start date
 * @returns {string} Calendar HTML
 */
export function generateEcsFcCalendar(startDate) {
    const calendarState = getCalendarState();

    // Clear calendar state
    calendarState.weeks = [];

    const regularWeeks = parseInt(document.getElementById('ecsFcRegularWeeks')?.value) || 8;
    const playoffWeeks = parseInt(document.getElementById('ecsFcPlayoffWeeks')?.value) || 1;

    let calendar = '<div class="calendar-weeks">';
    let currentDate = new Date(startDate);
    let weekNumber = 1;

    // Regular season weeks
    for (let i = 0; i < regularWeeks; i++) {
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'Regular',
            division: 'ecs_fc'
        });

        calendar += createWeekHTML(weekNumber, currentDate, 'regular', false, false, 'ecs_fc');
        weekNumber++;
        currentDate.setDate(currentDate.getDate() + 7);
    }

    // Playoff weeks
    for (let i = 0; i < playoffWeeks; i++) {
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'PLAYOFF',
            division: 'ecs_fc'
        });

        calendar += createWeekHTML(weekNumber, currentDate, 'playoff', false, false, 'ecs_fc');
        weekNumber++;
        currentDate.setDate(currentDate.getDate() + 7);
    }

    calendar += '</div>';
    return calendar;
}

/**
 * Generate combined Pub League calendar with special weeks
 * @param {Date} startDate - Season start date
 * @returns {Object} Calendar HTML for both divisions
 */
export function generateCombinedPubLeagueCalendar(startDate) {
    const calendarState = getCalendarState();

    // Clear calendar state
    calendarState.weeks = [];

    const includeTST = document.getElementById('includeTST')?.checked || false;
    const includeFUN = document.getElementById('includeFUN')?.checked || false;
    const includePlayoffs = document.getElementById('includePlayoffs')?.checked || false;
    const includePractice = document.getElementById('includePracticeWeeks')?.checked || false;

    const regularWeeks = parseInt(document.getElementById('pubLeagueRegularWeeks')?.value) || 7;
    const practiceWeeks = includePractice ? (parseInt(document.getElementById('practiceWeekCount')?.value) || 1) : 0;
    const playoffWeeks = includePlayoffs ? (parseInt(document.getElementById('pubLeaguePlayoffWeeks')?.value) || 1) : 0;

    let premierHTML = '<div class="calendar-weeks">';
    let classicHTML = '<div class="calendar-weeks">';

    let currentDate = new Date(startDate);
    let weekNumber = 1;

    // Practice weeks
    for (let i = 0; i < practiceWeeks; i++) {
        const weekData = {
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'Regular',
            division: 'premier',
            isPractice: true
        };

        premierHTML += createWeekHTML(weekNumber, currentDate, 'regular', true, false, 'premier');
        classicHTML += createWeekHTML(weekNumber, currentDate, 'regular', true, false, 'classic');

        calendarState.weeks.push({ ...weekData });
        calendarState.weeks.push({ ...weekData, division: 'classic' });

        weekNumber++;
        currentDate.setDate(currentDate.getDate() + 7);
    }

    // Regular weeks
    for (let i = 0; i < regularWeeks; i++) {
        premierHTML += createWeekHTML(weekNumber, currentDate, 'regular', false, false, 'premier');
        classicHTML += createWeekHTML(weekNumber, currentDate, 'regular', false, false, 'classic');

        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'Regular',
            division: 'premier'
        });
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'Regular',
            division: 'classic'
        });

        weekNumber++;
        currentDate.setDate(currentDate.getDate() + 7);
    }

    // TST week (shared)
    if (includeTST) {
        premierHTML += createWeekHTML(weekNumber, currentDate, 'tst', false, true, 'premier');
        classicHTML += createWeekHTML(weekNumber, currentDate, 'tst', false, true, 'classic');

        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'TST',
            division: 'premier',
            shared: true
        });
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'TST',
            division: 'classic',
            shared: true
        });

        weekNumber++;
        currentDate.setDate(currentDate.getDate() + 7);
    }

    // FUN week (shared)
    if (includeFUN) {
        premierHTML += createWeekHTML(weekNumber, currentDate, 'fun', false, true, 'premier');
        classicHTML += createWeekHTML(weekNumber, currentDate, 'fun', false, true, 'classic');

        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'FUN',
            division: 'premier',
            shared: true
        });
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'FUN',
            division: 'classic',
            shared: true
        });

        weekNumber++;
        currentDate.setDate(currentDate.getDate() + 7);
    }

    // Playoff weeks
    for (let i = 0; i < playoffWeeks; i++) {
        premierHTML += createWeekHTML(weekNumber, currentDate, 'playoff', false, false, 'premier');
        classicHTML += createWeekHTML(weekNumber, currentDate, 'playoff', false, false, 'classic');

        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'PLAYOFF',
            division: 'premier'
        });
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'PLAYOFF',
            division: 'classic'
        });

        weekNumber++;
        currentDate.setDate(currentDate.getDate() + 7);
    }

    premierHTML += '</div>';
    classicHTML += '</div>';

    return { premier: premierHTML, classic: classicHTML };
}

/**
 * Create HTML for a single week
 * @param {number} weekNumber - Week number
 * @param {Date} date - Week date
 * @param {string} type - Week type (regular, tst, fun, playoff)
 * @param {boolean} isPractice - Is practice week
 * @param {boolean} isShared - Is shared week
 * @param {string} division - Division name
 * @returns {string} HTML string
 */
export function createWeekHTML(weekNumber, date, type, isPractice = false, isShared = false, division = '') {
    const typeLabels = {
        regular: isPractice ? 'Practice Game 1' : 'Regular Match',
        tst: 'TST Week',
        fun: 'FUN Week',
        playoff: 'Playoff Match',
        bonus: 'Bonus Week'
    };

    const typeColors = {
        regular: isPractice ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300' : 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300',
        tst: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
        fun: 'bg-ecs-green-100 text-ecs-green-800 dark:bg-ecs-green-900 dark:text-ecs-green-300',
        playoff: 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300',
        bonus: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'
    };

    const sharedClass = isShared ? 'shared-week' : '';
    const sharedAttr = isShared ? `data-shared-type="${type}"` : '';

    return `
        <div class="week-item ${sharedClass}" draggable="true" data-week="${weekNumber}" data-type="${type}" ${sharedAttr}>
            <div class="flex justify-between items-center">
                <div>
                    <span class="week-number font-bold">Week ${weekNumber}</span>
                    <span class="week-date text-gray-500 dark:text-gray-400 ms-2">${formatDate(date)}</span>
                </div>
                <div>
                    <span class="px-2 py-0.5 text-xs font-medium rounded ${typeColors[type] || typeColors.regular} week-type">${typeLabels[type] || 'Regular Match'}</span>
                    ${isShared ? '<span class="px-2 py-0.5 text-xs font-medium rounded bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300 ms-1">Shared</span>' : ''}
                </div>
            </div>
        </div>
    `;
}

/**
 * Regenerate calendar HTML from current state
 * @returns {Object} Calendar HTML for divisions
 */
export function regenerateCalendarHTML() {
    const calendarState = getCalendarState();

    const premierWeeks = calendarState.weeks.filter(w => w.division === 'premier');
    const classicWeeks = calendarState.weeks.filter(w => w.division === 'classic');
    const ecsFcWeeks = calendarState.weeks.filter(w => w.division === 'ecs_fc');

    return {
        premier: generateCalendarHTMLFromState(premierWeeks, 'premier'),
        classic: generateCalendarHTMLFromState(classicWeeks, 'classic'),
        ecs_fc: generateCalendarHTMLFromState(ecsFcWeeks, 'ecs_fc')
    };
}

/**
 * Generate calendar HTML from week state array
 * @param {Array} weeks - Array of week objects
 * @param {string} division - Division name
 * @returns {string} HTML string
 */
export function generateCalendarHTMLFromState(weeks, division) {
    let html = '<div class="calendar-weeks">';

    weeks.forEach(week => {
        const type = week.type.toLowerCase();
        const isPractice = week.isPractice || false;
        const isShared = week.shared || false;

        html += createWeekHTML(week.weekNumber, week.date, type, isPractice, isShared, division);
    });

    html += '</div>';
    return html;
}

/**
 * Get total weeks count based on configuration
 * @param {string} divisionType - Division type (pub_league or ecs_fc)
 * @returns {number} Total weeks
 */
export function getTotalWeeksCount(divisionType) {
    if (divisionType === 'ecs_fc') {
        const regularWeeks = parseInt(document.getElementById('ecsFcRegularWeeks')?.value) || 8;
        const playoffWeeks = parseInt(document.getElementById('ecsFcPlayoffWeeks')?.value) || 1;
        return regularWeeks + playoffWeeks;
    }

    // Pub League
    const regularWeeks = parseInt(document.getElementById('pubLeagueRegularWeeks')?.value) || 7;
    const practiceWeeks = document.getElementById('includePracticeWeeks')?.checked
        ? (parseInt(document.getElementById('practiceWeekCount')?.value) || 1)
        : 0;
    const playoffWeeks = document.getElementById('includePlayoffs')?.checked
        ? (parseInt(document.getElementById('pubLeaguePlayoffWeeks')?.value) || 1)
        : 0;
    const tstWeeks = document.getElementById('includeTST')?.checked ? 1 : 0;
    const funWeeks = document.getElementById('includeFUN')?.checked ? 1 : 0;

    return regularWeeks + practiceWeeks + playoffWeeks + tstWeeks + funWeeks;
}

export default {
    generatePubLeagueCalendar,
    generateEcsFcCalendar,
    generateCombinedPubLeagueCalendar,
    createWeekHTML,
    regenerateCalendarHTML,
    generateCalendarHTMLFromState,
    getTotalWeeksCount
};
