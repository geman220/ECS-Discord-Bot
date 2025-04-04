// report_match.js - Consolidated match reporting functionality

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

    // Initialize playerChoices if not defined
    if (typeof window.playerChoices === 'undefined') {
        window.playerChoices = {};
    }

    console.log("Match reporting system initialized");
    
    // Setup edit match buttons when available
    setupEditMatchButtons();
});

// Ensure the playerChoices object is available globally
window.playerChoices = window.playerChoices || {};

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

    $(`#${containerId}`).find('.player-event-entry.to-be-removed').each(function () {
        const statId = $(this).find(`input[name="${baseName}-stat_id[]"]`).val();
        if (statId && statId.trim() !== '') {
            removedIds.push(statId);
        }
    });

    return removedIds;
}

// Function to add a new event entry
window.addEvent = function(matchId, containerId, statId = null, playerId = null, minute = null) {
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
};

// Function to remove an event entry
window.removeEvent = function(button) {
    // Handle cases where button might be undefined or null
    if (!button) {
        console.warn("removeEvent called with null or undefined button");
        return;
    }

    // Try multiple methods to find the parent element
    let eventEntry = null;
    let jQueryEntry = null;
    
    try {
        // Method 1: DOM API with instanceof check
        if (button instanceof Element) {
            eventEntry = button.closest('.player-event-entry') || 
                         button.closest('.input-group');
            
            // If found, wrap in jQuery
            if (eventEntry) {
                jQueryEntry = $(eventEntry);
            }
        }
        
        // Method 2: Try jQuery if element wasn't found or button is jQuery object
        if (!eventEntry || !jQueryEntry) {
            // Convert to jQuery if not already
            const $button = (button instanceof Element) ? $(button) : $(button);
            jQueryEntry = $button.closest('.player-event-entry');
            
            // If still not found, try alternates
            if (!jQueryEntry.length) {
                jQueryEntry = $button.closest('.input-group');
            }
            
            // If still not found, try extended selectors
            if (!jQueryEntry.length) {
                // Look up through ancestors for anything containing stat_id[] input
                jQueryEntry = $button.parents().has('input[name$="-stat_id[]"]').first();
            }
            
            // Set DOM element reference if found with jQuery
            if (jQueryEntry && jQueryEntry.length) {
                eventEntry = jQueryEntry[0];
            }
        }
        
        // Last resort fallback - go up 3 parent levels
        if ((!eventEntry || !jQueryEntry || !jQueryEntry.length) && button.parentNode) {
            let parent = button.parentNode;
            for (let i = 0; i < 3; i++) {
                if (parent && (parent.classList.contains('player-event-entry') || 
                               parent.classList.contains('input-group'))) {
                    eventEntry = parent;
                    jQueryEntry = $(parent);
                    break;
                }
                if (parent.parentNode) {
                    parent = parent.parentNode;
                } else {
                    break;
                }
            }
        }
    } catch (e) {
        console.error("Error finding parent element:", e);
    }

    // If still not found, tell user and exit
    if (!eventEntry || !jQueryEntry || !jQueryEntry.length) {
        console.warn("Could not find identifiable element for removal", {
            button: button,
            buttonType: typeof button,
            buttonClass: button.className
        });
        return; // Exit silently without showing error to user
    }

    // Get the unique ID from the data attribute
    let uniqueId, statId;
    try {
        uniqueId = jQueryEntry.data('unique-id');
        statId = jQueryEntry.find('input[name$="-stat_id[]"]').val();
    } catch (e) {
        console.warn("Error getting data attributes:", e);
    }

    // Log info for debugging
    console.log("Removing event:", {
        uniqueId: uniqueId,
        statId: statId,
        element: eventEntry
    });

    // Simple confirmation for mobile device (prevent accidental taps)
    if (window.innerWidth < 768) {
        // Mark as removed but keep in DOM until save (simplified for mobile)
        jQueryEntry.addClass('to-be-removed');
        jQueryEntry.hide();
        
        // Show a simple toast or notification if available
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: 'Removed',
                icon: 'success',
                toast: true,
                position: 'top-end',
                showConfirmButton: false,
                timer: 1500
            });
        }
    } else {
        // Full confirmation dialog for desktop
        Swal.fire({
            title: 'Remove Event?',
            text: "Do you want to remove this event?",
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: '#3085d6',
            cancelButtonColor: '#d33',
            confirmButtonText: 'Yes, remove it'
        }).then((result) => {
            if (result.isConfirmed) {
                // Mark as removed but keep in DOM until save
                jQueryEntry.addClass('to-be-removed');
                jQueryEntry.hide();
    
                // Show a brief message
                Swal.fire({
                    title: 'Removed',
                    text: 'Save your changes to apply',
                    icon: 'success',
                    timer: 1500,
                    showConfirmButton: false
                });
            }
        });
    }
};

// Define initialEvents as an object to store initial events per matchId
window.initialEvents = window.initialEvents || {};

// Function to set up edit match buttons
function setupEditMatchButtons() {
    // Select all edit match buttons on the page
    const editButtons = document.querySelectorAll('.edit-match-btn');
    
    if (editButtons.length > 0) {
        console.log(`Found ${editButtons.length} edit match buttons to fix`);
        
        // Manually fix each button
        editButtons.forEach(function(button) {
            // Get the match ID
            const matchId = button.getAttribute('data-match-id');
            if (!matchId) {
                console.warn('Edit button missing match ID:', button);
                return;
            }
            
            // Remove any existing click handlers by cloning and replacing the button
            const newButton = button.cloneNode(true);
            button.parentNode.replaceChild(newButton, button);
            
            // Add our dedicated click handler
            newButton.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                handleEditButtonClick(matchId);
            });
        });
    }
}

// Function to handle edit button clicks
function handleEditButtonClick(matchId) {
    console.log(`Edit button clicked for match ${matchId}`);
    
    // Show loading spinner
    Swal.fire({
        title: 'Loading...',
        text: 'Fetching match data',
        allowOutsideClick: false,
        didOpen: () => {
            Swal.showLoading();
        }
    });
    
    // Request match data 
    $.ajax({
        url: `/teams/report_match/${matchId}`,
        type: 'GET',
        headers: {
            'Accept': 'application/json'
        },
        timeout: 15000, // 15 second timeout
        success: function(data) {
            console.log('Match data received:', data);
            Swal.close();
            
            // Set up and display the modal
            setupAndShowModal(matchId, data);
        },
        error: function(xhr, status, error) {
            console.error('Error fetching match data:', error);
            console.error('Status:', status);
            console.error('Response:', xhr.responseText);
            
            Swal.fire({
                icon: 'error',
                title: 'Error',
                text: 'Failed to load match data. Please try again later.'
            });
        }
    });
}

// Helper function to set up and show the modal
function setupAndShowModal(matchId, data) {
    // Find the modal
    const modalId = `reportMatchModal-${matchId}`;
    const modal = document.getElementById(modalId);
    
    if (!modal) {
        console.error(`Modal #${modalId} not found, loading modals`);
        
        // Try to load modals
        $.ajax({
            url: '/modals/render_modals',
            method: 'GET',
            success: function(modalContent) {
                $('body').append(modalContent);
                console.log('Modals loaded dynamically');
                
                // Now try to find the modal again
                const modalRecheck = document.getElementById(modalId);
                if (modalRecheck) {
                    populateModal(modalRecheck, data);
                } else {
                    Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: 'Could not load the match reporting form. Please try refreshing the page.'
                    });
                }
            },
            error: function() {
                Swal.fire({
                    icon: 'error',
                    title: 'Error',
                    text: 'Failed to load modals. Please refresh the page and try again.'
                });
            }
        });
    } else {
        populateModal(modal, data);
    }
}

// Function to populate the modal with match data
function populateModal(modal, data) {
    const matchId = data.id || modal.id.replace('reportMatchModal-', '');
    
    // Build player choices data structure for this match
    if (!window.playerChoices) {
        window.playerChoices = {};
    }
    
    // Initialize player choices for this match
    playerChoices[matchId] = {};
    
    // Add home team players
    if (data.home_team && data.home_team.players) {
        const homeTeamName = data.home_team.name || 'Home Team';
        playerChoices[matchId][homeTeamName] = {};
        data.home_team.players.forEach(player => {
            playerChoices[matchId][homeTeamName][player.id] = player.name;
        });
    }
    
    // Add away team players
    if (data.away_team && data.away_team.players) {
        const awayTeamName = data.away_team.name || 'Away Team';
        playerChoices[matchId][awayTeamName] = {};
        data.away_team.players.forEach(player => {
            playerChoices[matchId][awayTeamName][player.id] = player.name;
        });
    }
    
    // Check if player data is available
    if (Object.keys(playerChoices[matchId]).length === 0) {
        console.error('No player data available for match:', matchId);
        Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'Match data is not loaded yet. Please try again in a moment.'
        });
        return;
    }
    
    // Set values in the form
    const homeScoreInput = modal.querySelector(`#home_team_score-${matchId}`);
    const awayScoreInput = modal.querySelector(`#away_team_score-${matchId}`);
    const notesInput = modal.querySelector(`#match_notes-${matchId}`);
    
    if (homeScoreInput) homeScoreInput.value = data.home_team_score != null ? data.home_team_score : 0;
    if (awayScoreInput) awayScoreInput.value = data.away_team_score != null ? data.away_team_score : 0;
    if (notesInput) notesInput.value = data.notes || '';
    
    // Update labels
    const homeLabel = modal.querySelector(`label[for="home_team_score-${matchId}"]`);
    const awayLabel = modal.querySelector(`label[for="away_team_score-${matchId}"]`);
    
    if (homeLabel) homeLabel.textContent = (data.home_team_name || 'Home Team') + ' Score';
    if (awayLabel) awayLabel.textContent = (data.away_team_name || 'Away Team') + ' Score';
    
    // Update title
    const modalTitle = modal.querySelector('.modal-title');
    if (modalTitle) {
        const homeTeamName = data.home_team_name || 'Home Team';
        const awayTeamName = data.away_team_name || 'Away Team';
        const reportType = data.reported ? 'Edit' : 'Report';
        modalTitle.innerHTML = `<i data-feather="edit" class="me-2"></i>${reportType} Match: ${homeTeamName} vs ${awayTeamName}`;
        
        // Re-initialize Feather icons if available
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }
    
    // Clear event containers
    const goalContainer = modal.querySelector(`#goalScorersContainer-${matchId}`);
    const assistContainer = modal.querySelector(`#assistProvidersContainer-${matchId}`);
    const yellowContainer = modal.querySelector(`#yellowCardsContainer-${matchId}`);
    const redContainer = modal.querySelector(`#redCardsContainer-${matchId}`);
    
    if (goalContainer) goalContainer.innerHTML = '';
    if (assistContainer) assistContainer.innerHTML = '';
    if (yellowContainer) yellowContainer.innerHTML = '';
    if (redContainer) redContainer.innerHTML = '';
    
    // Ensure initialEvents is defined
    if (!window.initialEvents) {
        window.initialEvents = {};
    }
    
    // Initialize arrays if they don't exist in the data
    const goal_scorers = data.goal_scorers || [];
    const assist_providers = data.assist_providers || [];
    const yellow_cards = data.yellow_cards || [];
    const red_cards = data.red_cards || [];
    
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
    
    // Populate the modal with existing events
    goal_scorers.forEach(function(goal) {
        window.addEvent(matchId, 'goalScorersContainer-' + matchId, goal.id, goal.player_id, goal.minute);
    });
    
    assist_providers.forEach(function(assist) {
        window.addEvent(matchId, 'assistProvidersContainer-' + matchId, assist.id, assist.player_id, assist.minute);
    });
    
    yellow_cards.forEach(function(yellow) {
        window.addEvent(matchId, 'yellowCardsContainer-' + matchId, yellow.id, yellow.player_id, yellow.minute);
    });
    
    red_cards.forEach(function(red) {
        window.addEvent(matchId, 'redCardsContainer-' + matchId, red.id, red.player_id, red.minute);
    });
    
    // Initialize and show the modal safely
    try {
        // Check if Bootstrap is available
        if (typeof bootstrap !== 'undefined') {
            // Look for existing modal instance and dispose it if needed
            let existingModal = bootstrap.Modal.getInstance(modal);
            if (existingModal) {
                existingModal.dispose();
            }
            
            // Create new modal instance with safety options
            const bsModal = new bootstrap.Modal(modal, {
                backdrop: 'static',
                keyboard: false
            });
            
            // Show the modal (wrap in small timeout to ensure DOM is ready)
            setTimeout(() => {
                try {
                    bsModal.show();
                } catch (err) {
                    console.error("Error showing modal:", err);
                    // Fallback to jQuery
                    $(modal).modal('show');
                }
            }, 50);
        } else {
            // Fallback to jQuery if available
            if (typeof $ !== 'undefined' && typeof $.fn.modal !== 'undefined') {
                $(modal).modal('show');
            } else {
                console.error('Neither Bootstrap nor jQuery modal available');
                // Manual fallback - just show the modal
                modal.style.display = 'block';
                modal.classList.add('show');
                document.body.classList.add('modal-open');
                
                // Create backdrop
                const backdrop = document.createElement('div');
                backdrop.className = 'modal-backdrop fade show';
                document.body.appendChild(backdrop);
            }
        }
    } catch (error) {
        console.error('Error showing modal:', error);
        // Last resort fallback
        Swal.fire({
            icon: 'error', 
            title: 'Error',
            text: 'Could not show match edit form. Please refresh and try again.'
        });
    }
}

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
                Swal.fire({
                    icon: 'success',
                    title: 'Success!',
                    text: 'Your match report has been submitted successfully.'
                }).then(() => {
                    // Close the modal
                    try {
                        const modalElem = document.getElementById(`reportMatchModal-${matchId}`);
                        if (modalElem) {
                            const bsModal = bootstrap.Modal.getInstance(modalElem);
                            if (bsModal) {
                                bsModal.hide();
                            } else {
                                $(modalElem).modal('hide');
                            }
                        }
                    } catch (e) {
                        console.error("Error closing modal:", e);
                    }

                    // Reload the page to reflect changes
                    location.reload();
                });
            } else {
                Swal.fire({
                    icon: 'error',
                    title: 'Error!',
                    text: response.message || 'There was an error submitting your report.'
                }).then(() => {
                    $(`#submitBtn-${matchId}`).prop('disabled', false);
                });
            }
        },
        error: function (xhr, status, error) {
            console.error('AJAX Error:', error);
            console.error('Response:', xhr.responseText);

            Swal.fire({
                icon: 'error',
                title: 'Error!',
                text: 'An unexpected error occurred while submitting your report.'
            }).then(() => {
                $(`#submitBtn-${matchId}`).prop('disabled', false);
            });
        }
    });
}

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