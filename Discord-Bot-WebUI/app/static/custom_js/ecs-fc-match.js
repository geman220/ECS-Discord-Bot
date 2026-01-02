/**
 * ECS FC Match Details Module
 * Extracted from ecs_fc_match_details.html
 * Handles match editing and reminder sending
 */

import { InitSystem } from '../js/init-system.js';

(function() {
    'use strict';

    /**
     * Initialize ECS FC Match module
     */
    function init() {
        console.log('[ECSFCMatch] Initialized');
    }

    /**
     * Get CSRF token
     */
    function getCSRFToken() {
        const meta = document.querySelector('meta[name="csrf-token"]');
        return meta ? meta.getAttribute('content') : '';
    }

    /**
     * Edit match (placeholder)
     * @param {string|number} matchId - Match ID
     */
    function editMatch(matchId) {
        // In a real implementation, this would open a modal
        alert('Edit match functionality would go here');
    }

    /**
     * Send reminder to players
     * @param {string|number} matchId - Match ID
     */
    function sendReminder(matchId) {
        if (!confirm('Send RSVP reminder to all players who haven\'t responded?')) {
            return;
        }

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

    // Register with window.InitSystem
    window.InitSystem.register('ecs-fc-match', init, {
        priority: 30,
        description: 'ECS FC match details module'
    });

    // Fallback for non-module usage
    // window.InitSystem handles initialization

    // Expose module globally
    window.ECSFCMatch = {
        init: init,
        editMatch: editMatch,
        sendReminder: sendReminder
    };
})();
