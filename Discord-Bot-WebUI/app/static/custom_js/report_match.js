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

function createTeamOptions(matchId) {
    let options = '<option value="" selected>Select a team</option>';
    
    // Try to get team info from stored match data
    if (window.currentMatchData && window.currentMatchData.matchId == matchId) {
        const homeTeamId = window.currentMatchData.home_team ? window.currentMatchData.home_team.id : null;
        const awayTeamId = window.currentMatchData.away_team ? window.currentMatchData.away_team.id : null;
        const homeTeamName = window.currentMatchData.home_team_name || 'Home Team';
        const awayTeamName = window.currentMatchData.away_team_name || 'Away Team';
        
        if (homeTeamId) options += `<option value="${homeTeamId}">${homeTeamName}</option>`;
        if (awayTeamId) options += `<option value="${awayTeamId}">${awayTeamName}</option>`;
    } else {
        // Fallback to window variables
        const homeTeamName = window['homeTeamName_' + matchId] || 'Home Team';
        const awayTeamName = window['awayTeamName_' + matchId] || 'Away Team';
        const homeTeamId = window['homeTeamId_' + matchId];
        const awayTeamId = window['awayTeamId_' + matchId];
        
        if (homeTeamId) options += `<option value="${homeTeamId}">${homeTeamName}</option>`;
        if (awayTeamId) options += `<option value="${awayTeamId}">${awayTeamName}</option>`;
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
    } else if (eventType === 'own_goals') {
        containerId = 'ownGoalsContainer-' + matchId;
    }
    return containerId;
}

// Function to collect stat IDs that have been marked for removal
function collectRemovedStatIds(matchId, eventType) {
    let containerId = getContainerId(eventType, matchId);
    let baseName = containerId.split('Container-')[0];
    let removedIds = [];
    
    // Map container base names to form field names
    let formBaseName = baseName;
    if (baseName === 'yellowCards') {
        formBaseName = 'yellow_cards';
    } else if (baseName === 'redCards') {
        formBaseName = 'red_cards';
    } else if (baseName === 'goalScorers') {
        formBaseName = 'goalScorers';
    } else if (baseName === 'assistProviders') {
        formBaseName = 'assistProviders';
    }

    $(`#${containerId}`).find('.player-event-entry.to-be-removed').each(function () {
        const statId = $(this).find(`input[name="${formBaseName}-stat_id[]"]`).val();
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

    // Determine visual indicator and styling based on event type
    var eventIndicator = '';
    var inputGroupClass = 'input-group mb-2 player-event-entry';
    var selectStyle = 'min-width: 200px;';
    var minuteStyle = 'max-width: 80px;';
    var formBaseName = baseName;
    
    if (baseName === 'yellowCards') {
        eventIndicator = '<span class="input-group-text bg-warning text-dark" style="min-width: 32px; padding: 0.375rem 0.25rem;">🟨</span>';
        inputGroupClass = 'input-group mb-1 player-event-entry';
        formBaseName = 'yellow_cards';
    } else if (baseName === 'redCards') {
        eventIndicator = '<span class="input-group-text bg-danger text-white" style="min-width: 32px; padding: 0.375rem 0.25rem;">🟥</span>';
        inputGroupClass = 'input-group mb-1 player-event-entry';
        formBaseName = 'red_cards';
    } else if (baseName === 'ownGoals') {
        formBaseName = 'own_goals';
    }

    // Define the new input group with appropriate naming conventions and data attributes
    var newInputGroup;
    
    if (baseName === 'ownGoals') {
        // Special handling for own goals - use team selector instead of player selector
        newInputGroup = `
            <div class="${inputGroupClass}" data-unique-id="${uniqueId}">
                ${eventIndicator}
                <input type="hidden" name="${formBaseName}-stat_id[]" value="${statId ? statId : ''}">
                <select class="form-select" name="${formBaseName}-team_id[]" style="${selectStyle}">
                    ${createTeamOptions(matchId)}
                </select>
                <input type="text" class="form-control" name="${formBaseName}-minute[]" 
                       placeholder="Min" 
                       value="${minute ? minute : ''}"
                       pattern="^\\d{1,3}(\\+\\d{1,2})?$" 
                       title="Enter a valid minute (e.g., '45' or '45+2')"
                       style="${minuteStyle}">
                <button class="btn btn-danger btn-sm" type="button" onclick="removeEvent(this)">×</button>
            </div>
        `;
    } else {
        // Standard event (goals, assists, cards)
        newInputGroup = `
            <div class="${inputGroupClass}" data-unique-id="${uniqueId}">
                ${eventIndicator}
                <input type="hidden" name="${formBaseName}-stat_id[]" value="${statId ? statId : ''}">
                <select class="form-select" name="${formBaseName}-player_id[]" style="${selectStyle}">
                    ${createPlayerOptions(matchId)}
                </select>
                <input type="text" class="form-control" name="${formBaseName}-minute[]" 
                       placeholder="Min" 
                       value="${minute ? minute : ''}"
                       pattern="^\\d{1,3}(\\+\\d{1,2})?$" 
                       title="Enter a valid minute (e.g., '45' or '45+2')"
                       style="${minuteStyle}">
                <button class="btn btn-danger btn-sm" type="button" onclick="removeEvent(this)">×</button>
            </div>
        `;
    }

    // Append the new input group to the container
    $(containerSelector).append(newInputGroup);

    // Set the selected player if provided
    if (playerId) {
        const lastAddedEntry = $(containerSelector).children().last();
        lastAddedEntry.find(`select[name="${formBaseName}-player_id[]"]`).val(playerId);
    }

    // Re-initialize Feather icons if necessary
    if (typeof feather !== 'undefined' && feather) {
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }
};

// Function to remove an event entry
window.removeEvent = function(button) {
    // Handle cases where button might be undefined or null
    if (!button) {
        // removeEvent called with null or undefined button
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
        // Error finding parent element
    }

    // If still not found, tell user and exit
    if (!eventEntry || !jQueryEntry || !jQueryEntry.length) {
        // Could not find identifiable element for removal
        return; // Exit silently without showing error to user
    }

    // Get the unique ID from the data attribute
    let uniqueId, statId;
    try {
        uniqueId = jQueryEntry.data('unique-id');
        statId = jQueryEntry.find('input[name$="-stat_id[]"]').val();
    } catch (e) {
        // Error getting data attributes
    }

    // Removing event

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
        // Silently fix each button
        editButtons.forEach(function(button) {
            // Get the match ID
            const matchId = button.getAttribute('data-match-id');
            if (!matchId) {
                // Edit button missing match ID
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
    // Edit button clicked for match
    
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
            // Match data received
            
            // Store match data globally for access by other functions
            window.currentMatchData = data;
            window.currentMatchData.matchId = matchId;
            
            Swal.close();
            
            // Set up and display the modal
            setupAndShowModal(matchId, data);
        },
        error: function(xhr, status, error) {
            // Error fetching match data
            
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
    
    // Debug logging for comparison
    setTimeout(() => {
        if (typeof debugModalStructure === 'function') {
            debugModalStructure(modalId);
        }
    }, 200);
    
    if (!modal) {
        // Modal not found, generating one dynamically
        
        // First try to load all modals
        $.ajax({
            url: '/modals/render_modals',
            method: 'GET',
            success: function(modalContent) {
                // Append to the container if it exists, otherwise to body
                const container = document.getElementById('reportMatchModal-container') || document.body;
                $(container).append(modalContent);
                // Modals loaded dynamically
                
                // Now try to find the modal again
                const modalRecheck = document.getElementById(modalId);
                if (modalRecheck) {
                    populateModal(modalRecheck, data);
                } else {
                    // Still not found - create a new one just for this match
                    createDynamicModal(matchId, data);
                }
            },
            error: function() {
                // Create a dynamic modal for just this match if loading all fails
                createDynamicModal(matchId, data);
            }
        });
    } else {
        populateModal(modal, data);
    }
}

// Function to create a dynamic modal for a specific match when needed
function createDynamicModal(matchId, data) {
    // Creating a dynamic modal for match
    
    // Create the container if it doesn't exist
    let container = document.getElementById('reportMatchModal-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'reportMatchModal-container';
        container.className = 'modal-container';
        document.body.appendChild(container);
    }
    
    // Create a basic modal structure
    const modalHtml = `
    <div class="modal fade ecs-modal" 
         id="reportMatchModal-${matchId}" 
         tabindex="-1" 
         role="dialog"
         aria-labelledby="reportMatchModalLabel-${matchId}" 
         aria-hidden="true"
         data-bs-backdrop="static">
        <div class="modal-dialog modal-lg modal-dialog-centered ecs-modal-dialog ecs-modal-lg ecs-modal-dialog-centered" role="document">
            <div class="modal-content ecs-modal-content">
                <!-- Modal Header -->
                <div class="modal-header bg-primary text-white ecs-modal-header">
                    <h5 class="modal-title ecs-modal-title" id="reportMatchModalLabel-${matchId}">
                        <i data-feather="edit" class="me-2"></i>
                        ${'Edit' ? data.reported : 'Report'} Match: 
                        <span class="home-team-name">${data.home_team_name || 'Home Team'}</span>
                        vs
                        <span class="away-team-name">${data.away_team_name || 'Away Team'}</span>
                    </h5>
                    <button type="button" 
                            class="btn-close btn-close-white ecs-modal-close" 
                            data-bs-dismiss="modal" 
                            aria-label="Close"></button>
                </div>

                <!-- Modal Body -->
                <form id="reportMatchForm-${matchId}" class="report-match-form" data-match-id="${matchId}" action="/teams/report_match/${matchId}" method="POST" novalidate>
                    <div class="modal-body ecs-modal-body">
                        <!-- CSRF Token -->
                        <input type="hidden" name="csrf_token" value="${$('input[name="csrf_token"]').val()}">

                        <!-- Home and Away Team Scores -->
                        <div class="row mb-4">
                            <!-- Home Team Score -->
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label for="home_team_score-${matchId}" class="form-label">${data.home_team_name || 'Home Team'} Score</label>
                                    <input type="number"
                                           min="0"
                                           class="form-control"
                                           id="home_team_score-${matchId}"
                                           name="home_team_score"
                                           value="${data.home_team_score || 0}"
                                           required />
                                </div>
                            </div>
                            <!-- Away Team Score -->
                            <div class="col-md-6">
                                <div class="mb-3">
                                    <label for="away_team_score-${matchId}" class="form-label">${data.away_team_name || 'Away Team'} Score</label>
                                    <input type="number"
                                           min="0"
                                           class="form-control"
                                           id="away_team_score-${matchId}"
                                           name="away_team_score"
                                           value="${data.away_team_score || 0}"
                                           required />
                                </div>
                            </div>
                        </div>

                        <!-- Goal Scorers -->
                        <div class="mb-4">
                            <label class="form-label">Goal Scorers</label>
                            <div class="card p-3 border-1 shadow-sm">
                                <div id="goalScorersContainer-${matchId}" class="mb-2">
                                    <!-- Goal scorers will be added here dynamically -->
                                </div>
                                <button class="btn btn-primary btn-sm" type="button" onclick="addEvent('${matchId}', 'goalScorersContainer-${matchId}')">
                                    <i data-feather="plus" class="me-1"></i> Add Goal Scorer
                                </button>
                            </div>
                        </div>

                        <!-- Assist Providers -->
                        <div class="mb-4">
                            <label class="form-label">Assist Providers</label>
                            <div class="card p-3 border-1 shadow-sm">
                                <div id="assistProvidersContainer-${matchId}" class="mb-2">
                                    <!-- Assist providers will be added here dynamically -->
                                </div>
                                <button class="btn btn-primary btn-sm" type="button" onclick="addEvent('${matchId}', 'assistProvidersContainer-${matchId}')">
                                    <i data-feather="plus" class="me-1"></i> Add Assist Provider
                                </button>
                            </div>
                        </div>

                        <!-- Yellow Cards -->
                        <div class="mb-4">
                            <label class="form-label">Yellow Cards</label>
                            <div class="card p-3 border-1 shadow-sm">
                                <div id="yellowCardsContainer-${matchId}" class="mb-2">
                                    <!-- Yellow cards will be added here dynamically -->
                                </div>
                                <button class="btn btn-primary btn-sm" type="button" onclick="addEvent('${matchId}', 'yellowCardsContainer-${matchId}')">
                                    <i data-feather="plus" class="me-1"></i> Add Yellow Card
                                </button>
                            </div>
                        </div>

                        <!-- Red Cards -->
                        <div class="mb-4">
                            <label class="form-label">Red Cards</label>
                            <div class="card p-3 border-1 shadow-sm">
                                <div id="redCardsContainer-${matchId}" class="mb-2">
                                    <!-- Red cards will be added here dynamically -->
                                </div>
                                <button class="btn btn-primary btn-sm" type="button" onclick="addEvent('${matchId}', 'redCardsContainer-${matchId}')">
                                    <i data-feather="plus" class="me-1"></i> Add Red Card
                                </button>
                            </div>
                        </div>

                        <!-- Match Notes -->
                        <div class="mb-4">
                            <label class="form-label" for="match_notes-${matchId}">Match Notes</label>
                            <textarea class="form-control" id="match_notes-${matchId}" name="match_notes" rows="3">${data.notes || ''}</textarea>
                        </div>
                    </div>

                    <!-- Modal Footer -->
                    <div class="modal-footer ecs-modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                        <button type="submit" class="btn btn-primary" id="submitBtn-${matchId}">
                            ${data.reported ? 'Save Changes' : 'Submit Report'}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    </div>`;
    
    // Add the modal to the container
    container.insertAdjacentHTML('beforeend', modalHtml);
    
    // Now process the modal
    const modal = document.getElementById(`reportMatchModal-${matchId}`);
    if (modal) {
        // Initialize feather icons if available
        if (typeof feather !== 'undefined') {
            if (typeof feather !== 'undefined') {
            feather.replace();
        }
        }
        
        // Populate the modal with the data
        populateModal(modal, data);
    } else {
        Swal.fire({
            icon: 'error',
            title: 'Error',
            text: 'Failed to create the match modal. Please refresh the page and try again.'
        });
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
        // No player data available for match
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
            if (typeof feather !== 'undefined') {
            feather.replace();
        }
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
    const own_goals = data.own_goals || [];
    
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
        })) || [],
        ownGoals: own_goals.map(ownGoal => ({
            unique_id: String(ownGoal.id),
            stat_id: String(ownGoal.id),
            team_id: String(ownGoal.team_id),
            minute: ownGoal.minute || null
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
    
    own_goals.forEach(function(ownGoal) {
        window.addOwnGoalEvent(matchId, 'ownGoalsContainer-' + matchId, ownGoal.id, ownGoal.team_id, ownGoal.minute);
    });
    
    // Add verification checkboxes if they're not already there
    updateVerificationSection(modal, matchId, data);
    
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
                    // Error showing modal
                    // Fallback to jQuery
                    $(modal).modal('show');
                }
            }, 50);
        } else {
            // Fallback to jQuery if available
            if (typeof $ !== 'undefined' && typeof $.fn.modal !== 'undefined') {
                $(modal).modal('show');
            } else {
                // Neither Bootstrap nor jQuery modal available
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
        // Error showing modal
        // Last resort fallback
        Swal.fire({
            icon: 'error', 
            title: 'Error',
            text: 'Could not show match edit form. Please refresh and try again.'
        });
    }
}

// Function to update or add the verification section to the modal
function updateVerificationSection(modal, matchId, data) {
    try {
        // Updating verification section with data
        
        // Look for existing verification section, create if not found
        let verificationSection = modal.querySelector(`#verificationSection-${matchId}`);
        
        if (!verificationSection) {
            // Create verification section just before the Modal Footer
            const modalBody = modal.querySelector('.modal-body');
            
            if (!modalBody) {
                // Modal body not found
                return;
            }
            
            // Creating verification section
            verificationSection = document.createElement('div');
            verificationSection.id = `verificationSection-${matchId}`;
            verificationSection.className = 'mb-4 verification-section border-top pt-4 mt-4';
            modalBody.appendChild(verificationSection);
        }
        
        // Get verification data from match data
        const homeTeamVerified = data.home_team_verified || false;
        const awayTeamVerified = data.away_team_verified || false;
        
        // Check if user can verify each team (from data API)
        const canVerifyHome = data.can_verify_home || false;
        const canVerifyAway = data.can_verify_away || false;
        
        // Verification status
        
        // Set up the HTML for the verification section
        let verificationHTML = `
            <h5 class="mb-3">Match Verification</h5>
            <div class="alert ${homeTeamVerified && awayTeamVerified ? 'alert-success' : 'alert-warning'} mb-3">
                <div class="d-flex align-items-center">
                    <i class="fa ${homeTeamVerified && awayTeamVerified ? 'fa-check-circle' : 'fa-exclamation-circle'} me-2 fs-3"></i>
                    <div>
                        <p class="mb-0">
                            ${homeTeamVerified && awayTeamVerified 
                                ? 'This match has been verified by both teams.' 
                                : 'This match requires verification from both teams to be complete.'}
                        </p>
                    </div>
                </div>
            </div>
            
            <div class="row">
                <div class="col-md-6">
                    <div class="card mb-2 ${homeTeamVerified ? 'border-success' : 'border-warning'}">
                        <div class="card-body">
                            <h6 class="card-title d-flex align-items-center">
                                <i class="fa ${homeTeamVerified ? 'fa-check text-success' : 'fa-clock text-warning'} me-2"></i>
                                ${data.home_team_name || 'Home Team'}
                            </h6>
                            <p class="card-text small mb-2">
                                ${homeTeamVerified 
                                    ? `Verified by ${data.home_verifier || 'Unknown'} 
                                       ${data.home_team_verified_at ? 'on ' + new Date(data.home_team_verified_at).toLocaleString() : ''}` 
                                    : 'Not verified yet'}
                            </p>
                            ${!homeTeamVerified && canVerifyHome 
                                ? `<div class="form-check">
                                    <input class="form-check-input" type="checkbox" value="true" id="verifyHomeTeam-${matchId}" name="verify_home_team">
                                    <label class="form-check-label" for="verifyHomeTeam-${matchId}">
                                        Verify for ${data.home_team_name || 'Home Team'}
                                    </label>
                                    <div class="text-muted small">Check this box to verify the match results for your team</div>
                                </div>` 
                                : ''}
                        </div>
                    </div>
                </div>
                
                <div class="col-md-6">
                    <div class="card mb-2 ${awayTeamVerified ? 'border-success' : 'border-warning'}">
                        <div class="card-body">
                            <h6 class="card-title d-flex align-items-center">
                                <i class="fa ${awayTeamVerified ? 'fa-check text-success' : 'fa-clock text-warning'} me-2"></i>
                                ${data.away_team_name || 'Away Team'}
                            </h6>
                            <p class="card-text small mb-2">
                                ${awayTeamVerified 
                                    ? `Verified by ${data.away_verifier || 'Unknown'} 
                                       ${data.away_team_verified_at ? 'on ' + new Date(data.away_team_verified_at).toLocaleString() : ''}` 
                                    : 'Not verified yet'}
                            </p>
                            ${!awayTeamVerified && canVerifyAway 
                                ? `<div class="form-check">
                                    <input class="form-check-input" type="checkbox" value="true" id="verifyAwayTeam-${matchId}" name="verify_away_team">
                                    <label class="form-check-label" for="verifyAwayTeam-${matchId}">
                                        Verify for ${data.away_team_name || 'Away Team'}
                                    </label>
                                    <div class="text-muted small">Check this box to verify the match results for your team</div>
                                </div>` 
                                : ''}
                        </div>
                    </div>
                </div>
            </div>
        `;
        
        // Setting verification HTML
        // Update the verification section HTML
        verificationSection.innerHTML = verificationHTML;
        
        // Verification section updated successfully
    } catch (error) {
        // Error updating verification section
    }
}

// Function to get final events from the form
function getFinalEvents(matchId, eventType) {
    let events = [];
    let containerId = getContainerId(eventType, matchId);
    let baseName = containerId.split('Container-')[0];
    
    // Map container base names to form field names
    let formBaseName = baseName;
    if (baseName === 'yellowCards') {
        formBaseName = 'yellow_cards';
    } else if (baseName === 'redCards') {
        formBaseName = 'red_cards';
    } else if (baseName === 'goalScorers') {
        formBaseName = 'goalScorers';
    } else if (baseName === 'assistProviders') {
        formBaseName = 'assistProviders';
    }

    // Handle own goals differently since they use team_id instead of player_id
    if (eventType === 'own_goals') {
        $(`#${containerId}`).find('.own-goal-event-entry:not(.to-be-removed)').each(function () {
            // Use 'own_goals' as the field name prefix (not 'ownGoals')
            let statId = $(this).find(`input[name="own_goals-stat_id[]"]`).val();
            let teamId = $(this).find(`select[name="own_goals-team_id[]"]`).val();
            let minute = $(this).find(`input[name="own_goals-minute[]"]`).val();
            let uniqueId = $(this).attr('data-unique-id');
            
            if (teamId) {
                events.push({
                    stat_id: statId || '',
                    team_id: teamId,
                    minute: minute || '',
                    unique_id: uniqueId
                });
            }
        });
    } else {
        // Only get visible entries (exclude ones marked for removal)
        $(`#${containerId}`).find('.player-event-entry:not(.to-be-removed)').each(function () {
            let statId = $(this).find(`input[name="${formBaseName}-stat_id[]"]`).val();
            let playerId = $(this).find(`select[name="${formBaseName}-player_id[]"]`).val();
            let minute = $(this).find(`input[name="${formBaseName}-minute[]"]`).val();
            let uniqueId = $(this).attr('data-unique-id');

        // Skip entries without player_id (which is required)
        if (!playerId) {
            // Skipping entry without player_id
            return;
        }

        // Convert values to strings or null
        statId = statId ? String(statId) : null;
        playerId = playerId ? String(playerId) : null;
        minute = minute ? String(minute) : null;

            events.push({ unique_id: uniqueId, stat_id: statId, player_id: playerId, minute: minute });
        });
    }

    // Final events
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
    // Event comparison failed - no stat_id or unique_id
    return false;
}

// Function to send the AJAX request to update stats
function updateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove,
    yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove, ownGoalsToAdd, ownGoalsToRemove) {
    const homeTeamScore = $('#home_team_score-' + matchId).val();
    const awayTeamScore = $('#away_team_score-' + matchId).val();
    const notes = $('#match_notes-' + matchId).val();
    
    // Get the version for optimistic locking
    const version = window.currentMatchData ? window.currentMatchData.version : null;
    
    // Get verification checkboxes status
    const verifyHomeTeam = $(`#verifyHomeTeam-${matchId}`).is(':checked');
    const verifyAwayTeam = $(`#verifyAwayTeam-${matchId}`).is(':checked');
    
    // Check if verification is required - only if user can verify a team and hasn't checked the box
    const homeTeamCheckbox = $(`#verifyHomeTeam-${matchId}`);
    const awayTeamCheckbox = $(`#verifyAwayTeam-${matchId}`);
    
    // Check if user can verify teams but hasn't checked the verification boxes
    let missingVerifications = [];
    if (homeTeamCheckbox.length > 0 && !verifyHomeTeam) {
        const homeTeamName = window.currentMatchData ? window.currentMatchData.home_team_name : 'Home Team';
        missingVerifications.push(homeTeamName);
    }
    if (awayTeamCheckbox.length > 0 && !verifyAwayTeam) {
        const awayTeamName = window.currentMatchData ? window.currentMatchData.away_team_name : 'Away Team';
        missingVerifications.push(awayTeamName);
    }
    
    // Allow submission if no verification boxes are present (user can't verify any team)
    // But if verification boxes are present, require at least one to be checked
    if (missingVerifications.length > 0 && (homeTeamCheckbox.length > 0 || awayTeamCheckbox.length > 0)) {
        // If user can verify but hasn't checked any boxes, require verification
        if (!verifyHomeTeam && !verifyAwayTeam) {
            Swal.fire({
                icon: 'warning',
                title: 'Verification Required',
                text: `Please verify the match results for your team before submitting.`,
                confirmButtonText: 'OK'
            });
            return; // Stop submission
        }
    }

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
            red_cards_to_remove: redCardsToRemove,
            own_goals_to_add: ownGoalsToAdd,
            own_goals_to_remove: ownGoalsToRemove,
            verify_home_team: verifyHomeTeam,
            verify_away_team: verifyAwayTeam,
            version: version
        }),
        success: function (response) {
            if (response.success) {
                // Determine message based on verification status
                let successMessage = 'Your match report has been submitted successfully.';
                
                if (response.home_team_verified && response.away_team_verified) {
                    successMessage = 'Match report submitted and fully verified by both teams.';
                } else if (response.home_team_verified || response.away_team_verified) {
                    successMessage = 'Match report submitted and verified by one team.';
                    
                    if (verifyHomeTeam || verifyAwayTeam) {
                        successMessage += ' Thank you for verifying!';
                    } else {
                        successMessage += ' The other team still needs to verify.';
                    }
                }
                
                Swal.fire({
                    icon: 'success',
                    title: 'Success!',
                    text: successMessage
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
                        // Error closing modal
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
            let errorMessage = 'An unexpected error occurred while submitting your report.';
            let errorTitle = 'Error!';
            let showRefreshOption = false;
            
            if (xhr.status === 409) {
                // Version conflict
                try {
                    const response = JSON.parse(xhr.responseText);
                    if (response.error_type === 'version_conflict') {
                        errorTitle = 'Match Updated by Another User';
                        errorMessage = 'This match was modified by another user while you were editing. Please refresh to get the latest data and try again.';
                        showRefreshOption = true;
                    }
                } catch (e) {
                    // Fallback to generic message
                }
            } else if (xhr.responseJSON && xhr.responseJSON.message) {
                errorMessage = xhr.responseJSON.message;
            }

            const swalOptions = {
                icon: 'warning',
                title: errorTitle,
                text: errorMessage
            };
            
            if (showRefreshOption) {
                swalOptions.showCancelButton = true;
                swalOptions.confirmButtonText = 'Refresh Page';
                swalOptions.cancelButtonText = 'Cancel';
            }
            
            Swal.fire(swalOptions).then((result) => {
                if (result.isConfirmed && showRefreshOption) {
                    location.reload();
                } else {
                    $(`#submitBtn-${matchId}`).prop('disabled', false);
                }
            });
        }
    });
}

// Attach submit handler using event delegation
$(document).on('submit', '.report-match-form', function (e) {
    e.preventDefault();
    e.stopPropagation();

    var matchId = $(this).data('match-id');
    // Submitting form for Match ID

    // Ensure initialEvents is properly defined
    if (typeof initialEvents === 'undefined') {
        window.initialEvents = {};
    }

    // Initialize the match data if it doesn't exist
    if (!initialEvents[matchId]) {
        // Initializing empty data for match
        initialEvents[matchId] = {
            goals: [],
            assists: [],
            yellowCards: [],
            redCards: [],
            ownGoals: []
        };
    }

    // Get final events (excludes items marked for removal)
    let finalGoals = getFinalEvents(matchId, 'goal_scorers');
    let finalAssists = getFinalEvents(matchId, 'assist_providers');
    let finalYellowCards = getFinalEvents(matchId, 'yellow_cards');
    let finalRedCards = getFinalEvents(matchId, 'red_cards');
    let finalOwnGoals = getFinalEvents(matchId, 'own_goals');

    // Get initial events (what was loaded from server)
    let initialGoals = initialEvents[matchId].goals || [];
    let initialAssists = initialEvents[matchId].assists || [];
    let initialYellowCards = initialEvents[matchId].yellowCards || [];
    let initialRedCards = initialEvents[matchId].redCards || [];
    let initialOwnGoals = initialEvents[matchId].ownGoals || [];

    // Also get any specifically removed events (those with to-be-removed class)
    let removedGoalIds = collectRemovedStatIds(matchId, 'goal_scorers');
    let removedAssistIds = collectRemovedStatIds(matchId, 'assist_providers');
    let removedYellowCardIds = collectRemovedStatIds(matchId, 'yellow_cards');
    let removedRedCardIds = collectRemovedStatIds(matchId, 'red_cards');
    let removedOwnGoalIds = collectRemovedOwnGoalIds(matchId);

    // Removed event IDs

    // Events to add: in final but not in initial
    let goalsToAdd = finalGoals.filter(goal => !eventExists(goal, initialGoals));
    let assistsToAdd = finalAssists.filter(assist => !eventExists(assist, initialAssists));
    let yellowCardsToAdd = finalYellowCards.filter(card => !eventExists(card, initialYellowCards));
    let redCardsToAdd = finalRedCards.filter(card => !eventExists(card, initialRedCards));
    let ownGoalsToAdd = finalOwnGoals.filter(ownGoal => !ownGoalExists(ownGoal, initialOwnGoals));

    // Create events to remove directly from removed IDs
    let goalsToRemove = [];
    let assistsToRemove = [];
    let yellowCardsToRemove = [];
    let redCardsToRemove = [];
    let ownGoalsToRemove = [];

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

    if (removedOwnGoalIds.length > 0) {
        removedOwnGoalIds.forEach(id => {
            const ownGoal = initialOwnGoals.find(og => og.stat_id === id);
            if (ownGoal) {
                ownGoalsToRemove.push(ownGoal);
            } else {
                ownGoalsToRemove.push({ stat_id: id });
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

    initialOwnGoals.forEach(ownGoal => {
        if (!ownGoalExists(ownGoal, finalOwnGoals) && !ownGoalsToRemove.some(og => og.stat_id === ownGoal.stat_id)) {
            ownGoalsToRemove.push(ownGoal);
        }
    });

    // Events to add/remove

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
            updateStats(matchId, goalsToAdd, goalsToRemove, assistsToAdd, assistsToRemove, yellowCardsToAdd, yellowCardsToRemove, redCardsToAdd, redCardsToRemove, ownGoalsToAdd, ownGoalsToRemove);
        }
    });
});

// Function to add a new own goal event entry
window.addOwnGoalEvent = function(matchId, containerId, statId = null, teamId = null, minute = null) {
    var containerSelector = '#' + containerId;

    // Generate a unique ID for the event if not provided
    var uniqueId = statId ? String(statId) : 'new-' + Date.now() + '-' + Math.random();

    // Get team names and IDs from the match data
    // First try window variables (for team detail pages)
    var homeTeamName = window['homeTeamName_' + matchId];
    var awayTeamName = window['awayTeamName_' + matchId];
    var homeTeamId = window['homeTeamId_' + matchId];
    var awayTeamId = window['awayTeamId_' + matchId];
    
    // If not available, try to get from the modal's match data
    if (!homeTeamName || !awayTeamName) {
        // Look for the modal with this match ID to get team data
        const modalSelector = '#reportMatchModal-' + matchId;
        const modal = document.querySelector(modalSelector);
        
        if (modal) {
            // Get team names from modal title or data attributes
            const modalTitle = modal.querySelector('.modal-title');
            if (modalTitle) {
                const titleText = modalTitle.textContent;
                // Parse "Report Match: Team A vs Team B" format
                const vsMatch = titleText.match(/Match:\s*(.+?)\s+vs\s+(.+)$/);
                if (vsMatch) {
                    homeTeamName = vsMatch[1].trim();
                    awayTeamName = vsMatch[2].trim();
                }
            }
        }
        
        // If still not found, try to get from the stored match data
        if (window.currentMatchData && window.currentMatchData.matchId == matchId) {
            homeTeamName = window.currentMatchData.home_team_name;
            awayTeamName = window.currentMatchData.away_team_name;
            homeTeamId = window.currentMatchData.home_team ? window.currentMatchData.home_team.id : null;
            awayTeamId = window.currentMatchData.away_team ? window.currentMatchData.away_team.id : null;
            
            // Got team names from stored match data
        }
    }
    
    // Final fallback to generic names if team names still aren't available
    if (!homeTeamName) homeTeamName = 'Home Team';
    if (!awayTeamName) awayTeamName = 'Away Team';

    // Define the new input group for own goals
    var newInputGroup = `
        <div class="input-group mb-2 player-event-entry" data-unique-id="${uniqueId}">
            <input type="hidden" name="own_goals-stat_id[]" value="${statId ? statId : ''}">
            <select class="form-select" name="own_goals-team_id[]" style="min-width: 200px;">
                <option value="${homeTeamId}"${teamId == homeTeamId ? ' selected' : ''}>${homeTeamName}</option>
                <option value="${awayTeamId}"${teamId == awayTeamId ? ' selected' : ''}>${awayTeamName}</option>
            </select>
            <input type="text" class="form-control" name="own_goals-minute[]" 
                   placeholder="Min" 
                   value="${minute ? minute : ''}"
                   pattern="^\\d{1,3}(\\+\\d{1,2})?$" 
                   title="Enter a valid minute (e.g., '45' or '45+2')"
                   style="max-width: 80px;">
            <button class="btn btn-danger btn-sm" type="button" onclick="removeEvent(this)">×</button>
        </div>
    `;

    // Append the new input group to the container
    $(containerSelector).append(newInputGroup);

    // Re-initialize Feather icons if necessary
    if (typeof feather !== 'undefined' && feather) {
        if (typeof feather !== 'undefined') {
            feather.replace();
        }
    }
};

// Function to remove an own goal event entry
window.removeOwnGoalEvent = function(button) {
    // Handle cases where button might be undefined or null
    if (!button) {
        // removeOwnGoalEvent called with null or undefined button
        return;
    }

    // Try multiple methods to find the parent element
    let eventEntry = null;
    let jQueryEntry = null;
    
    try {
        // Method 1: DOM API with instanceof check
        if (button instanceof Element) {
            eventEntry = button.closest('.own-goal-event-entry') || 
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
            jQueryEntry = $button.closest('.own-goal-event-entry');
            
            // If still not found, try alternates
            if (!jQueryEntry.length) {
                jQueryEntry = $button.closest('.input-group');
            }
        }
        
    } catch (error) {
        // Error in removeOwnGoalEvent
        return;
    }

    // Check if we found a valid entry
    if (!jQueryEntry || !jQueryEntry.length) {
        // Could not find parent element for own goal event removal
        return;
    }

    // Get the stat ID from the hidden input (if it exists)
    const statIdInput = jQueryEntry.find('input[name="own_goals-stat_id[]"]');
    const statId = statIdInput.val();

    if (statId && statId.trim() !== '' && !statId.startsWith('new-')) {
        // This is an existing event, mark it for removal
        jQueryEntry.addClass('to-be-removed').hide();
    } else {
        // This is a new event, remove it completely
        jQueryEntry.remove();
    }
};

// Function to collect removed own goal stat IDs
function collectRemovedOwnGoalIds(matchId) {
    let containerId = `ownGoalsContainer-${matchId}`;
    let removedIds = [];

    $(`#${containerId}`).find('.own-goal-event-entry.to-be-removed').each(function () {
        const statId = $(this).find('input[name="own_goals-stat_id[]"]').val();
        if (statId && statId.trim() !== '') {
            removedIds.push(statId);
        }
    });

    return removedIds;
}

// Function to check if an own goal exists in a list
function ownGoalExists(ownGoal, ownGoalList) {
    return ownGoalList.some(og => {
        // Check by stat_id if both have it
        if (ownGoal.stat_id && og.stat_id) {
            return ownGoal.stat_id === og.stat_id;
        }
        // Check by unique_id if both have it
        if (ownGoal.unique_id && og.unique_id) {
            return ownGoal.unique_id === og.unique_id;
        }
        // Check by team_id and minute as fallback
        return ownGoal.team_id === og.team_id && ownGoal.minute === og.minute;
    });
}