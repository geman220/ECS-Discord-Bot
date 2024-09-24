// report_match.js

// Assuming playerChoices and initialEvents are defined elsewhere and contain the necessary data.

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
    if (!matchId) {
        console.error("Match ID is undefined!");
        return '';
    }
    switch (eventType) {
        case 'goal_scorers':
            return `goalScorersContainer-${matchId}`;
        case 'assist_providers':
            return `assistProvidersContainer-${matchId}`;
        case 'yellow_cards':
            return `yellowCardsContainer-${matchId}`;
        case 'red_cards':
            return `redCardsContainer-${matchId}`;
        default:
            return '';
    }
}

// Function to add a new event entry
function addEvent(matchId, eventType, statId = null) {
    var container = $('#' + getContainerId(eventType, matchId));
    if (!container.length) {
        console.error(`Container not found for event type: ${eventType} and match ID: ${matchId}`);
        return;
    }

    // Generate a unique ID for the event
    var uniqueId = statId ? String(statId) : 'new-' + Date.now() + '-' + Math.random();

    var dataStatId = `data-stat-id="${statId || ''}"`;
    var dataUniqueId = `data-unique-id="${uniqueId}"`;

    var playerOptions = createPlayerOptions(matchId);

    var newForm = `
        <div class="player-event-entry mb-2" data-stat-id="${statId || ''}" data-unique-id="${uniqueId}">
            <input type="hidden" name="${eventType}-${uniqueId}-stat_id" value="${statId || ''}">
            <div class="row">
                <div class="col-md-6">
                    <label class="form-label">Player</label>
                    <select name="${eventType}-${uniqueId}-player_id" class="form-select" required>
                        ${playerOptions}
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="form-label">Minute (Optional)</label>
                    <input type="number" name="${eventType}-${uniqueId}-minute" class="form-control" placeholder="Minute (Optional)">
                </div>
                <div class="col-md-2 d-flex align-items-end">
                    <button type="button" class="btn btn-danger btn-sm remove-event-button">
                        <i class="ti ti-trash"></i> Remove
                    </button>
                </div>
            </div>
        </div>`;

    container.append(newForm);
    console.log(`Added new event entry for Match ID: ${matchId}, Event Type: ${eventType}, Stat ID: ${statId}, Unique ID: ${uniqueId}`);
}

// Function to remove an event entry
function removeEvent(button) {
    const eventEntry = $(button).closest('.player-event-entry');
    if (!confirm("Are you sure you want to remove this event?")) {
        return;
    }
    eventEntry.remove();
}

$(document).on('click', '.remove-event-button', function () {
    removeEvent(this);
});

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
                addEvent(matchId, 'goal_scorers', goal.id); // Pass statId
                const lastAddedEntry = $('#goalScorersContainer-' + matchId).children().last();
                lastAddedEntry.find(`select[name^="goal_scorers-"][name$="-player_id"]`).val(goal.player_id);
                lastAddedEntry.find(`input[type="number"][name^="goal_scorers-"][name$="-minute"]`).val(goal.minute);
                console.log(`Added goal scorer: Player ID ${goal.player_id}, Minute ${goal.minute}, Stat ID: ${goal.id}`);
            });

            response.assist_providers.forEach(function (assist) {
                addEvent(matchId, 'assist_providers', assist.id); // Pass statId
                const lastAddedEntry = $('#assistProvidersContainer-' + matchId).children().last();
                lastAddedEntry.find(`select[name^="assist_providers-"]`).val(assist.player_id);
                lastAddedEntry.find(`input[name^="assist_providers-"]`).val(assist.minute);
                console.log(`Added assist provider: Player ID ${assist.player_id}, Minute ${assist.minute}, Stat ID: ${assist.id}`);
            });

            response.yellow_cards.forEach(function (yellow) {
                addEvent(matchId, 'yellow_cards', yellow.id); // Pass statId
                const lastAddedEntry = $('#yellowCardsContainer-' + matchId).children().last();
                lastAddedEntry.find(`select[name^="yellow_cards-"]`).val(yellow.player_id);
                lastAddedEntry.find(`input[name^="yellow_cards-"]`).val(yellow.minute);
                console.log(`Added yellow card: Player ID ${yellow.player_id}, Minute ${yellow.minute}, Stat ID: ${yellow.id}`);
            });

            response.red_cards.forEach(function (red) {
                addEvent(matchId, 'red_cards', red.id); // Pass statId
                const lastAddedEntry = $('#redCardsContainer-' + matchId).children().last();
                lastAddedEntry.find(`select[name^="red_cards-"]`).val(red.player_id);
                lastAddedEntry.find(`input[name^="red_cards-"]`).val(red.minute);
                console.log(`Added red card: Player ID ${red.player_id}, Minute ${red.minute}, Stat ID: ${red.id}`);
            });

            $('#reportMatchModal-' + matchId).modal('show');
        },
        error: function (xhr, status, error) {
            console.error(`Error fetching match data: ${error}`);
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
        alert('Match data is not loaded yet. Please try again.');
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

    updateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove, yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove);
});

// Function to get final events from the form
function getFinalEvents(matchId, eventType) {
    let events = [];
    let containerId = getContainerId(eventType, matchId);
    $(`#${containerId}`).find('.player-event-entry').each(function () {
        let statId = $(this).find('input[type="hidden"][name$="-stat_id"]').val() || null;
        let playerId = $(this).find('select[name$="-player_id"]').val();
        let minuteInput = $(this).find('input[name$="-minute"]').val();
        let minute = minuteInput !== '' ? minuteInput : null;

        // Get the unique_id and convert to string
        let uniqueId = $(this).attr('data-unique-id');

        // Convert statId and playerId to strings
        statId = statId ? String(statId) : null;
        playerId = playerId ? String(playerId) : null;

        // Add debugging statements
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
        arrayStatId: eventsArray.map(e => e.stat_id),
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
    var csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

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
        dataType: 'json',  // Expect JSON response
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
        success: function (response) {
            if (response.success) {
                alert('Match report updated successfully.');
                location.reload();
            } else {
                alert(`Failed to update match report: ${response.message || 'Unknown error.'}`);
            }
        },
        error: function (xhr, status, error) {
            alert('Error updating match report.');
            console.error('AJAX Error:', error);
            console.error('Response:', xhr.responseText);
        }
    });
}
