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
    party: { label: 'Party/Social', color: '#9c27b0', icon: 'ti-confetti' },
    tournament: { label: 'Tournament', color: '#ffc107', icon: 'ti-trophy' },
    meeting: { label: 'Meeting', color: '#2196f3', icon: 'ti-users' },
    plop: { label: 'PLOP', color: '#4caf50', icon: 'ti-ball-football' },
    fundraiser: { label: 'Fundraiser', color: '#ff5722', icon: 'ti-heart-handshake' },
    social: { label: 'Social Event', color: '#e91e63', icon: 'ti-heart' },
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
                                    <option value="party">Party/Social</option>
                                    <option value="tournament">Tournament</option>
                                    <option value="meeting">Meeting</option>
                                    <option value="plop">PLOP</option>
                                    <option value="fundraiser">Fundraiser</option>
                                    <option value="social">Social Event</option>
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

                        <!-- Recurring Event Section -->
                        <div class="mb-4 p-3 bg-gray-50 dark:bg-gray-700 rounded-lg">
                            <div class="flex items-center mb-3">
                                <input id="eventRecurring" type="checkbox" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600">
                                <label for="eventRecurring" class="ms-2 text-sm font-medium text-gray-900 dark:text-gray-300">
                                    <i class="ti ti-repeat me-1"></i>
                                    Recurring event
                                </label>
                            </div>
                            <div id="recurringOptions" class="hidden space-y-3">
                                <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    <div>
                                        <label for="recurrencePattern" class="block mb-1 text-xs font-medium text-gray-700 dark:text-gray-300">Repeat</label>
                                        <select id="recurrencePattern" class="bg-white border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2 dark:bg-gray-600 dark:border-gray-500 dark:text-white">
                                            <option value="weekly">Weekly</option>
                                            <option value="biweekly">Every 2 weeks</option>
                                            <option value="monthly">Monthly</option>
                                        </select>
                                    </div>
                                    <div>
                                        <label for="recurrenceDay" class="block mb-1 text-xs font-medium text-gray-700 dark:text-gray-300">Day of Week</label>
                                        <select id="recurrenceDay" class="bg-white border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2 dark:bg-gray-600 dark:border-gray-500 dark:text-white">
                                            <option value="0">Sunday</option>
                                            <option value="1">Monday</option>
                                            <option value="2">Tuesday</option>
                                            <option value="3">Wednesday</option>
                                            <option value="4">Thursday</option>
                                            <option value="5">Friday</option>
                                            <option value="6">Saturday</option>
                                        </select>
                                    </div>
                                </div>
                                <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                                    <div>
                                        <label for="recurrenceTime" class="block mb-1 text-xs font-medium text-gray-700 dark:text-gray-300">Time</label>
                                        <input type="time" id="recurrenceTime" value="09:00" class="bg-white border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2 dark:bg-gray-600 dark:border-gray-500 dark:text-white">
                                    </div>
                                    <div>
                                        <label for="recurrenceEndDate" class="block mb-1 text-xs font-medium text-gray-700 dark:text-gray-300">Until (optional)</label>
                                        <input type="date" id="recurrenceEndDate" class="bg-white border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2 dark:bg-gray-600 dark:border-gray-500 dark:text-white">
                                    </div>
                                </div>
                                <p class="text-xs text-gray-500 dark:text-gray-400">
                                    <i class="ti ti-info-circle me-1"></i>
                                    Creates individual events based on the pattern. Leave end date empty to create 12 events.
                                </p>
                            </div>
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
                    <button type="button" class="hidden text-white bg-red-600 hover:bg-red-700 focus:ring-4 focus:ring-red-300 font-medium rounded-lg text-sm px-5 py-2.5 me-auto calendar-delete-event-btn dark:bg-red-600 dark:hover:bg-red-700 dark:focus:ring-red-900" id="deleteEventBtn">
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

    // Auto-fill end time 3 hours after start time
    document.getElementById('eventStartDate')?.addEventListener('change', function() {
        const startInput = this;
        const endInput = document.getElementById('eventEndDate');

        if (startInput.value && !endInput.value) {
            // Parse start time and add 3 hours
            const startDate = new Date(startInput.value);
            startDate.setHours(startDate.getHours() + 3);
            endInput.value = formatDateForInput(startDate);
        }
    });

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

    // Recurring checkbox toggles recurring options
    document.getElementById('eventRecurring')?.addEventListener('change', function() {
        const recurringOptions = document.getElementById('recurringOptions');
        const endDateSection = document.getElementById('eventEndDate').closest('div');
        const discordCheckbox = document.getElementById('eventNotifyDiscord');
        const discordLabel = discordCheckbox?.closest('.flex');

        if (this.checked) {
            recurringOptions.classList.remove('hidden');
            // Hide end date when recurring (each event can have its own duration if needed)
            if (endDateSection) endDateSection.style.opacity = '0.5';
            // Update Discord label to indicate it will only post once
            if (discordLabel) {
                const label = discordLabel.querySelector('label');
                if (label && !label.dataset.originalText) {
                    label.dataset.originalText = label.innerHTML;
                    label.innerHTML = '<i class="ti ti-brand-discord me-1"></i>Announce in Discord (single summary post)';
                }
            }
        } else {
            recurringOptions.classList.add('hidden');
            if (endDateSection) endDateSection.style.opacity = '1';
            // Restore original Discord label
            if (discordLabel) {
                const label = discordLabel.querySelector('label');
                if (label && label.dataset.originalText) {
                    label.innerHTML = label.dataset.originalText;
                }
            }
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
    document.getElementById('deleteEventBtn').classList.add('hidden');
    document.getElementById('saveEventBtn').innerHTML = '<i class="ti ti-check me-1"></i> Create Event';

    // Show recurring section for new events
    const recurringCheckbox = document.getElementById('eventRecurring');
    const recurringSection = recurringCheckbox?.closest('.mb-4.p-3');
    if (recurringSection) {
        recurringSection.classList.remove('hidden');
    }
    document.getElementById('recurringOptions')?.classList.add('hidden'); // Start collapsed

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

    // Hide recurring options when editing (can't convert single event to recurring)
    const recurringCheckbox = document.getElementById('eventRecurring');
    const recurringSection = recurringCheckbox?.closest('.mb-4.p-3');
    if (recurringCheckbox) {
        recurringCheckbox.checked = false;
    }
    if (recurringSection) {
        recurringSection.classList.add('hidden');
    }
    document.getElementById('recurringOptions')?.classList.add('hidden');

    // Update modal title and buttons
    document.getElementById('eventModalTitle').textContent = 'Edit League Event';
    document.getElementById('deleteEventBtn').classList.remove('hidden');
    document.getElementById('saveEventBtn').innerHTML = '<i class="ti ti-check me-1"></i> Save Changes';

    modal.show();
}

/**
 * Generate recurring event dates based on pattern
 * @param {Object} options - Recurrence options
 * @returns {Array<Date>} Array of dates for recurring events
 */
function generateRecurringDates(options) {
    const { pattern, dayOfWeek, time, endDate, maxOccurrences = 12 } = options;
    const dates = [];

    // Parse the time
    const [hours, minutes] = time.split(':').map(Number);

    // Start from next occurrence of the specified day
    let currentDate = new Date();
    currentDate.setHours(hours, minutes, 0, 0);

    // Move to the first occurrence of the target day
    const targetDay = parseInt(dayOfWeek, 10);
    const currentDay = currentDate.getDay();
    let daysUntilTarget = (targetDay - currentDay + 7) % 7;
    if (daysUntilTarget === 0 && currentDate < new Date()) {
        daysUntilTarget = 7; // If today is the target day but time has passed, go to next week
    }
    currentDate.setDate(currentDate.getDate() + daysUntilTarget);

    // Calculate end date limit
    const endDateLimit = endDate ? new Date(endDate) : null;
    if (endDateLimit) {
        endDateLimit.setHours(23, 59, 59, 999);
    }

    // Generate dates
    let occurrences = 0;
    while (occurrences < maxOccurrences) {
        // Check if we've passed the end date
        if (endDateLimit && currentDate > endDateLimit) {
            break;
        }

        dates.push(new Date(currentDate));
        occurrences++;

        // Move to next occurrence based on pattern
        switch (pattern) {
            case 'weekly':
                currentDate.setDate(currentDate.getDate() + 7);
                break;
            case 'biweekly':
                currentDate.setDate(currentDate.getDate() + 14);
                break;
            case 'monthly':
                // Move to same day of week in next month
                currentDate.setMonth(currentDate.getMonth() + 1);
                // Adjust to the correct day of week
                const newDay = currentDate.getDay();
                const diff = (targetDay - newDay + 7) % 7;
                currentDate.setDate(currentDate.getDate() + diff);
                break;
        }
    }

    return dates;
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
    const isRecurring = document.getElementById('eventRecurring')?.checked && !isEdit;

    // Base event data
    const baseEventData = {
        title: document.getElementById('eventTitle').value,
        event_type: document.getElementById('eventType').value,
        location: document.getElementById('eventLocation').value || null,
        description: document.getElementById('eventDescription').value || null,
        is_all_day: document.getElementById('eventAllDay').checked,
        notify_discord: document.getElementById('eventNotifyDiscord').checked
    };

    try {
        if (isRecurring) {
            // Generate recurring events
            const recurrenceOptions = {
                pattern: document.getElementById('recurrencePattern').value,
                dayOfWeek: document.getElementById('recurrenceDay').value,
                time: document.getElementById('recurrenceTime').value,
                endDate: document.getElementById('recurrenceEndDate').value || null
            };

            const dates = generateRecurringDates(recurrenceOptions);

            if (dates.length === 0) {
                showToast('error', 'No dates generated for the recurring pattern');
                return;
            }

            // Show progress
            showToast('info', `Creating ${dates.length} recurring events...`);

            let successCount = 0;
            let failCount = 0;
            const wantsDiscord = baseEventData.notify_discord;

            // Calculate event duration (3 hours default)
            const eventDurationHours = 3;

            // Create each event - only post to Discord for the FIRST event with a summary
            for (let i = 0; i < dates.length; i++) {
                const date = dates[i];
                const endDate = new Date(date);
                endDate.setHours(endDate.getHours() + eventDurationHours);

                // Build description with recurring info for the first event (Discord post)
                let description = baseEventData.description || '';
                if (i === 0 && wantsDiscord && dates.length > 1) {
                    // Add recurring schedule summary to the Discord announcement
                    const patternLabel = {
                        weekly: 'Weekly',
                        biweekly: 'Every 2 weeks',
                        monthly: 'Monthly'
                    }[recurrenceOptions.pattern] || 'Recurring';

                    const dayNames = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
                    const dayName = dayNames[parseInt(recurrenceOptions.dayOfWeek, 10)];

                    const scheduleInfo = `\n\n📅 **Recurring Schedule**: ${patternLabel} on ${dayName}s at ${recurrenceOptions.time} (${dates.length} events total)`;
                    description = description + scheduleInfo;
                }

                const eventData = {
                    ...baseEventData,
                    description: i === 0 ? description : baseEventData.description,
                    start_datetime: date.toISOString(),
                    end_datetime: endDate.toISOString(),
                    // Only notify Discord for the first event (it contains the recurring summary)
                    notify_discord: wantsDiscord && i === 0
                };

                try {
                    const response = await fetch('/api/calendar/league-events', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        },
                        body: JSON.stringify(eventData)
                    });

                    if (response.ok) {
                        successCount++;
                    } else {
                        failCount++;
                    }
                } catch (err) {
                    failCount++;
                }
            }

            modal.hide();

            if (failCount === 0) {
                const discordMsg = wantsDiscord ? ' (Discord announcement posted)' : '';
                showToast('success', `Created ${successCount} recurring events successfully${discordMsg}`);
            } else {
                showToast('warning', `Created ${successCount} events, ${failCount} failed`);
            }
        } else {
            // Single event create/update
            const eventData = {
                ...baseEventData,
                start_datetime: document.getElementById('eventStartDate').value,
                end_datetime: document.getElementById('eventEndDate').value || null
            };

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
        }

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

    // Use SweetAlert2 for confirmation instead of native browser confirm
    const result = await window.Swal.fire({
        title: 'Delete Event?',
        text: 'Are you sure you want to delete this event? This action cannot be undone.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc2626',
        cancelButtonColor: '#6b7280',
        confirmButtonText: 'Yes, delete it',
        cancelButtonText: 'Cancel'
    });

    if (!result.isConfirmed) {
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
