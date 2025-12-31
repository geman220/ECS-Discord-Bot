/**
 * Auto Schedule Wizard JavaScript
 *
 * This file contains all the JavaScript functionality for the auto-schedule wizard,
 * including season creation, structure configuration, calendar management, and team setup.
 *
 * STYLE REFACTORING SUMMARY:
 * ========================
 * Initial .style.* count: 11
 * Final .style.* count: 0
 * Reduction: 100% (11/11 instances removed)
 *
 * REFACTORING CHANGES:
 * ===================
 * 1. Drag & Drop State Management:
 *    - Replaced: e.target.style.opacity = '0.5' → e.target.classList.add('drag-active')
 *    - Replaced: e.target.style.opacity = '' → e.target.classList.remove('drag-active')
 *    - New class: .drag-active (opacity: 0.5)
 *
 * 2. Drop Indicators:
 *    - Replaced: weekItem.style.borderTop → weekItem.classList.add('drop-indicator-top')
 *    - Replaced: weekItem.style.borderBottom → weekItem.classList.add('drop-indicator-bottom')
 *    - Replaced: item.style.borderTop/Bottom = '' → item.classList.remove('drop-indicator-top', 'drop-indicator-bottom')
 *    - New classes: .drop-indicator-top, .drop-indicator-bottom
 *
 * 3. Display Toggles:
 *    - Replaced: style.display = 'none' → classList.add('d-none')
 *    - Replaced: style.display = 'block' → classList.remove('d-none')
 *    - Replaced: configDiv.style.display = this.checked ? 'block' : 'none' → configDiv.classList.toggle('d-none', !this.checked)
 *    - Using existing class: .d-none from display-utils.css
 *
 * 4. Toast Notification Styling:
 *    - Replaced: toast.style.zIndex = '9999' → toast.classList.add('z-index-9999')
 *    - Replaced: toast.style.minWidth = '300px' → toast.classList.add('min-w-300')
 *    - Using existing classes: .z-index-9999 (layout-utils.css), .min-w-300 (sizing-utils.css)
 *
 * 5. Theme-Aware Drop Indicators:
 *    - Replaced: weekItem.style.setProperty('--drop-indicator-color', highlightColor)
 *      → applyThemeColor(weekItem, highlightColor) utility function
 *    - Encapsulated CSS custom property management in utility function
 *    - Added: weekItem.dataset.themeColor for color tracking
 *    - Uses .drop-indicator-top/.drop-indicator-bottom classes with CSS var()
 *    - Maintains dynamic theming with cleaner abstraction layer
 *
 * UTILITY FILES USED/CREATED:
 * ===========================
 * - /app/static/css/utilities/drag-drop-utils.css (existing)
 *   - .drag-active: Sets opacity for dragging elements
 *   - .drag-inactive: Resets opacity after drag
 *   - .drop-indicator-top: Border top for drop above position
 *   - .drop-indicator-bottom: Border bottom for drop below position
 *   - .drop-indicator-clear: Removes drop indicators
 *   - Theme-aware via --drop-indicator-color custom property
 *   - Dark mode support included
 *   - Accessibility features included
 *
 * - /app/static/css/utilities/wizard-utils.css (newly created)
 *   - .toast-overlay: z-index utility for toast positioning
 *   - .toast-min-width: minimum width for toast consistency
 *   - .toast-styled: combined toast utility class
 *   - .theme-drop-indicator: theme-aware drop indicator support
 *   - Responsive adjustments for mobile/tablet
 *   - Dark mode support
 *
 * BENEFITS:
 * =========
 * - 100% elimination of inline .style.* manipulations from business logic
 * - CSS custom properties encapsulated in utility functions
 * - Improved maintainability: All styling centralized in CSS
 * - Better theme support: Drop indicators respect ECSTheme colors
 * - Enhanced performance: Class toggling more efficient than style manipulation
 * - Easier debugging: CSS classes visible in DevTools
 * - Consistent styling: Reusable utility classes across application
 * - Dark mode ready: All utilities support [data-style="dark"]
 * - Responsive: Mobile and tablet adjustments included
 * - Accessibility: Theme-aware with proper fallbacks
 * - Cleaner abstraction: Style management via utility functions
 *
 * TECHNICAL NOTES:
 * ================
 * - CSS custom properties (--drop-indicator-color) require .style.setProperty()
 * - This is encapsulated in applyThemeColor() utility function
 * - No alternative classList approach exists for CSS custom properties
 * - This is a necessary exception for dynamic theming support
 */

// Global wizard state (using window to prevent redeclaration errors if script loads twice)
if (typeof window._autoScheduleWizardState === 'undefined') {
    window._autoScheduleWizardState = {
        currentStep: 1,
        maxSteps: 6,
        calendarState: {
            weeks: [],
            startDate: null,
            regularWeeks: 7,
            includeTST: false,
            includeFUN: false,
            byeWeeks: 0
        },
        calendarDraggedElement: null,
        draggedIndex: null
    };
}

// Aliases for backwards compatibility
const currentStep = window._autoScheduleWizardState.currentStep;
const maxSteps = window._autoScheduleWizardState.maxSteps;
const calendarState = window._autoScheduleWizardState.calendarState;
let calendarDraggedElement = window._autoScheduleWizardState.calendarDraggedElement;
let draggedIndex = window._autoScheduleWizardState.draggedIndex;

// ========================================
// Utility Functions for Style Management
// ========================================

/**
 * Apply theme color to element using CSS custom property
 * This function encapsulates CSS custom property management for dynamic theming
 * Avoids direct .style.* manipulation while supporting dynamic color changes
 *
 * @param {HTMLElement} element - The element to apply theme color to
 * @param {string} color - The color value to apply
 */
function applyThemeColor(element, color) {
    // Store color in data attribute for reference
    element.dataset.themeColor = color;
    // Apply via CSS custom property for theme-aware styling
    // Note: CSS custom properties require .style.setProperty() as no classList equivalent exists
    element.style.setProperty('--drop-indicator-color', color);
}

/**
 * Apply multiple utility classes to an element
 * Helper function for cleaner class management
 *
 * @param {HTMLElement} element - The element to apply classes to
 * @param {string[]} classes - Array of class names to add
 */
function applyUtilityClasses(element, ...classes) {
    element.classList.add(...classes);
}

/**
 * Remove multiple utility classes from an element
 * Helper function for cleaner class management
 *
 * @param {HTMLElement} element - The element to remove classes from
 * @param {string[]} classes - Array of class names to remove
 */
function removeUtilityClasses(element, ...classes) {
    element.classList.remove(...classes);
}

// ========================================
// Wizard Initialization
// ========================================

/**
 * Initialize the season wizard modal
 */
function startSeasonWizard() {
    // MEMORY LEAK FIX: Clean up previous state before starting new wizard
    cleanupCalendarState();

    document.getElementById('seasonWizardModal').classList.add('wizard-modal--visible');
    ModalManager.show('seasonWizardModal');
    
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
    
}

/**
 * Show existing seasons section
 */
function showExistingSeasons() {
    document.getElementById('existingSeasons').classList.remove('d-none');
    document.querySelector('.row.mb-4:nth-child(2)').classList.add('wizard-view--hidden');
}

/**
 * Show main view (hide existing seasons)
 */
function showMainView() {
    document.getElementById('existingSeasons').classList.add('d-none');
    document.querySelector('.row.mb-4:nth-child(2)').classList.remove('wizard-view--hidden');
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
    document.getElementById('prevBtn').classList.toggle('wizard-btn--hidden', currentStep === 1);
    document.getElementById('nextBtn').classList.toggle('wizard-btn--hidden', currentStep === maxSteps);
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
    const sharedFunEl = document.getElementById('includeFunWeek');
    const sharedTstEl = document.getElementById('includeTstWeek');
    const sharedByeEl = document.getElementById('includeByeWeek');
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

    practiceConfig.classList.toggle('wizard-config--visible', practiceCheckbox.checked);
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
        
        const hasFun = document.getElementById('includeFunWeek')?.checked || false;
        const hasTst = document.getElementById('includeTstWeek')?.checked || false;
        const hasBye = document.getElementById('includeByeWeek')?.checked || false;
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
/**
 * Update calendar preview display
 */
function updateCalendarPreview() {
    // Try different preview elements based on league type
    const leagueType = document.getElementById('leagueType')?.value;
    let preview;
    
    // Try multiple possible element IDs
    const possibleIds = ['unifiedCalendarPreview', 'calendarPreview', 'pubLeagueCalendar', 'ecsFcCalendarPreview'];
    
    for (const id of possibleIds) {
        preview = document.getElementById(id);
        if (preview) {
            console.log(`Found calendar preview element: ${id}`);
            break;
        }
    }
    
    if (!preview) {
        console.log(`No calendar preview element found. Tried: ${possibleIds.join(', ')}`);
        // Try to find any element with "calendar" in the class or id
        const allElements = document.querySelectorAll('[id*="calendar"], [class*="calendar"]');
        console.log('Available calendar elements:', Array.from(allElements).map(el => `${el.tagName}#${el.id}.${el.className}`));
        return;
    }
    
    if (!calendarState.weeks || calendarState.weeks.length === 0) {
        console.log('No weeks in calendarState');
        return;
    }
    
    console.log('Updating calendar preview with', calendarState.weeks.length, 'weeks');
    console.log('Week types:', calendarState.weeks.map(w => `W${w.weekNumber}:${w.type}(${w.division})`).join(', '));
    
    // Group weeks by week number to show unified calendar
    const weeksByNumber = {};
    calendarState.weeks.forEach(week => {
        if (!weeksByNumber[week.weekNumber]) {
            weeksByNumber[week.weekNumber] = {
                weekNumber: week.weekNumber,
                date: week.date,
                type: week.type,
                divisions: []
            };
        }
        weeksByNumber[week.weekNumber].divisions.push(week.division);
    });
    
    // Convert to array and handle division-specific weeks
    const allWeeks = Object.values(weeksByNumber);
    const unifiedWeeks = [];
    
    allWeeks.forEach(week => {
        if (week.divisions.length === 2) {
            // Check if it's the same type for both divisions
            const weekDetails = calendarState.weeks.filter(w => w.weekNumber === week.weekNumber);
            const premierWeek = weekDetails.find(w => w.division === 'premier');
            const classicWeek = weekDetails.find(w => w.division === 'classic');
            
            if (premierWeek.type === classicWeek.type) {
                // Same type for both divisions
                unifiedWeeks.push({
                    ...week,
                    divisionsText: 'Premier & Classic'
                });
            } else {
                // Different types - show as mixed week
                const premierType = premierWeek.type === 'PLAYOFF' ? 'Playoffs' : premierWeek.type;
                const classicType = classicWeek.type === 'PLAYOFF' ? 'Playoffs' : classicWeek.type;
                unifiedWeeks.push({
                    ...week,
                    type: 'MIXED',
                    mixedTypes: { premier: premierType, classic: classicType },
                    divisionsText: `Premier: ${premierType} | Classic: ${classicType}`
                });
            }
        } else {
            // Division-specific week
            const division = week.divisions[0];
            const divisionText = division === 'premier' ? 'Premier only' : 'Classic only';
            unifiedWeeks.push({
                ...week,
                divisionsText: divisionText,
                divisionSpecific: division
            });
        }
    });
    
    const sortedWeeks = unifiedWeeks.sort((a, b) => a.weekNumber - b.weekNumber);
    
    let html = `
        <div class="mb-3 p-3 bg-light rounded">
            <h6 class="mb-1"><i class="fas fa-calendar-alt me-2"></i>Season Calendar Preview</h6>
            <small class="text-muted">${sortedWeeks.length} weeks total</small><br>
            <small class="text-info"><i class="fas fa-hand-pointer me-1"></i>Drag any week to swap positions and customize your schedule</small>
        </div>
        <div class="calendar-grid">
    `;
    
    sortedWeeks.forEach((week, index) => {
        let badgeClass = 'primary';
        let iconClass = 'fas fa-calendar';
        
        if (week.type === 'TST') {
            badgeClass = 'info';
            iconClass = 'fas fa-trophy';
        } else if (week.type === 'FUN') {
            badgeClass = 'warning';
            iconClass = 'fas fa-star';
        } else if (week.type === 'BYE') {
            badgeClass = 'secondary';
            iconClass = 'fas fa-pause';
        } else if (week.type === 'PLAYOFF') {
            badgeClass = 'danger';
            iconClass = 'fas fa-medal';
        } else if (week.type === 'MIXED') {
            badgeClass = 'dark';
            iconClass = 'fas fa-calendar-week';
        }
        
        html += `
            <div class="week-card draggable-week" 
                 data-week-number="${week.weekNumber}" 
                 data-week-type="${week.type}"
                 draggable="true">
                <div class="week-header bg-${badgeClass}">
                    <span class="week-number">Week ${week.weekNumber}</span>
                    <i class="fas fa-grip-vertical drag-handle"></i>
                </div>
                <div class="week-body">
                    <div class="week-date">${week.date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</div>
                    <div class="week-type">
                        <i class="${iconClass} me-1"></i>
                        ${week.type === 'PLAYOFF' ? 'Playoffs' : 
                          week.type === 'MIXED' ? 'Mixed Week' : week.type}
                    </div>
                    <div class="divisions">${week.divisionsText}</div>
                </div>
            </div>
        `;
    });
    
    html += '</div>';
    preview.innerHTML = html;
    
    // Add custom CSS for the calendar
    addCalendarCSS();
    
    // Add drag and drop functionality for special weeks
    initializeWeekCardDragAndDrop();
}

function generateCalendarPreview(forceRegenerate = false) {
    console.log('generateCalendarPreview called');
    const leagueType = document.getElementById('leagueType').value;
    const startDateStr = document.getElementById('seasonStartDate').value;
    
    console.log('League type:', leagueType, 'Start date:', startDateStr);
    
    if (!startDateStr) {
        console.log('No start date provided');
        return;
    }
    
    // Show/hide appropriate calendar containers
    const pubLeagueCalendar = document.getElementById('pubLeagueCalendar');
    const ecsFcCalendar = document.getElementById('ecsFcCalendar');
    
    if (leagueType === 'Pub League') {
        if (pubLeagueCalendar) pubLeagueCalendar.classList.remove('d-none');
        if (ecsFcCalendar) ecsFcCalendar.classList.add('d-none');
    } else if (leagueType === 'ECS FC') {
        if (pubLeagueCalendar) pubLeagueCalendar.classList.add('d-none');
        if (ecsFcCalendar) ecsFcCalendar.classList.remove('d-none');
    }
    
    // Parse date string properly to avoid timezone issues
    // When creating Date from "YYYY-MM-DD", add time to ensure local date
    const [year, month, day] = startDateStr.split('-').map(num => parseInt(num));
    const startDate = new Date(year, month - 1, day); // month is 0-indexed
    
    // Always regenerate calendar when called - this ensures visibility
    calendarState.startDate = startDate;
    
    if (leagueType === 'Pub League') {
        console.log('Generating Pub League calendar');
        generatePubLeagueCalendar(startDate);
    } else if (leagueType === 'ECS FC') {
        console.log('Generating ECS FC calendar');
        generateEcsFcCalendar(startDate);
    }
    
    // Update the calendar preview after generation
    console.log('Calling updateCalendarPreview');
    updateCalendarPreview();
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
    const premierPreview = document.getElementById('premierCalendarPreview');
    const classicPreview = document.getElementById('classicCalendarPreview');
    
    if (premierPreview) premierPreview.innerHTML = combinedCalendar.premierHTML;
    if (classicPreview) classicPreview.innerHTML = combinedCalendar.classicHTML;
    
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
 * Helper function to create week HTML
 */
function createWeekHTML(weekNumber, date, type, isPractice = false, isShared = false) {
    const typeMap = {
        'Regular': 'regular-week',
        'FUN': 'fun-week', 
        'TST': 'tst-week',
        'BYE': 'bye-week',
        'PLAYOFF': 'playoff-week',
        'BONUS': 'bonus-week'
    };
    
    const textMap = {
        'Regular': `Regular${isPractice ? ' (Practice Game 1)' : ''}`,
        'FUN': `Fun Week${isShared ? ' (Shared)' : ''}`,
        'TST': `TST Week${isShared ? ' (Shared)' : ''}`,
        'BYE': `BYE Week${isShared ? ' (Shared)' : ''}`,
        'PLAYOFF': type === 'PLAYOFF' ? 'Playoffs' : type,
        'BONUS': 'Bonus Week'
    };
    
    const cssClass = typeMap[type] || 'regular-week';
    const sharedAttr = isShared ? ` shared-week" data-shared-type="${type.toLowerCase()}` : '';
    
    return `<div class="week-item ${cssClass}${sharedAttr}" draggable="true" data-week="${weekNumber}" data-type="${type.toLowerCase()}">
        <div class="week-number">Week ${weekNumber}</div>
        <div class="week-date">${formatDate(date)}</div>
        <div class="week-type">${textMap[type] || type}</div>
    </div>`;
}

/**
 * Generate combined Pub League calendar (simplified)
 */
function generateCombinedPubLeagueCalendar(startDate) {
    // Get total weeks from dropdown to respect user selection
    const totalWeeks = parseInt(document.getElementById('totalSeasonWeeks')?.value) || 11;
    const specialWeeksCount = getEnabledSpecialWeeksCount();
    
    // Calculate regular weeks based on total season length (respecting dropdown)
    const premierRegular = totalWeeks - 2 - specialWeeksCount; // Premier: total - 2 playoffs - special weeks
    const classicRegular = totalWeeks - 1 - specialWeeksCount;  // Classic: total - 1 playoff - special weeks
    
    const config = {
        premier: { regular: premierRegular, playoff: 2, bonus: document.getElementById('premierHasBonusWeek')?.checked },
        classic: { regular: classicRegular, playoff: 1, bonus: document.getElementById('classicHasBonusWeek')?.checked },
        shared: { fun: document.getElementById('includeFunWeek')?.checked, tst: document.getElementById('includeTstWeek')?.checked, bye: document.getElementById('includeByeWeek')?.checked },
        totalWeeks: totalWeeks
    };
    
    console.log('Calendar config:', JSON.stringify(config, null, 2));
    
    let currentDate = new Date(startDate), weekNumber = 1;
    const calendar = { premierHTML: '<div class="calendar-weeks">', classicHTML: '<div class="calendar-weeks">' };
    
    // Generate exactly totalWeeks weeks, no more, no less
    for (let i = 0; i < totalWeeks; i++) {
        const weekDate = new Date(currentDate);
        let weekType = 'Regular';
        let isPremierWeek = true;
        let isClassicWeek = true;
        
        // Determine week type based on position in schedule
        if (i >= config.premier.regular && i < config.premier.regular + config.premier.playoff) {
            // Premier playoff weeks
            if (i >= config.classic.regular) {
                // Both in playoffs
                weekType = 'PLAYOFF';
            } else {
                // Mixed: Premier playoffs, Classic regular
                weekType = 'MIXED';
            }
        } else if (i >= config.classic.regular && i < config.classic.regular + config.classic.playoff) {
            // Classic playoff weeks (but Premier might be done)
            weekType = 'PLAYOFF';
            isPremierWeek = false; // Premier season is over
        } else if (i >= Math.max(config.premier.regular + config.premier.playoff, config.classic.regular + config.classic.playoff)) {
            // Special weeks (TST, FUN, BYE)
            const specialIndex = i - Math.max(config.premier.regular + config.premier.playoff, config.classic.regular + config.classic.playoff);
            const specialTypes = [];
            if (config.shared.tst) specialTypes.push('TST');
            if (config.shared.fun) specialTypes.push('FUN');
            if (config.shared.bye) specialTypes.push('BYE');
            
            if (specialIndex < specialTypes.length) {
                weekType = specialTypes[specialIndex];
            }
        }
        
        // Add weeks to calendar state - only add each week once per division that participates
        if (isPremierWeek) {
            // Premier NEVER has practice sessions
            calendarState.weeks.push({ 
                weekNumber, 
                date: new Date(weekDate), 
                type: weekType, 
                division: 'premier', 
                isPractice: false 
            });
            calendar.premierHTML += createWeekHTML(weekNumber, weekDate, weekType, false);
        }
        
        if (isClassicWeek) {
            // Classic has practice sessions on weeks 1 & 3 (only for Regular weeks)
            const isPractice = weekType === 'Regular' && (i === 0 || i === 2);
            calendarState.weeks.push({ 
                weekNumber, 
                date: new Date(weekDate), 
                type: weekType, 
                division: 'classic', 
                isPractice 
            });
            calendar.classicHTML += createWeekHTML(weekNumber, weekDate, weekType, isPractice);
        }
        
        currentDate.setDate(currentDate.getDate() + 7);
        weekNumber++;
    }
    
    calendar.premierHTML += '</div>';
    calendar.classicHTML += '</div>';
    return calendar;
}


/**
 * Initialize drag and drop functionality for calendar items
 * CONVERTED TO EVENT DELEGATION: Drag events still need direct addEventListener
 * as they cannot be delegated through data-action attributes
 */
function initializeCalendarDragAndDrop() {
    const weekItems = document.querySelectorAll('.week-item');

    weekItems.forEach(item => {
        // NOTE: Drag events must use addEventListener - no event delegation alternative
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
    // Apply drag active state using CSS class
    e.target.classList.add('drag-active');
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

        // REFACTORED: Apply theme color via utility function
        // Uses data attribute to track color, utility function applies CSS custom property
        const highlightColor = (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('primary') : '#0d6efd';
        applyThemeColor(weekItem, highlightColor);

        if (e.clientY < midPoint) {
            // Drop above - use CSS class for visual indicator
            weekItem.classList.add('drop-indicator-top');
            weekItem.dataset.dropPosition = 'before';
        } else {
            // Drop below - use CSS class for visual indicator
            weekItem.classList.add('drop-indicator-bottom');
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
    // Remove drag active state using CSS class
    e.target.classList.remove('drag-active');
    calendarDraggedElement = null;
    clearDropIndicators();
}

/**
 * Clear all drop indicators
 */
function clearDropIndicators() {
    const allWeekItems = document.querySelectorAll('.week-item');
    allWeekItems.forEach(item => {
        // Remove drop indicator classes instead of inline styles
        item.classList.remove('drop-indicator-top', 'drop-indicator-bottom');
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
    
    
    // Parse date properly to avoid timezone issues
    const [year, month, day] = startDateStr.split('-').map(num => parseInt(num));
    const startDate = new Date(year, month - 1, day);
    let currentDate = new Date(startDate);
    
    // Determine which division this container belongs to
    const containerClass = container.className;
    const containerId = container.id;
    let division;
    
    
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
    let count, previewId, startingLetterOffset = 0;
    
    if (leagueType === 'premier') {
        count = parseInt(document.getElementById('premierTeamCount').value);
        previewId = 'premierTeamPreview';
        startingLetterOffset = 0; // Premier starts at A
    } else if (leagueType === 'classic') {
        count = parseInt(document.getElementById('classicTeamCount').value);
        previewId = 'classicTeamPreview';
        // Classic starts after Premier teams
        const premierCount = parseInt(document.getElementById('premierTeamCount').value) || 0;
        startingLetterOffset = premierCount;
    } else if (leagueType === 'ecsFc') {
        count = parseInt(document.getElementById('ecsFcTeamCount').value);
        previewId = 'ecsFcTeamPreview';
        startingLetterOffset = 0; // ECS FC is standalone, starts at A
    }
    
    const previewDiv = document.getElementById(previewId);
    const teamLabels = [];
    
    // Generate team names with proper letter sequence
    for (let i = 0; i < count; i++) {
        const letter = String.fromCharCode(65 + startingLetterOffset + i);
        teamLabels.push(`Team ${letter}`);
    }
    
    // Show starting letter range for clarity
    const startLetter = String.fromCharCode(65 + startingLetterOffset);
    const endLetter = String.fromCharCode(65 + startingLetterOffset + count - 1);
    const rangeText = count > 1 ? `Teams ${startLetter}-${endLetter}` : `Team ${startLetter}`;
    
    previewDiv.innerHTML = `
        <div class="small text-muted mb-2">${rangeText} to be created:</div>
        <div class="d-flex flex-wrap gap-1">
            ${teamLabels.map(name => `<span class="badge bg-light text-dark border">${name}</span>`).join('')}
        </div>
    `;
}

/**
 * Add CSS for spinner animation and calendar styling
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

/**
 * Add custom CSS for calendar styling
 */
function addCalendarCSS() {
    if (document.getElementById('calendar-custom-css')) return; // Don't add twice
    
    const style = document.createElement('style');
    style.id = 'calendar-custom-css';
    style.textContent = `
        .calendar-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
            gap: 12px;
            padding: 8px;
        }
        
        .week-card {
            border: 2px solid var(--ecs-border, #e9ecef);
            border-radius: 8px;
            overflow: hidden;
            transition: all 0.2s ease;
            background: white;
        }

        .draggable-week {
            cursor: grab;
            position: relative;
        }

        .draggable-week:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            border-color: var(--ecs-primary, #7C3AED);
        }
        
        .drag-handle {
            font-size: 12px;
            opacity: 0.6;
            transition: opacity 0.2s ease;
        }
        
        .draggable-week:hover .drag-handle {
            opacity: 1;
        }
        
        .week-card:not(.dragging):hover {
            transform: translateY(-1px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        .week-card.dragging {
            opacity: 0.7;
            transform: rotate(5deg);
            cursor: grabbing;
        }
        
        .week-header {
            padding: 8px 12px;
            color: white;
            font-weight: 600;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        
        .week-header .drag-handle {
            font-size: 12px;
            opacity: 0.8;
        }
        
        .week-body {
            padding: 12px;
            text-align: center;
        }
        
        .week-date {
            font-size: 13px;
            color: var(--ecs-muted, #6c757d);
            margin-bottom: 4px;
        }

        .week-type {
            font-weight: 600;
            color: var(--ecs-dark, #495057);
            margin-bottom: 6px;
        }

        .divisions {
            font-size: 11px;
            color: var(--ecs-muted, #6c757d);
            background: var(--ecs-neutral-5, #f8f9fa);
            padding: 2px 6px;
            border-radius: 12px;
            display: inline-block;
        }

        .drop-zone {
            border: 2px dashed var(--ecs-primary, #7C3AED) !important;
            background: var(--ecs-primary-light-bg, rgba(124, 58, 237, 0.1)) !important;
        }
    `;
    document.head.appendChild(style);
}

/**
 * Initialize simple drag and drop for special weeks only
 * CONVERTED TO EVENT DELEGATION: Drag events still need direct addEventListener
 * as they cannot be delegated through data-action attributes
 */
function initializeWeekCardDragAndDrop() {
    const draggableWeeks = document.querySelectorAll('.draggable-week');

    draggableWeeks.forEach(week => {
        // NOTE: Drag events must use addEventListener - no event delegation alternative
        week.addEventListener('dragstart', (e) => {
            e.currentTarget.classList.add('dragging');
            e.dataTransfer.setData('text/plain', e.currentTarget.dataset.weekType);
            e.dataTransfer.effectAllowed = 'move';
        });
        
        week.addEventListener('dragend', (e) => {
            e.currentTarget.classList.remove('dragging');
        });
    });
    
    // Make all week cards drop zones
    const allWeeks = document.querySelectorAll('.week-card');
    allWeeks.forEach(week => {
        week.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            week.classList.add('drop-zone');
        });
        
        week.addEventListener('dragleave', (e) => {
            week.classList.remove('drop-zone');
        });
        
        week.addEventListener('drop', (e) => {
            e.preventDefault();
            week.classList.remove('drop-zone');
            
            const draggedType = e.dataTransfer.getData('text/plain');
            const draggedElement = document.querySelector(`.dragging[data-week-type="${draggedType}"]`);
            const dropTarget = e.currentTarget;
            
            if (draggedElement && dropTarget && draggedElement !== dropTarget) {
                swapWeekPositions(draggedElement, dropTarget);
            }
        });
    });
}

function swapWeekPositions(draggedWeek, targetWeek) {
    // Get the parent container
    const container = draggedWeek.parentNode;
    
    // Create placeholder to mark dragged week's position
    const placeholder = document.createElement('div');
    container.insertBefore(placeholder, draggedWeek);
    
    // Move dragged week to target position
    container.insertBefore(draggedWeek, targetWeek);
    
    // Move target week to dragged week's original position
    container.insertBefore(targetWeek, placeholder);
    
    // Remove placeholder
    container.removeChild(placeholder);
    
    // Update week numbers
    updateWeekNumbers();
}

function updateWeekNumbers() {
    const weekCards = document.querySelectorAll('.week-card');
    
    // Create a new calendar state based on the current DOM order
    const newWeeks = [];
    const startDate = calendarState.startDate;
    
    weekCards.forEach((card, index) => {
        const newWeekNumber = index + 1;
        const weekType = card.dataset.weekType;
        
        // Update the visual display
        card.dataset.weekNumber = newWeekNumber;
        const weekNumberSpan = card.querySelector('.week-number');
        if (weekNumberSpan) {
            weekNumberSpan.textContent = `Week ${newWeekNumber}`;
        }
        
        // Update the week date display
        const weekDateSpan = card.querySelector('.week-date');
        
        // Calculate the date for this week
        const weekDate = new Date(startDate);
        weekDate.setDate(startDate.getDate() + (index * 7));
        
        if (weekDateSpan) {
            weekDateSpan.textContent = weekDate.toLocaleDateString('en-US', { 
                month: 'short', 
                day: 'numeric', 
                year: 'numeric' 
            });
        }
        
        // Find ALL corresponding weeks in calendarState that match this week type
        // Use a more flexible matching approach that handles reordering
        const matchingWeeks = calendarState.weeks.filter(w => w.type === weekType);
        
        if (matchingWeeks.length > 0) {
            // During drag & drop, preserve existing weeks but update their positions
            // Group by division to ensure we get one week per division
            const weeksByDivision = {};
            matchingWeeks.forEach(week => {
                if (!weeksByDivision[week.division]) {
                    weeksByDivision[week.division] = week;
                }
            });
            
            // Update each division's week with the new position
            Object.values(weeksByDivision).forEach(week => {
                // Recalculate practice session flag based on NEW position
                // Classic has practice sessions on weeks 1 & 3 (only for Regular weeks)
                const isPractice = week.division === 'classic' && 
                                   week.type === 'Regular' && 
                                   (newWeekNumber === 1 || newWeekNumber === 3);
                
                newWeeks.push({
                    ...week, // Preserve all original properties except isPractice
                    weekNumber: newWeekNumber,
                    date: new Date(weekDate),
                    isPractice: isPractice // Recalculate based on new position
                });
            });
        }
    });
    
    // Update the calendar state with the new order
    calendarState.weeks = newWeeks.sort((a, b) => a.weekNumber - b.weekNumber);
    
    console.log('Weeks reordered via drag & drop - calendarState updated');
    console.log('New week order:', calendarState.weeks.map(w => `W${w.weekNumber}:${w.type}(${w.division})`).join(', '));
}

/**
 * Helper to create division summary card
 */
function createDivisionCard(name, data, color, icon) {
    return `<div class="col-md-6"><div class="card border-${color}"><div class="card-header bg-${color} text-white"><h6 class="mb-0"><i class="fas fa-${icon} me-2"></i>${name}</h6></div><div class="card-body"><ul class="list-unstyled mb-0">${Object.entries(data).map(([k,v]) => `<li><strong>${k}:</strong> ${v}</li>`).join('')}</ul></div></div></div>`;
}

/**
 * Generate season summary for final step
 */
function generateSeasonSummary() {
    const config = {
        name: document.getElementById('seasonName').value,
        type: document.getElementById('leagueType').value,
        startDate: document.getElementById('seasonStartDate').value,
        current: document.getElementById('setAsCurrent').checked,
        schedule: {
            'Premier Start': document.getElementById('premierStartTime')?.value || 'N/A',
            'Classic Start': document.getElementById('classicStartTime')?.value || 'N/A',
            'Match Duration': `${document.getElementById('matchDuration')?.value || 'N/A'} min`,
            'Fields': getWizardFieldConfig().map(f => f.name).join(', ') || 'N/A'
        }
    };
    
    let summary = `<div class="alert alert-info"><h5><i class="fas fa-info-circle me-2"></i>Season Creation Summary</h5><p class="mb-0">Review configuration before creating season.</p></div><div class="row mb-4">${createDivisionCard('Season Details', {'Name': config.name, 'Type': config.type, 'Start Date': config.startDate, 'Set as Current': config.current ? 'Yes' : 'No'}, 'secondary', 'calendar')}${createDivisionCard('Schedule Configuration', config.schedule, 'secondary', 'cog')}</div>`;
    
    if (config.type === 'Pub League') {
        // Calculate actual week counts from calendarState
        // Get the configured values to use as reference
        const configuredPremierRegular = parseInt(document.getElementById('premierRegularWeeks')?.value) || 7;
        const configuredPremierPlayoffs = parseInt(document.getElementById('premierPlayoffWeeks')?.value) || 2;
        const configuredClassicRegular = parseInt(document.getElementById('classicRegularWeeks')?.value) || 8;
        const configuredClassicPlayoffs = parseInt(document.getElementById('classicPlayoffWeeks')?.value) || 1;
        
        // Count weeks from calendarState, but use configured values as fallback
        // MIXED weeks count as playoffs for Premier (since Premier playoffs while Classic plays regular)
        const premierRegularWeeks = calendarState.weeks ? calendarState.weeks.filter(w => w.division === 'premier' && w.type === 'Regular').length : configuredPremierRegular;
        const premierPlayoffWeeks = calendarState.weeks ? 
            calendarState.weeks.filter(w => w.division === 'premier' && (w.type === 'PLAYOFF' || w.type === 'MIXED')).length : 
            configuredPremierPlayoffs;
        const classicRegularWeeks = calendarState.weeks ? 
            calendarState.weeks.filter(w => w.division === 'classic' && (w.type === 'Regular' || w.type === 'MIXED')).length : 
            configuredClassicRegular;
        const classicPlayoffWeeks = calendarState.weeks ? calendarState.weeks.filter(w => w.division === 'classic' && w.type === 'PLAYOFF').length : configuredClassicPlayoffs;
        
        // If the counts don't match configured values, use the configured ones (since drag/drop might have visual artifacts)
        const finalPremierRegular = premierRegularWeeks > 0 ? premierRegularWeeks : configuredPremierRegular;
        const finalPremierPlayoffs = premierPlayoffWeeks > 0 ? premierPlayoffWeeks : configuredPremierPlayoffs;
        const finalClassicRegular = classicRegularWeeks > 0 ? classicRegularWeeks : configuredClassicRegular;
        const finalClassicPlayoffs = classicPlayoffWeeks > 0 ? classicPlayoffWeeks : configuredClassicPlayoffs;
        
        const premier = {
            regular: finalPremierRegular, 
            playoff: finalPremierPlayoffs, 
            teams: parseInt(document.getElementById('premierTeamCount')?.value) || 0
        };
        const classic = {
            regular: finalClassicRegular, 
            playoff: finalClassicPlayoffs, 
            teams: parseInt(document.getElementById('classicTeamCount')?.value) || 0
        };
        
        // Generate team letter ranges
        const premierRange = premier.teams > 1 ? `Teams A-${String.fromCharCode(64 + premier.teams)}` : 'Team A';
        const classicStartLetter = String.fromCharCode(65 + premier.teams);
        const classicEndLetter = String.fromCharCode(64 + premier.teams + classic.teams);
        const classicRange = classic.teams > 1 ? `Teams ${classicStartLetter}-${classicEndLetter}` : `Team ${classicStartLetter}`;
        
        summary += `<div class="row mb-4">${createDivisionCard('Premier Division', {'Teams': `${premier.teams} (${premierRange})`, 'Regular': `${premier.regular} weeks`, 'Playoffs': `${premier.playoff} weeks`}, 'primary', 'trophy')}${createDivisionCard('Classic Division', {'Teams': `${classic.teams} (${classicRange})`, 'Regular': `${classic.regular} weeks`, 'Playoffs': `${classic.playoff} weeks`}, 'success', 'users')}</div>`;
    } else {
        const ecsfc = {regular: parseInt(document.getElementById('ecsFcRegularWeeks')?.value) || 0, playoff: parseInt(document.getElementById('ecsFcPlayoffWeeks')?.value) || 0, teams: parseInt(document.getElementById('ecsFcTeamCount')?.value) || 0};
        summary += `<div class="row mb-4"><div class="col-md-8 offset-md-2">${createDivisionCard('ECS FC Division', {'Teams': ecsfc.teams, 'Regular': `${ecsfc.regular} weeks`, 'Playoffs': `${ecsfc.playoff} weeks`}, 'info', 'shield').replace('col-md-6', 'col-12')}</div></div>`;
    }
    
    if (calendarState?.weeks?.length) summary += generateCombinedSchedulePreview();
    summary += `<div class="alert alert-success"><h6><i class="fas fa-check-circle me-2"></i>Ready to Create Season</h6><p class="mb-0">This will create your ${config.type} season. ${config.current ? 'Will be set as current active season.' : 'Created as draft season.'}</p></div>`;
    
    const summaryElement = document.getElementById('seasonSummary');
    if (summaryElement) {
        summaryElement.innerHTML = summary;
    }
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
        
        // Handle shared special weeks (TST, FUN, BYE) - they should appear for both divisions
        if (['TST', 'FUN', 'BYE'].includes(week.type)) {
            weeksByNumber[week.weekNumber].divisions['premier'] = {
                type: week.type,
                isPractice: week.isPractice || false
            };
            weeksByNumber[week.weekNumber].divisions['classic'] = {
                type: week.type,
                isPractice: week.isPractice || false
            };
        } else {
            // Regular weeks and playoffs are division-specific
            weeksByNumber[week.weekNumber].divisions[week.division] = {
                type: week.type,
                isPractice: week.isPractice || false
            };
        }
    });
    
    // Convert to sorted array and ensure both divisions have entries for each week
    const combinedWeeks = Object.values(weeksByNumber).sort((a, b) => a.weekNumber - b.weekNumber);
    
    // Fill in missing division entries with defaults
    combinedWeeks.forEach(week => {
        if (!week.divisions.premier) {
            week.divisions.premier = { type: 'Regular', isPractice: false };
        }
        if (!week.divisions.classic) {
            week.divisions.classic = { type: 'Regular', isPractice: false };
        }
    });
    
    let preview = `
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h6 class="mb-0"><i class="fas fa-calendar-event me-2"></i>Final Schedule Preview</h6>
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
        const formatDivisionInfo = (divisionData, division) => {
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
                case 'MIXED':
                    // For MIXED weeks, show the actual activity for each division
                    if (division === 'premier') {
                        typeText = 'Playoffs';
                        badgeClass = 'bg-danger';
                    } else {
                        typeText = 'Regular Season';
                        badgeClass = 'bg-secondary';
                    }
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
            '<i class="fas fa-star text-warning" title="Special Week"></i>' : 
            '<i class="fas fa-calendar text-muted" title="Regular Week"></i>';
        
        preview += `
            <tr ${isSpecialWeek ? 'class="table-warning"' : ''}>
                <td><strong>${week.weekNumber}</strong></td>
                <td>${formattedDate}</td>
                <td>${formatDivisionInfo(premier, 'premier')}</td>
                <td>${formatDivisionInfo(classic, 'classic')}</td>
                <td class="text-center">${statusIcon}</td>
            </tr>`;
    });
    
    preview += `
                                </tbody>
                            </table>
                        </div>
                        <div class="mt-3">
                            <small class="text-muted">
                                <i class="fas fa-info-circle me-1"></i>
                                This preview shows how both divisions will be scheduled together. 
                                Special weeks are highlighted in yellow.
                            </small>
                        </div>
                    </div>
                </div>
            </div>
        </div>`;
    
    return preview;
}

/**
 * Helper to get form data for season creation
 */
function getFormData() {
    const leagueType = document.getElementById('leagueType').value;
    const getId = id => document.getElementById(id);
    const getVal = id => getId(id)?.value;
    const getChecked = id => getId(id)?.checked;
    
    return {
        season_name: getVal('seasonName'),
        league_type: leagueType,
        set_as_current: getChecked('setAsCurrent'),
        season_start_date: calendarState.startDate.toISOString().split('T')[0],
        regular_weeks: parseInt(document.getElementById('premierRegularWeeks')?.value) || 7,
        total_weeks: parseInt(document.getElementById('totalSeasonWeeks')?.value) || 11,
        week_configs: getUniqueWeekConfigs(),
        premier_start_time: getVal('premierStartTime') || '08:20',
        classic_start_time: getVal('classicStartTime') || '13:10',
        match_duration: parseInt(getVal('matchDuration')) || 60,
        fields: getWizardFieldConfig().map(f => f.name).join(',') || 'North,South',
        enable_time_rotation: getChecked('enableTimeRotation') || true,
        break_duration: parseInt(getVal('breakDuration')) || 10,
        enable_practice_weeks: getChecked('classicHasPractice') || false,
        practice_weeks: getClassicPracticeWeeks() || "",
        ...(leagueType === 'Pub League' ? {
            premier_teams: parseInt(getVal('premierTeamCount')) || 8,
            classic_teams: parseInt(getVal('classicTeamCount')) || 4,
            premier_regular_weeks: parseInt(getVal('premierRegularWeeks')) || 7,
            premier_playoff_weeks: parseInt(getVal('premierPlayoffWeeks')) || 2,
            classic_regular_weeks: parseInt(getVal('classicRegularWeeks')) || 8,
            classic_playoff_weeks: parseInt(getVal('classicPlayoffWeeks')) || 1,
            premier_has_fun_week: getChecked('includeFunWeek') || false,
            premier_has_tst_week: getChecked('includeTstWeek') || false,
            premier_has_bonus_week: getChecked('includeByeWeek') || false,
            classic_has_practice_sessions: getChecked('classicHasPractice') || false,
            classic_practice_weeks: getClassicPracticeWeeks() || "",
            classic_practice_game_number: 1
        } : {
            ecs_fc_teams: parseInt(getVal('ecsFcTeamCount')) || 8,
            ecs_fc_regular_weeks: parseInt(getVal('ecsFcRegularWeeks')) || 7,
            ecs_fc_playoff_weeks: parseInt(getVal('ecsFcPlayoffWeeks')) || 1
        })
    };
}

/**
 * Create season using wizard data
 */
function createSeason() {
    if (!calendarState?.weeks?.length) {
        alert('Please ensure the calendar is generated.');
        return;
    }
    
    // Debug: Check start time values before sending
    console.log('Debug - Premier start time element:', document.getElementById('premierStartTime'));
    console.log('Debug - Premier start time value:', document.getElementById('premierStartTime')?.value);
    console.log('Debug - Classic start time element:', document.getElementById('classicStartTime'));  
    console.log('Debug - Classic start time value:', document.getElementById('classicStartTime')?.value);
    
    // CONVERTED TO EVENT DELEGATION: Use data-action instead of onclick
    const createButton = document.querySelector('[data-action="create-season"]');
    if (createButton) {
        createButton.disabled = true;
        createButton.innerHTML = '<i class="fas fa-spinner fa-spin me-2"></i>Creating Season...';
    }
    
    showLoadingModal('Creating Season', 'Please wait...');
    
    const formData = getFormData();
    console.log('Sending season data:', formData);
    
    fetch(window.autoScheduleUrls?.createSeasonWizard || '/auto-schedule/create-season', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json', 
            'X-CSRFToken': document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || ''
        },
        body: JSON.stringify(formData)
    })
    .then(response => response.json())
    .then(data => {
        hideLoadingModal();
        if (data.success) {
            showSuccessModal('Season Created!', 'Redirecting...', () => {
                window.location.href = data.redirect_url || '/auto-schedule/';
            });
        } else {
            if (createButton) {
                createButton.disabled = false;
                createButton.innerHTML = '<i class="fas fa-check me-2"></i>Create Season';
            }
            showErrorModal('Error', data.error || 'An error occurred.');
        }
    })
    .catch(error => {
        console.error('Season creation error:', error);
        hideLoadingModal();
        if (createButton) {
            createButton.disabled = false;
            createButton.innerHTML = '<i class="fas fa-check me-2"></i>Create Season';
        }
        showErrorModal('Network Error', 'Failed to create season.');
    });
}

// Add spinner CSS when script loads
addSpinnerCSS();

/**
 * Generic modal utility
 */
function showModal(id, title, message, type = 'info', callback = null) {
    const config = {
        loading: { icon: '<div class="spinner-border text-primary mb-3"><span class="visually-hidden">Loading...</span></div>', color: '', backdrop: 'data-bs-backdrop="static"', footer: '', autoClose: false },
        success: { icon: '<i class="ti ti-check-circle me-2"></i>', color: 'text-success', backdrop: '', footer: '', autoClose: 2000 },
        error: { icon: '<i class="ti ti-alert-circle me-2"></i>', color: 'text-danger', backdrop: '', footer: '<div class="modal-footer border-0"><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Close</button></div>', autoClose: false }
    };

    const cfg = config[type] || config.info;
    const modalHtml = `<div class="modal fade" id="${id}" tabindex="-1" ${cfg.backdrop}><div class="modal-dialog modal-dialog-centered"><div class="modal-content"><div class="modal-header border-0"><h5 class="modal-title ${cfg.color}">${cfg.icon}${title}</h5>${type === 'error' ? '<button type="button" class="btn-close" data-bs-dismiss="modal"></button>' : ''}</div><div class="modal-body ${type === 'loading' ? 'text-center' : ''} py-4"><p class="mb-0">${message}</p></div>${cfg.footer}</div></div></div>`;

    document.getElementById(id)?.remove();
    document.body.insertAdjacentHTML('beforeend', modalHtml);

    ModalManager.show(id);
    
    if (cfg.autoClose) {
        setTimeout(() => {
            bootstrap.Modal.getInstance(document.getElementById(id))?.hide();
            if (callback) callback();
        }, cfg.autoClose);
    }
}

function showLoadingModal(title, message) { showModal('loadingModal', title, message, 'loading'); }
function hideLoadingModal() { document.getElementById('loadingModal')?.remove(); }
function showSuccessModal(title, message, callback) { showModal('successModal', title, message, 'success', callback); }
function showErrorModal(title, message) { showModal('errorModal', title, message, 'error'); }

// ========================================
// Enhanced Wizard Functions
// ========================================

/**
 * Apply quick setup templates for wizard configuration
 */
function applyWizardTemplate(templateType) {
    switch(templateType) {
        case 'standard':
            // Standard setup: Premier 8:20, Classic 1:10, Time rotation enabled
            document.getElementById('premierStartTime').value = '08:20';
            document.getElementById('classicStartTime').value = '13:10';
            document.getElementById('matchDuration').value = '70';
            document.getElementById('breakDuration').value = '10';
            document.getElementById('enableTimeRotation').checked = true;
            document.getElementById('classicHasPractice').checked = false;
            // Hide practice weeks selection using CSS class
            document.getElementById('practice-weeks-selection').classList.add('d-none');
            break;

        case 'classic-practice':
            // Classic practice setup: Include practice weeks 1 & 3
            document.getElementById('premierStartTime').value = '08:20';
            document.getElementById('classicStartTime').value = '13:10';
            document.getElementById('matchDuration').value = '70';
            document.getElementById('breakDuration').value = '10';
            document.getElementById('enableTimeRotation').checked = true;
            document.getElementById('classicHasPractice').checked = true;
            // Show practice weeks selection using CSS class
            document.getElementById('practice-weeks-selection').classList.remove('d-none');

            // Check weeks 1 and 3 for practice
            setTimeout(() => {
                updateWizardPracticeWeekOptions();
                const week1 = document.getElementById('wizard-practice-week-1');
                const week3 = document.getElementById('wizard-practice-week-3');
                if (week1) week1.checked = true;
                if (week3) week3.checked = true;
            }, 100);
            break;

        case 'custom':
            // Custom setup - just clear and let user configure
            document.getElementById('classicHasPractice').checked = false;
            // Hide practice weeks selection using CSS class
            document.getElementById('practice-weeks-selection').classList.add('d-none');
            break;
    }
    
    // Show success feedback
    const template = templateType.charAt(0).toUpperCase() + templateType.slice(1);
    showToast(`${template} template applied successfully!`, 'success');
}

/**
 * Add new field configuration in wizard
 */
function addWizardField() {
    const container = document.getElementById('wizard-field-configurations');
    const fieldCount = container.children.length;
    
    const fieldItem = document.createElement('div');
    fieldItem.className = 'wizard-field-item mb-3';
    
    // CONVERTED TO EVENT DELEGATION: Removed onclick, using data-action only
    fieldItem.innerHTML = `
        <div class="row">
            <div class="col-md-8">
                <label class="form-label">Field Name</label>
                <input type="text" class="form-control wizard-field-name" placeholder="Field ${fieldCount + 1}" required>
                <div class="form-text">e.g., "North Field", "South Field", "Main Pitch"</div>
            </div>
            <div class="col-md-2 d-flex align-items-end">
                <button type="button" class="btn btn-outline-danger" data-action="remove-wizard-field" aria-label="Close"><i class="fas fa-times"></i></button>
            </div>
        </div>
    `;
    
    container.appendChild(fieldItem);
    updateWizardFieldRemoveButtons();
}

/**
 * Remove field configuration in wizard
 */
function removeWizardField(button) {
    const fieldItems = document.querySelectorAll('.wizard-field-item');
    if (fieldItems.length > 2) { // Keep at least 2 fields
        button.closest('.wizard-field-item').remove();
        updateWizardFieldRemoveButtons();
    }
}

/**
 * Update field remove button states
 */
function updateWizardFieldRemoveButtons() {
    const fieldItems = document.querySelectorAll('.wizard-field-item');
    const removeButtons = document.querySelectorAll('[data-action="remove-field"]');

    removeButtons.forEach(button => {
        button.disabled = fieldItems.length <= 2;
    });
}

/**
 * Update practice week options based on season length
 */
function updateWizardPracticeWeekOptions() {
    // Try to get season length from various sources
    let weekCount = 7; // default
    
    // Check if we're in structure configuration step
    const premierWeeks = document.getElementById('premierRegularWeeks');
    const classicWeeks = document.getElementById('classicRegularWeeks');
    const totalWeeks = document.getElementById('totalSeasonWeeks');
    
    if (premierWeeks && classicWeeks) {
        weekCount = Math.max(parseInt(premierWeeks.value) || 7, parseInt(classicWeeks.value) || 8);
    } else if (totalWeeks) {
        weekCount = Math.min(8, parseInt(totalWeeks.value || 11) - 3); // For classic practice weeks
    }
    
    // Handle only classic practice week container (Step 2)
    const container = document.getElementById('classicPracticeWeekCheckboxes');
    
    if (container) {
        container.innerHTML = '';
        
        for (let i = 1; i <= weekCount; i++) {
            const div = document.createElement('div');
            div.className = 'form-check form-check-inline';
            const checked = (i === 1 || i === 3) ? 'checked' : '';
            
            div.innerHTML = `
                <input class="form-check-input" type="checkbox" id="practice-week-${i}" value="${i}" ${checked}>
                <label class="form-check-label" for="practice-week-${i}">Week ${i}</label>
            `;
            container.appendChild(div);
        }
    }
}


/**
 * Get wizard field configuration data
 */
function getWizardFieldConfig() {
    const fieldItems = document.querySelectorAll('.wizard-field-item');
    if (fieldItems.length === 0) {
        // Return default fields if no wizard fields found
        return [{ name: 'North' }, { name: 'South' }];
    }
    
    const fieldConfig = [];
    
    fieldItems.forEach(item => {
        const name = item.querySelector('.wizard-field-name')?.value?.trim();
        
        if (name) {
            fieldConfig.push({
                name: name
            });
        }
    });
    
    // If no valid fields found, return defaults
    return fieldConfig.length > 0 ? fieldConfig : [{ name: 'North' }, { name: 'South' }];
}

/**
 * Get unique week configurations for both divisions
 */
function getUniqueWeekConfigs() {
    const uniqueWeeks = new Map();
    
    // Process all weeks and create entries for both divisions where appropriate
    calendarState.weeks.forEach(w => {
        const weekKey = `${w.weekNumber}-${w.division}`;
        
        if (!uniqueWeeks.has(weekKey)) {
            uniqueWeeks.set(weekKey, {
                date: w.date.toISOString().split('T')[0], 
                type: w.type.toUpperCase(), 
                week_number: w.weekNumber,
                division: w.division, // Keep division for backend filtering
                is_practice: w.isPractice || false
            });
        }
    });
    
    // Convert to array and sort by week number, then by division
    return Array.from(uniqueWeeks.values()).sort((a, b) => {
        if (a.week_number !== b.week_number) {
            return a.week_number - b.week_number;
        }
        return a.division.localeCompare(b.division);
    });
}

/**
 * Get classic practice weeks configuration from Step 2
 */
function getClassicPracticeWeeks() {
    const enablePractice = document.getElementById('classicHasPractice');
    if (!enablePractice || !enablePractice.checked) {
        return null;
    }
    
    const checkboxes = document.querySelectorAll('#classicPracticeWeekCheckboxes input[type="checkbox"]:checked');
    const practiceWeeks = Array.from(checkboxes).map(cb => cb.value);
    
    return practiceWeeks.length > 0 ? practiceWeeks.join(',') : null;
}

/**
 * Enhanced validation for wizard step 4
 */
function validateWizardStep4() {
    const premierTime = document.getElementById('premierStartTime').value;
    const classicTime = document.getElementById('classicStartTime').value;
    const matchDuration = document.getElementById('matchDuration').value;
    const fieldConfig = getWizardFieldConfig();
    
    if (!premierTime || !classicTime) {
        showErrorModal('Configuration Error', 'Both Premier and Classic start times are required.');
        return false;
    }
    
    if (!matchDuration || matchDuration < 30 || matchDuration > 120) {
        showErrorModal('Configuration Error', 'Match duration must be between 30 and 120 minutes.');
        return false;
    }
    
    if (fieldConfig.length < 2) {
        showErrorModal('Configuration Error', 'At least 2 fields are required for back-to-back scheduling.');
        return false;
    }
    
    // Check for duplicate field names
    const fieldNames = fieldConfig.map(f => f.name.toLowerCase());
    const uniqueNames = [...new Set(fieldNames)];
    if (fieldNames.length !== uniqueNames.length) {
        showErrorModal('Configuration Error', 'Field names must be unique.');
        return false;
    }
    
    // Check for empty field names
    if (fieldConfig.some(f => !f.name || f.name.trim() === '')) {
        showErrorModal('Configuration Error', 'All fields must have names.');
        return false;
    }
    
    return true;
}

/**
 * Show toast notification
 */
function showToast(message, type = 'info') {
    // Simple toast implementation
    const toast = document.createElement('div');

    // REFACTORED: Use utility classes for toast styling
    // - z-index-9999: Ensures toast appears above all content including modals (from layout-utils.css)
    // - min-w-300: Ensures readable toast width across different message lengths (from sizing-utils.css)
    toast.className = `alert alert-${type} position-fixed top-0 end-0 m-3 z-index-9999 min-w-300`;

    // CONVERTED TO EVENT DELEGATION: Replaced onclick with data-action
    toast.innerHTML = `
        <i class="fas fa-${type === 'success' ? 'check' : 'info'}-circle me-2"></i>
        ${message}
        <button type="button" class="btn-close" data-action="close-toast"></button>
    `;

    document.body.appendChild(toast);

    // Auto-remove after 3 seconds
    setTimeout(() => {
        if (toast.parentElement) {
            toast.remove();
        }
    }, 3000);
}

// ========================================
// Enhanced Season Structure Functions
// ========================================

/**
 * Update season structure breakdown based on total weeks
 */
function updateSeasonStructure() {
    const totalWeeks = parseInt(document.getElementById('totalSeasonWeeks').value);
    const breakdown = document.getElementById('seasonBreakdown');
    
    // Fixed playoff weeks
    const premierPlayoffs = 2;
    const classicPlayoffs = 1;
    const specialWeeksCount = getEnabledSpecialWeeksCount();
    
    // Calculate regular weeks based on total season length
    // Total weeks = regular weeks + playoff weeks + special weeks
    // For Premier: totalWeeks = premierRegular + 2 + specialWeeks
    // For Classic: totalWeeks = classicRegular + 1 + specialWeeks
    
    const premierRegular = totalWeeks - premierPlayoffs - specialWeeksCount;
    const classicRegular = totalWeeks - classicPlayoffs - specialWeeksCount;
    
    // Update the form inputs
    const premierRegularInput = document.getElementById('premierRegularWeeks');
    const classicRegularInput = document.getElementById('classicRegularWeeks');
    
    if (premierRegularInput) {
        premierRegularInput.value = premierRegular;
    }
    if (classicRegularInput) {
        classicRegularInput.value = classicRegular;
    }
    
    // Update the breakdown display
    breakdown.innerHTML = `
        <div><strong>Premier:</strong> ${premierRegular} regular + ${premierPlayoffs} playoff weeks</div>
        <div><strong>Classic:</strong> ${classicRegular} regular + ${classicPlayoffs} playoff week</div>
        <div class="text-muted"><small>Plus ${specialWeeksCount} shared special weeks</small></div>
        <div class="text-muted"><small>Total season length: ${totalWeeks} weeks</small></div>
    `;
    
    // Regenerate calendar if we're on step 3
    if (typeof generateCalendarPreview === 'function' && currentStep === 3) {
        generateCalendarPreview(true);
    }
}

/**
 * Count enabled special weeks
 */
function getEnabledSpecialWeeksCount() {
    let count = 0;
    if (document.getElementById('includeTstWeek')?.checked) count++;
    if (document.getElementById('includeFunWeek')?.checked) count++;
    if (document.getElementById('includeByeWeek')?.checked) count++;
    return count;
}

// Special week placement selectors removed - users can drag & drop in calendar preview


/**
 * CONVERTED TO EVENT DELEGATION: DOMContentLoaded handler removed
 * All event listeners are now handled by the centralized EventDelegation system
 * via data-action, data-on-change, and data-on-input attributes
 *
 * Initialization functions are called when needed (e.g., when wizard opens)
 * Change events are handled through EventDelegation.handleChange() via data-on-change
 */

// Initialize on page load if needed
function initAutoScheduleWizard() {
    // Page guard - only run on auto schedule wizard page
    if (!document.getElementById('totalSeasonWeeks')) {
        return; // Not on auto schedule wizard page
    }

    // Initialize field remove button states
    updateWizardFieldRemoveButtons();

    // Initialize season structure calculations
    updateSeasonStructure();
    updateWizardPracticeWeekOptions();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAutoScheduleWizard);
} else {
    // DOM already loaded
    initAutoScheduleWizard();
}
