/**
 * Draft Predictions JavaScript Module - Auto-save like Excel
 *
 * Handles instant auto-save functionality for draft predictions.
 * Changes are saved immediately when users make selections.
 */
// ES Module
'use strict';

import { ModalManager } from '../js/modal-manager.js';
import { InitSystem } from '../js/init-system.js';

let _initialized = false;

export class DraftPredictionsManager {
    constructor() {
        this.pendingSaves = new Map();
        this.saveTimeouts = new Map();
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
        row.classList.remove('table-success', 'table-warning', 'table-danger', 'is-saving', 'is-saved', 'is-error');

        if (status === 'saving') {
            row.classList.add('is-saving');
        } else if (status === true) {
            row.classList.add('is-saved');
        } else if (status === 'error') {
            row.classList.add('is-error');
        }
    }

    showAutoSaveStatus(status) {
        const statusElement = document.getElementById('autoSaveStatus');
        if (!statusElement) return;

        const savedSpan = statusElement.querySelector('[data-status="saved"]');
        const savingSpan = statusElement.querySelector('[data-status="saving"]');

        if (savedSpan) {
            savedSpan.classList.remove('is-active');
            savedSpan.classList.add('draft-status-saved');
        }
        if (savingSpan) {
            savingSpan.classList.remove('is-active');
            savingSpan.classList.add('draft-status-saving');
        }

        if (status === 'saved' && savedSpan) {
            savedSpan.classList.add('is-active');
        } else if (status === 'saving' && savingSpan) {
            savingSpan.classList.add('is-active');
        }
    }

    async submitPrediction(playerId, values) {
        try {
            const currentUrl = window.location.pathname;
            const seasonId = currentUrl.split('/').pop();

            const requestData = {
                draft_season_id: parseInt(seasonId),
                player_id: parseInt(playerId),
                predicted_round: values.predicted_round ? parseInt(values.predicted_round) : null,
                confidence_level: values.confidence_level ? parseInt(values.confidence_level) : null,
                notes: values.notes || ''
            };

            if (!requestData.predicted_round) {
                throw new Error('Predicted round is required');
            }

            const csrfToken = this.getCSRFToken();

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
        if (typeof window.Swal !== 'undefined') {
            const icon = type === 'success' ? 'success' : 'error';
            const title = type === 'success' ? 'Success!' : 'Error';

            window.Swal.fire({
                icon: icon,
                title: title,
                text: message,
                timer: 3000,
                showConfirmButton: false,
                toast: true,
                position: 'top-end'
            });
        } else {
            if (type === 'error') {
                console.error(message);
            }
        }
    }

    getCSRFToken() {
        const tokenMeta = document.querySelector('meta[name="csrf-token"]');
        if (tokenMeta) {
            const token = tokenMeta.getAttribute('content');
            if (token && token.trim()) {
                return token.trim();
            }
        }

        const tokenInput = document.querySelector('input[name="csrf_token"]');
        if (tokenInput && tokenInput.value) {
            return tokenInput.value.trim();
        }

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

        const modal = document.getElementById('playerImageModal');
        const modalImg = document.getElementById('playerImageModalImg');
        const modalName = document.getElementById('playerImageModalName');
        const modalLabel = document.getElementById('playerImageModalLabel');

        if (!modal || !modalImg || !modalName || !modalLabel) {
            console.error('Modal elements not found');
            return;
        }

        modalImg.src = fullImageUrl;
        modalImg.alt = playerName;
        modalName.textContent = playerName;
        modalLabel.textContent = `${playerName} - Player Photo`;

        ModalManager.show(modal.id);

        modalImg.onerror = function() {
            modalImg.src = imgElement.src;
            console.log('Full image failed to load, using thumbnail');
        };
    }
}

// Utility functions for quick access
window.DraftPredictions = {
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

    bulkSetRounds: function(roundMappings) {
        Object.entries(roundMappings).forEach(([playerId, round]) => {
            this.setPrediction(playerId, round);
        });
    }
};

// Export class to window
window.DraftPredictionsManager = DraftPredictionsManager;

// Initialize function
function init() {
    if (_initialized) return;
    _initialized = true;

    if (document.getElementById('playersTable')) {
        window.draftPredictionsManager = new DraftPredictionsManager();
    }
}

// ========================================================================
// EXPORTS
// ========================================================================

export { init };

// Register with InitSystem (primary)
if (InitSystem && InitSystem.register) {
    InitSystem.register('draft-predictions', init, {
        priority: 40,
        reinitializable: false,
        description: 'Draft predictions auto-save'
    });
}

// Fallback
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Backward compatibility
window.draftPredictionsInit = init;
