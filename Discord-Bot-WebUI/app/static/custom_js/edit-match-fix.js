/**
 * Edit Match Button Fix
 * 
 * This script specifically fixes the edit match button functionality.
 */

document.addEventListener('DOMContentLoaded', function() {
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
                
                // Request match data directly
                fetch(`/teams/report_match/${matchId}`, {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json'
                    }
                })
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`Server returned ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    console.log('Match data received:', data);
                    Swal.close();
                    
                    // Find the modal
                    const modalId = `reportMatchModal-${matchId}`;
                    const modal = document.getElementById(modalId);
                    
                    if (!modal) {
                        console.error(`Modal #${modalId} not found, loading modals`);
                        
                        // Try to load modals
                        fetch('/modals/render_modals')
                            .then(response => response.text())
                            .then(html => {
                                document.body.insertAdjacentHTML('beforeend', html);
                                console.log('Modals loaded dynamically');
                                
                                // Now try to find the modal again
                                const modalRecheck = document.getElementById(modalId);
                                if (modalRecheck) {
                                    setupAndShowModal(modalRecheck, data);
                                } else {
                                    Swal.fire({
                                        icon: 'error',
                                        title: 'Error',
                                        text: 'Could not load the match reporting form. Please try refreshing the page.'
                                    });
                                }
                            })
                            .catch(error => {
                                console.error('Error loading modals:', error);
                                Swal.fire({
                                    icon: 'error',
                                    title: 'Error',
                                    text: 'Failed to load modals. Please try refreshing the page.'
                                });
                            });
                    } else {
                        setupAndShowModal(modal, data);
                    }
                })
                .catch(error => {
                    console.error('Error fetching match data:', error);
                    Swal.fire({
                        icon: 'error',
                        title: 'Error',
                        text: 'Failed to load match data. Please try again later.'
                    });
                });
            });
        });
    }
    
    // Helper function to set up and show the modal
    function setupAndShowModal(modal, data) {
        const matchId = data.id || modal.id.replace('reportMatchModal-', '');
        
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
        
        // Clear event containers
        const goalContainer = modal.querySelector(`#goalScorersContainer-${matchId}`);
        const assistContainer = modal.querySelector(`#assistProvidersContainer-${matchId}`);
        const yellowContainer = modal.querySelector(`#yellowCardsContainer-${matchId}`);
        const redContainer = modal.querySelector(`#redCardsContainer-${matchId}`);
        
        if (goalContainer) goalContainer.innerHTML = '';
        if (assistContainer) assistContainer.innerHTML = '';
        if (yellowContainer) yellowContainer.innerHTML = '';
        if (redContainer) redContainer.innerHTML = '';
        
        // Populate events (using the global addEvent function)
        try {
            // Define removeEvent function if not already defined
            if (typeof window.removeEvent !== 'function') {
                console.warn("removeEvent function not found, creating fallback");
                window.removeEvent = function(button) {
                    var eventEntry = button.closest('.player-event-entry') || button.closest('.input-group');
                    
                    if (!eventEntry) {
                        console.error("Could not find identifiable element");
                        return;
                    }
                    
                    var uniqueId = eventEntry.getAttribute('data-unique-id');
                    var statId = eventEntry.querySelector('input[name$="-stat_id[]"]')?.value;
                    
                    console.log("Removing event:", {
                        uniqueId: uniqueId,
                        statId: statId,
                        element: eventEntry
                    });
                    
                    // Add a class to hide but keep in DOM until save
                    eventEntry.classList.add('to-be-removed');
                    eventEntry.style.display = 'none';
                };
            }
            
            // Add goal scorers
            if (data.goal_scorers && Array.isArray(data.goal_scorers)) {
                data.goal_scorers.forEach(function(goal) {
                    if (typeof window.addEvent === 'function') {
                        window.addEvent(matchId, `goalScorersContainer-${matchId}`, goal.id, goal.player_id, goal.minute);
                    }
                });
            }
            
            // Add assist providers
            if (data.assist_providers && Array.isArray(data.assist_providers)) {
                data.assist_providers.forEach(function(assist) {
                    if (typeof window.addEvent === 'function') {
                        window.addEvent(matchId, `assistProvidersContainer-${matchId}`, assist.id, assist.player_id, assist.minute);
                    }
                });
            }
            
            // Add yellow cards
            if (data.yellow_cards && Array.isArray(data.yellow_cards)) {
                data.yellow_cards.forEach(function(card) {
                    if (typeof window.addEvent === 'function') {
                        window.addEvent(matchId, `yellowCardsContainer-${matchId}`, card.id, card.player_id, card.minute);
                    }
                });
            }
            
            // Add red cards
            if (data.red_cards && Array.isArray(data.red_cards)) {
                data.red_cards.forEach(function(card) {
                    if (typeof window.addEvent === 'function') {
                        window.addEvent(matchId, `redCardsContainer-${matchId}`, card.id, card.player_id, card.minute);
                    }
                });
            }
        } catch (error) {
            console.error('Error populating events:', error);
        }
        
        // Initialize and show the modal
        try {
            // Check if Bootstrap is available
            if (typeof bootstrap !== 'undefined') {
                // Create new modal instance
                const bsModal = new bootstrap.Modal(modal);
                bsModal.show();
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
        }
    }
    
    console.log('Edit match button fix initialized');
});