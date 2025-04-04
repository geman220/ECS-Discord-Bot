document.addEventListener('DOMContentLoaded', function () {
    // Retrieve the values for playerId, discordId, and csrfToken from the DOM
    const rsvpDataElement = document.getElementById('rsvp-data');
    
    // Check if the element exists before proceeding
    if (!rsvpDataElement) {
        console.log('RSVP data element not found, RSVP functionality disabled');
        return; // Exit early if RSVP data is not available
    }
    
    const playerId = rsvpDataElement.getAttribute('data-player-id');
    const discordId = rsvpDataElement.getAttribute('data-discord-id');
    const csrfToken = rsvpDataElement.getAttribute('data-csrf-token');

    function submitRSVP(matchId, response) {
        fetch(`/rsvp/${matchId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken  // Include CSRF token
            },
            body: JSON.stringify({
                response: response,
                player_id: playerId,
                discord_id: discordId
            })
        })
            .then(response => {
                // Check if the response is ok (status in the range 200-299)
                if (!response.ok) {
                    throw new Error(`HTTP error ${response.status}`);
                }
                
                // For debugging, log the raw response text first
                return response.text().then(text => {
                    console.log('Raw response:', text);
                    try {
                        return JSON.parse(text);
                    } catch (e) {
                        console.error('JSON parse error:', e);
                        throw new Error('Invalid JSON response');
                    }
                });
            })
            .then(data => {
                if (data.success) {
                    console.log('RSVP updated successfully');
                    // Show success message
                    Swal.fire({
                        icon: 'success',
                        title: 'RSVP Updated',
                        text: 'Your RSVP status has been updated!',
                        toast: true,
                        position: 'top-end',
                        showConfirmButton: false,
                        timer: 3000
                    });
                    
                    // If we're on the match details page, reload to show the updated status
                    if (window.location.pathname.includes('/matches/')) {
                        setTimeout(() => window.location.reload(), 1000);
                    }
                } else {
                    console.error('Failed to update RSVP:', data.message);
                    Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: data.message || 'Failed to update RSVP',
                        toast: true,
                        position: 'top-end',
                        showConfirmButton: false,
                        timer: 3000
                    });
                }
            })
            .catch(error => {
                console.error('Error updating RSVP:', error);
                // Show error message to user
                Swal.fire({
                    icon: 'error',
                    title: 'RSVP Error',
                    text: `Could not update your RSVP: ${error.message}`,
                    toast: true,
                    position: 'top-end',
                    showConfirmButton: false,
                    timer: 5000
                });
            });
    }

    // Track the last selected response to allow "unclick" behavior
    const lastSelected = {};

    // Attach event listeners for RSVP radio buttons
    document.querySelectorAll('.btn-check.rsvp-input').forEach(function (element) {
        element.addEventListener('click', function (event) {
            const matchId = event.target.name.split('-')[1];  // Extract match ID from name attribute
            const response = event.target.value;

            if (lastSelected[matchId] === response) {
                // If the same option is clicked twice, uncheck it and reset to "no response"
                event.target.checked = false;
                submitRSVP(matchId, 'no_response');
                lastSelected[matchId] = null;
            } else {
                // Otherwise, submit the selected response
                submitRSVP(matchId, response);
                lastSelected[matchId] = response;
            }
        });
    });

    // Load and set the existing RSVP values when the page loads
    function setInitialRSVPs() {
        try {
            // Get all form inputs and extract unique match IDs
            const inputs = document.querySelectorAll('.btn-check.rsvp-input');
            if (!inputs || inputs.length === 0) {
                console.log('No RSVP inputs found on page');
                return;
            }
            
            // Extract match IDs, filtering out undefined or empty values
            const matchIds = [...new Set(
                [...inputs]
                .map(input => {
                    const parts = input.name ? input.name.split('-') : [];
                    return parts.length > 1 ? parts[1] : null;
                })
                .filter(id => id && id !== 'undefined' && id.trim() !== '')
            )];
            
            console.log(`Found ${matchIds.length} matches for RSVP status loading`);
            
            // For each valid match ID, fetch the status
            matchIds.forEach(matchId => {
                if (!matchId || matchId === 'undefined') {
                    console.warn('Invalid match ID for RSVP status fetch');
                    return;
                }
                
                fetch(`/rsvp/status/${matchId}`, {
                    method: 'GET',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken  // Include CSRF token
                    }
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error ${response.status}`);
                    }
                    return response.text().then(text => {
                        console.log(`Raw status response for match ${matchId}:`, text);
                        try {
                            return JSON.parse(text);
                        } catch (e) {
                            console.error(`JSON parse error for match ${matchId}:`, e);
                            throw new Error('Invalid JSON response');
                        }
                    });
                })
                .then(data => {
                    if (data && data.response) {
                        const radioButton = document.querySelector(`input[name="response-${matchId}"][value="${data.response}"]`);
                        if (radioButton) {
                            radioButton.checked = true;
                            lastSelected[matchId] = data.response;
                        }
                    }
                })
                .catch(error => {
                    console.log(`Could not load RSVP status for match ${matchId}: ${error.message}`);
                });
            });
        } catch (error) {
            console.error('Error in setInitialRSVPs:', error);
        }
    }

    // Call the function to set the initial RSVP statuses
    setInitialRSVPs();
});
