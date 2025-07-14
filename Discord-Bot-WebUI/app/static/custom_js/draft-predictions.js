/**
 * Draft Predictions JavaScript Module - Auto-save like Excel
 * 
 * Handles instant auto-save functionality for draft predictions.
 * Changes are saved immediately when users make selections.
 */

class DraftPredictionsManager {
    constructor() {
        this.pendingSaves = new Map(); // Track pending save operations
        this.saveTimeouts = new Map(); // Debounce saves
        this.init();
    }

    init() {
        this.bindEvents();
        this.showAutoSaveStatus('saved');
    }

    bindEvents() {
        // Auto-submit search form on input (with debouncing)
        const searchInput = document.querySelector('input[name="search"]');
        if (searchInput) {
            let searchTimeout;
            searchInput.addEventListener('input', (e) => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    this.submitFilterForm();
                }, 500);
            });
        }

        // Auto-submit on position filter change
        const positionFilter = document.querySelector('select[name="position"]');
        if (positionFilter) {
            positionFilter.addEventListener('change', (e) => {
                this.submitFilterForm();
            });
        }

        // Auto-save on any change to prediction fields
        document.addEventListener('change', (e) => {
            if (e.target.matches('.predicted-round-input, .confidence-input')) {
                this.handleFieldChange(e.target);
            }
        });

        // Auto-save notes with debouncing
        document.addEventListener('input', (e) => {
            if (e.target.matches('.notes-input')) {
                this.handleNotesChange(e.target);
            }
        });

        // Player image modal
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('player-avatar-clickable')) {
                this.showPlayerImageModal(e.target);
            }
        });
    }

    handleFieldChange(input) {
        const playerId = input.dataset.playerId;
        this.autoSavePrediction(playerId);
    }

    handleNotesChange(input) {
        const playerId = input.dataset.playerId;
        
        // Clear existing timeout for this player
        if (this.saveTimeouts.has(playerId)) {
            clearTimeout(this.saveTimeouts.get(playerId));
        }

        // Set new timeout for debounced save (500ms after user stops typing)
        const timeoutId = setTimeout(() => {
            this.autoSavePrediction(playerId);
            this.saveTimeouts.delete(playerId);
        }, 500);

        this.saveTimeouts.set(playerId, timeoutId);
    }

    async autoSavePrediction(playerId) {
        // Don't start new save if one is already pending for this player
        if (this.pendingSaves.has(playerId)) {
            return;
        }

        const values = this.getPlayerCurrentValues(playerId);
        
        // Only save if there's a predicted round
        if (!values.predicted_round) {
            this.updateRowAppearance(playerId, false);
            return;
        }

        try {
            this.pendingSaves.set(playerId, true);
            this.showAutoSaveStatus('saving');
            this.updateRowAppearance(playerId, 'saving');

            await this.submitPrediction(playerId, values);
            
            this.updateRowAppearance(playerId, true);
            this.showAutoSaveStatus('saved');

        } catch (error) {
            console.error('Auto-save failed for player', playerId, error);
            this.updateRowAppearance(playerId, 'error');
            this.showToast('error', `Failed to save prediction for ${this.getPlayerName(playerId)}`);
        } finally {
            this.pendingSaves.delete(playerId);
        }
    }

    getPlayerCurrentValues(playerId) {
        const row = document.querySelector(`tr[data-player-id="${playerId}"]`);
        if (!row) return {};

        const roundInput = row.querySelector('.predicted-round-input');
        const confidenceInput = row.querySelector('.confidence-input');
        const notesInput = row.querySelector('.notes-input');

        return {
            predicted_round: roundInput ? roundInput.value : '',
            confidence_level: confidenceInput ? confidenceInput.value : '',
            notes: notesInput ? notesInput.value : ''
        };
    }

    getPlayerName(playerId) {
        const row = document.querySelector(`tr[data-player-id="${playerId}"]`);
        if (row) {
            const nameElement = row.querySelector('.fw-medium');
            return nameElement ? nameElement.textContent : `Player ${playerId}`;
        }
        return `Player ${playerId}`;
    }

    updateRowAppearance(playerId, status) {
        const row = document.querySelector(`tr[data-player-id="${playerId}"]`);
        if (!row) return;

        // Remove all status classes
        row.classList.remove('table-success', 'table-warning', 'table-danger');

        if (status === 'saving') {
            row.classList.add('table-warning');
        } else if (status === true) {
            row.classList.add('table-success');
        } else if (status === 'error') {
            row.classList.add('table-danger');
        }
        // If status === false (no prediction), no special class
    }

    showAutoSaveStatus(status) {
        const statusElement = document.getElementById('autoSaveStatus');
        if (!statusElement) return;

        const savedSpan = statusElement.querySelector('.text-success');
        const savingSpan = statusElement.querySelector('.text-warning');

        // Hide all status indicators
        if (savedSpan) savedSpan.style.display = 'none';
        if (savingSpan) savingSpan.style.display = 'none';

        // Show appropriate status
        if (status === 'saved' && savedSpan) {
            savedSpan.style.display = 'inline';
        } else if (status === 'saving' && savingSpan) {
            savingSpan.style.display = 'inline';
        }
    }

    async submitPrediction(playerId, values) {
        try {
            // Get current draft season ID from URL
            const currentUrl = window.location.pathname;
            const seasonId = currentUrl.split('/').pop();

            const requestData = {
                draft_season_id: parseInt(seasonId),
                player_id: parseInt(playerId),
                predicted_round: values.predicted_round ? parseInt(values.predicted_round) : null,
                confidence_level: values.confidence_level ? parseInt(values.confidence_level) : null,
                notes: values.notes || ''
            };

            // Must have a predicted round to save
            if (!requestData.predicted_round) {
                throw new Error('Predicted round is required');
            }

            const csrfToken = this.getCSRFToken();
            console.log('Auto-saving prediction:', requestData);
            console.log('CSRF token:', csrfToken);

            const response = await fetch('/draft-predictions/predict', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(requestData)
            });

            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const result = await response.json();
            console.log('Auto-save response:', result);

            if (!result.success) {
                throw new Error(result.message || 'Failed to save prediction');
            }

            return result;

        } catch (error) {
            console.error('Error submitting prediction:', error);
            throw error;
        }
    }

    submitFilterForm() {
        const filterForm = document.getElementById('filterForm');
        if (filterForm) {
            filterForm.submit();
        }
    }

    showToast(type, message) {
        // Use SweetAlert2 if available, otherwise fall back to browser alert
        if (typeof Swal !== 'undefined') {
            const icon = type === 'success' ? 'success' : 'error';
            const title = type === 'success' ? 'Success!' : 'Error';
            
            Swal.fire({
                icon: icon,
                title: title,
                text: message,
                timer: 3000,
                showConfirmButton: false,
                toast: true,
                position: 'top-end'
            });
        } else {
            // Only show errors in console to avoid spamming user
            if (type === 'error') {
                console.error(message);
            }
        }
    }

    getCSRFToken() {
        // Get CSRF token from meta tag first (most reliable)
        const tokenMeta = document.querySelector('meta[name="csrf-token"]');
        if (tokenMeta) {
            const token = tokenMeta.getAttribute('content');
            if (token && token.trim()) {
                return token.trim();
            }
        }

        // Fallback: get from form
        const tokenInput = document.querySelector('input[name="csrf_token"]');
        if (tokenInput && tokenInput.value) {
            return tokenInput.value.trim();
        }

        // Last resort: get from cookies
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrf_token' && value) {
                return value.trim();
            }
        }

        console.error('CSRF token not found');
        return '';
    }

    showPlayerImageModal(imgElement) {
        const playerName = imgElement.dataset.playerName;
        const fullImageUrl = imgElement.dataset.fullImage;
        
        if (!fullImageUrl) {
            console.log('No full image URL available for player:', playerName);
            return;
        }

        // Get modal elements
        const modal = document.getElementById('playerImageModal');
        const modalImg = document.getElementById('playerImageModalImg');
        const modalName = document.getElementById('playerImageModalName');
        const modalLabel = document.getElementById('playerImageModalLabel');

        if (!modal || !modalImg || !modalName || !modalLabel) {
            console.error('Modal elements not found');
            return;
        }

        // Set modal content
        modalImg.src = fullImageUrl;
        modalImg.alt = playerName;
        modalName.textContent = playerName;
        modalLabel.textContent = `${playerName} - Player Photo`;

        // Show modal using Bootstrap 5
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        // Handle image load error
        modalImg.onerror = function() {
            modalImg.src = imgElement.src; // Fallback to thumbnail
            console.log('Full image failed to load, using thumbnail');
        };
    }
}

// Utility functions for quick access
window.DraftPredictions = {
    // Quick prediction submission for specific player
    setPrediction: function(playerId, round, confidence = null, notes = '') {
        const row = document.querySelector(`tr[data-player-id="${playerId}"]`);
        if (row) {
            const roundInput = row.querySelector('.predicted-round-input');
            const confidenceInput = row.querySelector('.confidence-input');
            const notesInput = row.querySelector('.notes-input');

            if (roundInput) {
                roundInput.value = round;
                roundInput.dispatchEvent(new Event('change'));
            }
            if (confidence && confidenceInput) {
                confidenceInput.value = confidence;
                confidenceInput.dispatchEvent(new Event('change'));
            }
            if (notes && notesInput) {
                notesInput.value = notes;
                notesInput.dispatchEvent(new Event('input'));
            }
        }
    },

    // Bulk prediction helper
    bulkSetRounds: function(roundMappings) {
        Object.entries(roundMappings).forEach(([playerId, round]) => {
            this.setPrediction(playerId, round);
        });
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('playersTable')) {
        window.draftPredictionsManager = new DraftPredictionsManager();
    }
});