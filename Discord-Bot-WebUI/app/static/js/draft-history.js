import { ModalManager } from './modal-manager.js';

/**
 * Draft History Admin Interface
 * JavaScript functionality for managing draft order history
 */

class DraftHistoryManager {
    constructor() {
        this.csrfToken = null;
        this.init();
    }

    init() {
        this.setupEventListeners();
        this.getCsrfToken();
        this.initDragAndDrop();
        console.log('Draft History Manager initialized');
    }

    // Get CSRF token from meta tag or cookie
    getCsrfToken() {
        // Try to get from meta tag first
        const metaToken = document.querySelector('meta[name="csrf-token"]');
        if (metaToken) {
            this.csrfToken = metaToken.getAttribute('content');
            return;
        }
        
        // Try to get from session cookie (fallback)
        const cookies = document.cookie.split(';');
        for (let cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'csrf_token') {
                this.csrfToken = value;
                return;
            }
        }
        
        console.warn('CSRF token not found');
    }

    setupEventListeners() {
        // Edit form submission
        const editForm = document.getElementById('editDraftPickForm');
        if (editForm) {
            editForm.addEventListener('submit', (e) => this.handleEditSubmit(e));
        }
    }

    // Initialize drag and drop functionality
    initDragAndDrop() {
        const sortableContainers = document.querySelectorAll('.sortable-draft-picks');
        
        sortableContainers.forEach(container => {
            const items = container.querySelectorAll('.sortable-item');
            
            items.forEach(item => {
                const draggableCard = item.querySelector('.draggable-card');
                
                // Drag start
                draggableCard.addEventListener('dragstart', (e) => {
                    item.classList.add('dragging');
                    container.classList.add('drag-active');
                    
                    // Store dragged player info for better UX
                    const playerName = item.querySelector('h6').textContent;
                    const currentPos = item.dataset.position;
                    
                    e.dataTransfer.setData('text/plain', item.dataset.pickId);
                    e.dataTransfer.setData('application/x-player-name', playerName);
                    e.dataTransfer.setData('application/x-current-pos', currentPos);
                    e.dataTransfer.effectAllowed = 'move';
                    
                    // Create custom drag image with better visibility
                    const dragImage = item.cloneNode(true);
                    dragImage.classList.add('drag-image-preview');
                    document.body.appendChild(dragImage);
                    e.dataTransfer.setDragImage(dragImage, 100, 50);
                    
                    // Remove the temporary drag image after a brief delay
                    setTimeout(() => {
                        if (document.body.contains(dragImage)) {
                            document.body.removeChild(dragImage);
                        }
                    }, 0);
                });
                
                // Drag end
                draggableCard.addEventListener('dragend', (e) => {
                    item.classList.remove('dragging');
                    container.classList.remove('drag-active');
                    
                    // Remove all drag-over classes
                    items.forEach(i => i.classList.remove('drag-over'));
                });
                
                // Drag over
                item.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    e.dataTransfer.dropEffect = 'move';
                    
                    if (!item.classList.contains('dragging')) {
                        item.classList.add('drag-over');
                    }
                });
                
                // Drag leave
                item.addEventListener('dragleave', (e) => {
                    // Only remove drag-over if we're actually leaving this element
                    if (!item.contains(e.relatedTarget)) {
                        item.classList.remove('drag-over');
                    }
                });
                
                // Drop
                item.addEventListener('drop', (e) => {
                    e.preventDefault();
                    item.classList.remove('drag-over');
                    container.classList.remove('drag-active');
                    
                    const draggedPickId = e.dataTransfer.getData('text/plain');
                    const playerName = e.dataTransfer.getData('application/x-player-name');
                    const currentPos = e.dataTransfer.getData('application/x-current-pos');
                    const targetPosition = parseInt(item.dataset.position);
                    
                    if (draggedPickId && targetPosition) {
                        // Show immediate feedback
                        this.showAlert('info', `Moving ${playerName} from position #${currentPos} to #${targetPosition}...`);
                        this.handleDragDrop(draggedPickId, targetPosition, playerName);
                    }
                });
            });
        });
    }

    // Handle drag and drop reordering
    async handleDragDrop(pickId, newPosition, playerName = 'Player') {
        try {
            const headers = {
                'Content-Type': 'application/json',
            };
            
            // Add CSRF token if available
            if (this.csrfToken) {
                headers['X-CSRFToken'] = this.csrfToken;
            }
            
            const response = await fetch(`/admin/draft-history/edit/${pickId}`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    position: newPosition,
                    mode: 'smart' // Use smart mode for drag and drop
                })
            });

            const data = await response.json();
            
            if (data.success) {
                this.showAlert('success', `Player moved to position #${newPosition}`);
                this.reloadPage();
            } else {
                this.showAlert('error', data.message);
            }
        } catch (error) {
            this.showAlert('error', 'Failed to reorder draft pick');
            console.error('Error reordering draft pick:', error);
        }
    }

    // Clear all filters
    clearFilters() {
        const currentUrl = new URL(window.location);
        currentUrl.search = '';
        window.location.href = currentUrl.toString();
    }

    // Show edit modal for a draft pick
    editDraftPick(pickId, position, notes, playerName) {
        document.getElementById('editPickId').value = pickId;
        document.getElementById('editPlayerName').value = playerName;
        document.getElementById('editDraftPosition').value = position;
        document.getElementById('editNotes').value = notes || '';

        window.ModalManager.show('editDraftPickModal');
    }

    // Handle edit form submission
    async handleEditSubmit(e) {
        e.preventDefault();
        
        const pickId = document.getElementById('editPickId').value;
        const position = parseInt(document.getElementById('editDraftPosition').value);
        const notes = document.getElementById('editNotes').value.trim();
        
        // Determine which mode is selected
        let mode = 'smart'; // new default - smart reorder
        if (document.getElementById('insertMode').checked) {
            mode = 'insert';
        } else if (document.getElementById('cascadingMode').checked) {
            mode = 'cascading';
        } else if (document.getElementById('absoluteMode').checked) {
            mode = 'absolute';
        }
        
        try {
            const headers = {
                'Content-Type': 'application/json',
            };
            
            // Add CSRF token if available
            if (this.csrfToken) {
                headers['X-CSRFToken'] = this.csrfToken;
            }
            
            const response = await fetch(`/admin/draft-history/edit/${pickId}`, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    position: position,
                    notes: notes,
                    mode: mode
                })
            });

            const data = await response.json();
            
            if (data.success) {
                this.showAlert('success', data.message);
                window.bootstrap.Modal.getInstance(document.getElementById('editDraftPickModal')).hide();
                this.reloadPage();
            } else {
                this.showAlert('error', data.message);
            }
        } catch (error) {
            this.showAlert('error', 'Failed to update draft pick');
            console.error('Error updating draft pick:', error);
        }
    }

    // Delete a draft pick
    async deleteDraftPick(pickId, position, playerName, teamName) {
        let confirmed = false;
        if (typeof window.Swal !== 'undefined') {
            const result = await window.Swal.fire({
                title: 'Delete Draft Pick?',
                html: `Are you sure you want to delete draft pick #${position} (<strong>${playerName}</strong> to <strong>${teamName}</strong>)?<br><br>This will adjust all subsequent draft positions and cannot be undone.`,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, Delete',
                cancelButtonText: 'Cancel',
                customClass: {
                    confirmButton: 'btn btn-danger',
                    cancelButton: 'btn btn-secondary'
                },
                buttonsStyling: false
            });
            confirmed = result.isConfirmed;
        }

        if (!confirmed) return;

        try {
            const headers = {
                'Content-Type': 'application/json',
            };
            
            // Add CSRF token if available
            if (this.csrfToken) {
                headers['X-CSRFToken'] = this.csrfToken;
            }
            
            const response = await fetch(`/admin/draft-history/delete/${pickId}`, {
                method: 'DELETE',
                headers: headers
            });

            const data = await response.json();
            
            if (data.success) {
                this.showAlert('success', data.message);
                this.reloadPage();
            } else {
                this.showAlert('error', data.message);
            }
        } catch (error) {
            this.showAlert('error', 'Failed to delete draft pick');
            console.error('Error deleting draft pick:', error);
        }
    }

    // Normalize draft positions for a season/league
    async normalizeDraftPositions(seasonId, leagueId, seasonName, leagueName) {
        let confirmed = false;
        if (typeof window.Swal !== 'undefined') {
            const result = await window.Swal.fire({
                title: 'Fix Draft Order?',
                html: `Fix the draft order for <strong>${seasonName} - ${leagueName}</strong>?<br><br>This will renumber all positions to run 1, 2, 3, 4... with no gaps. This action cannot be undone.`,
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Yes, Fix Order',
                cancelButtonText: 'Cancel',
                customClass: {
                    confirmButton: 'btn btn-primary',
                    cancelButton: 'btn btn-secondary'
                },
                buttonsStyling: false
            });
            confirmed = result.isConfirmed;
        }

        if (!confirmed) return;

        try {
            const headers = {
                'Content-Type': 'application/json',
            };
            
            // Add CSRF token if available
            if (this.csrfToken) {
                headers['X-CSRFToken'] = this.csrfToken;
            }
            
            const response = await fetch('/admin/draft-history/normalize', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    season_id: seasonId,
                    league_id: leagueId
                })
            });

            const data = await response.json();
            
            if (data.success) {
                this.showAlert('success', data.message);
                this.reloadPage();
            } else {
                this.showAlert('error', data.message);
            }
        } catch (error) {
            this.showAlert('error', 'Failed to normalize draft positions');
            console.error('Error normalizing draft positions:', error);
        }
    }

    // Clear all draft picks for a season/league
    async clearSeasonLeague(seasonId, leagueId, seasonName, leagueName) {
        let confirmed = false;
        if (typeof window.Swal !== 'undefined') {
            const result = await window.Swal.fire({
                title: 'Clear All Draft Picks?',
                html: `Are you sure you want to clear <strong>ALL</strong> draft picks for <strong>${seasonName} - ${leagueName}</strong>?<br><br>This action cannot be undone.`,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonText: 'Yes, Clear All',
                cancelButtonText: 'Cancel',
                customClass: {
                    confirmButton: 'btn btn-danger',
                    cancelButton: 'btn btn-secondary'
                },
                buttonsStyling: false
            });
            confirmed = result.isConfirmed;
        }

        if (!confirmed) return;

        try {
            const headers = {
                'Content-Type': 'application/json',
            };
            
            // Add CSRF token if available
            if (this.csrfToken) {
                headers['X-CSRFToken'] = this.csrfToken;
            }
            
            const response = await fetch('/admin/draft-history/clear', {
                method: 'POST',
                headers: headers,
                body: JSON.stringify({
                    season_id: seasonId,
                    league_id: leagueId
                })
            });

            const data = await response.json();
            
            if (data.success) {
                this.showAlert('success', data.message);
                this.reloadPage();
            } else {
                this.showAlert('error', data.message);
            }
        } catch (error) {
            this.showAlert('error', 'Failed to clear draft history');
            console.error('Error clearing draft history:', error);
        }
    }

    // Show alert message
    showAlert(type, message) {
        let alertClass, iconClass;
        if (type === 'success') {
            alertClass = 'alert-success';
            iconClass = 'ti-check';
        } else if (type === 'info') {
            alertClass = 'alert-info';
            iconClass = 'ti-info-circle';
        } else {
            alertClass = 'alert-danger';
            iconClass = 'ti-x';
        }
        
        const alertHtml = `
            <div class="alert ${alertClass} alert-dismissible fade show" role="alert">
                <i class="ti ${iconClass} me-2"></i>${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>
        `;
        
        const container = document.querySelector('.container-xxl');
        if (container) {
            container.insertAdjacentHTML('afterbegin', alertHtml);
            
            // Auto-dismiss after 5 seconds
            setTimeout(() => {
                const alert = container.querySelector('.alert');
                if (alert) {
                    alert.remove();
                }
            }, 5000);
        }
    }

    // Reload the page with a slight delay
    reloadPage() {
        setTimeout(() => {
            window.location.reload();
        }, 1000);
    }

    // Initialize tooltips if available
    initTooltips() {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new window.bootstrap.Tooltip(tooltipTriggerEl);
        });
    }
}

// Global functions for template compatibility (using var to allow safe re-declaration if script loads twice)
var draftHistoryManager;

function clearFilters() {
    draftHistoryManager.clearFilters();
}

function editDraftPick(pickId, position, notes, playerName) {
    draftHistoryManager.editDraftPick(pickId, position, notes, playerName);
}

function deleteDraftPick(pickId, position, playerName, teamName) {
    draftHistoryManager.deleteDraftPick(pickId, position, playerName, teamName);
}

function normalizeDraftPositions(seasonId, leagueId, seasonName, leagueName) {
    draftHistoryManager.normalizeDraftPositions(seasonId, leagueId, seasonName, leagueName);
}

function clearSeasonLeague(seasonId, leagueId, seasonName, leagueName) {
    draftHistoryManager.clearSeasonLeague(seasonId, leagueId, seasonName, leagueName);
}

import { InitSystem } from './init-system.js';

let _initialized = false;

function initDraftHistory() {
    if (_initialized) return;

    // Page guard - only run on draft history page
    if (!document.querySelector('.sortable-draft-picks') && !document.getElementById('editDraftPickForm')) {
        return; // Not on draft history page
    }

    _initialized = true;

    draftHistoryManager = new DraftHistoryManager();

    // Initialize tooltips
    draftHistoryManager.initTooltips();

    console.log('Draft History interface loaded successfully');
}

window.InitSystem.register('draft-history', initDraftHistory, {
    priority: 30,
    reinitializable: false,
    description: 'Draft history admin interface'
});

// Fallback
// window.InitSystem handles initialization

// No window exports needed - InitSystem handles initialization
// All functions are used internally via event delegation
