import { EventDelegation } from '../core.js';

/**
 * ECS FC Management Action Handlers
 * Handles match CRUD, opponent selection, CSV import for ECS FC teams
 */

// ECS FC MANAGEMENT ACTIONS
// ============================================================================

/**
 * Toggle Opponent Source (Library vs Custom)
 * Shows/hides the appropriate input based on selection
 */
window.EventDelegation.register('toggle-opponent-source', function(element, e) {
    const source = element.value || element.dataset.source;
    const librarySelect = document.getElementById('librarySelect');
    const customInput = document.getElementById('customInput');
    const opponentIdField = document.getElementById('external_opponent_id');
    const opponentNameField = document.getElementById('opponent_name');

    if (source === 'library') {
        if (librarySelect) librarySelect.style.display = '';
        if (customInput) customInput.style.display = 'none';
        if (opponentIdField) opponentIdField.required = true;
        if (opponentNameField) opponentNameField.required = false;
    } else {
        if (librarySelect) librarySelect.style.display = 'none';
        if (customInput) customInput.style.display = '';
        if (opponentIdField) opponentIdField.required = false;
        if (opponentNameField) opponentNameField.required = true;
    }
});

/**
 * Delete ECS FC Match
 * Confirms and deletes a match
 */
window.EventDelegation.register('delete-ecs-fc-match', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    const matchName = element.dataset.matchName || 'this match';

    if (!matchId) {
        console.error('[delete-ecs-fc-match] Missing match ID');
        return;
    }

    window.Swal.fire({
        title: 'Delete Match?',
        text: `Are you sure you want to delete ${matchName}? This cannot be undone.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#d33',
        cancelButtonColor: '#6c757d',
        confirmButtonText: 'Yes, delete it'
    }).then((result) => {
        if (result.isConfirmed) {
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value ||
                              document.querySelector('meta[name="csrf-token"]')?.content;

            fetch(`/admin-panel/ecs-fc/match/${matchId}/delete`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Deleted!', data.message || 'Match deleted.', 'success')
                        .then(() => window.location.reload());
                } else {
                    window.Swal.fire('Error', data.message || 'Failed to delete match.', 'error');
                }
            })
            .catch(error => {
                console.error('[delete-ecs-fc-match] Error:', error);
                window.Swal.fire('Error', 'An error occurred while deleting the match.', 'error');
            });
        }
    });
});

/**
 * Deactivate Opponent
 * Soft-deletes an opponent from the library
 */
window.EventDelegation.register('deactivate-opponent', function(element, e) {
    e.preventDefault();

    const opponentId = element.dataset.opponentId;
    const opponentName = element.dataset.opponentName || 'this opponent';

    if (!opponentId) {
        console.error('[deactivate-opponent] Missing opponent ID');
        return;
    }

    window.Swal.fire({
        title: 'Deactivate Opponent?',
        text: `Are you sure you want to deactivate ${opponentName}? You can reactivate them later.`,
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#ffc107',
        cancelButtonColor: '#6c757d',
        confirmButtonText: 'Yes, deactivate'
    }).then((result) => {
        if (result.isConfirmed) {
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value ||
                              document.querySelector('meta[name="csrf-token"]')?.content;

            const formData = new FormData();
            formData.append('is_active', 'false');
            formData.append('csrf_token', csrfToken);

            fetch(`/admin-panel/ecs-fc/opponent/${opponentId}/update`, {
                method: 'POST',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Deactivated!', data.message || 'Opponent deactivated.', 'success')
                        .then(() => window.location.reload());
                } else {
                    window.Swal.fire('Error', data.message || 'Failed to deactivate opponent.', 'error');
                }
            })
            .catch(error => {
                console.error('[deactivate-opponent] Error:', error);
                window.Swal.fire('Error', 'An error occurred.', 'error');
            });
        }
    });
});

/**
 * Add Quick Opponent
 * Opens modal to quickly add new opponent from match form
 */
window.EventDelegation.register('add-quick-opponent', function(element, e) {
    e.preventDefault();

    const modal = document.getElementById('addOpponentModal');
    if (modal && window.Modal) {
        const flowbiteModal = modal._flowbiteModal || (modal._flowbiteModal = new window.Modal(modal, { backdrop: 'dynamic', closable: true }));
        flowbiteModal.show();
    }
});

/**
 * Preview CSV Import
 * Parses and displays CSV content for review
 */
window.EventDelegation.register('preview-csv-import', function(element, e) {
    e.preventDefault();

    const fileInput = document.getElementById('csv_file');
    const previewContainer = document.getElementById('csvPreview');

    if (!fileInput || !fileInput.files[0]) {
        window.Swal.fire('Error', 'Please select a CSV file first.', 'warning');
        return;
    }

    const file = fileInput.files[0];
    const reader = new FileReader();

    reader.onload = function(event) {
        const csv = event.target.result;
        const lines = csv.split('\n').filter(line => line.trim());

        if (lines.length < 2) {
            window.Swal.fire('Error', 'CSV file is empty or has no data rows.', 'error');
            return;
        }

        // Parse header
        const headers = lines[0].split(',').map(h => h.trim().toLowerCase());

        // Build preview table
        let html = '<div class="table-responsive"><table class="c-table c-table--sm">';
        html += '<thead><tr>';
        headers.forEach(h => html += `<th>${h}</th>`);
        html += '</tr></thead><tbody>';

        // Parse data rows (limit to 10 for preview)
        const dataRows = lines.slice(1, 11);
        dataRows.forEach((line, idx) => {
            const cells = line.split(',');
            html += '<tr>';
            cells.forEach(cell => html += `<td>${cell.trim()}</td>`);
            html += '</tr>';
        });

        if (lines.length > 11) {
            html += `<tr><td colspan="${headers.length}" class="text-center text-muted">... and ${lines.length - 11} more rows</td></tr>`;
        }

        html += '</tbody></table></div>';
        html += `<p class="text-muted mt-2"><strong>Total rows:</strong> ${lines.length - 1}</p>`;

        if (previewContainer) {
            previewContainer.innerHTML = html;
            previewContainer.style.display = '';
        }
    };

    reader.onerror = function() {
        window.Swal.fire('Error', 'Failed to read the CSV file.', 'error');
    };

    reader.readAsText(file);
});

/**
 * Filter ECS FC Matches by Team
 * Handles team filter dropdown changes
 */
window.EventDelegation.register('filter-ecs-fc-team', function(element, e) {
    const teamId = element.value;
    const url = new URL(window.location.href);

    if (teamId) {
        url.searchParams.set('team_id', teamId);
    } else {
        url.searchParams.delete('team_id');
    }

    window.location.href = url.toString();
});

/**
 * Toggle Match Status Filter
 * Shows/hides past or upcoming matches
 */
window.EventDelegation.register('toggle-ecs-fc-status', function(element, e) {
    const status = element.value || element.dataset.status;
    const url = new URL(window.location.href);

    if (status) {
        url.searchParams.set('status', status);
    } else {
        url.searchParams.delete('status');
    }

    window.location.href = url.toString();
});

// ============================================================================
// ECS FC SUB POOL ACTIONS
// ============================================================================

/**
 * Edit Sub Preferences
 */
window.EventDelegation.register('edit-sub-preferences', function(element, e) {
    e.preventDefault();
    const entryId = element.dataset.entryId;
    if (typeof window.editSubPreferences === 'function') {
        window.editSubPreferences(entryId);
    }
}, { preventDefault: true });

/**
 * Remove From Pool
 */
window.EventDelegation.register('remove-from-pool', function(element, e) {
    e.preventDefault();
    const entryId = element.dataset.entryId;
    if (typeof window.removeFromPool === 'function') {
        window.removeFromPool(entryId);
    }
}, { preventDefault: true });

// NOTE: add-to-pool handler is in substitute-pool.js (shared by ECS FC and general sub pools)

// ============================================================================
// ECS FC RSVP ACTIONS
// ============================================================================

/**
 * Send RSVP Reminder
 * Triggers sending reminders to players who haven't responded
 */
window.EventDelegation.register('send-rsvp-reminder', function(element, e) {
    e.preventDefault();

    const matchId = element.dataset.matchId;
    if (!matchId) {
        console.error('[send-rsvp-reminder] Missing match ID');
        return;
    }

    window.Swal.fire({
        title: 'Send RSVP Reminder?',
        text: 'This will send reminders to all players who haven\'t responded yet.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Send Reminders',
        cancelButtonText: 'Cancel'
    }).then((result) => {
        if (result.isConfirmed) {
            const csrfToken = document.querySelector('input[name="csrf_token"]')?.value ||
                              document.querySelector('meta[name="csrf-token"]')?.content;

            fetch(`/admin-panel/ecs-fc/rsvp/${matchId}/send-reminder`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest',
                    'Content-Type': 'application/json'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire({
                        title: 'Reminders Sent!',
                        text: data.message || 'RSVP reminders have been queued.',
                        icon: 'success',
                        timer: 3000,
                        showConfirmButton: false
                    });
                } else {
                    window.Swal.fire('Error', data.message || 'Failed to send reminders.', 'error');
                }
            })
            .catch(error => {
                console.error('[send-rsvp-reminder] Error:', error);
                window.Swal.fire('Error', 'An error occurred while sending reminders.', 'error');
            });
        }
    });
});

// ============================================================================
// ECS FC MATCH FORM TEMPLATE HANDLERS
// ============================================================================

/**
 * Apply Match Template
 * Auto-fills date and time fields based on selected template
 */
window.EventDelegation.register('apply-match-template', function(element, e) {
    e.preventDefault();

    const template = element.dataset.template;
    const dateInput = document.getElementById('match_date');
    const timeInput = document.getElementById('match_time');
    const rsvpDeadline = document.getElementById('rsvp_deadline');

    if (!dateInput || !timeInput) {
        console.error('[apply-match-template] Date or time input not found');
        return;
    }

    const today = new Date();
    let targetDate = new Date(today);
    let targetTime = '19:00';

    switch (template) {
        case 'weekend':
            // Next Saturday at 3:00 PM
            const daysUntilSaturday = (6 - today.getDay() + 7) % 7 || 7;
            targetDate.setDate(today.getDate() + daysUntilSaturday);
            targetTime = '15:00';
            break;

        case 'midweek':
            // Next Wednesday at 7:30 PM
            const daysUntilWednesday = (3 - today.getDay() + 7) % 7 || 7;
            targetDate.setDate(today.getDate() + daysUntilWednesday);
            targetTime = '19:30';
            break;

        case 'sunday':
            // Next Sunday at 2:00 PM
            const daysUntilSunday = (7 - today.getDay()) % 7 || 7;
            targetDate.setDate(today.getDate() + daysUntilSunday);
            targetTime = '14:00';
            break;

        default:
            console.warn('[apply-match-template] Unknown template:', template);
            return;
    }

    // Format date as YYYY-MM-DD
    const dateStr = targetDate.toISOString().split('T')[0];
    dateInput.value = dateStr;
    timeInput.value = targetTime;

    // Auto-set RSVP deadline to 48 hours before
    if (rsvpDeadline) {
        const deadlineDate = new Date(targetDate);
        const [hours, minutes] = targetTime.split(':').map(Number);
        deadlineDate.setHours(hours, minutes, 0, 0);
        deadlineDate.setDate(deadlineDate.getDate() - 2);
        rsvpDeadline.value = deadlineDate.toISOString().slice(0, 16);
    }

    // Show success toast
    if (window.Swal) {
        window.Swal.fire({
            title: 'Template Applied',
            text: `${template.charAt(0).toUpperCase() + template.slice(1)} match template has been applied.`,
            icon: 'success',
            timer: 1500,
            showConfirmButton: false,
            toast: true,
            position: 'top-end'
        });
    }
});

// ============================================================================
// ECS FC MATCH WIZARD MODAL HANDLERS
// ============================================================================

/**
 * Match Wizard State Management
 * Tracks current step and provides navigation
 */
const MatchWizard = {
    currentStep: 1,
    totalSteps: 4,
    modal: null,

    init(modalElement) {
        this.modal = modalElement;
        this.currentStep = 1;
        this.showStep(1);

        // Set min date to today
        const dateInput = modalElement.querySelector('#modal_match_date');
        if (dateInput) {
            dateInput.min = new Date().toISOString().split('T')[0];
        }
    },

    showStep(step) {
        if (!this.modal) return;

        // Hide all steps, show current
        this.modal.querySelectorAll('.wizard-step').forEach(el => el.style.display = 'none');
        const currentStepEl = this.modal.querySelector(`.wizard-step[data-step="${step}"]`);
        if (currentStepEl) currentStepEl.style.display = 'block';

        // Update step indicators
        this.modal.querySelectorAll('.step-indicator').forEach(el => {
            const stepNum = parseInt(el.dataset.step);
            el.classList.remove('active', 'completed');
            if (stepNum === step) el.classList.add('active');
            if (stepNum < step) el.classList.add('completed');
        });

        // Update navigation buttons
        const prevBtn = this.modal.querySelector('#modalPrevBtn');
        const nextBtn = this.modal.querySelector('#modalNextBtn');
        const submitBtn = this.modal.querySelector('#modalSubmitBtn');

        if (prevBtn) prevBtn.style.display = step > 1 ? 'inline-block' : 'none';
        if (nextBtn) nextBtn.style.display = step < this.totalSteps ? 'inline-block' : 'none';
        if (submitBtn) submitBtn.style.display = step === this.totalSteps ? 'inline-block' : 'none';

        // Update review on final step
        if (step === this.totalSteps) this.updateReview();

        this.currentStep = step;
    },

    validateStep(step) {
        if (!this.modal) return false;

        if (step === 1) {
            const source = this.modal.querySelector('input[name="opponent_source"]:checked')?.value;
            if (source === 'library') {
                return !!this.modal.querySelector('#modal_external_opponent_id')?.value;
            } else {
                return !!this.modal.querySelector('#modal_opponent_name')?.value?.trim();
            }
        }
        if (step === 2) {
            return !!this.modal.querySelector('#modal_match_date')?.value &&
                   !!this.modal.querySelector('#modal_match_time')?.value;
        }
        if (step === 3) {
            return !!this.modal.querySelector('#modal_location')?.value?.trim();
        }
        return true;
    },

    updateReview() {
        if (!this.modal) return;

        const source = this.modal.querySelector('input[name="opponent_source"]:checked')?.value;
        let opponent = '-';
        if (source === 'library') {
            const select = this.modal.querySelector('#modal_external_opponent_id');
            opponent = select?.options[select.selectedIndex]?.text || '-';
        } else {
            opponent = this.modal.querySelector('#modal_opponent_name')?.value || '-';
        }

        const isHome = this.modal.querySelector('input[name="is_home_match"]:checked')?.value === 'true';
        const date = this.modal.querySelector('#modal_match_date')?.value;
        const time = this.modal.querySelector('#modal_match_time')?.value;
        const location = this.modal.querySelector('#modal_location')?.value || '-';
        const field = this.modal.querySelector('#modal_field_name')?.value || '-';

        const reviewOpponent = this.modal.querySelector('#reviewOpponent');
        const reviewHomeAway = this.modal.querySelector('#reviewHomeAway');
        const reviewDate = this.modal.querySelector('#reviewDate');
        const reviewTime = this.modal.querySelector('#reviewTime');
        const reviewLocation = this.modal.querySelector('#reviewLocation');
        const reviewField = this.modal.querySelector('#reviewField');

        if (reviewOpponent) reviewOpponent.textContent = opponent;
        if (reviewHomeAway) reviewHomeAway.textContent = isHome ? 'Home' : 'Away';
        if (reviewDate) {
            reviewDate.textContent = date
                ? new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
                    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
                })
                : '-';
        }
        if (reviewTime) {
            reviewTime.textContent = time
                ? new Date('2000-01-01T' + time).toLocaleTimeString('en-US', {
                    hour: 'numeric', minute: '2-digit'
                })
                : '-';
        }
        if (reviewLocation) reviewLocation.textContent = location;
        if (reviewField) reviewField.textContent = field;
    },

    reset() {
        if (!this.modal) return;

        const form = this.modal.querySelector('#quickMatchForm');
        if (form) form.reset();

        // Reset to library selection
        const libraryRadio = this.modal.querySelector('#modalOppLibrary');
        const librarySelect = this.modal.querySelector('#modalLibrarySelect');
        const customInput = this.modal.querySelector('#modalCustomInput');
        const homeRadio = this.modal.querySelector('#modalIsHome');

        if (libraryRadio) libraryRadio.checked = true;
        if (librarySelect) librarySelect.style.display = 'block';
        if (customInput) customInput.style.display = 'none';
        if (homeRadio) homeRadio.checked = true;

        this.showStep(1);
    }
};

/**
 * Toggle Modal Opponent Source
 */
window.EventDelegation.register('toggle-modal-opponent', function(element, e) {
    const modal = element.closest('.modal');
    if (!modal) return;

    const isLibrary = element.value === 'library';
    const librarySelect = modal.querySelector('#modalLibrarySelect');
    const customInput = modal.querySelector('#modalCustomInput');

    if (librarySelect) librarySelect.style.display = isLibrary ? 'block' : 'none';
    if (customInput) customInput.style.display = isLibrary ? 'none' : 'block';
});

/**
 * Set Match Time from Quick Templates
 */
window.EventDelegation.register('set-match-time', function(element, e) {
    e.preventDefault();

    const modal = element.closest('.modal');
    if (!modal) return;

    const template = element.dataset.template;
    const dateInput = modal.querySelector('#modal_match_date');
    const timeInput = modal.querySelector('#modal_match_time');

    if (!dateInput || !timeInput) return;

    const now = new Date();
    let targetDate = new Date(now);

    if (template === 'weekend') {
        // Next Saturday
        const daysUntilSat = (6 - now.getDay() + 7) % 7 || 7;
        targetDate.setDate(now.getDate() + daysUntilSat);
        timeInput.value = '15:00';
    } else if (template === 'midweek') {
        // Next Wednesday
        const daysUntilWed = (3 - now.getDay() + 7) % 7 || 7;
        targetDate.setDate(now.getDate() + daysUntilWed);
        timeInput.value = '19:30';
    } else if (template === 'sunday') {
        // Next Sunday
        const daysUntilSun = (7 - now.getDay()) % 7 || 7;
        targetDate.setDate(now.getDate() + daysUntilSun);
        timeInput.value = '14:00';
    }

    dateInput.value = targetDate.toISOString().split('T')[0];
});

/**
 * Wizard Next Button
 */
window.EventDelegation.register('wizard-next', function(element, e) {
    e.preventDefault();

    if (!MatchWizard.validateStep(MatchWizard.currentStep)) {
        if (window.Swal) {
            window.Swal.fire({
                icon: 'warning',
                title: 'Missing Information',
                text: 'Please fill in all required fields before continuing.',
                confirmButtonText: 'OK'
            });
        } else {
            alert('Please fill in all required fields.');
        }
        return;
    }

    if (MatchWizard.currentStep < MatchWizard.totalSteps) {
        MatchWizard.showStep(MatchWizard.currentStep + 1);
    }
});

/**
 * Wizard Previous Button
 */
window.EventDelegation.register('wizard-prev', function(element, e) {
    e.preventDefault();

    if (MatchWizard.currentStep > 1) {
        MatchWizard.showStep(MatchWizard.currentStep - 1);
    }
});

/**
 * Submit Quick Match Form
 */
window.EventDelegation.register('submit-quick-match', function(element, e) {
    e.preventDefault();

    const modal = element.closest('.modal');
    if (!modal) return;

    const form = modal.querySelector('#quickMatchForm');
    if (!form) return;

    const formData = new FormData(form);
    const submitUrl = form.dataset.submitUrl || '/admin-panel/ecs-fc/match/create';

    // Disable button during submission
    element.disabled = true;
    const originalHtml = element.innerHTML;
    element.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></span>Creating...';

    fetch(submitUrl, {
        method: 'POST',
        body: formData,
        headers: {
            'X-Requested-With': 'XMLHttpRequest'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            if (window.Swal) {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Match Created!',
                    text: 'RSVP will be posted to Discord the Monday before the match.',
                    confirmButtonText: 'OK'
                }).then(() => {
                    location.reload();
                });
            } else {
                alert('Match created successfully!');
                location.reload();
            }
        } else {
            throw new Error(data.message || 'Failed to create match');
        }
    })
    .catch(error => {
        element.disabled = false;
        element.innerHTML = originalHtml;

        if (window.Swal) {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: error.message || 'Failed to create match. Please try again.',
                confirmButtonText: 'OK'
            });
        } else {
            alert('Error: ' + (error.message || 'Failed to create match'));
        }
    });
});

// ============================================================================
// ECS FC TEAM PAGE WIZARD (for /teams/<id> page)
// ============================================================================

/**
 * ECS FC Team Page Wizard State Management
 */
const EcsFcTeamWizard = {
    currentStep: 1,
    totalSteps: 4,
    modal: null,

    init(modalElement) {
        this.modal = modalElement;
        this.currentStep = 1;
        this.showStep(1);

        // Set min date to today
        const dateInput = modalElement.querySelector('#ecs_match_date');
        if (dateInput) {
            dateInput.min = new Date().toISOString().split('T')[0];
        }
    },

    showStep(step) {
        if (!this.modal) return;

        // Hide all panels, show current (using BEM classes)
        this.modal.querySelectorAll('.c-wizard__panel').forEach(el => {
            el.classList.remove('c-wizard__panel--active');
        });
        const currentPanel = this.modal.querySelector(`.c-wizard__panel[data-step="${step}"]`);
        if (currentPanel) currentPanel.classList.add('c-wizard__panel--active');

        // Update step indicators (using BEM classes)
        this.modal.querySelectorAll('.c-wizard__step').forEach(el => {
            const stepNum = parseInt(el.dataset.step);
            el.classList.remove('c-wizard__step--active', 'c-wizard__step--completed');
            if (stepNum === step) el.classList.add('c-wizard__step--active');
            if (stepNum < step) el.classList.add('c-wizard__step--completed');
        });

        // Update navigation buttons (using BEM modifier classes)
        const prevBtn = this.modal.querySelector('.c-wizard__nav-prev');
        const nextBtn = this.modal.querySelector('.c-wizard__nav-next');
        const submitBtn = this.modal.querySelector('.c-wizard__nav-submit');

        if (prevBtn) prevBtn.classList.toggle('c-wizard__nav-prev--visible', step > 1);
        if (nextBtn) nextBtn.classList.toggle('c-wizard__nav-next--hidden', step >= this.totalSteps);
        if (submitBtn) submitBtn.classList.toggle('c-wizard__nav-submit--visible', step === this.totalSteps);

        // Update review on final step
        if (step === this.totalSteps) this.updateReview();

        this.currentStep = step;
    },

    validateStep(step) {
        if (!this.modal) return false;

        if (step === 1) {
            return !!this.modal.querySelector('#ecs_opponent_name')?.value?.trim();
        }
        if (step === 2) {
            return !!this.modal.querySelector('#ecs_match_date')?.value &&
                   !!this.modal.querySelector('#ecs_match_time')?.value;
        }
        if (step === 3) {
            return !!this.modal.querySelector('#ecs_location')?.value?.trim();
        }
        return true;
    },

    updateReview() {
        if (!this.modal) return;

        const opponent = this.modal.querySelector('#ecs_opponent_name')?.value || '-';
        const isHome = this.modal.querySelector('input[name="is_home_match"]:checked')?.value === 'true';
        const date = this.modal.querySelector('#ecs_match_date')?.value;
        const time = this.modal.querySelector('#ecs_match_time')?.value;
        const location = this.modal.querySelector('#ecs_location')?.value || '-';
        const field = this.modal.querySelector('#ecs_field_name')?.value || '-';

        const reviewOpponent = this.modal.querySelector('#ecsReviewOpponent');
        const reviewHomeAway = this.modal.querySelector('#ecsReviewHomeAway');
        const reviewDate = this.modal.querySelector('#ecsReviewDate');
        const reviewTime = this.modal.querySelector('#ecsReviewTime');
        const reviewLocation = this.modal.querySelector('#ecsReviewLocation');
        const reviewField = this.modal.querySelector('#ecsReviewField');

        if (reviewOpponent) reviewOpponent.textContent = opponent;
        if (reviewHomeAway) reviewHomeAway.textContent = isHome ? 'Home' : 'Away';
        if (reviewDate) {
            reviewDate.textContent = date
                ? new Date(date + 'T12:00:00').toLocaleDateString('en-US', {
                    weekday: 'short', month: 'short', day: 'numeric', year: 'numeric'
                })
                : '-';
        }
        if (reviewTime) {
            reviewTime.textContent = time
                ? new Date('2000-01-01T' + time).toLocaleTimeString('en-US', {
                    hour: 'numeric', minute: '2-digit'
                })
                : '-';
        }
        if (reviewLocation) reviewLocation.textContent = location;
        if (reviewField) reviewField.textContent = field;
    },

    reset() {
        if (!this.modal) return;

        const form = this.modal.querySelector('#ecsFcMatchForm');
        if (form) form.reset();

        // Reset to home selection
        const homeRadio = this.modal.querySelector('#ecsIsHome');
        if (homeRadio) homeRadio.checked = true;

        // Reset nav buttons to initial state
        const prevBtn = this.modal.querySelector('.c-wizard__nav-prev');
        const nextBtn = this.modal.querySelector('.c-wizard__nav-next');
        const submitBtn = this.modal.querySelector('.c-wizard__nav-submit');

        if (prevBtn) prevBtn.classList.remove('c-wizard__nav-prev--visible');
        if (nextBtn) nextBtn.classList.remove('c-wizard__nav-next--hidden');
        if (submitBtn) submitBtn.classList.remove('c-wizard__nav-submit--visible');

        this.showStep(1);
    }
};

/**
 * Set ECS FC Match Time from Quick Templates
 */
window.EventDelegation.register('set-ecs-match-time', function(element, e) {
    e.preventDefault();

    const modal = element.closest('.modal');
    if (!modal) return;

    const template = element.dataset.template;
    const dateInput = modal.querySelector('#ecs_match_date');
    const timeInput = modal.querySelector('#ecs_match_time');

    if (!dateInput || !timeInput) return;

    const now = new Date();
    let targetDate = new Date(now);

    if (template === 'weekend') {
        const daysUntilSat = (6 - now.getDay() + 7) % 7 || 7;
        targetDate.setDate(now.getDate() + daysUntilSat);
        timeInput.value = '15:00';
    } else if (template === 'midweek') {
        const daysUntilWed = (3 - now.getDay() + 7) % 7 || 7;
        targetDate.setDate(now.getDate() + daysUntilWed);
        timeInput.value = '19:30';
    } else if (template === 'sunday') {
        const daysUntilSun = (7 - now.getDay()) % 7 || 7;
        targetDate.setDate(now.getDate() + daysUntilSun);
        timeInput.value = '14:00';
    }

    dateInput.value = targetDate.toISOString().split('T')[0];
});

/**
 * ECS FC Wizard Next Button
 */
window.EventDelegation.register('ecs-wizard-next', function(element, e) {
    e.preventDefault();

    if (!EcsFcTeamWizard.validateStep(EcsFcTeamWizard.currentStep)) {
        if (window.Swal) {
            window.Swal.fire({
                icon: 'warning',
                title: 'Missing Information',
                text: 'Please fill in all required fields before continuing.',
                confirmButtonText: 'OK'
            });
        } else {
            alert('Please fill in all required fields.');
        }
        return;
    }

    if (EcsFcTeamWizard.currentStep < EcsFcTeamWizard.totalSteps) {
        EcsFcTeamWizard.showStep(EcsFcTeamWizard.currentStep + 1);
    }
});

/**
 * ECS FC Wizard Previous Button
 */
window.EventDelegation.register('ecs-wizard-prev', function(element, e) {
    e.preventDefault();

    if (EcsFcTeamWizard.currentStep > 1) {
        EcsFcTeamWizard.showStep(EcsFcTeamWizard.currentStep - 1);
    }
});

/**
 * Submit ECS FC Match (JSON API)
 */
window.EventDelegation.register('submit-ecs-match', function(element, e) {
    e.preventDefault();

    const modal = element.closest('.modal');
    if (!modal) return;

    const form = modal.querySelector('#ecsFcMatchForm');
    if (!form) return;

    // Build JSON payload
    const teamData = document.getElementById('ecs-fc-team-data');
    const teamId = teamData?.dataset.teamId;

    const matchData = {
        team_id: parseInt(teamId),
        opponent_name: form.querySelector('#ecs_opponent_name')?.value,
        match_date: form.querySelector('#ecs_match_date')?.value,
        match_time: form.querySelector('#ecs_match_time')?.value,
        location: form.querySelector('#ecs_location')?.value,
        field_name: form.querySelector('#ecs_field_name')?.value || null,
        is_home_match: form.querySelector('input[name="is_home_match"]:checked')?.value === 'true',
        notes: form.querySelector('#ecs_notes')?.value || null,
        send_discord_rsvp: form.querySelector('#send_discord_rsvp')?.checked || false
    };

    const csrfToken = form.querySelector('input[name="csrf_token"]')?.value ||
                      document.querySelector('meta[name="csrf-token"]')?.content;

    // Disable button during submission
    element.disabled = true;
    const originalHtml = element.innerHTML;
    element.innerHTML = '<span class="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2"></span>Creating...';

    fetch('/api/ecs-fc/matches', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest'
        },
        body: JSON.stringify(matchData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // Close modal
            if (modal._flowbiteModal) modal._flowbiteModal.hide();

            if (window.Swal) {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Match Created!',
                    text: 'RSVP will be posted to Discord the Monday before the match.',
                    confirmButtonText: 'OK'
                }).then(() => {
                    location.reload();
                });
            } else {
                alert('Match created successfully!');
                location.reload();
            }
        } else {
            throw new Error(data.message || 'Failed to create match');
        }
    })
    .catch(error => {
        element.disabled = false;
        element.innerHTML = originalHtml;

        if (window.Swal) {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: error.message || 'Failed to create match. Please try again.',
                confirmButtonText: 'OK'
            });
        } else {
            alert('Error: ' + (error.message || 'Failed to create match'));
        }
    });
});

// ============================================================================
// INITIALIZATION
// ============================================================================

// Initialize wizard when modal opens
document.addEventListener('DOMContentLoaded', function() {
    // Admin panel modal (team_schedule.html)
    const addMatchModal = document.getElementById('addMatchModal');
    if (addMatchModal) {
        addMatchModal.addEventListener('show.bs.modal', function() {
            MatchWizard.init(this);
            MatchWizard.reset();
        });
    }

    // Team page modal (team_details.html via ecs_fc_schedule_section.html)
    const ecsFcModal = document.getElementById('ecsFcCreateMatchModal');
    if (ecsFcModal) {
        ecsFcModal.addEventListener('show.bs.modal', function() {
            EcsFcTeamWizard.init(this);
            EcsFcTeamWizard.reset();
        });
    }

    // Match form page initialization (for standalone form, not modal)
    const matchDateInput = document.getElementById('match_date');
    const rsvpDeadlineInput = document.getElementById('rsvp_deadline');

    // Set minimum date to today
    if (matchDateInput && !matchDateInput.value) {
        matchDateInput.min = new Date().toISOString().split('T')[0];
    }

    // Auto-set RSVP deadline to 48 hours before match when date changes
    if (matchDateInput && rsvpDeadlineInput) {
        matchDateInput.addEventListener('change', function() {
            if (!rsvpDeadlineInput.value && this.value) {
                const matchDate = new Date(this.value + 'T19:00:00');
                matchDate.setDate(matchDate.getDate() - 2); // 48 hours before
                const deadlineStr = matchDate.toISOString().slice(0, 16);
                rsvpDeadlineInput.value = deadlineStr;
            }
        });
    }
});

// ============================================================================

// Handlers loaded
