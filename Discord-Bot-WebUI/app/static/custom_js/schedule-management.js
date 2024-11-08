// schedule-management.js
class ScheduleManager {
    constructor() {
        this.modal = null;
        this.currentMatchId = null;
        this.isAddOperation = false;
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;

        this.initialize();
    }

    initialize() {
        document.addEventListener('DOMContentLoaded', () => {
            // Initialize modal
            const modalElement = document.getElementById('editMatchModal');
            if (modalElement) {
                this.modal = new bootstrap.Modal(modalElement);

                // Setup form submission
                const form = document.getElementById('editMatchForm');
                if (form) {
                    form.addEventListener('submit', (e) => this.handleEditSubmit(e));
                }
            }

            // Setup all buttons
            this.setupEditButtons();
            this.setupDeleteButtons();
            this.setupAddMatchButtons();
        });
    }

    setupAddMatchButtons() {
        document.querySelectorAll('.add-match-btn').forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                const weekData = {
                    week: button.dataset.week,
                    date: button.dataset.date,
                    league_id: button.dataset.leagueId
                };
                this.openAddMatchModal(weekData);
            });
        });
    }

    setupEditButtons() {
        document.querySelectorAll('.edit-match-btn').forEach(button => {
            button.addEventListener('click', (e) => {
                e.preventDefault();
                const matchData = {
                    match_id: button.dataset.matchId,
                    date: button.dataset.date,
                    time: button.dataset.time,
                    team_a: button.dataset.teamA,
                    team_b: button.dataset.teamB,
                    team_a_id: button.dataset.teamAId,
                    team_b_id: button.dataset.teamBId,
                    location: button.dataset.location,
                    week: button.dataset.week
                };
                this.openEditModal(matchData);
            });
        });
    }

    setupDeleteButtons() {
        document.querySelectorAll('.delete-match-btn').forEach(button => {
            button.addEventListener('click', async (e) => {
                e.preventDefault();
                await this.deleteMatch(button.dataset.matchId);
            });
        });
    }

    formatDate(dateString) {
        if (!dateString) return '';

        // Handle ISO format dates (YYYY-MM-DD)
        if (dateString.includes('-')) {
            return dateString;
        }

        try {
            // Handle date string format (MM/DD/YYYY)
            if (dateString.includes('/')) {
                const parts = dateString.split('/');
                if (parts.length === 3) {
                    const [month, day, year] = parts;
                    return `${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}`;
                }
            }

            // If none of the above formats match, try to parse as a date
            const date = new Date(dateString);
            if (!isNaN(date)) {
                const year = date.getFullYear();
                const month = (date.getMonth() + 1).toString().padStart(2, '0');
                const day = date.getDate().toString().padStart(2, '0');
                return `${year}-${month}-${day}`;
            }

            console.warn('Unable to parse date:', dateString);
            return '';
        } catch (e) {
            console.error('Error formatting date:', e);
            return '';
        }
    }

    formatTime(timeString) {
        if (!timeString) return '';
        const timeMatch = timeString.match(/(\d+):(\d+)\s*(AM|PM)/i);
        if (timeMatch) {
            let [_, hours, minutes, period] = timeMatch;
            hours = parseInt(hours);
            if (period.toUpperCase() === 'PM' && hours < 12) hours += 12;
            if (period.toUpperCase() === 'AM' && hours === 12) hours = 0;
            return `${hours.toString().padStart(2, '0')}:${minutes}`;
        }
        return timeString;
    }

    openAddMatchModal(weekData) {
        if (!this.modal) {
            console.error('Modal not initialized');
            return;
        }

        this.isAddOperation = true;
        this.currentMatchId = null;

        // Reset form
        const form = document.getElementById('editMatchForm');
        form.reset();

        // Set initial values
        document.getElementById('editWeek').value = weekData.week;

        // Handle the date more safely
        const dateValue = weekData.date ? this.formatDate(weekData.date) : '';
        document.getElementById('editDate').value = dateValue;

        // Update modal title and button
        document.getElementById('editMatchModalLabel').textContent = 'Add Match';
        document.querySelector('#editMatchForm button[type="submit"]').textContent = 'Add Match';

        this.modal.show();
    }

    openEditModal(matchData) {
        if (!this.modal) {
            console.error('Modal not initialized');
            return;
        }

        this.isAddOperation = false;
        this.currentMatchId = matchData.match_id;

        // Populate form fields
        document.getElementById('editMatchId').value = matchData.match_id;
        document.getElementById('editDate').value = this.formatDate(matchData.date);
        document.getElementById('editTime').value = this.formatTime(matchData.time);
        document.getElementById('editTeamA').value = matchData.team_a_id;
        document.getElementById('editTeamB').value = matchData.team_b_id;
        document.getElementById('editLocation').value = matchData.location;
        document.getElementById('editWeek').value = matchData.week;

        // Update modal title and button
        document.getElementById('editMatchModalLabel').textContent = 'Edit Match';
        document.querySelector('#editMatchForm button[type="submit"]').textContent = 'Save Changes';

        this.modal.show();
    }

    async handleEditSubmit(event) {
        event.preventDefault();
        const form = event.target;
        const formData = new FormData(form);

        try {
            const url = this.isAddOperation ?
                '/publeague/schedules/add_match' :
                `/publeague/schedules/edit_match/${this.currentMatchId}`;

            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Accept': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData
            });

            // Check if response is JSON
            const contentType = response.headers.get("content-type");
            if (!contentType || !contentType.includes("application/json")) {
                const text = await response.text();
                console.error('Non-JSON response:', text);
                throw new Error(`Server returned an invalid response. Status: ${response.status}`);
            }

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.message || `Server error: ${response.status}`);
            }

            if (result.success) {
                this.modal.hide();
                await Swal.fire({
                    title: 'Success!',
                    text: result.message || (this.isAddOperation ? 'Match added successfully' : 'Match updated successfully'),
                    icon: 'success',
                    timer: 1500
                });
                window.location.reload();
            } else {
                throw new Error(result.message || 'Failed to process match');
            }
        } catch (error) {
            console.error('Error processing match:', error);
            await Swal.fire({
                title: 'Error!',
                text: error.message || 'An unexpected error occurred',
                icon: 'error',
                showConfirmButton: true,
                confirmButtonText: 'OK'
            });
        }
    }

    async deleteMatch(matchId) {
        try {
            // Show confirmation dialog first
            const result = await Swal.fire({
                title: 'Are you sure?',
                text: "You won't be able to revert this!",
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#3085d6',
                cancelButtonColor: '#d33',
                confirmButtonText: 'Yes, delete it!'
            });

            // Only proceed if user confirmed
            if (result.isConfirmed) {
                const response = await fetch(`/publeague/schedules/delete_match/${matchId}`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': this.csrfToken,
                        'Accept': 'application/json',
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                const contentType = response.headers.get("content-type");
                if (!contentType || !contentType.includes("application/json")) {
                    throw new Error('Non-JSON response received from server');
                }

                const data = await response.json();

                if (data.success) {
                    await Swal.fire({
                        title: 'Deleted!',
                        text: 'Match has been deleted.',
                        icon: 'success',
                        timer: 1500
                    });
                    window.location.reload();
                } else {
                    throw new Error(data.error || 'Failed to delete match');
                }
            }
        } catch (error) {
            console.error('Error deleting match:', error);
            await Swal.fire({
                title: 'Error!',
                text: error.message || 'An error occurred while deleting the match',
                icon: 'error'
            });
        }
    }

    showAlert(message, type) {
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        `;

        const container = document.querySelector('.container');
        if (container) {
            container.insertBefore(alertDiv, container.firstChild);
            setTimeout(() => alertDiv.remove(), 3000);
        }
    }
}

// Initialize the schedule manager
const scheduleManager = new ScheduleManager();