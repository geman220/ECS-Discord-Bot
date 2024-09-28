document.addEventListener('DOMContentLoaded', function () {
    // Retrieve the values for playerId, discordId, and csrfToken from the DOM
    const rsvpDataElement = document.getElementById('rsvp-data');
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
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('RSVP updated successfully');
                    // Optionally, display a success message to the user
                } else {
                    console.error('Failed to update RSVP:', data.message);
                    // Optionally, display an error message to the user
                }
            })
            .catch(error => {
                console.error('Error:', error);
            });
    }

    // Track the last selected response to allow "unclick" behavior
    const lastSelected = {};

    // Attach event listeners for RSVP radio buttons
    document.querySelectorAll('.form-check-input').forEach(function (element) {
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
        const matchIds = [...new Set([...document.querySelectorAll('.form-check-input')].map(input => input.name.split('-')[1]))];

        matchIds.forEach(matchId => {
            fetch(`/rsvp/status/${matchId}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken  // Include CSRF token
                }
            })
                .then(response => response.json())
                .then(data => {
                    if (data.response) {
                        const radioButton = document.querySelector(`input[name="response-${matchId}"][value="${data.response}"]`);
                        if (radioButton) {
                            radioButton.checked = true;
                            lastSelected[matchId] = data.response;
                        }
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                });
        });
    }

    // Call the function to set the initial RSVP statuses
    setInitialRSVPs();
});
