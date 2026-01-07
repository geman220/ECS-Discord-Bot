/**
 * Auto Schedule Wizard - Date Utilities
 * Reusable date manipulation functions for schedule generation
 *
 * @module auto-schedule-wizard/date-utils
 */

/**
 * Get the next Sunday from a given date
 * @param {Date} date - Starting date
 * @returns {Date} Next Sunday
 */
export function getNextSunday(date) {
    const result = new Date(date);
    const day = result.getDay();
    const diff = day === 0 ? 0 : 7 - day;
    result.setDate(result.getDate() + diff);
    return result;
}

/**
 * Format a date as MM/DD/YYYY
 * @param {Date} date - Date to format
 * @returns {string} Formatted date string
 */
export function formatDate(date) {
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const year = date.getFullYear();
    return `${month}/${day}/${year}`;
}

/**
 * Format a date as YYYY-MM-DD (ISO format for inputs)
 * @param {Date} date - Date to format
 * @returns {string} ISO formatted date string
 */
export function formatDateISO(date) {
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const year = date.getFullYear();
    return `${year}-${month}-${day}`;
}

/**
 * Check if a date is a Sunday
 * @param {Date} date - Date to check
 * @returns {boolean} True if Sunday
 */
export function isSunday(date) {
    return date.getDay() === 0;
}

/**
 * Add days to a date
 * @param {Date} date - Starting date
 * @param {number} days - Number of days to add
 * @returns {Date} New date
 */
export function addDays(date, days) {
    const result = new Date(date);
    result.setDate(result.getDate() + days);
    return result;
}

/**
 * Add weeks to a date
 * @param {Date} date - Starting date
 * @param {number} weeks - Number of weeks to add
 * @returns {Date} New date
 */
export function addWeeks(date, weeks) {
    return addDays(date, weeks * 7);
}

/**
 * Parse a date string in various formats
 * @param {string} dateString - Date string to parse
 * @returns {Date|null} Parsed date or null if invalid
 */
export function parseDate(dateString) {
    if (!dateString) return null;

    // Try ISO format first (YYYY-MM-DD)
    let date = new Date(dateString);
    if (!isNaN(date.getTime())) {
        return date;
    }

    // Try MM/DD/YYYY format
    const parts = dateString.split('/');
    if (parts.length === 3) {
        const month = parseInt(parts[0], 10) - 1;
        const day = parseInt(parts[1], 10);
        const year = parseInt(parts[2], 10);
        date = new Date(year, month, day);
        if (!isNaN(date.getTime())) {
            return date;
        }
    }

    return null;
}

/**
 * Get the week number of a date within a season
 * @param {Date} date - The date to check
 * @param {Date} seasonStart - Season start date
 * @returns {number} Week number (1-based)
 */
export function getWeekNumber(date, seasonStart) {
    const diffTime = date.getTime() - seasonStart.getTime();
    const diffDays = Math.floor(diffTime / (1000 * 60 * 60 * 24));
    return Math.floor(diffDays / 7) + 1;
}

/**
 * Check if two dates are the same day
 * @param {Date} date1 - First date
 * @param {Date} date2 - Second date
 * @returns {boolean} True if same day
 */
export function isSameDay(date1, date2) {
    return date1.getFullYear() === date2.getFullYear() &&
           date1.getMonth() === date2.getMonth() &&
           date1.getDate() === date2.getDate();
}

export default {
    getNextSunday,
    formatDate,
    formatDateISO,
    isSunday,
    addDays,
    addWeeks,
    parseDate,
    getWeekNumber,
    isSameDay
};
