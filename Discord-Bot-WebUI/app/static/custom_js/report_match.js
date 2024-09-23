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
        return '';  // Prevent undefined IDs
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
            return '';  // Handle any unexpected event types
    }
}

// Function to add a new event entry
function addEvent(matchId, eventType, statId = null) {
    var container = $('#' + getContainerId(eventType, matchId));
    if (!container.length) {
        console.error(`Container not found for event type: ${eventType} and match ID: ${matchId}`);
        return;
    }
    var index = container.children().length;
    var playerOptions = createPlayerOptions(matchId);

    var dataStatId = statId ? `data-stat-id="${statId}"` : '';

    var newForm = `
        <div class="player-event-entry mb-2" ${dataStatId}>
            <div class="row">
                <div class="col-md-6">
                    <label class="form-label">Player</label>
                    <select name="${eventType}-${index}-player_id" class="form-select" required>
                        ${playerOptions}
                    </select>
                </div>
                <div class="col-md-4">
                    <label class="form-label">Minute</label>
                    <input type="number" name="${eventType}-${index}-minute" class="form-control" required>
                </div>
                <div class="col-md-2 d-flex align-items-end">
                    <button type="button" class="btn btn-danger btn-sm remove-event-button">
                        <i class="ti ti-trash"></i> Remove
                    </button>
                </div>
            </div>
        </div>`;

    container.append(newForm);
    console.log(`Added new event entry for Match ID: ${matchId}, Event Type: ${eventType}, Stat ID: ${statId}`);
}

function removeEvent(button, statId) {
    if (!statId) {
        console.error("Stat ID is undefined!");
        return;
    }

    const eventEntry = button.closest('.player-event-entry');

    if (!confirm("Are you sure you want to remove this event?")) {
        return;
    }

    const csrfToken = $('input[name="csrf_token"]').val();

    $.ajax({
        url: `/players/remove_match_stat/${statId}`,
        type: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        },
        success: function (response) {
            if (response.success) {
                eventEntry.remove();
                alert('Event removed successfully!');
            } else {
                alert('Failed to remove event.');
            }
        },
        error: function (xhr, status, error) {
            console.error(`Error removing event: ${error}`);
            alert('Error removing event. Please try again.');
        }
    });
}

$(document).on('click', '.remove-event-button', function () {
    const button = $(this);
    const eventEntry = button.closest('.player-event-entry');
    let statId = eventEntry.data('stat-id');

    removeEvent(button, statId);
});

let initialEvents = {
    goals: [],
    assists: [],
    yellowCards: [],
    redCards: []
};

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
            console.log(`Home Team Score: ${response.home_team_score}, Away Team Score: ${response.away_team_score}`);

            initialEvents.goals = response.goal_scorers.map(goal => ({ stat_id: goal.id, player_id: goal.player_id, minute: goal.minute }));
            initialEvents.assists = response.assist_providers.map(assist => ({ stat_id: assist.id, player_id: assist.player_id, minute: assist.minute }));
            initialEvents.yellowCards = response.yellow_cards.map(card => ({ stat_id: card.id, player_id: card.player_id, minute: card.minute }));
            initialEvents.redCards = response.red_cards.map(card => ({ stat_id: card.id, player_id: card.player_id, minute: card.minute }));

            $('#goalScorersContainer-' + matchId).empty();
            $('#assistProvidersContainer-' + matchId).empty();
            $('#yellowCardsContainer-' + matchId).empty();
            $('#redCardsContainer-' + matchId).empty();

            response.goal_scorers.forEach(function (goal) {
                addEvent(matchId, 'goal_scorers', goal.id); // Pass statId
                const lastAddedEntry = $('#goalScorersContainer-' + matchId).children().last();
                lastAddedEntry.find(`select[name^="goal_scorers-"]`).val(goal.player_id);
                lastAddedEntry.find(`input[name^="goal_scorers-"]`).val(goal.minute);
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
$('#reportMatchForm').submit(function (e) {
    e.preventDefault();

    const matchId = $(this).data('match-id');

    let finalGoals = getFinalEvents(matchId, 'goal_scorers');
    let finalAssists = getFinalEvents(matchId, 'assist_providers');
    let finalYellowCards = getFinalEvents(matchId, 'yellow_cards');
    let finalRedCards = getFinalEvents(matchId, 'red_cards');

    let goalsToAdd = finalGoals.filter(goal => !eventExists(goal, initialEvents.goals));
    let goalsToRemove = initialEvents.goals.filter(goal => !eventExists(goal, finalGoals));

    let assistsToAdd = finalAssists.filter(assist => !eventExists(assist, initialEvents.assists));
    let assistsToRemove = initialEvents.assists.filter(assist => !eventExists(assist, finalAssists));

    let yellowCardsToAdd = finalYellowCards.filter(card => !eventExists(card, initialEvents.yellowCards));
    let yellowCardsToRemove = initialEvents.yellowCards.filter(card => !eventExists(card, finalYellowCards));

    let redCardsToAdd = finalRedCards.filter(card => !eventExists(card, initialEvents.redCards));
    let redCardsToRemove = initialEvents.redCards.filter(card => !eventExists(card, finalRedCards));

    updateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove, yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove);
});
function getFinalEvents(matchId, type) {
    let events = [];
    $(`#${type}Container-${matchId}`).find('.player-event-entry').each(function () {
        let statId = $(this).data('stat-id') || null;
        let playerId = $(this).find('select').val();
        let minute = $(this).find('input').val();
        events.push({ stat_id: statId, player_id: playerId, minute: minute });
    });
    return events;
}

function eventExists(event, eventsArray) {
    if (event.stat_id) {
        return eventsArray.some(e => e.stat_id === event.stat_id);
    } else {
        return eventsArray.some(e => e.player_id === event.player_id && e.minute === event.minute);
    }
}

function updateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove, yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove) {
    $.ajax({
        url: `/update_match_stats/${matchId}`,
        method: 'POST',
        contentType: 'application/json',
        data: JSON.stringify({
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
        error: function (error) {
            alert('Error updating match report.');
            console.error(error);
        }
    });
}