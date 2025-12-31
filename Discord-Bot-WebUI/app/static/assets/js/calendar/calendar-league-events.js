/**
 * Calendar League Events Module
 *
 * Handles CRUD operations for league events (non-match calendar events).
 * Provides modal-based event creation/editing for admins.
 */

'use strict';

// League Event Manager
const LeagueEventManager = (function() {
    // Event types with colors and labels
    const EVENT_TYPES = {
        party: { label: 'Party', color: '#9c27b0', icon: 'ti-confetti' },
        meeting: { label: 'Meeting', color: '#ff9800', icon: 'ti-users' },
        social: { label: 'Social Event', color: '#e91e63', icon: 'ti-heart' },
        training: { label: 'Training', color: '#4caf50', icon: 'ti-ball-football' },
        tournament: { label: 'Tournament', color: '#f44336', icon: 'ti-trophy' },
        other: { label: 'Other', color: '#607d8b', icon: 'ti-calendar-event' }
    };

    // State
    let currentEvent = null;
    let modal = null;
    let isAdmin = false;

    /**
     * Initialize the league events module
     * @param {Object} options - Configuration options
     */
    function init(options = {}) {
        isAdmin = options.isAdmin || false;

        if (isAdmin) {
            createModal();
            bindEvents();
        }
    }

    /**
     * Create the event modal HTML
     */
    function createModal() {
        // Check if modal already exists
        if (document.getElementById('leagueEventModal')) {
            modal = new window.bootstrap.Modal(document.getElementById('leagueEventModal'));
            return;
        }

        const modalHtml = `
        <div class="modal fade" id="leagueEventModal" tabindex="-1" aria-labelledby="leagueEventModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="leagueEventModalLabel">
                            <i class="ti ti-calendar-plus me-2"></i>
                            <span id="eventModalTitle">Create League Event</span>
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <form id="leagueEventForm">
                            <input type="hidden" id="eventId" value="">

                            <div class="mb-3">
                                <label for="eventTitle" class="form-label">Event Title <span class="text-danger">*</span></label>
                                <input type="text" class="form-control" id="eventTitle" placeholder="e.g., Pre-Season Party" required>
                            </div>

                            <div class="row mb-3">
                                <div class="col-md-6">
                                    <label for="eventType" class="form-label">Event Type</label>
                                    <select class="form-select" id="eventType">
                                        <option value="party">Party</option>
                                        <option value="meeting">Meeting</option>
                                        <option value="social">Social Event</option>
                                        <option value="training">Training</option>
                                        <option value="tournament">Tournament</option>
                                        <option value="other" selected>Other</option>
                                    </select>
                                </div>
                                <div class="col-md-6">
                                    <label for="eventLocation" class="form-label">Location</label>
                                    <input type="text" class="form-control" id="eventLocation" placeholder="e.g., The Local Pub">
                                </div>
                            </div>

                            <div class="row mb-3">
                                <div class="col-md-6">
                                    <label for="eventStartDate" class="form-label">Start Date/Time <span class="text-danger">*</span></label>
                                    <input type="datetime-local" class="form-control" id="eventStartDate" required>
                                </div>
                                <div class="col-md-6">
                                    <label for="eventEndDate" class="form-label">End Date/Time</label>
                                    <input type="datetime-local" class="form-control" id="eventEndDate">
                                </div>
                            </div>

                            <div class="mb-3">
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="eventAllDay">
                                    <label class="form-check-label" for="eventAllDay">
                                        All-day event
                                    </label>
                                </div>
                            </div>

                            <div class="mb-3">
                                <label for="eventDescription" class="form-label">Description</label>
                                <textarea class="form-control" id="eventDescription" rows="3" placeholder="Event details..."></textarea>
                            </div>

                            <div class="mb-3">
                                <div class="form-check">
                                    <input class="form-check-input" type="checkbox" id="eventNotifyDiscord">
                                    <label class="form-check-label" for="eventNotifyDiscord">
                                        <i class="ti ti-brand-discord me-1"></i>
                                        Announce in Discord
                                    </label>
                                </div>
                            </div>
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-outline-danger me-auto calendar-delete-event-btn" id="deleteEventBtn">
                            <i class="ti ti-trash me-1"></i> Delete
                        </button>
                        <button type="button" class="btn btn-outline-secondary" data-bs-dismiss="modal">Cancel</button>
                        <button type="button" class="btn btn-primary" id="saveEventBtn">
                            <i class="ti ti-check me-1"></i> Save Event
                        </button>
                    </div>
                </div>
            </div>
        </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
        modal = new window.bootstrap.Modal(document.getElementById('leagueEventModal'));
    }

    /**
     * Bind event handlers
     */
    function bindEvents() {
        // Save button
        document.getElementById('saveEventBtn')?.addEventListener('click', saveEvent);

        // Delete button
        document.getElementById('deleteEventBtn')?.addEventListener('click', deleteEvent);

        // All-day checkbox toggles time inputs
        document.getElementById('eventAllDay')?.addEventListener('change', function() {
            const startInput = document.getElementById('eventStartDate');
            const endInput = document.getElementById('eventEndDate');

            if (this.checked) {
                // Change to date-only inputs
                startInput.type = 'date';
                endInput.type = 'date';
            } else {
                // Change back to datetime-local
                startInput.type = 'datetime-local';
                endInput.type = 'datetime-local';
            }
        });
    }

    /**
     * Open the modal to create a new event
     * @param {Date} date - Optional default date
     */
    function openCreateModal(date = null) {
        if (!isAdmin) {
            window.showToast('error', 'You do not have permission to create events');
            return;
        }

        currentEvent = null;

        // Reset form
        document.getElementById('leagueEventForm').reset();
        document.getElementById('eventId').value = '';
        document.getElementById('eventModalTitle').textContent = 'Create League Event';
        document.getElementById('deleteEventBtn').classList.remove('is-visible');
        document.getElementById('saveEventBtn').innerHTML = '<i class="ti ti-check me-1"></i> Create Event';

        // Set default date if provided
        if (date) {
            const dateStr = formatDateForInput(date);
            document.getElementById('eventStartDate').value = dateStr;
        }

        modal.show();
    }

    /**
     * Open the modal to edit an existing event
     * @param {Object} event - The event data
     */
    function openEditModal(event) {
        if (!isAdmin) {
            window.showToast('error', 'You do not have permission to edit events');
            return;
        }

        currentEvent = event;

        // Parse event ID
        const eventId = event.id.replace('event-', '');

        // Populate form
        document.getElementById('eventId').value = eventId;
        document.getElementById('eventTitle').value = event.title || '';
        document.getElementById('eventType').value = event.extendedProps?.eventType || 'other';
        document.getElementById('eventLocation').value = event.extendedProps?.location || '';
        document.getElementById('eventDescription').value = event.extendedProps?.description || '';
        document.getElementById('eventAllDay').checked = event.allDay || false;
        document.getElementById('eventNotifyDiscord').checked = event.extendedProps?.notifyDiscord || false;

        // Set dates
        if (event.start) {
            document.getElementById('eventStartDate').value = formatDateForInput(new Date(event.start));
        }
        if (event.end) {
            document.getElementById('eventEndDate').value = formatDateForInput(new Date(event.end));
        }

        // Update modal title and buttons
        document.getElementById('eventModalTitle').textContent = 'Edit League Event';
        document.getElementById('deleteEventBtn').classList.add('is-visible');
        document.getElementById('saveEventBtn').innerHTML = '<i class="ti ti-check me-1"></i> Save Changes';

        modal.show();
    }

    /**
     * Save event (create or update)
     */
    async function saveEvent() {
        const form = document.getElementById('leagueEventForm');
        if (!form.checkValidity()) {
            form.reportValidity();
            return;
        }

        const eventId = document.getElementById('eventId').value;
        const isEdit = !!eventId;

        const eventData = {
            title: document.getElementById('eventTitle').value,
            event_type: document.getElementById('eventType').value,
            location: document.getElementById('eventLocation').value || null,
            description: document.getElementById('eventDescription').value || null,
            start_datetime: document.getElementById('eventStartDate').value,
            end_datetime: document.getElementById('eventEndDate').value || null,
            is_all_day: document.getElementById('eventAllDay').checked,
            notify_discord: document.getElementById('eventNotifyDiscord').checked
        };

        try {
            const url = isEdit
                ? `/api/calendar/league-events/${eventId}`
                : '/api/calendar/league-events';

            const response = await fetch(url, {
                method: isEdit ? 'PUT' : 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: JSON.stringify(eventData)
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to save event');
            }

            const savedEvent = await response.json();

            modal.hide();
            window.showToast('success', isEdit ? 'Event updated successfully' : 'Event created successfully');

            // Trigger calendar refresh
            if (typeof window.refreshCalendar === 'function') {
                window.refreshCalendar();
            } else if (document.getElementById('refreshScheduleBtn')) {
                document.getElementById('refreshScheduleBtn').click();
            }

        } catch (error) {
            console.error('Error saving event:', error);
            window.showToast('error', error.message || 'Failed to save event');
        }
    }

    /**
     * Delete the current event
     */
    async function deleteEvent() {
        const eventId = document.getElementById('eventId').value;
        if (!eventId) return;

        if (!confirm('Are you sure you want to delete this event?')) {
            return;
        }

        try {
            const response = await fetch(`/api/calendar/league-events/${eventId}`, {
                method: 'DELETE',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error || 'Failed to delete event');
            }

            modal.hide();
            window.showToast('success', 'Event deleted successfully');

            // Trigger calendar refresh
            if (typeof window.refreshCalendar === 'function') {
                window.refreshCalendar();
            } else if (document.getElementById('refreshScheduleBtn')) {
                document.getElementById('refreshScheduleBtn').click();
            }

        } catch (error) {
            console.error('Error deleting event:', error);
            window.showToast('error', error.message || 'Failed to delete event');
        }
    }

    /**
     * Format a date for datetime-local input
     * @param {Date} date
     * @returns {string}
     */
    function formatDateForInput(date) {
        const d = new Date(date);
        const year = d.getFullYear();
        const month = String(d.getMonth() + 1).padStart(2, '0');
        const day = String(d.getDate()).padStart(2, '0');
        const hours = String(d.getHours()).padStart(2, '0');
        const minutes = String(d.getMinutes()).padStart(2, '0');
        return `${year}-${month}-${day}T${hours}:${minutes}`;
    }

    /**
     * Get event type info
     * @param {string} type
     * @returns {Object}
     */
    function getEventTypeInfo(type) {
        return EVENT_TYPES[type] || EVENT_TYPES.other;
    }

    /**
     * Show toast notification
     * @param {string} type - 'success', 'error', 'warning', 'info'
     * @param {string} message
     */
    function showToast(type, message) {
        // Use existing toast system if available
        if (typeof window.showToast === 'function') {
            window.showToast(type, message);
            return;
        }

        // Fallback to Toastify
        if (typeof window.Toastify !== 'undefined') {
            const bgColors = {
                success: 'linear-gradient(to right, #00b09b, #96c93d)',
                error: 'linear-gradient(to right, #ff5f6d, #ffc371)',
                warning: 'linear-gradient(to right, #f7b733, #fc4a1a)',
                info: 'linear-gradient(to right, #2193b0, #6dd5ed)'
            };

            window.Toastify({
                text: message,
                duration: 3000,
                gravity: 'top',
                position: 'right',
                style: { background: bgColors[type] || bgColors.info }
            }).showToast();
            return;
        }

        // Final fallback
        alert(message);
    }

    // Public API
    return {
        init,
        openCreateModal,
        openEditModal,
        getEventTypeInfo,
        EVENT_TYPES
    };
})();

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = LeagueEventManager;
}
