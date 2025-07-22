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
        
        const modal = new bootstrap.Modal(document.getElementById('editDraftPickModal'));
        modal.show();
    }

    // Handle edit form submission
    async handleEditSubmit(e) {
        e.preventDefault();
        
        const pickId = document.getElementById('editPickId').value;
        const position = parseInt(document.getElementById('editDraftPosition').value);
        const notes = document.getElementById('editNotes').value.trim();
        
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
                    notes: notes
                })
            });

            const data = await response.json();
            
            if (data.success) {
                this.showAlert('success', data.message);
                bootstrap.Modal.getInstance(document.getElementById('editDraftPickModal')).hide();
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
        const confirmed = confirm(
            `Are you sure you want to delete draft pick #${position} (${playerName} to ${teamName})?\n\n` +
            'This will adjust all subsequent draft positions and cannot be undone.'
        );

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

    // Clear all draft picks for a season/league
    async clearSeasonLeague(seasonId, leagueId, seasonName, leagueName) {
        const confirmed = confirm(
            `Are you sure you want to clear ALL draft picks for ${seasonName} - ${leagueName}?\n\n` +
            'This action cannot be undone.'
        );

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
        const alertClass = type === 'success' ? 'alert-success' : 'alert-danger';
        const iconClass = type === 'success' ? 'ti-check' : 'ti-x';
        
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
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }
}

// Global functions for template compatibility
let draftHistoryManager;

function clearFilters() {
    draftHistoryManager.clearFilters();
}

function editDraftPick(pickId, position, notes, playerName) {
    draftHistoryManager.editDraftPick(pickId, position, notes, playerName);
}

function deleteDraftPick(pickId, position, playerName, teamName) {
    draftHistoryManager.deleteDraftPick(pickId, position, playerName, teamName);
}

function clearSeasonLeague(seasonId, leagueId, seasonName, leagueName) {
    draftHistoryManager.clearSeasonLeague(seasonId, leagueId, seasonName, leagueName);
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    draftHistoryManager = new DraftHistoryManager();
    
    // Initialize tooltips
    draftHistoryManager.initTooltips();
    
    console.log('Draft History interface loaded successfully');
});