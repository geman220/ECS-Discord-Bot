'use strict';

/**
 * ECS FC Match Details Module
 * Extracted from ecs_fc_match_details.html
 * Handles match editing and reminder sending
 * @module ecs-fc-match
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Initialize ECS FC Match module
 */
export function init() {
    console.log('[ECSFCMatch] Initialized');
}

// getCSRFToken is provided globally by csrf-fetch.js
const getCSRFToken = () => window.getCSRFToken ? window.getCSRFToken() : '';

/**
 * Edit match - delegates to report_match.js handleEditButtonClick
 * @param {string|number} matchId - Match ID
 */
export function editMatch(matchId) {
    // Delegate to report_match.js handler
    if (typeof window.handleEditButtonClick === 'function') {
        window.handleEditButtonClick(matchId);
    } else {
        console.error('[ECSFCMatch] handleEditButtonClick not found. Ensure report_match.js is loaded.');
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Match editing is not available. Please refresh the page.'
            });
        } else {
            alert('Match editing is not available. Please refresh the page.');
        }
    }
}

/**
 * Send reminder to players
 * @param {string|number} matchId - Match ID
 */
export function sendReminder(matchId) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Send Reminder',
            text: 'Send RSVP reminder to all players who haven\'t responded?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#3085d6',
            cancelButtonColor: '#d33',
            confirmButtonText: 'Yes, send it!'
        }).then((result) => {
            if (result.isConfirmed) {
                performSendReminder(matchId);
            }
        });
    }
}

/**
 * Perform the actual reminder sending
 * @param {string|number} matchId - Match ID
 */
function performSendReminder(matchId) {
    fetch(`/api/ecs-fc/matches/${matchId}/remind`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Reminder Sent!',
                    text: data.message,
                    timer: 3000
                });
            } else {
                alert('Reminder sent successfully!');
            }
        } else {
            throw new Error(data.message);
        }
    })
    .catch(error => {
        console.error('[ECSFCMatch] Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: error.message || 'Failed to send reminder'
            });
        } else {
            alert('Error: ' + (error.message || 'Failed to send reminder'));
        }
    });
}

// Event delegation
document.addEventListener('click', function(e) {
    const target = e.target.closest('[data-action]');
    if (!target) return;

    const action = target.dataset.action;

    switch(action) {
        case 'edit-match':
            editMatch(target.dataset.matchId);
            break;
        case 'send-reminder':
            sendReminder(target.dataset.matchId);
            break;
    }
});

// Register with InitSystem
if (typeof InitSystem !== 'undefined' && InitSystem.register) {
    InitSystem.register('ecs-fc-match', init, {
        priority: 30,
        description: 'ECS FC match details module'
    });
} else if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('ecs-fc-match', init, {
        priority: 30,
        description: 'ECS FC match details module'
    });
}

// Window exports for backward compatibility
window.ECSFCMatch = {
    init: init,
    editMatch: editMatch,
    sendReminder: sendReminder
};
