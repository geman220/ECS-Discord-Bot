'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

/**
 * Generate unique operation ID for idempotency
 */
export function generateOperationId() {
    return 'web_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
}

// Track the last selected response to allow "unclick" behavior
const lastSelected = {};

// Flag to suppress submit during programmatic initialization
let _settingInitialValues = false;

// Current operation ID for retry logic
let currentOperationId = null;

/**
 * Submit RSVP for a match
 * @param {string} matchId - Match ID
 * @param {string} response - RSVP response
 * @param {string} csrfToken - CSRF token
 * @param {string} discordId - Discord ID
 * @param {number} retryCount - Retry count
 */
function submitRSVP(matchId, response, csrfToken, discordId, retryCount = 0) {
    // Use same operation ID for retries to ensure idempotency
    const operationId = currentOperationId || generateOperationId();
    currentOperationId = operationId;

    fetch(`/api/v2/rsvp/update`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify({
            match_id: parseInt(matchId),
            availability: response,
            operation_id: operationId,
            source: 'web',
            discord_id: discordId
        })
    })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error ${response.status}`);
            }

            return response.text().then(text => {
                try {
                    return JSON.parse(text);
                } catch (e) {
                    throw new Error('Invalid JSON response');
                }
            });
        })
        .then(data => {
            // Clear operation ID on success
            currentOperationId = null;

            if (data.message && data.match_id) {
                window.Swal.fire({
                    icon: 'success',
                    title: 'RSVP Updated',
                    text: data.message || 'Your RSVP status has been updated!',
                    toast: true,
                    position: 'top-end',
                    showConfirmButton: false,
                    timer: 3000
                });

                if (window.location.pathname.includes('/matches/')) {
                    setTimeout(() => window.location.reload(), 1000);
                }
            } else if (data.error) {
                throw new Error(data.error);
            } else {
                if (data.success) {
                    window.Swal.fire({
                        icon: 'success',
                        title: 'RSVP Updated',
                        text: 'Your RSVP status has been updated!',
                        toast: true,
                        position: 'top-end',
                        showConfirmButton: false,
                        timer: 3000
                    });

                    if (window.location.pathname.includes('/matches/')) {
                        setTimeout(() => window.location.reload(), 1000);
                    }
                } else {
                    throw new Error(data.message || 'Failed to update RSVP');
                }
            }
        })
        .catch(error => {
            const maxRetries = 2;
            if (retryCount < maxRetries &&
                (error.message.includes('HTTP error 5') || error.message.includes('NetworkError'))) {

                setTimeout(() => {
                    console.log(`Retrying RSVP update (attempt ${retryCount + 1}/${maxRetries})`);
                    submitRSVP(matchId, response, csrfToken, discordId, retryCount + 1);
                }, Math.pow(2, retryCount) * 1000);

                return;
            }

            currentOperationId = null;

            window.Swal.fire({
                icon: 'error',
                title: 'RSVP Error',
                text: `Could not update your RSVP: ${error.message}`,
                toast: true,
                position: 'top-end',
                showConfirmButton: true,
                confirmButtonText: 'Retry',
                timer: 8000
            }).then((result) => {
                if (result.isConfirmed) {
                    currentOperationId = null;
                    submitRSVP(matchId, response, csrfToken, discordId, 0);
                }
            });
        });
}

/**
 * Set initial RSVP values from server
 * @param {string} csrfToken - CSRF token
 */
export function setInitialRSVPs(csrfToken) {
    try {
        const inputs = document.querySelectorAll('.rsvp-input');
        if (!inputs || inputs.length === 0) {
            return;
        }

        const matchIds = [...new Set(
            [...inputs]
            .map(input => {
                const parts = input.name ? input.name.split('-') : [];
                return parts.length > 1 ? parts[1] : null;
            })
            .filter(id => id && id !== 'undefined' && id.trim() !== '')
        )];

        matchIds.forEach(matchId => {
            if (!matchId || matchId === 'undefined') {
                return;
            }

            fetch(`/rsvp/status/${matchId}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            })
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error ${response.status}`);
                }
                return response.text().then(text => {
                    try {
                        return JSON.parse(text);
                    } catch (e) {
                        throw new Error('Invalid JSON response');
                    }
                });
            })
            .then(data => {
                if (data && data.response) {
                    const radioButton = document.querySelector(`input[name="response-${matchId}"][value="${data.response}"]`);
                    if (radioButton) {
                        radioButton.checked = true;
                        _settingInitialValues = true;
                        radioButton.dispatchEvent(new Event('change', { bubbles: true }));
                        _settingInitialValues = false;
                        lastSelected[matchId] = data.response;
                    }
                }
            })
            .catch(error => {
                // Silently fail for status checks
            });
        });
    } catch (error) {
        // Silently fail
    }
}

/**
 * Initialize RSVP functionality
 */
export function initRsvp() {
    if (_initialized) return;

    const rsvpDataElement = document.getElementById('rsvp-data');

    if (!rsvpDataElement) {
        return;
    }

    _initialized = true;

    const playerId = rsvpDataElement.getAttribute('data-player-id');
    const discordId = rsvpDataElement.getAttribute('data-discord-id');
    const csrfToken = rsvpDataElement.getAttribute('data-csrf-token');

    // Attach event listeners for RSVP radio buttons using event delegation
    document.addEventListener('change', function(event) {
        const element = event.target;
        if (!element || !element.classList.contains('rsvp-input')) return;
        if (_settingInitialValues) return;

        const matchId = element.name.split('-')[1];
        const response = element.value;

        if (lastSelected[matchId] === response) {
            element.checked = false;
            submitRSVP(matchId, 'no_response', csrfToken, discordId);
            lastSelected[matchId] = null;
        } else {
            submitRSVP(matchId, response, csrfToken, discordId);
            lastSelected[matchId] = response;
        }
    });

    // Load initial RSVP values
    setInitialRSVPs(csrfToken);

    // Set up real-time RSVP updates via WebSocket
    _setupRealtimeRsvpUpdates(playerId);
}

/**
 * Set up WebSocket listeners for real-time RSVP updates from other sources
 * (Discord, mobile app, other browser sessions)
 * @param {string} playerId - Current user's player ID
 */
function _setupRealtimeRsvpUpdates(playerId) {
    if (!window.SocketManager) return;

    const matchIds = _getMatchIdsFromDom();
    if (matchIds.length === 0) return;

    // Join match rooms and listen for updates once connected
    window.SocketManager.onConnect('rsvp-realtime', (socket) => {
        // Join each match room so we receive rsvp_update events
        matchIds.forEach(matchId => {
            socket.emit('join_match_rsvp', { match_id: parseInt(matchId) });
        });
    });

    // Listen for rsvp_update events
    window.SocketManager.on('rsvp-realtime', 'rsvp_update', (data) => {
        if (!data || !data.match_id) return;

        const matchId = String(data.match_id);

        // Only update the radio button if this is about the current user
        if (String(data.player_id) === String(playerId)) {
            const availability = data.availability || data.response || 'no_response';
            _updateRsvpRadioButton(matchId, availability);
        }
    });
}

/**
 * Get all match IDs from RSVP radio buttons in the DOM
 * @returns {string[]}
 */
function _getMatchIdsFromDom() {
    const inputs = document.querySelectorAll('.rsvp-input');
    return [...new Set(
        [...inputs]
        .map(input => {
            const parts = input.name ? input.name.split('-') : [];
            return parts.length > 1 ? parts[1] : null;
        })
        .filter(id => id && id !== 'undefined' && id.trim() !== '')
    )];
}

/**
 * Update RSVP radio button visual state for a match
 * @param {string} matchId
 * @param {string} availability - 'yes', 'no', 'maybe', or 'no_response'
 */
function _updateRsvpRadioButton(matchId, availability) {
    // Uncheck all radio buttons for this match first
    const allInputs = document.querySelectorAll(`input[name="response-${matchId}"]`);
    allInputs.forEach(input => { input.checked = false; });

    if (availability && availability !== 'no_response') {
        const radioButton = document.querySelector(`input[name="response-${matchId}"][value="${availability}"]`);
        if (radioButton) {
            _settingInitialValues = true;
            radioButton.checked = true;
            radioButton.dispatchEvent(new Event('change', { bubbles: true }));
            _settingInitialValues = false;
            lastSelected[matchId] = availability;
        }
    } else {
        lastSelected[matchId] = null;
    }
}

// Register with window.InitSystem (primary)
if (true && window.InitSystem.register) {
    window.InitSystem.register('rsvp', initRsvp, {
        priority: 50,
        reinitializable: true,
        description: 'RSVP functionality'
    });
}

// Fallback
// window.InitSystem handles initialization

// No window exports needed - InitSystem handles initialization
