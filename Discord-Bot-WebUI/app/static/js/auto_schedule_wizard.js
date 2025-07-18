/**
 * Auto Schedule Wizard JavaScript
 * 
 * This file contains all the JavaScript functionality for the auto-schedule wizard,
 * including season creation, structure configuration, calendar management, and team setup.
 */

// Global wizard state
let currentStep = 1;
const maxSteps = 6;

// Global state for calendar
let calendarState = {
    weeks: [],
    startDate: null,
    regularWeeks: 7,
    includeTST: false,
    includeFUN: false,
    byeWeeks: 0
};

// Calendar drag and drop state
let calendarDraggedElement = null;
let draggedIndex = null;

/**
 * Initialize the season wizard modal
 */
function startSeasonWizard() {
    // MEMORY LEAK FIX: Clean up previous state before starting new wizard
    cleanupCalendarState();
    
    document.getElementById('seasonWizardModal').style.display = 'block';
    const modal = new bootstrap.Modal(document.getElementById('seasonWizardModal'));
    modal.show();
    
    // Set default start date to next Sunday (you can change this to any day)
    const today = new Date();
    const nextSunday = new Date(today);
    nextSunday.setDate(today.getDate() + (7 - today.getDay()) % 7);
    document.getElementById('seasonStartDate').value = nextSunday.toISOString().split('T')[0];
    
    updateCalendarPreview();
}

/**
 * Clean up calendar state and event listeners to prevent memory leaks
 */
function cleanupCalendarState() {
    // Clear calendar state
    calendarState.weeks = [];
    calendarState.startDate = null;
    
    // Remove all existing event listeners from calendar items
    document.querySelectorAll('.week-item').forEach(item => {
        // Clone the element to remove all event listeners
        const newItem = item.cloneNode(true);
        if (item.parentNode) {
            item.parentNode.replaceChild(newItem, item);
        }
    });
    
    // Reset drag state
    calendarDraggedElement = null;
    draggedIndex = null;
    
    console.log('Calendar state cleaned up');
}

/**
 * Show existing seasons section
 */
function showExistingSeasons() {
    document.getElementById('existingSeasons').classList.remove('d-none');
    document.querySelector('.row.mb-4:nth-child(2)').style.display = 'none';
}

/**
 * Show main view (hide existing seasons)
 */
function showMainView() {
    document.getElementById('existingSeasons').classList.add('d-none');
    document.querySelector('.row.mb-4:nth-child(2)').style.display = '';
}

/**
 * Set a season as active
 */
function setActiveSeason(seasonId, leagueType) {
    if (confirm(`Are you sure you want to set this season as the current ${leagueType} season?`)) {
        fetch(window.autoScheduleUrls.setActiveSeason, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name=csrf-token]').getAttribute('content')
            },
            body: JSON.stringify({
                season_id: seasonId,
                league_type: leagueType
            })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Refresh the page to show updated season status
                location.reload();
            } else {
                alert('Error: ' + data.error);
            }
        })
        .catch(error => {
            console.error('Error:', error);
            alert('An error occurred while updating the active season');
        });
    }
}

/**
 * Navigate to next step in wizard
 */
function nextStep() {
    if (currentStep < maxSteps) {
        if (validateStep(currentStep)) {
            updateStepDisplay(currentStep + 1);
        }
    }
}

/**
 * Navigate to previous step in wizard
 */
function previousStep() {
    if (currentStep > 1) {
        updateStepDisplay(currentStep - 1);
    }
}

/**
 * Update the wizard step display
 */
function updateStepDisplay(step) {
    // Hide current step
    document.querySelector(`.wizard-step[data-step="${currentStep}"]`).classList.remove('active');
    document.querySelector(`.step[data-step="${currentStep}"]`).classList.remove('active');
    
    // Show new step
    currentStep = step;
    document.querySelector(`.wizard-step[data-step="${currentStep}"]`).classList.add('active');
    document.querySelector(`.step[data-step="${currentStep}"]`).classList.add('active');
    
    // Update previous steps as completed
    for (let i = 1; i < currentStep; i++) {
        document.querySelector(`.step[data-step="${i}"]`).classList.add('completed');
    }
    
    // Update buttons
    document.getElementById('prevBtn').style.display = currentStep === 1 ? 'none' : 'block';
    document.getElementById('nextBtn').style.display = currentStep === maxSteps ? 'none' : 'block';
    document.getElementById('createBtn').classList.toggle('d-none', currentStep !== maxSteps);
    
    if (currentStep === 2) {
        updateStructureSections();
    } else if (currentStep === 3) {
        updateCalendarSections();
        generateCalendarPreview(); // Don't force regeneration - preserve drag-and-drop changes
    } else if (currentStep === 5) {
        updateTeamSections();
    } else if (currentStep === 6) {
        generateSeasonSummary();
    }
}

/**
 * Validate current step
 */
function validateStep(step) {
    // Add validation logic for each step
    return true;
}

/**
 * Update season structure sections based on league type
 */
function updateStructureSections() {
    const leagueType = document.getElementById('leagueType').value;
    const pubLeagueStructure = document.getElementById('pubLeagueStructure');
    const ecsFcStructure = document.getElementById('ecsFcStructure');
    
    if (leagueType === 'Pub League') {
        pubLeagueStructure.classList.remove('d-none');
        ecsFcStructure.classList.add('d-none');
        updateTotalWeeks('premier');
        updateTotalWeeks('classic');
    } else if (leagueType === 'ECS FC') {
        pubLeagueStructure.classList.add('d-none');
        ecsFcStructure.classList.remove('d-none');
        updateTotalWeeks('ecsFc');
    }
}

/**
 * Update total weeks calculation for a division
 */
function updateTotalWeeks(divisionType) {
    // Get shared special weeks
    const sharedFunEl = document.getElementById('sharedHasFunWeek');
    const sharedTstEl = document.getElementById('sharedHasTstWeek');
    const sharedByeEl = document.getElementById('sharedHasByeWeek');
    const funWeeks = (sharedFunEl && sharedFunEl.checked) ? 1 : 0;
    const tstWeeks = (sharedTstEl && sharedTstEl.checked) ? 1 : 0;
    const byeWeeks = (sharedByeEl && sharedByeEl.checked) ? 1 : 0;
    
    if (divisionType === 'premier') {
        const regularEl = document.getElementById('premierRegularWeeks');
        const playoffEl = document.getElementById('premierPlayoffWeeks');
        const bonusWeekEl = document.getElementById('premierHasBonusWeek');
        const totalEl = document.getElementById('premierTotalWeeks');
        
        if (regularEl && playoffEl && bonusWeekEl && totalEl) {
            const regular = parseInt(regularEl.value) || 0;
            const playoff = parseInt(playoffEl.value) || 0;
            const bonus = bonusWeekEl.checked ? 1 : 0;
            const total = regular + playoff + funWeeks + tstWeeks + byeWeeks + bonus;
            totalEl.textContent = total;
        }
    } else if (divisionType === 'classic') {
        const regularEl = document.getElementById('classicRegularWeeks');
        const playoffEl = document.getElementById('classicPlayoffWeeks');
        const bonusWeekEl = document.getElementById('classicHasBonusWeek');
        const totalEl = document.getElementById('classicTotalWeeks');
        
        if (regularEl && playoffEl && bonusWeekEl && totalEl) {
            const regular = parseInt(regularEl.value) || 0;
            const playoff = parseInt(playoffEl.value) || 0;
            const bonus = bonusWeekEl.checked ? 1 : 0;
            const total = regular + playoff + funWeeks + tstWeeks + byeWeeks + bonus;
            totalEl.textContent = total;
        }
    } else if (divisionType === 'ecsFc') {
        const regularEl = document.getElementById('ecsFcRegularWeeks');
        const playoffEl = document.getElementById('ecsFcPlayoffWeeks');
        const totalEl = document.getElementById('ecsFcTotalWeeks');
        
        if (regularEl && playoffEl && totalEl) {
            const regular = parseInt(regularEl.value) || 0;
            const playoff = parseInt(playoffEl.value) || 0;
            const total = regular + playoff;
            totalEl.textContent = total;
        }
    }
}

/**
 * Toggle practice configuration display
 */
function togglePracticeConfig() {
    const practiceCheckbox = document.getElementById('classicHasPractice');
    const practiceConfig = document.querySelector('.classic-practice-config');
    
    if (practiceCheckbox.checked) {
        practiceConfig.style.display = 'block';
    } else {
        practiceConfig.style.display = 'none';
    }
}

/**
 * Update calendar sections based on league type
 */
function updateCalendarSections() {
    const leagueType = document.getElementById('leagueType').value;
    const pubLeagueCalendar = document.getElementById('pubLeagueCalendar');
    const ecsFcCalendar = document.getElementById('ecsFcCalendar');
    
    if (leagueType === 'Pub League') {
        pubLeagueCalendar.classList.remove('d-none');
        ecsFcCalendar.classList.add('d-none');
        updateCalendarSummary();
    } else if (leagueType === 'ECS FC') {
        pubLeagueCalendar.classList.add('d-none');
        ecsFcCalendar.classList.remove('d-none');
        updateCalendarSummary();
    }
}

/**
 * Update calendar summary display
 */
function updateCalendarSummary() {
    const leagueType = document.getElementById('leagueType').value;
    const summaryEl = document.getElementById('calendarSummary');
    
    if (leagueType === 'Pub League') {
        // Get structure values
        const premierRegular = document.getElementById('premierRegularWeeks')?.value || 7;
        const premierPlayoff = document.getElementById('premierPlayoffWeeks')?.value || 2;
        const classicRegular = document.getElementById('classicRegularWeeks')?.value || 8;
        const classicPlayoff = document.getElementById('classicPlayoffWeeks')?.value || 1;
        
        const hasFun = document.getElementById('sharedHasFunWeek')?.checked || false;
        const hasTst = document.getElementById('sharedHasTstWeek')?.checked || false;
        const hasBye = document.getElementById('sharedHasByeWeek')?.checked || false;
        const hasBonus = document.getElementById('premierHasBonusWeek')?.checked || false;
        
        let summary = `<strong>Premier:</strong> ${premierRegular} regular + ${premierPlayoff} playoff`;
        if (hasFun || hasTst || hasBye || hasBonus) {
            summary += ' + ';
            const specials = [];
            if (hasFun) specials.push('Fun');
            if (hasTst) specials.push('TST');
            if (hasBye) specials.push('BYE');
            if (hasBonus) specials.push('Bonus');
            summary += specials.join(', ');
        }
        
        summary += `<br><strong>Classic:</strong> ${classicRegular} regular + ${classicPlayoff} playoff`;
        if (hasFun || hasTst || hasBye) {
            summary += ' + ';
            const specials = [];
            if (hasFun) specials.push('Fun');
            if (hasTst) specials.push('TST');
            if (hasBye) specials.push('BYE');
            summary += specials.join(', ');
        }
        
        summaryEl.innerHTML = summary;
    } else if (leagueType === 'ECS FC') {
        const regular = document.getElementById('ecsFcRegularWeeks')?.value || 8;
        const playoff = document.getElementById('ecsFcPlayoffWeeks')?.value || 1;
        
        summaryEl.innerHTML = `<strong>ECS FC:</strong> ${regular} regular + ${playoff} playoff weeks`;
    }
}

/**
 * Generate calendar preview
 */
function generateCalendarPreview(forceRegenerate = false) {
    const leagueType = document.getElementById('leagueType').value;
    const startDateStr = document.getElementById('seasonStartDate').value;
    
    if (!startDateStr) {
        return;
    }
    
    // Parse date string properly to avoid timezone issues
    // When creating Date from "YYYY-MM-DD", add time to ensure local date
    const [year, month, day] = startDateStr.split('-').map(num => parseInt(num));
    const startDate = new Date(year, month - 1, day); // month is 0-indexed
    
    // Always regenerate calendar when called - this ensures visibility
    calendarState.startDate = startDate;
    
    if (leagueType === 'Pub League') {
        generatePubLeagueCalendar(startDate);
    } else if (leagueType === 'ECS FC') {
        generateEcsFcCalendar(startDate);
    }
}

/**
 * Generate Pub League calendar with Premier and Classic divisions
 * FIXED: Properly handle shared special weeks (TST, FUN) between divisions
 */
function generatePubLeagueCalendar(startDate) {
    // Clear calendar state before generating new calendars
    calendarState.weeks = [];
    
    // Generate combined calendar with shared special weeks
    const combinedCalendar = generateCombinedPubLeagueCalendar(startDate);
    
    // Split the calendar HTML for display
    document.getElementById('premierCalendarPreview').innerHTML = combinedCalendar.premierHTML;
    document.getElementById('classicCalendarPreview').innerHTML = combinedCalendar.classicHTML;
    
    // Initialize drag and drop functionality
    initializeCalendarDragAndDrop();
}

/**
 * Regenerate calendar HTML from existing calendar state
 */
function regenerateCalendarHTML() {
    const leagueType = document.getElementById('leagueType').value;
    
    if (leagueType === 'Pub League') {
        // Group weeks by division
        const premierWeeks = calendarState.weeks.filter(w => w.division === 'premier');
        const classicWeeks = calendarState.weeks.filter(w => w.division === 'classic');
        
        document.getElementById('premierCalendarPreview').innerHTML = generateCalendarHTMLFromState(premierWeeks);
        document.getElementById('classicCalendarPreview').innerHTML = generateCalendarHTMLFromState(classicWeeks);
    } else if (leagueType === 'ECS FC') {
        const ecsFcWeeks = calendarState.weeks.filter(w => w.division === 'ecs_fc');
        document.getElementById('ecsFcCalendarPreview').innerHTML = generateCalendarHTMLFromState(ecsFcWeeks);
    }
    
    // Initialize drag and drop functionality
    initializeCalendarDragAndDrop();
}

/**
 * Generate calendar HTML from calendar state
 */
function generateCalendarHTMLFromState(weeks) {
    let calendar = '<div class="calendar-weeks">';
    
    weeks.forEach(week => {
        const weekTypeClass = week.type === 'PLAYOFF' ? 'playoff-week' : 
                             week.type === 'FUN' ? 'fun-week' : 
                             week.type === 'TST' ? 'tst-week' : 
                             week.type === 'BYE' ? 'bye-week' : 
                             week.type === 'BONUS' ? 'bonus-week' : 
                             'regular-week';
        
        const weekTypeText = week.type === 'PLAYOFF' ? 
                            (week.division === 'classic' ? 'Playoffs' : `Playoffs Round ${week.weekNumber - 7}`) :
                            week.type === 'FUN' ? 'Fun Week' :
                            week.type === 'TST' ? 'TST Week' :
                            week.type === 'BYE' ? 'BYE Week' :
                            week.type === 'BONUS' ? 'Bonus Week' :
                            'Regular' + (week.isPractice ? ' (Practice Game 1)' : '');
        
        calendar += `<div class="week-item ${weekTypeClass}" draggable="true" data-week="${week.weekNumber}" data-type="${week.type.toLowerCase()}">
            <div class="week-number">Week ${week.weekNumber}</div>
            <div class="week-date">${formatDate(week.date)}</div>
            <div class="week-type">${weekTypeText}</div>
        </div>`;
    });
    
    calendar += '</div>';
    return calendar;
}

/**
 * Generate combined Pub League calendar with proper shared special weeks
 * FIXED: Proper shared TST/FUN/BYE weeks for both Premier and Classic divisions
 */
function generateCombinedPubLeagueCalendar(startDate) {
    // Get configuration from form
    const premierRegular = parseInt(document.getElementById('premierRegularWeeks')?.value) || 7;
    const premierPlayoff = parseInt(document.getElementById('premierPlayoffWeeks')?.value) || 2;
    const classicRegular = parseInt(document.getElementById('classicRegularWeeks')?.value) || 8;
    const classicPlayoff = parseInt(document.getElementById('classicPlayoffWeeks')?.value) || 1;
    
    // Shared special weeks - these affect BOTH divisions
    const hasFun = document.getElementById('sharedHasFunWeek')?.checked || false;
    const hasTst = document.getElementById('sharedHasTstWeek')?.checked || false;
    const hasBye = document.getElementById('sharedHasByeWeek')?.checked || false;
    
    // Division-specific bonus weeks
    const premierHasBonus = document.getElementById('premierHasBonusWeek')?.checked || false;
    const classicHasBonus = document.getElementById('classicHasBonusWeek')?.checked || false;
    
    let currentDate = new Date(startDate);
    let weekNumber = 1;
    
    // Build calendar structure
    const calendar = {
        premierHTML: '<div class="calendar-weeks">',
        classicHTML: '<div class="calendar-weeks">'
    };
    
    // Phase 1: Regular season weeks
    const maxRegularWeeks = Math.max(premierRegular, classicRegular);
    for (let i = 0; i < maxRegularWeeks; i++) {
        const weekDate = new Date(currentDate);
        
        // Premier regular weeks
        if (i < premierRegular) {
            const isPractice = false; // Premier doesn't have practice weeks
            
            calendarState.weeks.push({
                weekNumber: weekNumber,
                date: new Date(weekDate),
                type: 'Regular',
                division: 'premier',
                isPractice: isPractice
            });
            
            calendar.premierHTML += `<div class="week-item regular-week" draggable="true" data-week="${weekNumber}" data-type="regular">
                <div class="week-number">Week ${weekNumber}</div>
                <div class="week-date">${formatDate(weekDate)}</div>
                <div class="week-type">Regular</div>
            </div>`;
        }
        
        // Classic regular weeks
        if (i < classicRegular) {
            const isPractice = (i === 0 || i === 2); // Classic practice weeks 1 and 3
            
            calendarState.weeks.push({
                weekNumber: weekNumber,
                date: new Date(weekDate),
                type: 'Regular',
                division: 'classic',
                isPractice: isPractice
            });
            
            const practiceText = isPractice ? ' (Practice Game 1)' : '';
            calendar.classicHTML += `<div class="week-item regular-week" draggable="true" data-week="${weekNumber}" data-type="regular">
                <div class="week-number">Week ${weekNumber}</div>
                <div class="week-date">${formatDate(weekDate)}</div>
                <div class="week-type">Regular${practiceText}</div>
            </div>`;
        }
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    // Phase 2: Shared special weeks (TST, FUN)
    if (hasFun) {
        const weekDate = new Date(currentDate);
        
        // Add FUN week for BOTH divisions with same week number
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(weekDate),
            type: 'FUN',
            division: 'premier'
        });
        
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(weekDate),
            type: 'FUN',
            division: 'classic'
        });
        
        // Add to both calendar HTMLs - draggable but synchronized
        const funWeekHTML = `<div class="week-item fun-week shared-week" draggable="true" data-week="${weekNumber}" data-type="fun" data-shared-type="fun">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(weekDate)}</div>
            <div class="week-type">Fun Week (Shared)</div>
        </div>`;
        
        calendar.premierHTML += funWeekHTML;
        calendar.classicHTML += funWeekHTML;
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    if (hasTst) {
        const weekDate = new Date(currentDate);
        
        // Add TST week for BOTH divisions with same week number
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(weekDate),
            type: 'TST',
            division: 'premier'
        });
        
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(weekDate),
            type: 'TST',
            division: 'classic'
        });
        
        // Add to both calendar HTMLs - draggable but synchronized
        const tstWeekHTML = `<div class="week-item tst-week shared-week" draggable="true" data-week="${weekNumber}" data-type="tst" data-shared-type="tst">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(weekDate)}</div>
            <div class="week-type">TST Week (Shared)</div>
        </div>`;
        
        calendar.premierHTML += tstWeekHTML;
        calendar.classicHTML += tstWeekHTML;
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    if (hasBye) {
        const weekDate = new Date(currentDate);
        
        // Add BYE week for BOTH divisions with same week number
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(weekDate),
            type: 'BYE',
            division: 'premier'
        });
        
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(weekDate),
            type: 'BYE',
            division: 'classic'
        });
        
        // Add to both calendar HTMLs - draggable but synchronized
        const byeWeekHTML = `<div class="week-item bye-week shared-week" draggable="true" data-week="${weekNumber}" data-type="bye" data-shared-type="bye">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(weekDate)}</div>
            <div class="week-type">BYE Week (Shared)</div>
        </div>`;
        
        calendar.premierHTML += byeWeekHTML;
        calendar.classicHTML += byeWeekHTML;
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    // Phase 3: Playoff weeks
    const maxPlayoffWeeks = Math.max(premierPlayoff, classicPlayoff);
    for (let i = 0; i < maxPlayoffWeeks; i++) {
        const weekDate = new Date(currentDate);
        
        // Premier playoff weeks
        if (i < premierPlayoff) {
            calendarState.weeks.push({
                weekNumber: weekNumber,
                date: new Date(weekDate),
                type: 'PLAYOFF',
                division: 'premier'
            });
            
            const playoffText = `Playoffs Round ${i + 1}`;
            calendar.premierHTML += `<div class="week-item playoff-week" draggable="true" data-week="${weekNumber}" data-type="playoff">
                <div class="week-number">Week ${weekNumber}</div>
                <div class="week-date">${formatDate(weekDate)}</div>
                <div class="week-type">${playoffText}</div>
            </div>`;
        }
        
        // Classic playoff weeks
        if (i < classicPlayoff) {
            calendarState.weeks.push({
                weekNumber: weekNumber,
                date: new Date(weekDate),
                type: 'PLAYOFF',
                division: 'classic'
            });
            
            const playoffText = 'Playoffs';
            calendar.classicHTML += `<div class="week-item playoff-week" draggable="true" data-week="${weekNumber}" data-type="playoff">
                <div class="week-number">Week ${weekNumber}</div>
                <div class="week-date">${formatDate(weekDate)}</div>
                <div class="week-type">${playoffText}</div>
            </div>`;
        }
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    // Phase 4: Bonus weeks (division-specific)
    if (premierHasBonus) {
        const weekDate = new Date(currentDate);
        
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(weekDate),
            type: 'BONUS',
            division: 'premier'
        });
        
        calendar.premierHTML += `<div class="week-item bonus-week" draggable="true" data-week="${weekNumber}" data-type="bonus">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(weekDate)}</div>
            <div class="week-type">Bonus Week</div>
        </div>`;
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    if (classicHasBonus) {
        const weekDate = new Date(currentDate);
        
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(weekDate),
            type: 'BONUS',
            division: 'classic'
        });
        
        calendar.classicHTML += `<div class="week-item bonus-week" draggable="true" data-week="${weekNumber}" data-type="bonus">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(weekDate)}</div>
            <div class="week-type">Bonus Week</div>
        </div>`;
    }
    
    // Close calendar HTML
    calendar.premierHTML += '</div>';
    calendar.classicHTML += '</div>';
    
    return calendar;
}

/**
 * Generate calendar for a specific division
 */
function generateDivisionCalendar(division, startDate, startWeekNumber = 1) {
    const regularWeeks = parseInt(document.getElementById(`${division}RegularWeeks`)?.value) || 7;
    const playoffWeeks = parseInt(document.getElementById(`${division}PlayoffWeeks`)?.value) || 2;
    const hasFun = document.getElementById('sharedHasFunWeek')?.checked || false;
    const hasTst = document.getElementById('sharedHasTstWeek')?.checked || false;
    const hasBonus = document.getElementById(`${division}HasBonusWeek`)?.checked || false;
    
    let calendar = '<div class="calendar-weeks">';
    let currentDate = new Date(startDate);
    let weekNumber = startWeekNumber;
    
    // Regular season weeks
    for (let i = 0; i < regularWeeks; i++) {
        const isPractice = (division === 'classic' && (i === 0 || i === 2)); // Weeks 1 and 3 for classic
        const practiceText = isPractice ? ' (Practice Game 1)' : '';
        
        // Add to calendar state - practice sessions are still Regular weeks
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'Regular',
            division: division,
            isPractice: isPractice
        });
        
        calendar += `<div class="week-item regular-week" draggable="true" data-week="${weekNumber}" data-type="regular">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(currentDate)}</div>
            <div class="week-type">Regular${practiceText}</div>
        </div>`;
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    // Special weeks
    if (hasFun) {
        // Add to calendar state
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'FUN',
            division: division
        });
        
        calendar += `<div class="week-item fun-week" draggable="true" data-week="${weekNumber}" data-type="fun">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(currentDate)}</div>
            <div class="week-type">Fun Week</div>
        </div>`;
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    if (hasTst) {
        // Add to calendar state
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'TST',
            division: division
        });
        
        calendar += `<div class="week-item tst-week" draggable="true" data-week="${weekNumber}" data-type="tst">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(currentDate)}</div>
            <div class="week-type">TST Week</div>
        </div>`;
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    // Playoff weeks
    for (let i = 0; i < playoffWeeks; i++) {
        let playoffText;
        let specialNote = '';
        
        if (division === 'classic') {
            // Classic only has 1 playoff round
            playoffText = 'Playoffs';
        } else if (division === 'premier') {
            // Premier has 2 playoff rounds
            playoffText = `Playoffs Round ${i + 1}`;
        } else {
            playoffText = `Playoffs Round ${i + 1}`;
        }
        
        // Add to calendar state
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'PLAYOFF',
            division: division
        });
        
        calendar += `<div class="week-item playoff-week" draggable="true" data-week="${weekNumber}" data-type="playoff">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(currentDate)}</div>
            <div class="week-type">${playoffText}${specialNote}</div>
        </div>`;
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    // Bonus week (Premier only)
    if (hasBonus && division === 'premier') {
        // Add to calendar state
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'BONUS',
            division: division
        });
        
        calendar += `<div class="week-item bonus-week" draggable="true" data-week="${weekNumber}" data-type="bonus">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(currentDate)}</div>
            <div class="week-type">Bonus Week</div>
        </div>`;
    }
    
    calendar += '</div>';
    return calendar;
}

/**
 * Initialize drag and drop functionality for calendar items
 */
function initializeCalendarDragAndDrop() {
    const weekItems = document.querySelectorAll('.week-item');
    
    weekItems.forEach(item => {
        // Add drag event listeners to all week items (including shared weeks)
        item.addEventListener('dragstart', handleCalendarDragStart);
        item.addEventListener('dragover', handleCalendarDragOver);
        item.addEventListener('dragenter', handleCalendarDragEnter);
        item.addEventListener('dragleave', handleCalendarDragLeave);
        item.addEventListener('drop', handleCalendarDrop);
        item.addEventListener('dragend', handleCalendarDragEnd);
    });
}

/**
 * Handle calendar drag start
 */
function handleCalendarDragStart(e) {
    calendarDraggedElement = e.target;
    e.target.style.opacity = '0.5';
    e.dataTransfer.effectAllowed = 'move';
}

/**
 * Handle calendar drag enter
 */
function handleCalendarDragEnter(e) {
    e.preventDefault();
}

/**
 * Handle calendar drag leave
 */
function handleCalendarDragLeave(e) {
    // Only clear indicators if we're leaving the week item entirely
    const weekItem = e.target.closest('.week-item');
    if (weekItem && !weekItem.contains(e.relatedTarget)) {
        clearDropIndicators();
    }
}

/**
 * Handle calendar drag over
 */
function handleCalendarDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    
    // Get the actual week item, not just the element being hovered
    const weekItem = e.target.closest('.week-item');
    if (weekItem && weekItem !== calendarDraggedElement) {
        // Clear any existing drop indicators
        clearDropIndicators();
        
        // Calculate drop position based on mouse position
        const rect = weekItem.getBoundingClientRect();
        const midPoint = rect.top + rect.height / 2;
        
        if (e.clientY < midPoint) {
            // Drop above
            weekItem.style.borderTop = '3px solid #007bff';
            weekItem.dataset.dropPosition = 'before';
        } else {
            // Drop below
            weekItem.style.borderBottom = '3px solid #007bff';
            weekItem.dataset.dropPosition = 'after';
        }
    }
}

/**
 * Handle calendar drop
 */
function handleCalendarDrop(e) {
    e.preventDefault();
    
    if (calendarDraggedElement) {
        const targetWeekItem = e.target.closest('.week-item');
        const draggedWeekItem = calendarDraggedElement.closest('.week-item');
        
        if (targetWeekItem && draggedWeekItem && targetWeekItem !== draggedWeekItem) {
            const container = targetWeekItem.closest('.calendar-container');
            const draggedContainer = draggedWeekItem.closest('.calendar-container');
            
            // Only allow reordering within the same division
            if (container === draggedContainer) {
                const dropPosition = targetWeekItem.dataset.dropPosition;
                const calendarWeeks = container.querySelector('.calendar-weeks');
                
                if (calendarWeeks) {
                    // Check if this is a shared week
                    const isSharedWeek = draggedWeekItem.classList.contains('shared-week');
                    const sharedType = draggedWeekItem.dataset.sharedType;
                    
                    if (dropPosition === 'before') {
                        calendarWeeks.insertBefore(draggedWeekItem, targetWeekItem);
                    } else if (dropPosition === 'after') {
                        calendarWeeks.insertBefore(draggedWeekItem, targetWeekItem.nextSibling);
                    }
                    
                    // If this is a shared week, synchronize the corresponding week in the other division
                    if (isSharedWeek && sharedType) {
                        synchronizeSharedWeek(draggedWeekItem, sharedType, dropPosition, targetWeekItem);
                    }
                    
                    // Update week numbers and recalculate dates after reordering
                    updateWeekNumbersAndDates(container);
                    
                    // If shared week was moved, update the other division too
                    if (isSharedWeek) {
                        const otherContainer = getOtherDivisionContainer(container);
                        if (otherContainer) {
                            updateWeekNumbersAndDates(otherContainer);
                        }
                    }
                    
                    // Save the current state after reordering
                    console.log('Saving calendar state after drag-and-drop');
                }
            }
        }
    }
    
    // Clear all drop indicators
    clearDropIndicators();
}

/**
 * Handle calendar drag end
 */
function handleCalendarDragEnd(e) {
    e.target.style.opacity = '';
    calendarDraggedElement = null;
    clearDropIndicators();
}

/**
 * Clear all drop indicators
 */
function clearDropIndicators() {
    const allWeekItems = document.querySelectorAll('.week-item');
    allWeekItems.forEach(item => {
        item.style.borderTop = '';
        item.style.borderBottom = '';
        delete item.dataset.dropPosition;
    });
}

/**
 * Synchronize shared week movement to the other division
 */
function synchronizeSharedWeek(draggedWeekItem, sharedType, dropPosition, targetWeekItem) {
    const otherContainer = getOtherDivisionContainer(draggedWeekItem.closest('.calendar-container'));
    if (!otherContainer) return;
    
    // Find the corresponding shared week in the other division
    const otherSharedWeek = otherContainer.querySelector(`[data-shared-type="${sharedType}"]`);
    if (!otherSharedWeek) return;
    
    // Find the corresponding target week in the other division
    const targetWeekNumber = targetWeekItem.dataset.week;
    const otherTargetWeek = otherContainer.querySelector(`[data-week="${targetWeekNumber}"]`);
    if (!otherTargetWeek) return;
    
    const otherCalendarWeeks = otherContainer.querySelector('.calendar-weeks');
    if (!otherCalendarWeeks) return;
    
    // Move the shared week in the other division to the same relative position
    if (dropPosition === 'before') {
        otherCalendarWeeks.insertBefore(otherSharedWeek, otherTargetWeek);
    } else if (dropPosition === 'after') {
        otherCalendarWeeks.insertBefore(otherSharedWeek, otherTargetWeek.nextSibling);
    }
    
    console.log(`Synchronized ${sharedType} week movement to other division`);
}

/**
 * Get the other division's container (Premier <-> Classic)
 */
function getOtherDivisionContainer(currentContainer) {
    const containerId = currentContainer.id;
    
    if (containerId.includes('premier')) {
        return document.getElementById('classicCalendarPreview');
    } else if (containerId.includes('classic')) {
        return document.getElementById('premierCalendarPreview');
    }
    
    return null;
}

/**
 * Update week numbers and dates after reordering
 */
function updateWeekNumbersAndDates(container) {
    const weekItems = container.querySelectorAll('.week-item');
    const startDateStr = document.getElementById('seasonStartDate').value;
    
    if (!startDateStr) return;
    
    console.log('Updating week numbers and dates for', weekItems.length, 'weeks');
    
    // Parse date properly to avoid timezone issues
    const [year, month, day] = startDateStr.split('-').map(num => parseInt(num));
    const startDate = new Date(year, month - 1, day);
    let currentDate = new Date(startDate);
    
    // Determine which division this container belongs to
    const containerClass = container.className;
    const containerId = container.id;
    let division;
    
    console.log('Container class:', containerClass);
    console.log('Container id:', containerId);
    
    if (containerClass.includes('premier') || containerId.includes('premier')) {
        division = 'premier';
    } else if (containerClass.includes('classic') || containerId.includes('classic')) {
        division = 'classic';
    } else if (containerClass.includes('ecs') || containerId.includes('ecs')) {
        division = 'ecs_fc';
    } else {
        // Fallback: check parent containers
        const parentContainer = container.closest('[id*="premier"], [id*="classic"], [id*="ecs"]');
        if (parentContainer) {
            if (parentContainer.id.includes('premier')) {
                division = 'premier';
            } else if (parentContainer.id.includes('classic')) {
                division = 'classic';
            } else if (parentContainer.id.includes('ecs')) {
                division = 'ecs_fc';
            }
        }
    }
    
    console.log('Detected division:', division);
    
    // MEMORY LEAK FIX: Remove old weeks for this division before adding new ones
    calendarState.weeks = calendarState.weeks.filter(w => w.division !== division);
    
    weekItems.forEach((item, index) => {
        // Update week number
        const weekNumber = item.querySelector('.week-number');
        weekNumber.textContent = `Week ${index + 1}`;
        item.dataset.week = index + 1;
        
        // Update date
        const weekDate = item.querySelector('.week-date');
        if (weekDate) {
            weekDate.textContent = formatDate(currentDate);
        }
        
        // Update calendarState.weeks array
        const weekType = item.dataset.type;
        const mappedType = weekType === 'regular' ? 'Regular' : 
                          weekType === 'fun' ? 'FUN' : 
                          weekType === 'tst' ? 'TST' : 
                          weekType === 'playoff' ? 'PLAYOFF' : 
                          weekType === 'bonus' ? 'BONUS' : 'Regular';
        
        // Check if this is a practice session
        const weekTypeText = item.querySelector('.week-type').textContent;
        const isPractice = weekTypeText.includes('Practice Game 1');
        
        // Add the updated week to calendar state
        console.log(`Adding updated week ${index + 1} in ${division} with type ${mappedType}`);
        calendarState.weeks.push({
            weekNumber: index + 1,
            date: new Date(currentDate),
            type: mappedType,
            division: division,
            isPractice: isPractice
        });
        
        // Move to next week (add 7 days for next Sunday)
        currentDate.setDate(currentDate.getDate() + 7);
    });
    
    console.log('Updated calendar state after drag-and-drop:');
    console.log('Total weeks in state:', calendarState.weeks.length);
    console.log('Weeks by division:', calendarState.weeks.reduce((acc, week) => {
        acc[week.division] = (acc[week.division] || 0) + 1;
        return acc;
    }, {}));
}

/**
 * Generate ECS FC calendar
 */
function generateEcsFcCalendar(startDate) {
    // Clear calendar state before generating new calendar
    calendarState.weeks = [];
    
    const regularWeeks = parseInt(document.getElementById('ecsFcRegularWeeks')?.value) || 8;
    const playoffWeeks = parseInt(document.getElementById('ecsFcPlayoffWeeks')?.value) || 1;
    
    let calendar = '<div class="calendar-weeks">';
    let currentDate = new Date(startDate);
    let weekNumber = 1;
    
    // Regular season weeks
    for (let i = 0; i < regularWeeks; i++) {
        // Add to calendar state
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'Regular',
            division: 'ecs_fc'
        });
        
        calendar += `<div class="week-item regular-week">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(currentDate)}</div>
            <div class="week-type">Regular</div>
        </div>`;
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    // Playoff weeks
    for (let i = 0; i < playoffWeeks; i++) {
        // Add to calendar state
        calendarState.weeks.push({
            weekNumber: weekNumber,
            date: new Date(currentDate),
            type: 'PLAYOFF',
            division: 'ecs_fc'
        });
        
        calendar += `<div class="week-item playoff-week">
            <div class="week-number">Week ${weekNumber}</div>
            <div class="week-date">${formatDate(currentDate)}</div>
            <div class="week-type">Playoffs</div>
        </div>`;
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    calendar += '</div>';
    document.getElementById('ecsFcCalendarPreview').innerHTML = calendar;
}

/**
 * Get next Sunday from a date
 */
function getNextSunday(date) {
    const result = new Date(date);
    const day = result.getDay();
    const diff = day === 0 ? 0 : 7 - day;
    result.setDate(result.getDate() + diff);
    return result;
}

/**
 * Format date for display
 */
function formatDate(date) {
    return date.toLocaleDateString('en-US', { 
        month: 'short', 
        day: 'numeric',
        year: 'numeric'
    });
}

/**
 * Check if date is Sunday
 */
function isSunday(date) {
    return new Date(date).getDay() === 0;
}

/**
 * Update team sections based on league type
 */
function updateTeamSections() {
    const leagueType = document.getElementById('leagueType').value;
    const pubLeagueSection = document.getElementById('pubLeagueTeams');
    const ecsFcSection = document.getElementById('ecsFcTeams');
    
    if (leagueType === 'Pub League') {
        pubLeagueSection.classList.remove('d-none');
        ecsFcSection.classList.add('d-none');
        updateTeamPreview('premier');
        updateTeamPreview('classic');
    } else if (leagueType === 'ECS FC') {
        pubLeagueSection.classList.add('d-none');
        ecsFcSection.classList.remove('d-none');
        updateTeamPreview('ecsFc');
    }
}

/**
 * Update team preview display
 */
function updateTeamPreview(leagueType) {
    let count, previewId;
    
    if (leagueType === 'premier') {
        count = parseInt(document.getElementById('premierTeamCount').value);
        previewId = 'premierTeamPreview';
    } else if (leagueType === 'classic') {
        count = parseInt(document.getElementById('classicTeamCount').value);
        previewId = 'classicTeamPreview';
    } else if (leagueType === 'ecsFc') {
        count = parseInt(document.getElementById('ecsFcTeamCount').value);
        previewId = 'ecsFcTeamPreview';
    }
    
    const previewDiv = document.getElementById(previewId);
    const teamLabels = [];
    
    // Generate team names (Team A, Team B, etc.)
    for (let i = 0; i < count; i++) {
        const letter = String.fromCharCode(65 + i); // A, B, C, etc.
        teamLabels.push(`Team ${letter}`);
    }
    
    previewDiv.innerHTML = `
        <div class="small text-muted mb-2">Teams to be created:</div>
        <div class="d-flex flex-wrap gap-1">
            ${teamLabels.map(name => `<span class="badge bg-light text-dark border">${name}</span>`).join('')}
        </div>
    `;
}

/**
 * Initialize calendar from inputs
 */
function initializeCalendar() {
    const startDateInput = document.getElementById('seasonStartDate');
    const startDate = startDateInput.value;
    
    if (!startDate) return;
    
    // Parse date properly to avoid timezone issues
    const [year, month, day] = startDate.split('-').map(num => parseInt(num));
    const selectedDate = new Date(year, month - 1, day);
    const warningDiv = document.getElementById('startDateWarning');
    
    // Accept any day - no forcing to Sunday
    const dayName = selectedDate.toLocaleDateString('en-US', { weekday: 'long' });
    warningDiv.innerHTML = `
        <small class="text-success">
            <i class="ti ti-check me-1"></i>
            Season will start on ${dayName}, ${selectedDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </small>
    `;
    calendarState.startDate = selectedDate;
    
    // Get settings
    calendarState.regularWeeks = parseInt(document.getElementById('regularWeeks')?.value) || 7;
    calendarState.includeTST = document.getElementById('includeTST')?.checked || false;
    calendarState.includeFUN = document.getElementById('includeFUN')?.checked || false;
    calendarState.byeWeeks = parseInt(document.getElementById('byeWeekCount')?.value) || 0;
    
    // Build week array
    rebuildWeekArray();
    
    // Update UI
    updateCalendarPreview();
    updateTotalWeeks();
}

/**
 * Rebuild the week array based on current settings
 */
function rebuildWeekArray() {
    calendarState.weeks = [];
    let currentDate = new Date(calendarState.startDate);
    let weekNum = 1;
    
    // Add regular weeks
    for (let i = 0; i < calendarState.regularWeeks; i++) {
        calendarState.weeks.push({
            weekNumber: weekNum++,
            date: new Date(currentDate),
            type: 'Regular',
            isSpecial: false
        });
        currentDate.setDate(currentDate.getDate() + 7);
    }
    
    // Add special weeks at the end (will be dragged to position)
    if (calendarState.includeTST) {
        calendarState.weeks.push({
            weekNumber: weekNum++,
            date: new Date(currentDate),
            type: 'TST',
            isSpecial: true
        });
        currentDate.setDate(currentDate.getDate() + 7);
    }
    
    if (calendarState.includeFUN) {
        calendarState.weeks.push({
            weekNumber: weekNum++,
            date: new Date(currentDate),
            type: 'FUN',
            isSpecial: true
        });
        currentDate.setDate(currentDate.getDate() + 7);
    }
    
    // Add BYE weeks
    for (let i = 0; i < calendarState.byeWeeks; i++) {
        calendarState.weeks.push({
            weekNumber: weekNum++,
            date: new Date(currentDate),
            type: 'BYE',
            isSpecial: true
        });
        currentDate.setDate(currentDate.getDate() + 7);
    }
}

/**
 * Update calendar preview display
 */
function updateCalendarPreview() {
    const preview = document.getElementById('calendarPreview');
    if (!preview) return;
    
    let html = '<div class="row" id="calendarWeeks">';
    
    calendarState.weeks.forEach((week, index) => {
        let badgeClass = 'bg-primary';
        if (week.type === 'TST') badgeClass = 'bg-info';
        else if (week.type === 'FUN') badgeClass = 'bg-warning';
        else if (week.type === 'BYE') badgeClass = 'bg-secondary';
        
        html += `
            <div class="col-md-3 mb-2 week-item" data-index="${index}">
                <div class="text-center">
                    <div class="badge ${badgeClass} w-100 p-3 week-badge" draggable="true" data-week-type="${week.type}">
                        <div class="week-number">Week ${week.weekNumber}</div>
                        <div class="week-date">${week.date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</div>
                        <div class="week-type"><strong>${week.type}</strong></div>
                    </div>
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    preview.innerHTML = html;
    
    // Add drag and drop functionality
    addDragAndDropToWeeks();
}

/**
 * Add drag and drop functionality to weeks
 */
function addDragAndDropToWeeks() {
    const weekItems = document.querySelectorAll('.week-item');
    
    weekItems.forEach(item => {
        const badge = item.querySelector('.week-badge');
        
        badge.addEventListener('dragstart', handleDragStart);
        item.addEventListener('dragover', handleDragOver);
        item.addEventListener('drop', handleDrop);
        item.addEventListener('dragleave', handleDragLeave);
        badge.addEventListener('dragend', handleDragEnd);
    });
}

/**
 * Handle drag start
 */
function handleDragStart(e) {
    const weekItem = this.closest('.week-item');
    draggedIndex = parseInt(weekItem.dataset.index);
    e.dataTransfer.effectAllowed = 'move';
    this.classList.add('dragging');
}

/**
 * Handle drag over
 */
function handleDragOver(e) {
    if (e.preventDefault) {
        e.preventDefault();
    }
    e.dataTransfer.dropEffect = 'move';
    this.classList.add('drop-zone');
    return false;
}

/**
 * Handle drag leave
 */
function handleDragLeave(e) {
    this.classList.remove('drop-zone');
}

/**
 * Handle drop
 */
function handleDrop(e) {
    if (e.stopPropagation) {
        e.stopPropagation();
    }
    
    this.classList.remove('drop-zone');
    
    const dropIndex = parseInt(this.dataset.index);
    
    if (draggedIndex !== null && draggedIndex !== dropIndex) {
        // Reorder the weeks array
        const draggedWeek = calendarState.weeks[draggedIndex];
        calendarState.weeks.splice(draggedIndex, 1);
        calendarState.weeks.splice(dropIndex, 0, draggedWeek);
        
        // Recalculate all dates maintaining Sunday schedule
        recalculateDatesAfterReorder();
        
        // Update the display
        updateCalendarPreview();
    }
    
    return false;
}

/**
 * Handle drag end
 */
function handleDragEnd(e) {
    document.querySelectorAll('.week-badge').forEach(badge => {
        badge.classList.remove('dragging');
    });
    document.querySelectorAll('.week-item').forEach(item => {
        item.classList.remove('drop-zone');
    });
    draggedIndex = null;
}

/**
 * Recalculate dates after reordering
 */
function recalculateDatesAfterReorder() {
    let currentDate = new Date(calendarState.startDate);
    
    calendarState.weeks.forEach((week, index) => {
        week.weekNumber = index + 1;
        week.date = new Date(currentDate);
        currentDate.setDate(currentDate.getDate() + 7);
    });
}

/**
 * Generate season summary
 */
function generateSeasonSummary() {
    const seasonName = document.getElementById('seasonName').value;
    const leagueType = document.getElementById('leagueType').value;
    const seasonStartDate = document.getElementById('seasonStartDate').value;
    const setAsCurrent = document.getElementById('setAsCurrent').checked;
    
    // Get shared special weeks
    const sharedFunWeek = document.getElementById('sharedHasFunWeek')?.checked || false;
    const sharedTstWeek = document.getElementById('sharedHasTstWeek')?.checked || false;
    
    let summary = `
        <div class="alert alert-info">
            <h5><i class="ti ti-info-circle me-2"></i>Season Creation Summary</h5>
            <p class="mb-0">Please review the following configuration before creating your season. This will set up all divisions, teams, and schedule structure according to your specifications.</p>
        </div>
        
        <div class="row mb-4">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0"><i class="ti ti-calendar me-2"></i>Season Details</h6>
                    </div>
                    <div class="card-body">
                        <ul class="list-unstyled mb-0">
                            <li><strong>Name:</strong> ${seasonName}</li>
                            <li><strong>Type:</strong> ${leagueType}</li>
                            <li><strong>Start Date:</strong> ${seasonStartDate}</li>
                            <li><strong>Set as Current:</strong> ${setAsCurrent ? 'Yes' : 'No'}</li>
                        </ul>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0"><i class="ti ti-settings me-2"></i>Schedule Configuration</h6>
                    </div>
                    <div class="card-body">
                        <ul class="list-unstyled mb-0">
                            <li><strong>Premier Start:</strong> ${document.getElementById('premierStartTime')?.value || 'N/A'}</li>
                            <li><strong>Classic Start:</strong> ${document.getElementById('classicStartTime')?.value || 'N/A'}</li>
                            <li><strong>Match Duration:</strong> ${document.getElementById('matchDuration')?.value || 'N/A'} min</li>
                            <li><strong>Number of Fields:</strong> ${document.getElementById('fields')?.value || 'N/A'}</li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>`;
    
    if (leagueType === 'Pub League') {
        // Get division-specific data
        const premierRegular = parseInt(document.getElementById('premierRegularWeeks')?.value) || 0;
        const premierPlayoff = parseInt(document.getElementById('premierPlayoffWeeks')?.value) || 0;
        const premierBonusWeek = document.getElementById('premierHasBonusWeek')?.checked || false;
        const premierTeamCount = parseInt(document.getElementById('premierTeamCount')?.value) || 0;
        
        const classicRegular = parseInt(document.getElementById('classicRegularWeeks')?.value) || 0;
        const classicPlayoff = parseInt(document.getElementById('classicPlayoffWeeks')?.value) || 0;
        const classicBonusWeek = document.getElementById('classicHasBonusWeek')?.checked || false;
        const classicHasPractice = document.getElementById('classicHasPractice')?.checked || false;
        const classicPracticeWeeks = document.getElementById('classicPracticeWeeks')?.value || '';
        const classicPracticeGame = parseInt(document.getElementById('classicPracticeGame')?.value) || 1;
        const classicTeamCount = parseInt(document.getElementById('classicTeamCount')?.value) || 0;
        
        // Calculate total weeks for each division
        const premierTotal = premierRegular + premierPlayoff + (sharedFunWeek ? 1 : 0) + (sharedTstWeek ? 1 : 0) + (premierBonusWeek ? 1 : 0);
        const classicTotal = classicRegular + classicPlayoff + (sharedFunWeek ? 1 : 0) + (sharedTstWeek ? 1 : 0) + (classicBonusWeek ? 1 : 0);
        
        summary += `
            <div class="row mb-4">
                <div class="col-md-6">
                    <div class="card border-primary">
                        <div class="card-header bg-primary text-white">
                            <h6 class="mb-0"><i class="ti ti-trophy me-2"></i>Premier Division</h6>
                        </div>
                        <div class="card-body">
                            <ul class="list-unstyled mb-3">
                                <li><strong>Teams:</strong> ${premierTeamCount}</li>
                                <li><strong>Regular Season:</strong> ${premierRegular} weeks</li>
                                <li><strong>Playoff Weeks:</strong> ${premierPlayoff} weeks</li>
                                <li><strong>Bonus Week:</strong> ${premierBonusWeek ? 'Yes' : 'No'}</li>
                                <li><strong>Total Weeks:</strong> ${premierTotal}</li>
                            </ul>
                            <div class="alert alert-light small">
                                <strong>Structure:</strong> ${premierRegular} regular + ${premierPlayoff} playoff${sharedFunWeek ? ' + 1 fun' : ''}${sharedTstWeek ? ' + 1 TST' : ''}${premierBonusWeek ? ' + 1 bonus' : ''}
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card border-success">
                        <div class="card-header bg-success text-white">
                            <h6 class="mb-0"><i class="ti ti-users me-2"></i>Classic Division</h6>
                        </div>
                        <div class="card-body">
                            <ul class="list-unstyled mb-3">
                                <li><strong>Teams:</strong> ${classicTeamCount}</li>
                                <li><strong>Regular Season:</strong> ${classicRegular} weeks</li>
                                <li><strong>Playoff Weeks:</strong> ${classicPlayoff} weeks</li>
                                <li><strong>Bonus Week:</strong> ${classicBonusWeek ? 'Yes' : 'No'}</li>
                                <li><strong>Total Weeks:</strong> ${classicTotal}</li>
                            </ul>
                            ${classicHasPractice ? `
                                <div class="alert alert-info small">
                                    <strong>Practice Sessions:</strong> Week(s) ${classicPracticeWeeks}, Game ${classicPracticeGame}
                                </div>
                            ` : ''}
                            <div class="alert alert-light small">
                                <strong>Structure:</strong> ${classicRegular} regular + ${classicPlayoff} playoff${sharedFunWeek ? ' + 1 fun' : ''}${sharedTstWeek ? ' + 1 TST' : ''}${classicBonusWeek ? ' + 1 bonus' : ''}
                            </div>
                        </div>
                    </div>
                </div>
            </div>`;
        
        // Add shared special weeks section
        if (sharedFunWeek || sharedTstWeek) {
            summary += `
                <div class="row mb-4">
                    <div class="col-12">
                        <div class="card border-warning">
                            <div class="card-header bg-warning text-dark">
                                <h6 class="mb-0"><i class="ti ti-star me-2"></i>Shared Special Weeks</h6>
                            </div>
                            <div class="card-body">
                                <p class="mb-2">These weeks will be shared between Premier and Classic divisions:</p>
                                <ul class="list-unstyled mb-0">
                                    ${sharedFunWeek ? '<li><i class="ti ti-check text-success me-2"></i>Fun Week</li>' : ''}
                                    ${sharedTstWeek ? '<li><i class="ti ti-check text-success me-2"></i>TST Week</li>' : ''}
                                </ul>
                            </div>
                        </div>
                    </div>
                </div>`;
        }
    } else if (leagueType === 'ECS FC') {
        // ECS FC configuration
        const ecsFcRegular = parseInt(document.getElementById('ecsFcRegularWeeks')?.value) || 0;
        const ecsFcPlayoff = parseInt(document.getElementById('ecsFcPlayoffWeeks')?.value) || 0;
        const ecsFcTeamCount = parseInt(document.getElementById('ecsFcTeamCount')?.value) || 0;
        const ecsFcTotal = ecsFcRegular + ecsFcPlayoff;
        
        summary += `
            <div class="row mb-4">
                <div class="col-md-8 offset-md-2">
                    <div class="card border-info">
                        <div class="card-header bg-info text-white">
                            <h6 class="mb-0"><i class="ti ti-shield me-2"></i>ECS FC Division</h6>
                        </div>
                        <div class="card-body">
                            <ul class="list-unstyled mb-3">
                                <li><strong>Teams:</strong> ${ecsFcTeamCount}</li>
                                <li><strong>Regular Season:</strong> ${ecsFcRegular} weeks</li>
                                <li><strong>Playoff Weeks:</strong> ${ecsFcPlayoff} weeks</li>
                                <li><strong>Total Weeks:</strong> ${ecsFcTotal}</li>
                            </ul>
                            <div class="alert alert-light small">
                                <strong>Structure:</strong> ${ecsFcRegular} regular + ${ecsFcPlayoff} playoff weeks
                            </div>
                        </div>
                    </div>
                </div>
            </div>`;
    }
    
    // Add combined schedule preview
    if (calendarState && calendarState.weeks && calendarState.weeks.length > 0) {
        summary += generateCombinedSchedulePreview();
    }
    
    // Add final confirmation
    summary += `
        <div class="alert alert-success">
            <h6><i class="ti ti-check-circle me-2"></i>Ready to Create Season</h6>
            <p class="mb-0">
                This will create your ${leagueType} season with all configured divisions, teams, and schedule structure. 
                ${setAsCurrent ? 'This season will be set as the current active season.' : 'This will be created as a draft season.'}
            </p>
        </div>`;
    
    document.getElementById('seasonSummary').innerHTML = summary;
}

/**
 * Generate combined schedule preview for final step
 */
function generateCombinedSchedulePreview() {
    if (!calendarState || !calendarState.weeks || calendarState.weeks.length === 0) {
        return '';
    }
    
    // Group weeks by week number and date
    const weeksByNumber = {};
    calendarState.weeks.forEach(week => {
        if (!weeksByNumber[week.weekNumber]) {
            weeksByNumber[week.weekNumber] = {
                weekNumber: week.weekNumber,
                date: week.date,
                divisions: {}
            };
        }
        weeksByNumber[week.weekNumber].divisions[week.division] = {
            type: week.type,
            isPractice: week.isPractice
        };
    });
    
    // Convert to sorted array
    const combinedWeeks = Object.values(weeksByNumber).sort((a, b) => a.weekNumber - b.weekNumber);
    
    let preview = `
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0"><i class="ti ti-calendar-event me-2"></i>Combined Schedule Preview</h6>
                    </div>
                    <div class="card-body">
                        <div class="table-responsive">
                            <table class="table table-sm table-hover">
                                <thead>
                                    <tr>
                                        <th width="10%">Week</th>
                                        <th width="15%">Date</th>
                                        <th width="35%">Premier Division</th>
                                        <th width="35%">Classic Division</th>
                                        <th width="5%">Status</th>
                                    </tr>
                                </thead>
                                <tbody>`;
    
    combinedWeeks.forEach(week => {
        const formattedDate = week.date.toLocaleDateString('en-US', { 
            month: 'short', 
            day: 'numeric' 
        });
        
        const premier = week.divisions.premier || { type: 'Regular', isPractice: false };
        const classic = week.divisions.classic || { type: 'Regular', isPractice: false };
        
        // Format division info
        const formatDivisionInfo = (divisionData) => {
            let typeText = '';
            let badgeClass = 'bg-secondary';
            
            switch (divisionData.type) {
                case 'Regular':
                    typeText = divisionData.isPractice ? 'Practice Session' : 'Regular Season';
                    badgeClass = divisionData.isPractice ? 'bg-success' : 'bg-secondary';
                    break;
                case 'FUN':
                    typeText = 'Fun Week';
                    badgeClass = 'bg-warning';
                    break;
                case 'TST':
                    typeText = 'TST Week';
                    badgeClass = 'bg-info';
                    break;
                case 'PLAYOFF':
                    typeText = 'Playoffs';
                    badgeClass = 'bg-danger';
                    break;
                case 'BONUS':
                    typeText = 'Bonus Week';
                    badgeClass = 'bg-success';
                    break;
                case 'BYE':
                    typeText = 'BYE Week';
                    badgeClass = 'bg-dark';
                    break;
                default:
                    typeText = divisionData.type;
                    badgeClass = 'bg-secondary';
            }
            
            return `<span class="badge ${badgeClass}">${typeText}</span>`;
        };
        
        // Determine if this is a special week
        const isSpecialWeek = premier.type !== 'Regular' || classic.type !== 'Regular' || 
                             premier.isPractice || classic.isPractice;
        
        const statusIcon = isSpecialWeek ? 
            '<i class="ti ti-star text-warning" title="Special Week"></i>' : 
            '<i class="ti ti-calendar text-muted" title="Regular Week"></i>';
        
        preview += `
            <tr ${isSpecialWeek ? 'class="table-warning"' : ''}>
                <td><strong>${week.weekNumber}</strong></td>
                <td>${formattedDate}</td>
                <td>${formatDivisionInfo(premier)}</td>
                <td>${formatDivisionInfo(classic)}</td>
                <td class="text-center">${statusIcon}</td>
            </tr>`;
    });
    
    preview += `
                                </tbody>
                            </table>
                        </div>
                        <div class="mt-3">
                            <small class="text-muted">
                                <i class="ti ti-info-circle me-1"></i>
                                This preview shows how both divisions will be scheduled together. 
                                Special weeks (Fun, TST, Playoffs) are highlighted in yellow.
                                ${combinedWeeks.some(w => w.divisions.classic?.isPractice) ? 
                                    ' Practice sessions are shown for Classic division where configured.' : ''}
                            </small>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;
    
    return preview;
}

/**
 * Create season with all collected data
 */
function createSeason() {
    // Validate calendar state and regenerate if needed
    const seasonStartDateInput = document.getElementById('seasonStartDate');
    if (!calendarState || !calendarState.startDate || !calendarState.weeks || calendarState.weeks.length === 0) {
        if (seasonStartDateInput && seasonStartDateInput.value) {
            // Regenerate calendar if it's missing
            generateCalendarPreview(true); // Force regeneration when calendar is missing
        } else {
            alert('Please ensure the season start date is set and the calendar is generated.');
            return;
        }
    }
    
    // Build week configuration from calendar state
    console.log('Calendar state weeks:', calendarState.weeks);
    console.log('Calendar state weeks count:', calendarState.weeks.length);
    
    const weekConfigs = calendarState.weeks.map(week => ({
        date: week.date.toISOString().split('T')[0],
        type: week.type === 'Regular' ? 'REGULAR' : 
              week.type === 'Playoff' ? 'PLAYOFF' :
              week.type === 'FUN' ? 'FUN' :
              week.type === 'TST' ? 'TST' :
              week.type === 'BYE' ? 'BYE' :
              week.type === 'BONUS' ? 'BONUS' :
              week.type.toUpperCase(), // fallback for any other values
        week_number: week.weekNumber,
        division: week.division // Include division field for backend filtering
    }));
    console.log('Week configs being sent:', weekConfigs);
    console.log('Week configs count:', weekConfigs.length);
    
    // Extract special week dates
    const tstWeek = calendarState.weeks.find(w => w.type === 'TST');
    const funWeek = calendarState.weeks.find(w => w.type === 'FUN');
    const byeWeeks = calendarState.weeks.filter(w => w.type === 'BYE');
    
    // Collect team counts based on league type
    const leagueType = document.getElementById('leagueType').value;
    let teamCounts = {};
    
    if (leagueType === 'Pub League') {
        teamCounts = {
            premier_teams: parseInt(document.getElementById('premierTeamCount').value),
            classic_teams: parseInt(document.getElementById('classicTeamCount').value)
        };
    } else if (leagueType === 'ECS FC') {
        teamCounts = {
            ecs_fc_teams: parseInt(document.getElementById('ecsFcTeamCount').value)
        };
    }
    
    // Collect season structure data
    let structureData = {};
    
    if (leagueType === 'Pub League') {
        structureData = {
            // Shared Special Weeks
            has_fun_week: document.getElementById('sharedHasFunWeek').checked,
            has_tst_week: document.getElementById('sharedHasTstWeek').checked,
            
            // Premier Division Configuration
            premier_regular_weeks: parseInt(document.getElementById('premierRegularWeeks').value),
            premier_playoff_weeks: parseInt(document.getElementById('premierPlayoffWeeks').value),
            premier_has_bonus_week: document.getElementById('premierHasBonusWeek').checked,
            
            // Classic Division Configuration
            classic_regular_weeks: parseInt(document.getElementById('classicRegularWeeks').value),
            classic_playoff_weeks: parseInt(document.getElementById('classicPlayoffWeeks').value),
            classic_has_bonus_week: document.getElementById('classicHasBonusWeek').checked,
            classic_has_practice_sessions: document.getElementById('classicHasPractice').checked,
            classic_practice_weeks: document.getElementById('classicPracticeWeeks').value,
            classic_practice_game_number: parseInt(document.getElementById('classicPracticeGame').value)
        };
    } else if (leagueType === 'ECS FC') {
        structureData = {
            // ECS FC Configuration
            ecs_fc_regular_weeks: parseInt(document.getElementById('ecsFcRegularWeeks').value),
            ecs_fc_playoff_weeks: parseInt(document.getElementById('ecsFcPlayoffWeeks').value)
        };
    }

    // Get season start date with fallback
    const seasonStartDate = calendarState.startDate || (seasonStartDateInput ? new Date(seasonStartDateInput.value) : null);
    
    if (!seasonStartDate) {
        alert('Please set a season start date.');
        return;
    }

    // Collect form data and submit
    const formData = {
        season_name: document.getElementById('seasonName').value,
        league_type: leagueType,
        set_as_current: document.getElementById('setAsCurrent').checked,
        season_start_date: seasonStartDate.toISOString().split('T')[0],
        regular_weeks: calendarState.regularWeeks || 0,
        total_weeks: calendarState.weeks.length,
        week_configs: weekConfigs,
        tst_week_date: tstWeek ? tstWeek.date.toISOString().split('T')[0] : null,
        fun_week_date: funWeek ? funWeek.date.toISOString().split('T')[0] : null,
        bye_week_dates: byeWeeks.map(w => w.date.toISOString().split('T')[0]),
        premier_start_time: document.getElementById('premierStartTime')?.value,
        classic_start_time: document.getElementById('classicStartTime')?.value,
        match_duration: document.getElementById('matchDuration')?.value,
        fields: document.getElementById('fields')?.value,
        ...teamCounts,
        ...structureData
    };
    
    // Get the create season button and disable it
    const createButton = document.querySelector('.btn-primary[onclick="createSeason()"]') || 
                        document.querySelector('button[onclick="createSeason()"]') ||
                        document.querySelector('.wizard-create-button');
    
    if (createButton) {
        createButton.disabled = true;
        createButton.innerHTML = '<i class="ti ti-loader-2 me-2 spin"></i>Creating Season...';
        createButton.classList.add('disabled');
    }
    
    // Show loading modal
    showLoadingModal('Creating Season', 'Please wait while we create your season, teams, and generate schedules...');
    
    // Submit to backend
    fetch(window.autoScheduleUrls.createSeasonWizard, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('meta[name=csrf-token]').getAttribute('content')
        },
        body: JSON.stringify(formData)
    })
    .then(response => response.json())
    .then(data => {
        hideLoadingModal();
        
        if (data.success) {
            // Show success message briefly before redirect
            showSuccessModal('Season Created Successfully!', 'Your season has been created successfully. Redirecting...', () => {
                window.location.href = data.redirect_url;
            });
        } else {
            // Re-enable button on error
            if (createButton) {
                createButton.disabled = false;
                createButton.innerHTML = '<i class="ti ti-check me-2"></i>Create Season';
                createButton.classList.remove('disabled');
            }
            showErrorModal('Error Creating Season', data.error || 'An unexpected error occurred.');
        }
    })
    .catch(error => {
        hideLoadingModal();
        
        // Re-enable button on error
        if (createButton) {
            createButton.disabled = false;
            createButton.innerHTML = '<i class="ti ti-check me-2"></i>Create Season';
            createButton.classList.remove('disabled');
        }
        showErrorModal('Network Error', 'Failed to create season. Please check your connection and try again.');
        console.error('Error creating season:', error);
    });
}

/**
 * Initialize event listeners when DOM is ready
 */
document.addEventListener('DOMContentLoaded', function() {
    // Initialize calendar when wizard is shown
    const seasonStartDate = document.getElementById('seasonStartDate');
    if (seasonStartDate) {
        seasonStartDate.addEventListener('change', function() {
            if (currentStep === 3) {
                generateCalendarPreview(true); // Force regeneration when start date changes
            }
        });
    }
    
    // League type change listener
    const leagueType = document.getElementById('leagueType');
    if (leagueType) {
        leagueType.addEventListener('change', function() {
            // Update structure sections when league type changes
            if (currentStep === 2) {
                updateStructureSections();
            }
            // Update team sections when league type changes
            if (currentStep === 5) {
                updateTeamSections();
            }
        });
    }
    
    // Season structure change listeners (with null checks)
    // Shared Special Weeks
    const sharedHasFunWeek = document.getElementById('sharedHasFunWeek');
    const sharedHasTstWeek = document.getElementById('sharedHasTstWeek');
    const sharedHasByeWeek = document.getElementById('sharedHasByeWeek');
    
    if (sharedHasFunWeek) {
        sharedHasFunWeek.addEventListener('change', () => {
            updateTotalWeeks('premier');
            updateTotalWeeks('classic');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    if (sharedHasTstWeek) {
        sharedHasTstWeek.addEventListener('change', () => {
            updateTotalWeeks('premier');
            updateTotalWeeks('classic');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    if (sharedHasByeWeek) {
        sharedHasByeWeek.addEventListener('change', () => {
            updateTotalWeeks('premier');
            updateTotalWeeks('classic');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    // Premier Division
    const premierRegularWeeks = document.getElementById('premierRegularWeeks');
    const premierPlayoffWeeks = document.getElementById('premierPlayoffWeeks');
    const premierHasBonusWeek = document.getElementById('premierHasBonusWeek');
    
    if (premierRegularWeeks) {
        premierRegularWeeks.addEventListener('input', () => {
            updateTotalWeeks('premier');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    if (premierPlayoffWeeks) {
        premierPlayoffWeeks.addEventListener('input', () => {
            updateTotalWeeks('premier');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    if (premierHasBonusWeek) {
        premierHasBonusWeek.addEventListener('change', () => {
            updateTotalWeeks('premier');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    // Classic Division
    const classicRegularWeeks = document.getElementById('classicRegularWeeks');
    const classicPlayoffWeeks = document.getElementById('classicPlayoffWeeks');
    const classicHasBonusWeek = document.getElementById('classicHasBonusWeek');
    const classicHasPractice = document.getElementById('classicHasPractice');
    
    if (classicRegularWeeks) {
        classicRegularWeeks.addEventListener('input', () => {
            updateTotalWeeks('classic');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    if (classicPlayoffWeeks) {
        classicPlayoffWeeks.addEventListener('input', () => {
            updateTotalWeeks('classic');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    if (classicHasBonusWeek) {
        classicHasBonusWeek.addEventListener('change', () => {
            updateTotalWeeks('classic');
            if (currentStep === 3) generateCalendarPreview();
        });
    }
    
    if (classicHasPractice) {
        classicHasPractice.addEventListener('change', togglePracticeConfig);
    }
    
    // ECS FC
    const ecsFcRegularWeeks = document.getElementById('ecsFcRegularWeeks');
    const ecsFcPlayoffWeeks = document.getElementById('ecsFcPlayoffWeeks');
    
    if (ecsFcRegularWeeks) {
        ecsFcRegularWeeks.addEventListener('input', () => {
            updateTotalWeeks('ecsFc');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    if (ecsFcPlayoffWeeks) {
        ecsFcPlayoffWeeks.addEventListener('input', () => {
            updateTotalWeeks('ecsFc');
            if (currentStep === 3) generateCalendarPreview(true); // Force regeneration on config change
        });
    }
    
    // Team count change listeners
    const premierTeamCount = document.getElementById('premierTeamCount');
    const classicTeamCount = document.getElementById('classicTeamCount');
    const ecsFcTeamCount = document.getElementById('ecsFcTeamCount');
    
    if (premierTeamCount) {
        premierTeamCount.addEventListener('change', () => updateTeamPreview('premier'));
    }
    
    if (classicTeamCount) {
        classicTeamCount.addEventListener('change', () => updateTeamPreview('classic'));
    }
    
    if (ecsFcTeamCount) {
        ecsFcTeamCount.addEventListener('change', () => updateTeamPreview('ecsFc'));
    }
});

/**
 * Add CSS for spinner animation
 */
function addSpinnerCSS() {
    const style = document.createElement('style');
    style.textContent = `
        .spin {
            animation: spin 1s linear infinite;
        }
        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }
    `;
    document.head.appendChild(style);
}

// Add spinner CSS when script loads
addSpinnerCSS();

/**
 * Show loading modal with spinner
 */
function showLoadingModal(title, message) {
    const modalHtml = `
        <div class="modal fade" id="loadingModal" tabindex="-1" aria-labelledby="loadingModalLabel" aria-hidden="true" data-bs-backdrop="static">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header border-0">
                        <h5 class="modal-title" id="loadingModalLabel">${title}</h5>
                    </div>
                    <div class="modal-body text-center py-4">
                        <div class="spinner-border text-primary mb-3" role="status">
                            <span class="visually-hidden">Loading...</span>
                        </div>
                        <p class="mb-0">${message}</p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    const existingModal = document.getElementById('loadingModal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // Add modal to body
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('loadingModal'));
    modal.show();
}

/**
 * Hide loading modal
 */
function hideLoadingModal() {
    const modal = document.getElementById('loadingModal');
    if (modal) {
        const bsModal = bootstrap.Modal.getInstance(modal);
        if (bsModal) {
            bsModal.hide();
        }
        // Remove modal from DOM after hiding
        setTimeout(() => {
            modal.remove();
        }, 300);
    }
}

/**
 * Show success modal
 */
function showSuccessModal(title, message, callback) {
    const modalHtml = `
        <div class="modal fade" id="successModal" tabindex="-1" aria-labelledby="successModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header border-0">
                        <h5 class="modal-title text-success" id="successModalLabel">
                            <i class="ti ti-check-circle me-2"></i>${title}
                        </h5>
                    </div>
                    <div class="modal-body text-center py-4">
                        <p class="mb-0">${message}</p>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    const existingModal = document.getElementById('successModal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // Add modal to body
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('successModal'));
    modal.show();
    
    // Auto-close after 2 seconds and execute callback
    setTimeout(() => {
        const bsModal = bootstrap.Modal.getInstance(document.getElementById('successModal'));
        if (bsModal) {
            bsModal.hide();
        }
        if (callback) {
            callback();
        }
    }, 2000);
}

/**
 * Show error modal
 */
function showErrorModal(title, message) {
    const modalHtml = `
        <div class="modal fade" id="errorModal" tabindex="-1" aria-labelledby="errorModalLabel" aria-hidden="true">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header border-0">
                        <h5 class="modal-title text-danger" id="errorModalLabel">
                            <i class="ti ti-alert-circle me-2"></i>${title}
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body py-4">
                        <p class="mb-0">${message}</p>
                    </div>
                    <div class="modal-footer border-0">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Remove existing modal if any
    const existingModal = document.getElementById('errorModal');
    if (existingModal) {
        existingModal.remove();
    }
    
    // Add modal to body
    document.body.insertAdjacentHTML('beforeend', modalHtml);
    
    // Show modal
    const modal = new bootstrap.Modal(document.getElementById('errorModal'));
    modal.show();
}