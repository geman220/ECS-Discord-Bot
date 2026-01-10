/**
 * Schedule Management
 * Handles match scheduling, editing, and deletion
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
import { ModalManager } from '../js/modal-manager.js';
let _initialized = false;

export class ScheduleManager {
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
                this.editMatchModal = window.ModalManager.getInstance('editMatchModal');
            }

            // Set up all event handlers using delegation
            this.setupFormDelegation();
            this.setupSingleWeekModal();
            this.setupEditButtons();
            this.setupDeleteButtons();
            this.setupAddMatchButtons();
            this.setupEventDelegation();
        });
    }

    /**
     * Setup delegated form submission handlers
     */
    setupFormDelegation() {
        const self = this;

        // Delegated submit handler for forms
        document.addEventListener('submit', function(e) {
            // Edit match form
            if (e.target.id === 'editMatchForm') {
                self.handleMatchFormSubmit(e);
                return;
            }

            // Single week form
            if (e.target.id === 'addSingleWeekForm') {
                self.handleSingleWeekSubmit(e);
                return;
            }
        });
    }

    /**
     * Setup event delegation for dynamically created elements
     */
    setupEventDelegation() {
        document.addEventListener('click', (e) => {
            const btn = e.target.closest('[data-action="remove-match-row"]');
            if (btn) {
                btn.closest('.row')?.remove();
            }
        });
    }

    _singleWeekDelegationRegistered = false;

    // ----------------------------------------------------------------
    // 1) SINGLE WEEK MODAL / TIME SLOTS - Using Event Delegation
    // ----------------------------------------------------------------
    setupSingleWeekModal() {
        // Only register once
        if (this._singleWeekDelegationRegistered) return;
        this._singleWeekDelegationRegistered = true;

        const self = this;

        // Delegated show.bs.modal handler for single week modal
        document.addEventListener('show.bs.modal', function(e) {
            if (e.target.id !== 'addSingleWeekModal') return;

            const button = e.relatedTarget;
            if (!button) return;

            const leagueId = button.getAttribute('data-league-id');
            const leagueIdInput = document.getElementById('singleWeekLeagueId');
            const timeSlotsContainer = document.getElementById('singleWeekTimeSlots');

            if (leagueIdInput) leagueIdInput.value = leagueId;
            if (timeSlotsContainer) timeSlotsContainer.innerHTML = '';

            // Add at least one slot
            self.addSingleWeekTimeSlot();
        });

        // Delegated click handler for add time slot button
        document.addEventListener('click', function(e) {
            if (e.target.closest('#addTimeSlotBtn')) {
                e.preventDefault();
                self.addSingleWeekTimeSlot();
            }
        });

        // Note: Form submission is handled by setupFormDelegation
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
            <input type="time" name="times[]" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" required>
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
            <div class="flex gap-2">
              <select name="team_b[]" class="form-select" required>
                ${optionsHtml}
              </select>
              <button type="button" class="text-white bg-red-600 hover:bg-red-700 focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-sm px-5 py-2.5" data-action="remove-match-row" aria-label="Delete"><i class="ti ti-trash"></i></button>
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
                document.getElementById('addSingleWeekModal')?._flowbiteModal?.hide();
                location.reload();
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', result.message || 'Error adding single week', 'error');
                }
            }
        } catch (err) {
            // console.error('Error in handleSingleWeekSubmit:', err);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Error adding single week', 'error');
            }
        }
    }

    // ----------------------------------------------------------------
    // 2) EDIT/ADD MATCH LOGIC
    // ROOT CAUSE FIX: Uses single event delegation handler for all button types
    // ----------------------------------------------------------------
    _buttonDelegationRegistered = false;

    setupAddMatchButtons() {
        // Uses delegated handler from setupButtonDelegation
        this.setupButtonDelegation();
    }

    setupEditButtons() {
        // Uses delegated handler from setupButtonDelegation
        this.setupButtonDelegation();
    }

    setupDeleteButtons() {
        // Uses delegated handler from setupButtonDelegation
        this.setupButtonDelegation();
    }

    setupButtonDelegation() {
        // Only register once
        if (this._buttonDelegationRegistered) return;
        this._buttonDelegationRegistered = true;

        const self = this;

        // Single delegated click listener for all schedule buttons
        document.addEventListener('click', function(e) {
            // Add match button
            const addBtn = e.target.closest('.schedule-add-match-btn');
            if (addBtn) {
                e.preventDefault();
                const data = {
                    league_id: addBtn.dataset.leagueId,
                    week: addBtn.dataset.week,
                    date: addBtn.dataset.date
                };
                self.openAddMatchModal(data);
                return;
            }

            // Edit match button
            const editBtn = e.target.closest('.schedule-edit-match-btn');
            if (editBtn) {
                e.preventDefault();
                const matchData = {
                    match_id: editBtn.dataset.matchId,
                    date: editBtn.dataset.date,
                    time: editBtn.dataset.time,
                    location: editBtn.dataset.location,
                    team_a_id: editBtn.dataset.teamAId,
                    team_b_id: editBtn.dataset.teamBId,
                    week: editBtn.dataset.week
                };
                self.openEditMatchModal(matchData);
                return;
            }

            // Delete match button
            const deleteBtn = e.target.closest('.schedule-delete-match-btn');
            if (deleteBtn) {
                e.preventDefault();
                const matchId = deleteBtn.dataset.matchId;
                self.deleteMatch(matchId);
                return;
            }
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
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Success', data.message || (this.isAddOperation
                        ? 'Match created successfully' : 'Match updated successfully'), 'success');
                }
                location.reload();
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', data.message || 'Failed to save match', 'error');
                }
            }
        } catch (err) {
            // console.error('Error in handleMatchFormSubmit:', err);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Error saving match', 'error');
            }
        }
    }

    async deleteMatch(matchId) {
        if (typeof window.Swal !== 'undefined') {
            const result = await window.Swal.fire({
                title: 'Delete Match',
                text: 'Are you sure you want to delete this match?',
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: '#dc3545',
                confirmButtonText: 'Yes, delete it'
            });
            if (!result.isConfirmed) {
                return;
            }
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
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Deleted', data.message || 'Match deleted', 'success');
                }
                location.reload();
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', data.message || 'Failed to delete match', 'error');
                }
            }
        } catch (err) {
            // console.error('Error deleting match:', err);
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Error deleting match', 'error');
            }
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

    // Export to window
    window.ScheduleManager = ScheduleManager;

    // Initialize function
    function initScheduleManagement() {
        if (_initialized) return;
        _initialized = true;

        window.scheduleManager = new window.ScheduleManager();
    }

    // Register with window.InitSystem (primary)
    if (true && window.InitSystem.register) {
        window.InitSystem.register('schedule-management', initScheduleManagement, {
            priority: 40,
            reinitializable: false,
            description: 'Schedule management'
        });
    }

    // Fallback - ScheduleManager has its own DOMContentLoaded in constructor
    // So we just register it, the constructor handles the DOM wait
    // window.InitSystem handles initialization

// Backward compatibility
window.initScheduleManagement = initScheduleManagement;
