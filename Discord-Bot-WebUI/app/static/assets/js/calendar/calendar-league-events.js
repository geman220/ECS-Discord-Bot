/**
 * Calendar League Events Module
 *
 * Handles CRUD operations for league events (non-match calendar events).
 * Provides modal-based event creation/editing for admins.
 */
// ES Module
'use strict';

// Event types with colors and labels
export const EVENT_TYPES = {
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
export function init(options = {}) {
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
        const modalEl = document.getElementById('leagueEventModal');
        modal = modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
        return;
    }

    const modalHtml = `
    <div id="leagueEventModal" tabindex="-1" aria-hidden="true" class="hidden overflow-y-auto overflow-x-hidden fixed top-0 right-0 left-0 z-50 justify-center items-center w-full md:inset-0 h-[calc(100%-1rem)] max-h-full">
        <div class="relative p-4 w-full max-w-xl max-h-full">
            <div class="relative bg-white rounded-lg shadow-sm dark:bg-gray-800">
                <div class="flex items-center justify-between p-4 md:p-5 border-b rounded-t dark:border-gray-600">
                    <h3 class="text-lg font-semibold text-gray-900 dark:text-white" id="leagueEventModalLabel">
                        <i class="ti ti-calendar-plus me-2"></i>
                        <span id="eventModalTitle">Create League Event</span>
                    </h3>
                    <button type="button" class="text-gray-400 bg-transparent hover:bg-gray-200 hover:text-gray-900 rounded-lg text-sm w-8 h-8 ms-auto inline-flex justify-center items-center dark:hover:bg-gray-600 dark:hover:text-white" onclick="var modal = document.getElementById('leagueEventModal'); if(modal._flowbiteModal) modal._flowbiteModal.hide();" aria-label="Close">
                        <i class="ti ti-x text-xl"></i>
                    </button>
                </div>
                <div class="p-4 md:p-5">
                    <form id="leagueEventForm">
                        <input type="hidden" id="eventId" value="">

                        <div class="mb-4">
                            <label for="eventTitle" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Event Title <span class="text-red-500">*</span></label>
                            <input type="text" id="eventTitle" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-ecs-green dark:focus:border-ecs-green" placeholder="e.g., Pre-Season Party" required>
                        </div>

                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                            <div>
                                <label for="eventType" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Event Type</label>
                                <select id="eventType" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-ecs-green dark:focus:border-ecs-green">
                                    <option value="party">Party</option>
                                    <option value="meeting">Meeting</option>
                                    <option value="social">Social Event</option>
                                    <option value="training">Training</option>
                                    <option value="tournament">Tournament</option>
                                    <option value="other" selected>Other</option>
                                </select>
                            </div>
                            <div>
                                <label for="eventLocation" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Location</label>
                                <input type="text" id="eventLocation" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-ecs-green dark:focus:border-ecs-green" placeholder="e.g., The Local Pub">
                            </div>
                        </div>

                        <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
                            <div>
                                <label for="eventStartDate" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Start Date/Time <span class="text-red-500">*</span></label>
                                <input type="datetime-local" id="eventStartDate" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-ecs-green dark:focus:border-ecs-green" required>
                            </div>
                            <div>
                                <label for="eventEndDate" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">End Date/Time</label>
                                <input type="datetime-local" id="eventEndDate" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-ecs-green dark:focus:border-ecs-green">
                            </div>
                        </div>

                        <div class="flex items-center mb-4">
                            <input id="eventAllDay" type="checkbox" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600">
                            <label for="eventAllDay" class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300">All-day event</label>
                        </div>

                        <div class="mb-4">
                            <label for="eventDescription" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Description</label>
                            <textarea id="eventDescription" rows="3" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white dark:focus:ring-ecs-green dark:focus:border-ecs-green" placeholder="Event details..."></textarea>
                        </div>

                        <div class="flex items-center mb-4">
                            <input id="eventNotifyDiscord" type="checkbox" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600">
                            <label for="eventNotifyDiscord" class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300">
                                <i class="ti ti-brand-discord me-1"></i>
                                Announce in Discord
                            </label>
                        </div>
                    </form>
                </div>
                <div class="flex items-center p-4 md:p-5 border-t border-gray-200 rounded-b dark:border-gray-600">
                    <button type="button" class="text-white bg-red-600 hover:bg-red-700 focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-sm px-5 py-2.5 me-auto calendar-delete-event-btn dark:bg-red-600 dark:hover:bg-red-700 dark:focus:ring-red-900" id="deleteEventBtn">
                        <i class="ti ti-trash me-1"></i> Delete
                    </button>
                    <button type="button" class="text-gray-900 bg-gray-200 hover:bg-gray-300 focus:ring-4 focus:ring-gray-100 font-medium rounded-lg text-sm px-5 py-2.5 me-2 dark:bg-gray-700 dark:text-white dark:hover:bg-gray-600 dark:focus:ring-gray-600" onclick="var modal = document.getElementById('leagueEventModal'); if(modal._flowbiteModal) modal._flowbiteModal.hide();">Cancel</button>
                    <button type="button" class="text-white bg-ecs-green hover:bg-ecs-green-dark focus:ring-4 focus:ring-green-300 font-medium rounded-lg text-sm px-5 py-2.5 dark:focus:ring-green-800" id="saveEventBtn">
                        <i class="ti ti-check me-1"></i> Save Event
                    </button>
                </div>
            </div>
        </div>
    </div>
    `;

    document.body.insertAdjacentHTML('beforeend', modalHtml);
    const modalEl = document.getElementById('leagueEventModal');
    modal = modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true });
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
            startInput.type = 'date';
            endInput.type = 'date';
        } else {
            startInput.type = 'datetime-local';
            endInput.type = 'datetime-local';
        }
    });
}

/**
 * Open the modal to create a new event
 * @param {Date} date - Optional default date
 */
export function openCreateModal(date = null) {
    if (!isAdmin) {
        showToast('error', 'You do not have permission to create events');
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
export function openEditModal(event) {
    if (!isAdmin) {
        showToast('error', 'You do not have permission to edit events');
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
        showToast('success', isEdit ? 'Event updated successfully' : 'Event created successfully');

        // Trigger calendar refresh
        if (typeof window.refreshCalendar === 'function') {
            window.refreshCalendar();
        } else if (document.getElementById('refreshScheduleBtn')) {
            document.getElementById('refreshScheduleBtn').click();
        }

    } catch (error) {
        console.error('Error saving event:', error);
        showToast('error', error.message || 'Failed to save event');
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
        showToast('success', 'Event deleted successfully');

        // Trigger calendar refresh
        if (typeof window.refreshCalendar === 'function') {
            window.refreshCalendar();
        } else if (document.getElementById('refreshScheduleBtn')) {
            document.getElementById('refreshScheduleBtn').click();
        }

    } catch (error) {
        console.error('Error deleting event:', error);
        showToast('error', error.message || 'Failed to delete event');
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
export function getEventTypeInfo(type) {
    return EVENT_TYPES[type] || EVENT_TYPES.other;
}

/**
 * Show toast notification
 * @param {string} type - 'success', 'error', 'warning', 'info'
 * @param {string} message
 */
function showToast(type, message) {
    // Use centralized toast service (via compat layer)
    // Note: toast-service uses (message, type) signature
    if (typeof window.showToast === 'function') {
        window.showToast(message, type);
    }
}

// LeagueEventManager object for backward compatibility
export const LeagueEventManager = {
    init,
    openCreateModal,
    openEditModal,
    getEventTypeInfo,
    EVENT_TYPES
};

// Backward compatibility
window.LeagueEventManager = LeagueEventManager;
