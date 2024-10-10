// report_match.js

// Function to create player options grouped by team
function createPlayerOptions(matchId) {
    let options = '<option value="" selected>Select a player</option>';
    if (playerChoices[matchId]) {
        for (const teamName in playerChoices[matchId]) {
            options += `<optgroup label="${teamName}">`;
            for (const playerId in playerChoices[matchId][teamName]) {
                options += `<option value="${playerId}">${playerChoices[matchId][teamName][playerId]}</option>`;
            }
            options += `</optgroup>`;
        }
    }
    return options;
}

// Function to get the container ID based on event type
function getContainerId(eventType, matchId) {
    let containerId;
    if (eventType === 'goal_scorers') {
        containerId = 'goalScorersContainer-' + matchId;
    } else if (eventType === 'assist_providers') {
        containerId = 'assistProvidersContainer-' + matchId;
    } else if (eventType === 'yellow_cards') {
        containerId = 'yellowCardsContainer-' + matchId;
    } else if (eventType === 'red_cards') {
        containerId = 'redCardsContainer-' + matchId;
    }
    return containerId;
}

// Function to add a new event entry
function addEvent(matchId, containerId, statId = null, playerId = null, minute = null) {
    var containerSelector = '#' + containerId;

    // Generate a unique ID for the event if not provided
    var uniqueId = statId ? String(statId) : 'new-' + Date.now() + '-' + Math.random();

    // Get the base name for input fields
    var baseName = containerId.split('Container-')[0];

    // Define the new input group with appropriate naming conventions and data attributes
    var newInputGroup = `
        <div class="input-group mb-2 player-event-entry" data-unique-id="${uniqueId}">
            <input type="hidden" name="${baseName}-stat_id[]" value="${statId ? statId : ''}">
            <select class="form-select" name="${baseName}-player_id[]">
                ${createPlayerOptions(matchId)}
            </select>
            <input type="text" class="form-control" name="${baseName}-minute[]" 
                   placeholder="Minute (e.g., '45' or '45+2')" 
                   value="${minute ? minute : ''}"
                   pattern="^\\d{1,3}(\\+\\d{1,2})?$" 
                   title="Enter a valid minute (e.g., '45' or '45+2')">
            <button class="btn btn-danger" type="button" onclick="removeEvent(this)">Remove</button>
        </div>
    `;

    // Append the new input group to the container
    $(containerSelector).append(newInputGroup);

    // Set the selected player if provided
    if (playerId) {
        const lastAddedEntry = $(containerSelector).children().last();
        lastAddedEntry.find(`select[name="${baseName}-player_id[]"]`).val(playerId);
    }

    // Re-initialize Feather icons if necessary
    if (typeof feather !== 'undefined' && feather) {
        feather.replace();
    }

    console.log(`Added new event entry to ${containerId}:`, newInputGroup);
}

// Function to remove an event entry
function removeEvent(button) {
    const eventEntry = $(button).closest('.input-group');
    Swal.fire({
        title: 'Are you sure?',
        text: "Do you want to remove this event entry?",
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#d33',
        confirmButtonText: 'Yes, remove it!'
    }).then((result) => {
        if (result.isConfirmed) {
            eventEntry.remove();
            Swal.fire(
                'Removed!',
                'The event entry has been removed.',
                'success'
            );
        }
    });
}

// Define initialEvents as an object to store initial events per matchId
let initialEvents = {};

// Event handler for opening the modal and loading match data
$(document).on('click', '.edit-match-btn', function () {
    const matchId = $(this).data('match-id');
    console.log(`Fetching data for Match ID: ${matchId}`);

    if (!matchId) {
        console.error("Match ID is not defined!");
        return;
    }

    $.ajax({
        url: `/teams/report_match/${matchId}`,
        type: 'GET',
        success: function (response) {
            console.log(`Received response for Match ID: ${matchId}`, response);

            $('#home_team_score-' + matchId).val(response.home_team_score);
            $('#away_team_score-' + matchId).val(response.away_team_score);
            $('#match_notes-' + matchId).val(response.notes || '');
            $('#submitBtn-' + matchId).prop('disabled', false);

            // Update initialEvents per matchId
            initialEvents[matchId] = {
                goals: response.goal_scorers.map(goal => ({
                    unique_id: String(goal.id), // Convert to string
                    stat_id: String(goal.id),
                    player_id: String(goal.player_id),
                    minute: goal.minute || null
                })),
                assists: response.assist_providers.map(assist => ({
                    unique_id: String(assist.id),
                    stat_id: String(assist.id),
                    player_id: String(assist.player_id),
                    minute: assist.minute || null
                })),
                yellowCards: response.yellow_cards.map(card => ({
                    unique_id: String(card.id),
                    stat_id: String(card.id),
                    player_id: String(card.player_id),
                    minute: card.minute || null
                })),
                redCards: response.red_cards.map(card => ({
                    unique_id: String(card.id),
                    stat_id: String(card.id),
                    player_id: String(card.player_id),
                    minute: card.minute || null
                }))
            };

            // Clear existing entries
            $('#goalScorersContainer-' + matchId).empty();
            $('#assistProvidersContainer-' + matchId).empty();
            $('#yellowCardsContainer-' + matchId).empty();
            $('#redCardsContainer-' + matchId).empty();

            // Populate the modal with existing events
            response.goal_scorers.forEach(function (goal) {
                addEvent(matchId, 'goalScorersContainer-' + matchId, goal.id, goal.player_id, goal.minute);
                console.log(`Added goal scorer: Player ID ${goal.player_id}, Minute ${goal.minute}, Stat ID: ${goal.id}`);
            });

            response.assist_providers.forEach(function (assist) {
                addEvent(matchId, 'assistProvidersContainer-' + matchId, assist.id, assist.player_id, assist.minute);
                console.log(`Added assist provider: Player ID ${assist.player_id}, Minute ${assist.minute}, Stat ID: ${assist.id}`);
            });

            response.yellow_cards.forEach(function (yellow) {
                addEvent(matchId, 'yellowCardsContainer-' + matchId, yellow.id, yellow.player_id, yellow.minute);
                console.log(`Added yellow card: Player ID ${yellow.player_id}, Minute ${yellow.minute}, Stat ID: ${yellow.id}`);
            });

            response.red_cards.forEach(function (red) {
                addEvent(matchId, 'redCardsContainer-' + matchId, red.id, red.player_id, red.minute);
                console.log(`Added red card: Player ID ${red.player_id}, Minute ${red.minute}, Stat ID: ${red.id}`);
            });

            // Show the modal after populating it
            $('#reportMatchModal-' + matchId).modal('show');
        },
        error: function (xhr, status, error) {
            console.error(`Error fetching match data: ${error}`);
            Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to load match data. Please try again later.'
            });
        }
    });
});

// Attach submit handler using event delegation
$(document).on('submit', '.report-match-form', function (e) {
    e.preventDefault();
    e.stopPropagation();

    var matchId = $(this).data('match-id');

    // Check if initialEvents[matchId] is defined
    if (!initialEvents[matchId]) {
        Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'Match data is not loaded yet. Please try again.'
        });
        return;
    }

    let finalGoals = getFinalEvents(matchId, 'goal_scorers');
    let finalAssists = getFinalEvents(matchId, 'assist_providers');
    let finalYellowCards = getFinalEvents(matchId, 'yellow_cards');
    let finalRedCards = getFinalEvents(matchId, 'red_cards');

    let initialGoals = initialEvents[matchId].goals || [];
    let initialAssists = initialEvents[matchId].assists || [];
    let initialYellowCards = initialEvents[matchId].yellowCards || [];
    let initialRedCards = initialEvents[matchId].redCards || [];

    let goalsToAdd = finalGoals.filter(goal => !eventExists(goal, initialGoals));
    let goalsToRemove = initialGoals.filter(goal => !eventExists(goal, finalGoals));

    let assistsToAdd = finalAssists.filter(assist => !eventExists(assist, initialAssists));
    let assistsToRemove = initialAssists.filter(assist => !eventExists(assist, finalAssists));

    let yellowCardsToAdd = finalYellowCards.filter(card => !eventExists(card, initialYellowCards));
    let yellowCardsToRemove = initialYellowCards.filter(card => !eventExists(card, finalYellowCards));

    let redCardsToAdd = finalRedCards.filter(card => !eventExists(card, initialRedCards));
    let redCardsToRemove = initialRedCards.filter(card => !eventExists(card, finalRedCards));

    // Confirmation before submitting
    Swal.fire({
        title: 'Confirm Submission',
        text: "Are you sure you want to submit this match report?",
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: '#3085d6',
        cancelButtonColor: '#d33',
        confirmButtonText: 'Yes, submit it!'
    }).then((result) => {
        if (result.isConfirmed) {
            updateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove, yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove);
        }
    });
});

// Function to get final events from the form
function getFinalEvents(matchId, eventType) {
    let events = [];
    let containerId = getContainerId(eventType, matchId);
    let baseName = containerId.split('Container-')[0];

    $(`#${containerId}`).find('.player-event-entry').each(function () {
        let statId = $(this).find(`input[name="${baseName}-stat_id[]"]`).val();
        let playerId = $(this).find(`select[name="${baseName}-player_id[]"]`).val();
        let minute = $(this).find(`input[name="${baseName}-minute[]"]`).val();
        let uniqueId = $(this).attr('data-unique-id');

        // Convert values to strings or null
        statId = statId ? String(statId) : null;
        playerId = playerId ? String(playerId) : null;
        minute = minute ? String(minute) : null;

        // Add detailed debugging statements
        console.log('Event Entry:', {
            uniqueId: uniqueId,
            statId: statId,
            playerId: playerId,
            minute: minute
        });

        events.push({ unique_id: uniqueId, stat_id: statId, player_id: playerId, minute: minute });
    });
    return events;
}

// Function to check if an event exists in an array
function eventExists(event, eventsArray) {
    console.log('Comparing events:', {
        eventStatId: event.stat_id,
        arrayStatIds: eventsArray.map(e => e.stat_id),
        eventUniqueId: event.unique_id,
        arrayUniqueIds: eventsArray.map(e => e.unique_id)
    });

    if (event.stat_id) {
        // Compare based on stat_id for existing events
        return eventsArray.some(e => String(e.stat_id) === String(event.stat_id));
    } else {
        // Compare based on unique_id for new events
        return eventsArray.some(e => String(e.unique_id) === String(event.unique_id));
    }
}

// Function to send the AJAX request to update stats
function updateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove, yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove) {
    const homeTeamScore = $('#home_team_score-' + matchId).val();
    const awayTeamScore = $('#away_team_score-' + matchId).val();
    const notes = $('#match_notes-' + matchId).val();
    var csrfToken = $('input[name="csrf_token"]').val();

    // Log the data being sent
    console.log('Data being sent to server:', {
        home_team_score: homeTeamScore,
        away_team_score: awayTeamScore,
        notes: notes,
        goals_to_add: goalsToAdd,
        goals_to_remove: goalsToRemove,
        assists_to_add: assistsToAdd,
        assists_to_remove: assistsToRemove,
        yellow_cards_to_add: yellowCardsToAdd,
        yellow_cards_to_remove: yellowCardsToRemove,
        red_cards_to_add: redCardsToAdd,
        red_cards_to_remove: redCardsToRemove
    });

    $.ajax({
        url: `/teams/report_match/${matchId}`,
        method: 'POST',
        contentType: 'application/json',
        dataType: 'json',
        headers: {
            'X-CSRFToken': csrfToken
        },
        data: JSON.stringify({
            home_team_score: homeTeamScore,
            away_team_score: awayTeamScore,
            notes: notes,
            goals_to_add: goalsToAdd,
            goals_to_remove: goalsToRemove,
            assists_to_add: assistsToAdd,
            assists_to_remove: assistsToRemove,
            yellow_cards_to_add: yellowCardsToAdd,
            yellow_cards_to_remove: yellowCardsToRemove,
            red_cards_to_add: redCardsToAdd,
            red_cards_to_remove: redCardsToRemove
        }),
        beforeSend: function () {
            // Disable the submit button to prevent multiple submissions
            $(`#submitBtn-${matchId}`).prop('disabled', true);
            // Optionally, show a loading spinner
            Swal.fire({
                title: 'Submitting...',
                text: 'Please wait while your report is being submitted.',
                allowOutsideClick: false,
                didOpen: () => {
                    Swal.showLoading()
                }
            });
        },
        success: function (response) {
            if (response.success) {
                Swal.fire(
                    'Success!',
                    'Your match report has been submitted successfully.',
                    'success'
                ).then(() => {
                    // Optionally, close the modal
                    const modalElement = document.getElementById(`reportMatchModal-${matchId}`);
                    const modal = bootstrap.Modal.getInstance(modalElement);
                    modal.hide();

                    // Optionally, reload the page to reflect changes
                    location.reload();
                });
            } else {
                Swal.fire(
                    'Error!',
                    response.message || 'There was an error submitting your report.',
                    'error'
                ).then(() => {
                    // Re-enable the submit button
                    $(`#submitBtn-${matchId}`).prop('disabled', false);
                });
            }
        },
        error: function (xhr, status, error) {
            Swal.fire(
                'Error!',
                'An unexpected error occurred while submitting your report.',
                'error'
            ).then(() => {
                // Re-enable the submit button
                $(`#submitBtn-${matchId}`).prop('disabled', false);
            });
            console.error('AJAX Error:', error);
            console.error('Response:', xhr.responseText);
        }
    });
}
