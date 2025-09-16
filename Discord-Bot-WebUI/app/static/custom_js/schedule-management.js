// schedule-management.js
class ScheduleManager {
    constructor() {
        // We'll store references to the "Add/Edit Match" modal and the "Add Single Week" form
        this.editMatchModal = null;
        this.isAddOperation = false;  // determines if the modal is adding or editing
        this.currentMatchId = null;

        // Attempt to read CSRF from hidden form fields or meta
        this.csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || null;

        this.init();
    }

    init() {
        document.addEventListener('DOMContentLoaded', () => {
            // Hook up the Edit/Match modal
            const modalEl = document.getElementById('editMatchModal');
            if (modalEl) {
                this.editMatchModal = new bootstrap.Modal(modalEl);

                // The form inside the modal
                const editForm = document.getElementById('editMatchForm');
                if (editForm) {
                    editForm.addEventListener('submit', (evt) => this.handleMatchFormSubmit(evt));
                }
            }

            // Listen for the "Add Single Week" modal's dynamic parts
            this.setupSingleWeekModal();

            // Set up each type of button
            this.setupEditButtons();
            this.setupDeleteButtons();
            this.setupAddMatchButtons();
        });
    }

    // ----------------------------------------------------------------
    // 1) SINGLE WEEK MODAL / TIME SLOTS
    // ----------------------------------------------------------------
    setupSingleWeekModal() {
        // We assume there's a button that triggers #addSingleWeekModal
        const addWeekModal = document.getElementById('addSingleWeekModal');
        if (!addWeekModal) return;

        // When the modal shows, we set the league_id and clear old timeslots
        addWeekModal.addEventListener('show.bs.modal', (event) => {
            const button = event.relatedTarget;
            if (!button) return;
            const leagueId = button.getAttribute('data-league-id');
            document.getElementById('singleWeekLeagueId').value = leagueId;
            document.getElementById('singleWeekTimeSlots').innerHTML = '';

            // Add at least one slot
            this.addSingleWeekTimeSlot();
        });

        // "Add Time Slot" button
        const addTimeSlotBtn = document.getElementById('addTimeSlotBtn');
        if (addTimeSlotBtn) {
            addTimeSlotBtn.addEventListener('click', (e) => {
                e.preventDefault();
                this.addSingleWeekTimeSlot();
            });
        }

        // Handle the singleWeek form submission
        const singleWeekForm = document.getElementById('addSingleWeekForm');
        if (singleWeekForm) {
            singleWeekForm.addEventListener('submit', (evt) => this.handleSingleWeekSubmit(evt));
        }
    }

    addSingleWeekTimeSlot() {
        // Generate one row with time, field, team_a, team_b
        const container = document.getElementById('singleWeekTimeSlots');
        if (!container) return;

        // Read the leagueId so we can build the team dropdown
        const leagueId = document.getElementById('singleWeekLeagueId').value;
        const teams = window.leagueTeams[leagueId] || [];

        let optionsHtml = '<option value="">--Select--</option>';
        teams.forEach(t => {
            optionsHtml += `<option value="${t.id}">${t.name}</option>`;
        });

        const row = document.createElement('div');
        row.className = 'row g-2 mb-2';

        row.innerHTML = `
          <div class="col-md-3">
            <input type="time" name="times[]" class="form-control" required>
          </div>
          <div class="col-md-3">
            <select name="fields[]" class="form-select" required>
              <option value="North">North</option>
              <option value="South">South</option>
            </select>
          </div>
          <div class="col-md-3">
            <select name="team_a[]" class="form-select" required>
              ${optionsHtml}
            </select>
          </div>
          <div class="col-md-3">
            <div class="input-group">
              <select name="team_b[]" class="form-select" required>
                ${optionsHtml}
              </select>
              <button type="button" class="btn btn-danger" onclick="this.closest('.row').remove()">
                <i class="ti ti-trash"></i>
              </button>
            </div>
          </div>
        `;
        container.appendChild(row);
    }

    async handleSingleWeekSubmit(evt) {
        evt.preventDefault();
        const form = evt.target;
        const formData = new FormData(form);

        try {
            const resp = await fetch(form.action || '/publeague/schedules/add_single_week', {
                method: 'POST',
                body: formData
            });
            const result = await resp.json();
            if (result.success) {
                bootstrap.Modal.getInstance(document.getElementById('addSingleWeekModal')).hide();
                location.reload();
            } else {
                alert(result.message || 'Error adding single week');
            }
        } catch (err) {
            // console.error('Error in handleSingleWeekSubmit:', err);
            alert('Error adding single week');
        }
    }

    // ----------------------------------------------------------------
    // 2) EDIT/ADD MATCH LOGIC
    // ----------------------------------------------------------------
    setupAddMatchButtons() {
        // .schedule-add-match-btn => open the edit modal in "Add" mode
        document.querySelectorAll('.schedule-add-match-btn').forEach(btn => {
            btn.addEventListener('click', (evt) => {
                evt.preventDefault();
                const data = {
                    league_id: btn.dataset.leagueId,
                    week: btn.dataset.week,
                    date: btn.dataset.date
                };
                this.openAddMatchModal(data);
            });
        });
    }

    setupEditButtons() {
        // .schedule-edit-match-btn => open the edit modal in "Edit" mode
        document.querySelectorAll('.schedule-edit-match-btn').forEach(btn => {
            btn.addEventListener('click', (evt) => {
                evt.preventDefault();
                const matchData = {
                    match_id: btn.dataset.matchId,
                    date: btn.dataset.date,
                    time: btn.dataset.time,
                    location: btn.dataset.location,
                    team_a_id: btn.dataset.teamAId,
                    team_b_id: btn.dataset.teamBId,
                    week: btn.dataset.week
                };
                this.openEditMatchModal(matchData);
            });
        });
    }

    setupDeleteButtons() {
        // .schedule-delete-match-btn => confirm + POST delete
        document.querySelectorAll('.schedule-delete-match-btn').forEach(btn => {
            btn.addEventListener('click', async (evt) => {
                evt.preventDefault();
                const matchId = btn.dataset.matchId;
                this.deleteMatch(matchId);
            });
        });
    }

    openAddMatchModal({ league_id, week, date }) {
        if (!this.editMatchModal) {
            // console.error('No edit match modal found.');
            return;
        }
        this.isAddOperation = true;
        this.currentMatchId = null;

        // Reset the form
        const form = document.getElementById('editMatchForm');
        form.reset();

        // Set default values (week, date)
        document.getElementById('editWeek').value = week;
        document.getElementById('editDate').value = this.toISODate(date);

        // Change label, button text
        document.getElementById('editMatchModalLabel').textContent = 'Add Match';
        form.querySelector('button[type="submit"]').textContent = 'Add Match';

        // Show modal
        this.editMatchModal.show();
    }

    openEditMatchModal(matchData) {
        if (!this.editMatchModal) {
            // console.error('No edit match modal found.');
            return;
        }
        this.isAddOperation = false;
        this.currentMatchId = matchData.match_id;

        // Fill the form fields
        document.getElementById('editMatchId').value = matchData.match_id;
        document.getElementById('editWeek').value = matchData.week || '';
        document.getElementById('editDate').value = this.toISODate(matchData.date);
        document.getElementById('editTime').value = this.toISOTime(matchData.time);
        document.getElementById('editLocation').value = matchData.location || '';
        // TeamA + TeamB
        document.getElementById('editTeamA').value = matchData.team_a_id || '';
        document.getElementById('editTeamB').value = matchData.team_b_id || '';

        // Change label, button text
        document.getElementById('editMatchModalLabel').textContent = 'Edit Match';
        document.querySelector('#editMatchForm button[type="submit"]').textContent = 'Save Changes';

        this.editMatchModal.show();
    }

    // POST the form to either add_match or edit_match
    async handleMatchFormSubmit(evt) {
        evt.preventDefault();
        const form = evt.target;
        const formData = new FormData(form);

        const url = this.isAddOperation
            ? '/publeague/schedules/add_match'
            : `/publeague/schedules/edit_match/${this.currentMatchId}`;

        try {
            const resp = await fetch(url, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                    // optionally 'X-CSRFToken': this.csrfToken if needed
                }
            });
            const data = await resp.json();
            if (data.success) {
                this.editMatchModal.hide();
                alert(data.message || (this.isAddOperation
                    ? 'Match created successfully' : 'Match updated successfully'));
                location.reload();
            } else {
                alert(data.message || 'Failed to save match');
            }
        } catch (err) {
            // console.error('Error in handleMatchFormSubmit:', err);
            alert('Error saving match');
        }
    }

    async deleteMatch(matchId) {
        if (!confirm('Are you sure you want to delete this match?')) {
            return;
        }

        try {
            const resp = await fetch(`/publeague/schedules/delete_match/${matchId}`, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            const data = await resp.json();
            if (data.success) {
                alert(data.message || 'Match deleted');
                location.reload();
            } else {
                alert(data.message || 'Failed to delete match');
            }
        } catch (err) {
            // console.error('Error deleting match:', err);
            alert('Error deleting match');
        }
    }

    // Helpers for date/time
    toISODate(val) {
        // If already "YYYY-MM-DD", just return
        if (/^\d{4}-\d{2}-\d{2}$/.test(val)) return val;
        // Otherwise try to parse
        const d = new Date(val);
        if (isNaN(d)) return '';
        const yyyy = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        return `${yyyy}-${mm}-${dd}`;
    }

    toISOTime(val) {
        // If already "HH:MM"
        if (/^\d{2}:\d{2}$/.test(val)) return val;
        // If "7:30 PM"
        const match = val.match(/(\d{1,2}):(\d{2})\s*(AM|PM)/i);
        if (!match) return val; // fallback
        let [_, hh, mm, ampm] = match;
        let h = parseInt(hh, 10);
        ampm = ampm.toUpperCase();
        if (ampm === 'PM' && h < 12) h += 12;
        if (ampm === 'AM' && h === 12) h = 0;
        return String(h).padStart(2, '0') + ':' + mm;
    }
}

// Instantiate once DOM is loaded
new ScheduleManager();