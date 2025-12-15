document.addEventListener('DOMContentLoaded', () => {
    const calendarEl = document.getElementById('leagueCalendar');
    if (!calendarEl) {
        // console.error('Element with ID "leagueCalendar" not found');
        return;
    }

    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';

    // Function to get the next Sunday
    function getNextSunday() {
        const today = new Date();
        const nextSunday = new Date(today);
        nextSunday.setDate(today.getDate() + (7 - today.getDay()) % 7);
        return nextSunday;
    }

    const calendar = new FullCalendar.Calendar(calendarEl, {
        themeSystem: 'bootstrap5',
        initialView: 'timeGridWeek',
        initialDate: getNextSunday(),
        headerToolbar: {
            left: 'prev,next today',
            center: 'title',
            right: 'timeGridDay,timeGridWeek,dayGridMonth'
        },
        slotMinTime: "07:30:00",
        slotMaxTime: "15:30:00",
        hiddenDays: [1, 2, 3, 4, 5, 6],
        allDaySlot: false,
        slotDuration: '00:15:00',
        slotLabelInterval: '01:00',
        eventDisplay: 'block',
        eventBackgroundColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
        eventBorderColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd',
        eventTextColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('white') : '#ffffff',
        eventTimeFormat: {
            hour: 'numeric',
            minute: '2-digit',
            meridiem: 'short'
        },
        height: 'auto',
        contentHeight: 'auto',
        datesSet: handleDateChange,
        eventContent: renderEventContent,
        eventClick: handleEventClick,
        views: {
            timeGridWeek: {
                type: 'timeGrid',
                duration: { days: 1 },
                buttonText: 'week'
            }
        },
        slotLabelFormat: {
            hour: 'numeric',
            minute: '2-digit',
            omitZeroMinute: false,
            meridiem: 'short'
        }
    });

    // Initialize calendar
    calendar.render();

    // Fetch and populate referees list based on the current week
    fetchAvailableReferees(calendar.getDate());

    // Fetch and load events into calendar
    loadCalendarEvents();

    // Handle form submission for assigning referees
    document.getElementById('assignRefForm').addEventListener('submit', assignReferee);

    // Attach event listener to the Remove Referee button
    document.getElementById('removeRefButton').addEventListener('click', removeReferee);

    // Attach event listener to the refresh button
    document.getElementById('refreshCalendar').addEventListener('click', () => {
        loadCalendarEvents();
        fetchAvailableReferees(calendar.getDate());
    });

    function renderEventContent(info) {
        const { event, timeText } = info;
        const { ref = 'Unassigned', division = 'Unknown League', teams = 'Teams Not Available' } = event.extendedProps;

        const container = document.createElement('div');
        container.classList.add('event-content-container');

        const header = document.createElement('div');
        header.classList.add('event-header');
        header.innerHTML = `<strong>${timeText} - ${division}</strong>`;

        const teamsEl = document.createElement('div');
        teamsEl.classList.add('event-teams');
        teamsEl.textContent = teams;

        const refEl = document.createElement('div');
        refEl.classList.add('event-referee');
        refEl.textContent = `Ref: ${ref}`;

        container.appendChild(header);
        container.appendChild(teamsEl);
        container.appendChild(refEl);

        return { domNodes: [container] };
    }

    function handleDateChange(dateInfo) {
        const start = dateInfo.start || calendar.getDate();
        const end = dateInfo.end || new Date(start.getTime() + 7 * 24 * 60 * 60 * 1000); // Default to 1 week later
        fetchAvailableReferees(start, end);
    }

    async function fetchAvailableReferees(startDate, endDate) {
        try {
            const response = await fetch(`/calendar/available_refs?start_date=${startDate.toISOString()}&end_date=${endDate.toISOString()}`);
            if (!response.ok) throw new Error('Failed to fetch referees.');

            const referees = await response.json();
            const refList = document.getElementById('refereeList');
            refList.innerHTML = ''; // Clear existing list

            if (referees.length === 0) {
                const noRef = document.createElement('li');
                noRef.classList.add('list-group-item', 'text-center', 'text-muted');
                noRef.textContent = 'No referees available.';
                refList.appendChild(noRef);
                return;
            }

            referees.forEach(ref => {
                const li = document.createElement('li');
                li.classList.add('list-group-item', 'd-flex', 'justify-content-between', 'align-items-center');
                li.innerHTML = `
                    ${ref.name}
                    <div>
                        <span class="badge bg-primary rounded-pill" title="Matches this week">
                            ${ref.matches_assigned_in_week}
                        </span>
                        <span class="badge bg-secondary rounded-pill" title="Total matches">
                            ${ref.total_matches_assigned}
                        </span>
                    </div>
                `;
                refList.appendChild(li);
            });
        } catch (error) {
            // console.error('Error fetching referees:', error);
        }
    }

    async function loadCalendarEvents() {
        try {
            const response = await fetch('/calendar/events');
            if (!response.ok) throw new Error('Failed to fetch events.');

            const data = await response.json();
            calendar.removeAllEvents();
            calendar.addEventSource(data.events);
            updateQuickStats(data.stats);
        } catch (error) {
            // console.error('Error loading events:', error);
        }
    }

    function updateQuickStats(stats) {
        document.getElementById('totalMatches').textContent = stats.totalMatches;
        document.getElementById('assignedRefs').textContent = stats.assignedRefs;
        document.getElementById('unassignedMatches').textContent = stats.unassignedMatches;
    }

    async function removeReferee() {
        const matchId = document.getElementById('matchId').value;

        if (!confirm('Are you sure you want to remove the referee from this match?')) {
            return;
        }

        try {
            const response = await fetch('/calendar/remove_ref', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ match_id: matchId })
            });

            const result = await response.json();

            if (!response.ok || result.error) {
                const errorMsg = result.error || 'Failed to remove referee.';
                displayModalFeedback('assignRefFeedback', errorMsg, 'danger');
                return;
            }

            displayModalFeedback('assignRefFeedback', 'Referee removed successfully!', 'success');

            // Refresh calendar and referees list after a short delay
            setTimeout(() => {
                bootstrap.Modal.getInstance(document.getElementById('assignRefModal')).hide();
                loadCalendarEvents();
                fetchAvailableReferees(calendar.getDate());
            }, 1000);
        } catch (error) {
            // console.error('Error removing referee:', error);
            displayModalFeedback('assignRefFeedback', 'Error removing referee.', 'danger');
        }
    }
    async function handleEventClick(info) {
        info.jsEvent.preventDefault();

        const event = info.event;
        const matchId = event.id;
        const matchTitle = event.title;
        const matchDescription = event.extendedProps.description || '';
        const matchDate = new Date(event.start).toLocaleDateString();
        const matchTime = new Date(event.start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const currentRef = event.extendedProps.ref || 'Unassigned';

        // Populate modal fields
        document.getElementById('matchId').value = matchId;
        document.getElementById('matchDetails').value = `${matchTitle} - ${matchDescription}`;
        document.getElementById('matchDateTime').value = `${matchDate} ${matchTime}`;

        if (currentRef !== 'Unassigned') {
            document.getElementById('currentRefereeSection').style.display = 'block';
            document.getElementById('currentRefereeName').textContent = currentRef;
            document.getElementById('removeRefButton').style.display = 'inline-block';
        } else {
            document.getElementById('currentRefereeSection').style.display = 'none';
            document.getElementById('removeRefButton').style.display = 'none';
        }

        // Fetch available referees for the match
        try {
            const response = await fetch(`/calendar/refs?match_id=${matchId}`);
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to fetch referees for this match.');
            }

            const referees = await response.json();
            const refSelect = document.getElementById('refSelect');
            refSelect.innerHTML = '<option value="" selected disabled>Choose a referee</option>';

            if (referees.length === 0) {
                const option = document.createElement('option');
                option.value = "";
                option.textContent = "No referees available";
                option.disabled = true;
                refSelect.appendChild(option);
            } else {
                referees.forEach(ref => {
                    const option = document.createElement('option');
                    option.value = ref.id;
                    option.textContent = `${ref.name} (Week: ${ref.matches_assigned_in_week}, Total: ${ref.total_matches_assigned})`;
                    refSelect.appendChild(option);
                });
            }

            refSelect.disabled = false;
            document.getElementById('assignRefButton').disabled = false;
        } catch (error) {
            // console.error('Error fetching referees:', error);
            displayModalFeedback('assignRefFeedback', `Error fetching referees: ${error.message}`, 'danger');
        }

        clearModalFeedback('assignRefFeedback');

        const assignRefModal = new bootstrap.Modal(document.getElementById('assignRefModal'));
        assignRefModal.show();
    }

    async function assignReferee(event) {
        event.preventDefault();

        const matchId = document.getElementById('matchId').value;
        const refId = document.getElementById('refSelect').value;

        if (!refId) {
            displayModalFeedback('assignRefFeedback', 'Please select a referee.', 'warning');
            return;
        }

        try {
            const response = await fetch('/calendar/assign_ref', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken,
                    'Accept': 'application/json'
                },
                body: JSON.stringify({ match_id: matchId, ref_id: refId })
            });

            const result = await response.json();

            if (!response.ok || result.error) {
                const errorMsg = result.error || 'Failed to assign referee.';
                displayModalFeedback('assignRefFeedback', errorMsg, 'danger');
                return;
            }

            displayModalFeedback('assignRefFeedback', 'Referee assigned successfully!', 'success');

            // Refresh calendar and referees list after a short delay
            setTimeout(() => {
                bootstrap.Modal.getInstance(document.getElementById('assignRefModal')).hide();
                loadCalendarEvents();
                fetchAvailableReferees(calendar.getDate());
            }, 1000);
        } catch (error) {
            // console.error('Error assigning referee:', error);
            displayModalFeedback('assignRefFeedback', 'Error assigning referee.', 'danger');
        }
    }

    function displayModalFeedback(elementId, message, type) {
        const feedbackEl = document.getElementById(elementId);
        feedbackEl.innerHTML = `<div class="alert alert-${type} p-2 m-0" role="alert">${message}</div>`;
    }

    function clearModalFeedback(elementId) {
        const feedbackEl = document.getElementById(elementId);
        feedbackEl.innerHTML = '';
    }
});