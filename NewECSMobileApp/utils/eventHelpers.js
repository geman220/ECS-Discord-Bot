// utils/eventHelpers.js

import { argonTheme } from '../constants';

const getEventIcon = (eventType) => {
    switch (eventType) {
        case 'GOAL':
            return 'futbol'; // Valid FontAwesome5 icon
        case 'ASSIST':
            return 'hands-helping';
        case 'YELLOW_CARD':
            return 'square';
        case 'RED_CARD':
            return 'square';
        case 'SUBSTITUTION':
            return 'exchange-alt';
        case 'INJURY':
            return 'medkit';
        default:
            return 'circle';
    }
};

const getEventIconFamily = (eventType) => {
    switch (eventType) {
        case 'GOAL':
            return 'FontAwesome5'; // Updated to FontAwesome5
        case 'ASSIST':
            return 'FontAwesome5';
        case 'YELLOW_CARD':
        case 'RED_CARD':
            return 'FontAwesome';
        case 'SUBSTITUTION':
        case 'INJURY':
            return 'FontAwesome5';
        default:
            return 'FontAwesome';
    }
};

const getEventColor = (eventType) => {
    switch (eventType) {
        case 'GOAL':
            return argonTheme.COLORS.SUCCESS;
        case 'ASSIST':
            return argonTheme.COLORS.INFO;
        case 'YELLOW_CARD':
            return argonTheme.COLORS.WARNING;
        case 'RED_CARD':
            return argonTheme.COLORS.ERROR;
        case 'SUBSTITUTION':
            return argonTheme.COLORS.PRIMARY;
        case 'INJURY':
            return argonTheme.COLORS.MUTED;
        default:
            return argonTheme.COLORS.DEFAULT;
    }
};

const getRSVPColor = (status) => {
    switch (status) {
        case 'yes': return argonTheme.COLORS.SUCCESS;
        case 'no': return argonTheme.COLORS.ERROR;
        case 'maybe': return argonTheme.COLORS.WARNING;
        default: return argonTheme.COLORS.MUTED;
    }
};

export { getEventIcon, getEventIconFamily, getEventColor, getRSVPColor };
