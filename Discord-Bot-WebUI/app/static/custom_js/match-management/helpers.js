'use strict';

/**
 * Match Management Helpers
 * Formatting and status helper functions
 * @module match-management/helpers
 */

/**
 * Get status color class
 * @param {string} status
 * @returns {string}
 */
export function getStatusColor(status) {
    const statusColors = {
        'PENDING': 'warning',
        'STARTED': 'info',
        'SUCCESS': 'success',
        'FAILURE': 'danger',
        'RETRY': 'warning',
        'REVOKED': 'secondary',
        'RUNNING': 'info',
        'FINISHED': 'success',
        'MISSING': 'danger',
        'Completed': 'success',
        'Scheduled': 'warning',
        'Active': 'info',
        'Issue': 'danger'
    };
    return statusColors[status] || 'secondary';
}

/**
 * Get status icon class
 * @param {string} status
 * @returns {string}
 */
export function getStatusIcon(status) {
    const statusIcons = {
        'PENDING': 'fa-clock',
        'STARTED': 'fa-play',
        'SUCCESS': 'fa-check',
        'FAILURE': 'fa-times',
        'RETRY': 'fa-redo',
        'REVOKED': 'fa-ban',
        'RUNNING': 'fa-play',
        'FINISHED': 'fa-check',
        'MISSING': 'fa-exclamation-triangle',
        'Completed': 'fa-check',
        'Scheduled': 'fa-clock',
        'Active': 'fa-play',
        'Issue': 'fa-exclamation-triangle'
    };
    return statusIcons[status] || 'fa-question';
}

/**
 * Format duration from seconds
 * @param {number} seconds
 * @returns {string}
 */
export function formatDuration(seconds) {
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    if (minutes < 60) return `${minutes}m ${remainingSeconds}s`;
    const hours = Math.floor(minutes / 60);
    const remainingMinutes = minutes % 60;
    return `${hours}h ${remainingMinutes}m`;
}

/**
 * Format task ETA
 * @param {string} etaString
 * @returns {string}
 */
export function formatTaskETA(etaString) {
    if (!etaString) return 'Unknown';

    try {
        const etaDate = new Date(etaString);
        const now = new Date();
        const diff = etaDate - now;

        if (diff > 0) {
            const minutes = Math.floor(diff / (1000 * 60));
            const hours = Math.floor(minutes / 60);

            if (hours > 0) {
                return `${hours}h ${minutes % 60}m`;
            } else {
                return `${minutes}m`;
            }
        } else {
            return 'Now';
        }
    } catch (e) {
        return 'Invalid';
    }
}

/**
 * Format TTL
 * @param {number} seconds
 * @returns {string}
 */
export function formatTTL(seconds) {
    if (!seconds || seconds <= 0) return 'No limit';

    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);

    if (hours > 0) {
        return `${hours}h ${minutes}m`;
    } else if (minutes > 0) {
        return `${minutes}m`;
    } else {
        return `${seconds}s`;
    }
}

/**
 * Format scheduled time
 * @param {string} isoString
 * @returns {string}
 */
export function formatScheduledTime(isoString) {
    if (!isoString) return 'Unknown';

    try {
        const date = new Date(isoString);
        const now = new Date();
        const diff = date - now;

        if (diff > 0) {
            const hours = Math.floor(diff / (1000 * 60 * 60));
            const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));

            if (hours > 24) {
                const days = Math.floor(hours / 24);
                const remainingHours = hours % 24;
                return `${days}d ${remainingHours}h`;
            } else if (hours > 0) {
                return `${hours}h ${minutes}m`;
            } else {
                return `${minutes}m`;
            }
        } else {
            return 'Overdue';
        }
    } catch (e) {
        return 'Invalid';
    }
}

/**
 * Format all scheduled time elements on page
 */
export function formatScheduledTimes() {
    document.querySelectorAll('[data-time][data-component="scheduled-time"]').forEach(element => {
        const isoTime = element.getAttribute('data-time');
        element.textContent = formatScheduledTime(isoTime);
    });
}

/**
 * Get schedule status color
 * @param {string} status
 * @returns {string}
 */
export function getScheduleStatusColor(status) {
    const colors = {
        'not_started': 'secondary',
        'scheduled': 'warning',
        'running': 'success',
        'completed': 'info',
        'stopped': 'danger',
        'failed': 'danger'
    };
    return colors[status] || 'secondary';
}

/**
 * Get schedule status icon
 * @param {string} status
 * @returns {string}
 */
export function getScheduleStatusIcon(status) {
    const icons = {
        'not_started': 'fa-circle',
        'scheduled': 'fa-clock',
        'running': 'fa-play-circle',
        'completed': 'fa-check-circle',
        'stopped': 'fa-stop-circle',
        'failed': 'fa-exclamation-triangle'
    };
    return icons[status] || 'fa-circle';
}

/**
 * Get status display text
 * @param {string} status
 * @returns {string}
 */
export function getStatusDisplay(status) {
    const displays = {
        'not_started': 'Not Started',
        'scheduled': 'Scheduled',
        'running': 'Running',
        'completed': 'Completed',
        'stopped': 'Stopped',
        'failed': 'Failed'
    };
    return displays[status] || status;
}

/**
 * Get task status color
 * @param {string} status
 * @returns {string}
 */
export function getTaskStatusColor(status) {
    const colors = {
        'PENDING': 'warning',
        'STARTED': 'info',
        'RETRY': 'warning',
        'FAILURE': 'danger',
        'SUCCESS': 'success'
    };
    return colors[status] || 'secondary';
}
