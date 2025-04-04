// report_match.js

// This ensures that all AJAX requests include the CSRF token
$(document).ready(function () {
    // Set up CSRF token for all AJAX requests
    var csrftoken = $('input[name="csrf_token"]').val();

    $.ajaxSetup({
        beforeSend: function (xhr, settings) {
            if (!/^(GET|HEAD|OPTIONS|TRACE)$/i.test(settings.type) && !this.crossDomain) {
                xhr.setRequestHeader("X-CSRFToken", csrftoken);
            }
        }
    });
});

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

// Function to collect stat IDs that have been marked for removal
function collectRemovedStatIds(matchId, eventType) {
    let containerId = getContainerId(eventType, matchId);
    let baseName = containerId.split('Container-')[0];
    let removedIds = [];
    
    $(`#${containerId}`).find('.player-event-entry.to-be-removed').each(function() {
        const statId = $(this).find(`input[name="${baseName}-stat_id[]"]`).val();
        if (statId && statId.trim() !== '') {
            removedIds.push(statId);
        }
    });
    
    return removedIds;
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
}

// Function to remove an event entry
function removeEvent(button) {
    // Get the parent event entry element
    const eventEntry = $(button).closest('.player-event-entry');
    
    if (!eventEntry.length) {
        console.error("Could not find identifiable element");
        Swal.fire({
            title: 'Error',
            text: 'Could not find the event to remove. Please try again.',
            icon: 'error'
        });
        return;
    }
    
    // Get the unique ID from the data attribute
    const uniqueId = eventEntry.data('unique-id');
    const statId = eventEntry.find('input[name$="-stat_id[]"]').val();
    
    // Log info for debugging
    console.log("Removing event:", {
        uniqueId: uniqueId,
        statId: statId,
        element: eventEntry
    });
    
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
            // Mark as removed but keep in DOM until save
            eventEntry.addClass('to-be-removed');
            eventEntry.hide();
            
            // Show a brief message
            Swal.fire({
                title: 'Removed!',
                text: 'The event entry has been removed. Save your changes to apply.',
                icon: 'success',
                timer: 2000,
                showConfirmButton: false
            });
        }
    });
}

// Define initialEvents as an object to store initial events per matchId
var initialEvents = initialEvents || {};

// Event handler for opening the modal and loading match data
$(document).on('click', '.edit-match-btn', function (e) {
    // Prevent any default action or propagation
    e.preventDefault();
    e.stopPropagation();
    
    // Get match ID either from data attribute or fallback to attribute
    const matchId = $(this).data('match-id') || $(this).attr('data-match-id');
    console.log(`Fetching data for Match ID: ${matchId}`);

    if (!matchId) {
        console.error("Match ID is not defined!");
        return;
    }
    
    // Show a loading indicator using SweetAlert
    Swal.fire({
        title: 'Loading...',
        text: 'Fetching match data',
        allowOutsideClick: false,
        didOpen: () => {
            Swal.showLoading();
        }
    });

    $.ajax({
        url: `/teams/report_match/${matchId}`,
        type: 'GET',
        timeout: 15000, // 15 second timeout
        success: function (response) {
            console.log(`Received response for Match ID: ${matchId}`, response);
            
            // Close loading indicator
            Swal.close();
            
            // Validate that we received a proper response
            if (!response || typeof response !== 'object') {
                console.error('Invalid response format:', response);
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Received invalid response format. Please try again.'
                });
                return;
            }

            // Set default values if response fields are null/undefined
            $('#home_team_score-' + matchId).val(response.home_team_score != null ? response.home_team_score : 0);
            $('#away_team_score-' + matchId).val(response.away_team_score != null ? response.away_team_score : 0);
            $('#match_notes-' + matchId).val(response.notes || '');
            $('#submitBtn-' + matchId).prop('disabled', false);
            
            // Update the team name labels in the modal
            $('label[for="home_team_score-' + matchId + '"]').text((response.home_team_name || 'Home Team') + ' Score');
            $('label[for="away_team_score-' + matchId + '"]').text((response.away_team_name || 'Away Team') + ' Score');

            // Initialize arrays if they don't exist in the response
            const goal_scorers = response.goal_scorers || [];
            const assist_providers = response.assist_providers || [];
            const yellow_cards = response.yellow_cards || [];
            const red_cards = response.red_cards || [];

            // Ensure initialEvents is defined - Fix for the initialization issue
            if (!window.initialEvents) {
                window.initialEvents = {};
            }
            
            // Update initialEvents with default empty arrays if needed
            initialEvents[matchId] = {
                goals: goal_scorers.map(goal => ({
                    unique_id: String(goal.id),
                    stat_id: String(goal.id),
                    player_id: String(goal.player_id),
                    minute: goal.minute || null
                })) || [],
                assists: assist_providers.map(assist => ({
                    unique_id: String(assist.id),
                    stat_id: String(assist.id),
                    player_id: String(assist.player_id),
                    minute: assist.minute || null
                })) || [],
                yellowCards: yellow_cards.map(card => ({
                    unique_id: String(card.id),
                    stat_id: String(card.id),
                    player_id: String(card.player_id),
                    minute: card.minute || null
                })) || [],
                redCards: red_cards.map(card => ({
                    unique_id: String(card.id),
                    stat_id: String(card.id),
                    player_id: String(card.player_id),
                    minute: card.minute || null
                })) || []
            };

            // Clear existing entries
            $('#goalScorersContainer-' + matchId).empty();
            $('#assistProvidersContainer-' + matchId).empty();
            $('#yellowCardsContainer-' + matchId).empty();
            $('#redCardsContainer-' + matchId).empty();

            // Populate the modal with existing events
            goal_scorers.forEach(function (goal) {
                addEvent(matchId, 'goalScorersContainer-' + matchId, goal.id, goal.player_id, goal.minute);
            });

            assist_providers.forEach(function (assist) {
                addEvent(matchId, 'assistProvidersContainer-' + matchId, assist.id, assist.player_id, assist.minute);
            });

            yellow_cards.forEach(function (yellow) {
                addEvent(matchId, 'yellowCardsContainer-' + matchId, yellow.id, yellow.player_id, yellow.minute);
            });

            red_cards.forEach(function (red) {
                addEvent(matchId, 'redCardsContainer-' + matchId, red.id, red.player_id, red.minute);
            });

            // Show the modal after populating it
            const modalId = 'reportMatchModal-' + matchId;
            const modalElement = document.getElementById(modalId);
            
            // Check if the modal exists and is in the correct container
            if (modalElement) {
                try {
                    // Look for existing modal instance and dispose it if needed to prevent duplicates
                    const existingModalInstance = bootstrap.Modal.getInstance(modalElement);
                    if (existingModalInstance) {
                        existingModalInstance.dispose();
                    }
                    
                    // Create a new modal instance
                    const bsModal = new bootstrap.Modal(modalElement, {
                        backdrop: 'static',
                        keyboard: false
                    });
                    
                    // Update modal title to show correct match info
                    const modalTitle = modalElement.querySelector('.modal-title');
                    if (modalTitle) {
                        const homeTeamName = response.home_team_name || 'Home Team';
                        const awayTeamName = response.away_team_name || 'Away Team';
                        const reportType = response.reported ? 'Edit' : 'Report';
                        modalTitle.innerHTML = `<i data-feather="edit" class="me-2"></i>${reportType} Match: ${homeTeamName} vs ${awayTeamName}`;
                        // Re-initialize Feather icons if they exist
                        if (typeof feather !== 'undefined') {
                            feather.replace();
                        }
                    }
                    
                    // Show the modal
                    bsModal.show();
                } catch (error) {
                    console.error('Error showing modal:', error);
                    Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: 'There was a problem showing the form. Please try again.'
                    });
                }
            } else {
                console.error(`Modal element #${modalId} not found`);
                
                // Try to load modals first, then retry
                $.ajax({
                    url: '/modals/render_modals',
                    method: 'GET',
                    success: function(modalContent) {
                        $('body').append(modalContent);
                        console.log('Modals loaded dynamically');
                        
                        // Now try to find the modal again
                        const reloadedModal = document.getElementById(modalId);
                        if (reloadedModal) {
                            // Create a new modal instance
                            const bsModal = new bootstrap.Modal(reloadedModal);
                            bsModal.show();
                        } else {
                            // Alert user if modal still wasn't found
                            Swal.fire({
                                icon: 'error',
                                title: 'Error',
                                text: 'Could not find match reporting form. Please try refreshing the page.'
                            });
                        }
                    },
                    error: function() {
                        Swal.fire({
                            icon: 'error',
                            title: 'Error',
                            text: 'Failed to load the modal. Please refresh the page and try again.'
                        });
                    }
                });
            }
        },
        error: function (xhr, status, error) {
            console.error(`Error fetching match data: ${error}`);
            console.error('Status:', status);
            console.error('Response:', xhr.responseText);
            
            // Check for timeout
            if (status === 'timeout') {
                Swal.fire({
                    icon: 'error',
                    title: 'Connection Timeout',
                    text: 'The request took too long to complete. Please try again.'
                });
            } 
            // Check for server errors
            else if (xhr.status >= 500) {
                Swal.fire({
                    icon: 'error',
                    title: 'Server Error',
                    text: 'The server encountered an error processing your request. Please try again later.'
                });
            }
            // Other errors
            else {
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Failed to load match data. Please try again later.'
                });
            }
        },
        // Always close the loader even on error
        complete: function() {
            Swal.close();
        }
    });
});

// Attach submit handler using event delegation
$(document).on('submit', '.report-match-form', function (e) {
    e.preventDefault();
    e.stopPropagation();

    var matchId = $(this).data('match-id');
    console.log(`Submitting form for Match ID: ${matchId}`);

    // Ensure initialEvents is properly defined
    if (typeof initialEvents === 'undefined') {
        window.initialEvents = {};
    }
    
    // Initialize the match data if it doesn't exist
    if (!initialEvents[matchId]) {
        console.log(`Initializing empty data for match ${matchId}`);
        initialEvents[matchId] = {
            goals: [],
            assists: [],
            yellowCards: [],
            redCards: []
        };
    }

    // Get final events (excludes items marked for removal)
    let finalGoals = getFinalEvents(matchId, 'goal_scorers');
    let finalAssists = getFinalEvents(matchId, 'assist_providers');
    let finalYellowCards = getFinalEvents(matchId, 'yellow_cards');
    let finalRedCards = getFinalEvents(matchId, 'red_cards');

    // Get initial events (what was loaded from server)
    let initialGoals = initialEvents[matchId].goals || [];
    let initialAssists = initialEvents[matchId].assists || [];
    let initialYellowCards = initialEvents[matchId].yellowCards || [];
    let initialRedCards = initialEvents[matchId].redCards || [];

    // Also get any specifically removed events (those with to-be-removed class)
    let removedGoalIds = collectRemovedStatIds(matchId, 'goal_scorers');
    let removedAssistIds = collectRemovedStatIds(matchId, 'assist_providers');
    let removedYellowCardIds = collectRemovedStatIds(matchId, 'yellow_cards');
    let removedRedCardIds = collectRemovedStatIds(matchId, 'red_cards');

    console.log("Removed event IDs:", {
        goals: removedGoalIds,
        assists: removedAssistIds,
        yellowCards: removedYellowCardIds,
        redCards: removedRedCardIds
    });

    // Events to add: in final but not in initial
    let goalsToAdd = finalGoals.filter(goal => !eventExists(goal, initialGoals));
    let assistsToAdd = finalAssists.filter(assist => !eventExists(assist, initialAssists));
    let yellowCardsToAdd = finalYellowCards.filter(card => !eventExists(card, initialYellowCards));
    let redCardsToAdd = finalRedCards.filter(card => !eventExists(card, initialRedCards));

    // Create events to remove directly from removed IDs
    let goalsToRemove = [];
    let assistsToRemove = [];
    let yellowCardsToRemove = [];
    let redCardsToRemove = [];
    
    // Add explicitly removed items (items with to-be-removed class)
    if (removedYellowCardIds.length > 0) {
        // Find the actual events from initialYellowCards based on IDs
        removedYellowCardIds.forEach(id => {
            const card = initialYellowCards.find(c => c.stat_id === id);
            if (card) {
                yellowCardsToRemove.push(card);
            } else {
                // If not found, create a minimal object with the ID
                yellowCardsToRemove.push({ stat_id: id });
            }
        });
    }
    
    if (removedGoalIds.length > 0) {
        removedGoalIds.forEach(id => {
            const goal = initialGoals.find(g => g.stat_id === id);
            if (goal) {
                goalsToRemove.push(goal);
            } else {
                goalsToRemove.push({ stat_id: id });
            }
        });
    }
    
    if (removedAssistIds.length > 0) {
        removedAssistIds.forEach(id => {
            const assist = initialAssists.find(a => a.stat_id === id);
            if (assist) {
                assistsToRemove.push(assist);
            } else {
                assistsToRemove.push({ stat_id: id });
            }
        });
    }
    
    if (removedRedCardIds.length > 0) {
        removedRedCardIds.forEach(id => {
            const card = initialRedCards.find(c => c.stat_id === id);
            if (card) {
                redCardsToRemove.push(card);
            } else {
                redCardsToRemove.push({ stat_id: id });
            }
        });
    }
    
    // Also add items that were in initial but missing from final (normal removal logic)
    initialGoals.forEach(goal => {
        if (!eventExists(goal, finalGoals) && !goalsToRemove.some(g => g.stat_id === goal.stat_id)) {
            goalsToRemove.push(goal);
        }
    });
    
    initialAssists.forEach(assist => {
        if (!eventExists(assist, finalAssists) && !assistsToRemove.some(a => a.stat_id === assist.stat_id)) {
            assistsToRemove.push(assist);
        }
    });
    
    initialYellowCards.forEach(card => {
        if (!eventExists(card, finalYellowCards) && !yellowCardsToRemove.some(c => c.stat_id === card.stat_id)) {
            yellowCardsToRemove.push(card);
        }
    });
    
    initialRedCards.forEach(card => {
        if (!eventExists(card, finalRedCards) && !redCardsToRemove.some(c => c.stat_id === card.stat_id)) {
            redCardsToRemove.push(card);
        }
    });
    
    console.log("Events to add/remove:", {
        goalsToAdd, goalsToRemove,
        assistsToAdd, assistsToRemove,
        yellowCardsToAdd, yellowCardsToRemove,
        redCardsToAdd, redCardsToRemove
    });

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

    // Only get visible entries (exclude ones marked for removal)
    $(`#${containerId}`).find('.player-event-entry:not(.to-be-removed)').each(function () {
        let statId = $(this).find(`input[name="${baseName}-stat_id[]"]`).val();
        let playerId = $(this).find(`select[name="${baseName}-player_id[]"]`).val();
        let minute = $(this).find(`input[name="${baseName}-minute[]"]`).val();
        let uniqueId = $(this).attr('data-unique-id');

        // Skip entries without player_id (which is required)
        if (!playerId) {
            console.warn(`Skipping entry without player_id: uniqueId=${uniqueId}, statId=${statId}`);
            return;
        }

        // Convert values to strings or null
        statId = statId ? String(statId) : null;
        playerId = playerId ? String(playerId) : null;
        minute = minute ? String(minute) : null;

        events.push({ unique_id: uniqueId, stat_id: statId, player_id: playerId, minute: minute });
    });
    
    console.log(`Final ${eventType} events:`, events);
    return events;
}

// Function to check if an event exists in an array
function eventExists(event, eventsArray) {
    // Special case - if element is marked for removal with to-be-removed class
    if (event.element && event.element.classList && event.element.classList.contains('to-be-removed')) {
        return false; // Treat as non-existent if marked for removal
    }
    
    // If both have stat_id, compare them (for existing events)
    if (event.stat_id) {
        return eventsArray.some(e => e.stat_id && String(e.stat_id) === String(event.stat_id));
    } 
    // For new events or when comparing by unique_id
    else if (event.unique_id) {
        return eventsArray.some(e => String(e.unique_id) === String(event.unique_id));
    }
    
    // If we get here, we have no reliable way to compare - log this
    console.warn("Event comparison failed - no stat_id or unique_id:", event);
    return false;
}

// Function to send the AJAX request to update stats
function updateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove,
    yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove) {
    const homeTeamScore = $('#home_team_score-' + matchId).val();
    const awayTeamScore = $('#away_team_score-' + matchId).val();
    const notes = $('#match_notes-' + matchId).val();

    $.ajax({
        url: `/teams/report_match/${matchId}`,
        method: 'POST',
        contentType: 'application/json',
        dataType: 'json',
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
                Swal.fire(
                    'Success!',
                    'Your match report has been submitted successfully.',
                    'success'
                ).then(() => {
                    // Close the modal
                    $(`#reportMatchModal-${matchId}`).modal('hide');

                    // Reload the page to reflect changes
                    location.reload();
                });
            } else {
                Swal.fire(
                    'Error!',
                    response.message || 'There was an error submitting your report.',
                    'error'
                ).then(() => {
                    $(`#submitBtn-${matchId}`).prop('disabled', false);
                });
            }
        },
        error: function (xhr, status, error) {
            console.error('AJAX Error:', error);
            console.error('Response:', xhr.responseText);

            Swal.fire(
                'Error!',
                'An unexpected error occurred while submitting your report.',
                'error'
            ).then(() => {
                $(`#submitBtn-${matchId}`).prop('disabled', false);
            });
        }
    });
}