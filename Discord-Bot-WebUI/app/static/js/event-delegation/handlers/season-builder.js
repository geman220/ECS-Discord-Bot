/**
 * Season Builder Wizard - Event Handlers
 * Handles the 6-step season creation wizard with division-specific week configurations
 */

console.log('[SeasonBuilder] Module loading...');

// Guard: Ensure EventDelegation is available
if (typeof window.EventDelegation === 'undefined') {
    console.error('[SeasonBuilder] ERROR: window.EventDelegation is not defined! Module cannot load.');
}

// ============================================================================
// STATE MANAGEMENT
// ============================================================================

const SeasonBuilderState = {
    currentStep: 1,
    totalSteps: 5, // Reduced from 6: combined Calendar + Schedule

    // Step 1: Basics
    seasonName: '',
    leagueType: 'Pub League',
    setAsCurrent: true,

    // Step 2: Teams
    premierTeams: 8,
    classicTeams: 4,
    ecsFcTeams: 8,

    // Step 3: Schedule (date picker + week types combined)
    seasonStartDate: null,
    premierWeekConfigs: [],
    classicWeekConfigs: [],
    ecsFcWeekConfigs: [],

    // Step 4: Time & Fields
    premierStartTime: '08:20',
    classicStartTime: '13:10',
    matchDuration: 70,
    breakDuration: 10,
    fields: ['North', 'South'],
    enableTimeRotation: true

    // Step 5: Review & Create
};

// ============================================================================
// WEEK TYPE STYLES & CONFIGURATION
// ============================================================================

const weekTypeStyles = {
    'REGULAR':  { bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-800 dark:text-green-400', border: 'border-green-200 dark:border-green-800', icon: 'ti-ball-football' },
    'TST':      { bg: 'bg-blue-100 dark:bg-blue-900/30', text: 'text-blue-800 dark:text-blue-400', border: 'border-blue-200 dark:border-blue-800', icon: 'ti-tournament' },
    'FUN':      { bg: 'bg-yellow-100 dark:bg-yellow-900/30', text: 'text-yellow-800 dark:text-yellow-400', border: 'border-yellow-200 dark:border-yellow-800', icon: 'ti-confetti' },
    'BYE':      { bg: 'bg-gray-100 dark:bg-gray-700', text: 'text-gray-600 dark:text-gray-400', border: 'border-gray-300 dark:border-gray-600', icon: 'ti-calendar-off' },
    'PLAYOFF':  { bg: 'bg-purple-100 dark:bg-purple-900/30', text: 'text-purple-800 dark:text-purple-400', border: 'border-purple-200 dark:border-purple-800', icon: 'ti-trophy' },
    'PRACTICE': { bg: 'bg-cyan-100 dark:bg-cyan-900/30', text: 'text-cyan-800 dark:text-cyan-400', border: 'border-cyan-200 dark:border-cyan-800', icon: 'ti-run' }
};

const divisionWeekTypes = {
    premier: ['REGULAR', 'TST', 'FUN', 'BYE', 'PLAYOFF'],
    classic: ['REGULAR', 'PRACTICE', 'TST', 'FUN', 'BYE', 'PLAYOFF'], // TST and FUN are shared with Premier
    ecs_fc: ['REGULAR', 'BYE', 'PLAYOFF']
};

// Quick templates
// IMPORTANT: Premier and Classic must have the same number of weeks (same season length)
// Premier has 2 playoff weeks, Classic has 1 - but FUN week is shared
// Example: Week 9 = Premier PLAYOFF 1 / Classic REGULAR, Week 10 = FUN, Week 11 = Premier PLAYOFF 2 / Classic PLAYOFF
const weekTemplates = {
    premier: {
        standard: [
            // Weeks 1-3: Regular season start
            { type: 'REGULAR' }, { type: 'REGULAR' }, { type: 'REGULAR' },
            // Week 4: TST (Tournament)
            { type: 'TST' },
            // Weeks 5-8: Regular season
            { type: 'REGULAR' }, { type: 'REGULAR' }, { type: 'REGULAR' }, { type: 'REGULAR' },
            // Week 9: Premier Playoff 1 (Classic still has regular matches)
            { type: 'PLAYOFF' },
            // Week 10: FUN week (everyone together)
            { type: 'FUN' },
            // Week 11: Premier Playoff 2
            { type: 'PLAYOFF' }
        ],
        compact: [
            { type: 'REGULAR' }, { type: 'REGULAR' }, { type: 'REGULAR' },
            { type: 'TST' },
            { type: 'REGULAR' }, { type: 'REGULAR' },
            { type: 'PLAYOFF' }, { type: 'FUN' }, { type: 'PLAYOFF' }
        ]
    },
    classic: {
        standard: [
            // Weeks 1-2: Practice weeks (practice session + match)
            { type: 'PRACTICE' }, { type: 'PRACTICE' },
            // Week 3: Regular
            { type: 'REGULAR' },
            // Week 4: TST (shared with Premier)
            { type: 'TST' },
            // Weeks 5-8: Regular season
            { type: 'REGULAR' }, { type: 'REGULAR' }, { type: 'REGULAR' }, { type: 'REGULAR' },
            // Week 9: Classic still has regular matches (while Premier is in Playoff 1)
            { type: 'REGULAR' },
            // Week 10: FUN week (everyone together)
            { type: 'FUN' },
            // Week 11: Classic Playoff (single week)
            { type: 'PLAYOFF' }
        ],
        compact: [
            { type: 'PRACTICE' }, { type: 'REGULAR' }, { type: 'REGULAR' },
            { type: 'TST' },
            { type: 'REGULAR' }, { type: 'REGULAR' },
            { type: 'REGULAR' }, { type: 'FUN' }, { type: 'PLAYOFF' }
        ]
    },
    ecs_fc: {
        standard: [
            { type: 'REGULAR' }, { type: 'REGULAR' }, { type: 'REGULAR' },
            { type: 'REGULAR' }, { type: 'REGULAR' }, { type: 'REGULAR' },
            { type: 'REGULAR' }, { type: 'PLAYOFF' }
        ]
    }
};

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function isDark() {
    return document.documentElement.classList.contains('dark');
}

function showToast(message, type = 'info') {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            toast: true,
            position: 'top-end',
            icon: type,
            title: message,
            showConfirmButton: false,
            timer: 3000,
            background: isDark() ? '#1f2937' : '#ffffff',
            color: isDark() ? '#f3f4f6' : '#111827'
        });
    }
}

function showValidationError(message) {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            icon: 'warning',
            title: 'Required Field',
            text: message,
            background: isDark() ? '#1f2937' : '#ffffff',
            color: isDark() ? '#f3f4f6' : '#111827',
            confirmButtonColor: '#1a472a'
        });
    }
}

// ============================================================================
// WEEK CARD RENDERING
// ============================================================================

function renderWeekCard(weekConfig, index, division) {
    const style = weekTypeStyles[weekConfig.type] || weekTypeStyles['REGULAR'];
    const types = divisionWeekTypes[division] || divisionWeekTypes.premier;
    const weekNum = index + 1;

    const typeOptions = types.map(t => {
        const selected = t === weekConfig.type ? 'selected' : '';
        return `<option value="${t}" ${selected}>${t}</option>`;
    }).join('');

    return `
        <div class="week-card flex items-center gap-3 p-3 rounded-lg border ${style.border} ${style.bg} transition-all"
             data-week-index="${index}" data-division="${division}" draggable="true">
            <div class="drag-handle cursor-grab active:cursor-grabbing p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <i class="ti ti-grip-vertical text-lg"></i>
            </div>
            <div class="w-8 h-8 rounded-full flex items-center justify-center ${style.bg} ${style.text} font-bold text-sm">
                ${weekNum}
            </div>
            <select class="week-type-select flex-1 text-sm rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white focus:ring-ecs-green focus:border-ecs-green"
                    data-on-change="sb-change-week-type" data-week-index="${index}" data-division="${division}">
                ${typeOptions}
            </select>
            <span class="px-2 py-0.5 text-xs font-medium rounded ${style.bg} ${style.text}">
                <i class="ti ${style.icon} mr-1"></i>${weekConfig.type}
            </span>
            <button type="button" class="p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                    data-action="sb-remove-week" data-week-index="${index}" data-division="${division}">
                <i class="ti ti-x"></i>
            </button>
        </div>
    `;
}

function renderWeekBuilder(division, configs) {
    const container = document.getElementById(`${division}WeekBuilder`);
    if (!container) return;

    const cardsContainer = container.querySelector('.week-cards-container');
    if (!cardsContainer) return;

    if (configs.length === 0) {
        cardsContainer.innerHTML = `
            <div class="text-center py-8 text-gray-500 dark:text-gray-400">
                <i class="ti ti-calendar-plus text-3xl mb-2"></i>
                <p>No weeks configured. Add weeks or apply a template.</p>
            </div>
        `;
        return;
    }

    cardsContainer.innerHTML = configs.map((config, index) =>
        renderWeekCard(config, index, division)
    ).join('');

    // Re-initialize drag-drop
    initWeekDragDrop(division);
}

// Render week card with actual date
function renderWeekCardWithDate(weekConfig, index, division, weekDate) {
    const style = weekTypeStyles[weekConfig.type] || weekTypeStyles['REGULAR'];
    const types = divisionWeekTypes[division] || divisionWeekTypes.premier;
    const weekNum = index + 1;
    const dateStr = weekDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    const typeOptions = types.map(t => {
        const selected = t === weekConfig.type ? 'selected' : '';
        return `<option value="${t}" ${selected}>${t}</option>`;
    }).join('');

    // Check if this is a shared week type (TST, BYE, FUN)
    const isSharedWeekType = ['TST', 'BYE', 'FUN'].includes(weekConfig.type);
    const sharedBadge = isSharedWeekType ? '<span class="text-xs text-purple-500 dark:text-purple-400 ml-1">(All)</span>' : '';

    return `
        <div class="week-card flex items-center gap-2 p-3 rounded-lg border ${style.border} ${style.bg} transition-all"
             data-week-index="${index}" data-division="${division}" draggable="true">
            <div class="drag-handle cursor-grab active:cursor-grabbing p-1 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <i class="ti ti-grip-vertical text-lg"></i>
            </div>
            <div class="flex flex-col items-center min-w-[50px]">
                <span class="text-xs text-gray-500 dark:text-gray-400">${dateStr}</span>
                <span class="text-sm font-bold ${style.text}">W${weekNum}</span>
            </div>
            <select class="week-type-select flex-1 text-sm rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white focus:ring-ecs-green focus:border-ecs-green"
                    data-on-change="sb-change-week-type" data-week-index="${index}" data-division="${division}">
                ${typeOptions}
            </select>
            <span class="px-2 py-0.5 text-xs font-medium rounded ${style.bg} ${style.text} whitespace-nowrap">
                <i class="ti ${style.icon} mr-1"></i>${weekConfig.type}${sharedBadge}
            </span>
            <button type="button" class="p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors"
                    data-action="sb-remove-week" data-week-index="${index}" data-division="${division}">
                <i class="ti ti-x"></i>
            </button>
        </div>
    `;
}

function renderWeekBuilderWithDates(division, configs) {
    const container = document.getElementById(`${division}WeekBuilder`);
    if (!container) return;

    const cardsContainer = container.querySelector('.week-cards-container');
    if (!cardsContainer) return;

    const startDate = SeasonBuilderState.seasonStartDate;

    if (configs.length === 0) {
        cardsContainer.innerHTML = `
            <div class="text-center py-8 text-gray-500 dark:text-gray-400">
                <i class="ti ti-calendar-plus text-3xl mb-2"></i>
                <p>No weeks configured. Add weeks or apply a template.</p>
            </div>
        `;
        return;
    }

    if (!startDate) {
        // Fall back to regular render if no start date
        cardsContainer.innerHTML = configs.map((config, index) =>
            renderWeekCard(config, index, division)
        ).join('');
    } else {
        // Render with actual dates
        const start = new Date(startDate + 'T00:00:00');
        cardsContainer.innerHTML = configs.map((config, index) => {
            const weekDate = new Date(start);
            weekDate.setDate(weekDate.getDate() + (index * 7));
            return renderWeekCardWithDate(config, index, division, weekDate);
        }).join('');
    }

    // Re-initialize drag-drop
    initWeekDragDrop(division);

    // Update week count display
    const weekCountEl = container.querySelector('.week-count');
    if (weekCountEl) {
        weekCountEl.textContent = `${configs.length} weeks`;
    }
}

function updateWeekBadge(element) {
    const weekIndex = parseInt(element.dataset.weekIndex);
    const division = element.dataset.division;
    const newType = element.value;

    // Update state
    const configs = getWeekConfigs(division);
    if (configs[weekIndex]) {
        configs[weekIndex].type = newType;
    }

    // Re-render with dates
    renderWeekBuilderWithDates(division, configs);
}

// ============================================================================
// WEEK CONFIG HELPERS
// ============================================================================

function getWeekConfigs(division) {
    switch (division) {
        case 'premier': return SeasonBuilderState.premierWeekConfigs;
        case 'classic': return SeasonBuilderState.classicWeekConfigs;
        case 'ecs_fc': return SeasonBuilderState.ecsFcWeekConfigs;
        default: return [];
    }
}

function setWeekConfigs(division, configs) {
    switch (division) {
        case 'premier':
            SeasonBuilderState.premierWeekConfigs = configs;
            break;
        case 'classic':
            SeasonBuilderState.classicWeekConfigs = configs;
            break;
        case 'ecs_fc':
            SeasonBuilderState.ecsFcWeekConfigs = configs;
            break;
    }
}

// ============================================================================
// DRAG AND DROP FOR WEEKS
// ============================================================================

let draggedWeekElement = null;
let draggedWeekIndex = null;
let draggedDivision = null;

function initWeekDragDrop(division) {
    const container = document.getElementById(`${division}WeekBuilder`);
    if (!container) return;

    const cards = container.querySelectorAll('.week-card[draggable="true"]');

    cards.forEach(card => {
        card.addEventListener('dragstart', handleWeekDragStart);
        card.addEventListener('dragend', handleWeekDragEnd);
        card.addEventListener('dragover', handleWeekDragOver);
        card.addEventListener('drop', handleWeekDrop);
        card.addEventListener('dragleave', handleWeekDragLeave);
    });
}

function handleWeekDragStart(e) {
    draggedWeekElement = e.currentTarget;
    draggedWeekIndex = parseInt(e.currentTarget.dataset.weekIndex);
    draggedDivision = e.currentTarget.dataset.division;

    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', draggedWeekIndex);

    setTimeout(() => {
        e.currentTarget.classList.add('opacity-50', 'scale-95');
    }, 0);
}

function handleWeekDragEnd(e) {
    e.currentTarget.classList.remove('opacity-50', 'scale-95');

    // Remove all drop indicators
    document.querySelectorAll('.week-card').forEach(card => {
        card.classList.remove('border-t-4', 'border-t-ecs-green', 'border-b-4', 'border-b-ecs-green');
    });

    draggedWeekElement = null;
    draggedWeekIndex = null;
    draggedDivision = null;
}

function handleWeekDragOver(e) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';

    const card = e.currentTarget;
    const division = card.dataset.division;

    // Only allow dropping within the same division
    if (division !== draggedDivision) return;

    const rect = card.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;

    // Remove previous indicators
    card.classList.remove('border-t-4', 'border-t-ecs-green', 'border-b-4', 'border-b-ecs-green');

    // Add indicator based on mouse position
    if (e.clientY < midY) {
        card.classList.add('border-t-4', 'border-t-ecs-green');
    } else {
        card.classList.add('border-b-4', 'border-b-ecs-green');
    }
}

function handleWeekDragLeave(e) {
    e.currentTarget.classList.remove('border-t-4', 'border-t-ecs-green', 'border-b-4', 'border-b-ecs-green');
}

function handleWeekDrop(e) {
    e.preventDefault();

    const targetCard = e.currentTarget;
    const targetIndex = parseInt(targetCard.dataset.weekIndex);
    const targetDivision = targetCard.dataset.division;

    // Only allow dropping within the same division
    if (targetDivision !== draggedDivision) return;

    // Remove indicators
    targetCard.classList.remove('border-t-4', 'border-t-ecs-green', 'border-b-4', 'border-b-ecs-green');

    // Calculate insertion position
    const rect = targetCard.getBoundingClientRect();
    const midY = rect.top + rect.height / 2;
    const insertAfter = e.clientY >= midY;

    // Reorder the configs
    const configs = getWeekConfigs(draggedDivision);
    const [movedItem] = configs.splice(draggedWeekIndex, 1);

    let newIndex = insertAfter ? targetIndex : targetIndex;
    if (draggedWeekIndex < targetIndex) {
        newIndex = insertAfter ? targetIndex : targetIndex - 1;
    } else {
        newIndex = insertAfter ? targetIndex + 1 : targetIndex;
    }

    configs.splice(newIndex, 0, movedItem);

    // Re-render with dates and update calendar preview
    renderWeekBuilderWithDates(draggedDivision, configs);
    updateCalendarPreview();
}

// ============================================================================
// CALENDAR PREVIEW
// ============================================================================

function updateCalendarPreview() {
    const startDate = SeasonBuilderState.seasonStartDate;
    const container = document.getElementById('calendarPreviewContent');

    if (!container) return;

    if (!startDate) {
        container.innerHTML = `
            <div class="text-center text-gray-500 dark:text-gray-400 py-8">
                <i class="ti ti-calendar-plus text-4xl mb-2"></i>
                <p>Select a start date to see your season calendar</p>
            </div>
        `;
        return;
    }

    const start = new Date(startDate + 'T00:00:00');
    const isPubLeague = SeasonBuilderState.leagueType === 'Pub League';

    if (isPubLeague) {
        container.innerHTML = renderDualCalendar(start);
    } else {
        container.innerHTML = renderSingleCalendar(start, 'ecs_fc');
    }
}

function renderDualCalendar(startDate) {
    const premierConfigs = SeasonBuilderState.premierWeekConfigs;
    const classicConfigs = SeasonBuilderState.classicWeekConfigs;

    return `
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <!-- Premier Division -->
            <div>
                <h5 class="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                    <span class="w-6 h-6 bg-ecs-green rounded-full flex items-center justify-center">
                        <i class="ti ti-trophy text-white text-xs"></i>
                    </span>
                    Premier Division (${premierConfigs.length} weeks)
                </h5>
                <div class="space-y-2">
                    ${premierConfigs.map((config, i) => renderCalendarWeek(startDate, i, config.type, 'premier')).join('')}
                </div>
            </div>
            <!-- Classic Division -->
            <div>
                <h5 class="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                    <span class="w-6 h-6 bg-blue-500 rounded-full flex items-center justify-center">
                        <i class="ti ti-shield text-white text-xs"></i>
                    </span>
                    Classic Division (${classicConfigs.length} weeks)
                </h5>
                <div class="space-y-2">
                    ${classicConfigs.map((config, i) => renderCalendarWeek(startDate, i, config.type, 'classic')).join('')}
                </div>
            </div>
        </div>
        ${renderCalendarLegend()}
    `;
}

function renderSingleCalendar(startDate, division) {
    const configs = getWeekConfigs(division);

    return `
        <div>
            <h5 class="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                <span class="w-6 h-6 bg-green-500 rounded-full flex items-center justify-center">
                    <i class="ti ti-shield text-white text-xs"></i>
                </span>
                ECS FC Schedule (${configs.length} weeks)
            </h5>
            <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                ${configs.map((config, i) => renderCalendarWeek(startDate, i, config.type, 'ecs_fc')).join('')}
            </div>
        </div>
        ${renderCalendarLegend()}
    `;
}

function renderCalendarWeek(startDate, weekIndex, weekType, division) {
    const weekDate = new Date(startDate);
    weekDate.setDate(weekDate.getDate() + (weekIndex * 7));
    const dateStr = weekDate.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });

    const style = weekTypeStyles[weekType] || weekTypeStyles['REGULAR'];
    const weekNum = weekIndex + 1;

    return `
        <div class="flex items-center gap-3 p-2.5 rounded-lg border ${style.border} ${style.bg}">
            <div class="w-8 h-8 rounded-full flex items-center justify-center ${style.bg}">
                <span class="text-xs font-bold ${style.text}">${weekNum}</span>
            </div>
            <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-gray-900 dark:text-white truncate">${dateStr}</p>
            </div>
            <span class="px-2 py-0.5 text-xs font-medium rounded ${style.bg} ${style.text}">
                ${weekType}
            </span>
        </div>
    `;
}

function renderCalendarLegend() {
    const types = SeasonBuilderState.leagueType === 'Pub League'
        ? ['REGULAR', 'TST', 'FUN', 'BYE', 'PRACTICE', 'PLAYOFF']
        : ['REGULAR', 'BYE', 'PLAYOFF'];

    return `
        <div class="mt-4 pt-4 border-t border-gray-200 dark:border-gray-700">
            <p class="text-xs text-gray-500 dark:text-gray-400 mb-2">Legend:</p>
            <div class="flex flex-wrap gap-3 text-xs">
                ${types.map(t => {
                    const style = weekTypeStyles[t];
                    return `<span class="inline-flex items-center gap-1">
                        <span class="w-3 h-3 rounded-full ${style.bg} ${style.border} border"></span>
                        ${t}
                    </span>`;
                }).join('')}
            </div>
        </div>
    `;
}

// ============================================================================
// SUMMARY RENDERING
// ============================================================================

function updateSeasonSummary() {
    const summary = document.getElementById('seasonSummary');
    if (!summary) return;

    const state = SeasonBuilderState;
    const isPubLeague = state.leagueType === 'Pub League';

    // Format date
    let formattedDate = 'Not set';
    if (state.seasonStartDate) {
        const dateObj = new Date(state.seasonStartDate + 'T00:00:00');
        formattedDate = dateObj.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    }

    // Teams info
    let teamsInfo = isPubLeague
        ? `Premier: ${state.premierTeams}, Classic: ${state.classicTeams}`
        : `${state.ecsFcTeams} teams`;

    // Schedule breakdown
    let scheduleBreakdown = '';
    if (isPubLeague) {
        const premierTypes = countWeekTypes(state.premierWeekConfigs);
        const classicTypes = countWeekTypes(state.classicWeekConfigs);

        scheduleBreakdown = `
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                    <p class="font-medium text-gray-900 dark:text-white mb-2">Premier (${state.premierWeekConfigs.length} weeks)</p>
                    <div class="flex flex-wrap gap-1">
                        ${Object.entries(premierTypes).map(([type, count]) => {
                            const style = weekTypeStyles[type];
                            return `<span class="px-2 py-0.5 text-xs rounded ${style.bg} ${style.text}">${count} ${type}</span>`;
                        }).join('')}
                    </div>
                </div>
                <div>
                    <p class="font-medium text-gray-900 dark:text-white mb-2">Classic (${state.classicWeekConfigs.length} weeks)</p>
                    <div class="flex flex-wrap gap-1">
                        ${Object.entries(classicTypes).map(([type, count]) => {
                            const style = weekTypeStyles[type];
                            return `<span class="px-2 py-0.5 text-xs rounded ${style.bg} ${style.text}">${count} ${type}</span>`;
                        }).join('')}
                    </div>
                </div>
            </div>
        `;
    } else {
        const ecsFcTypes = countWeekTypes(state.ecsFcWeekConfigs);
        scheduleBreakdown = `
            <p class="font-medium text-gray-900 dark:text-white mb-2">ECS FC (${state.ecsFcWeekConfigs.length} weeks)</p>
            <div class="flex flex-wrap gap-1">
                ${Object.entries(ecsFcTypes).map(([type, count]) => {
                    const style = weekTypeStyles[type];
                    return `<span class="px-2 py-0.5 text-xs rounded ${style.bg} ${style.text}">${count} ${type}</span>`;
                }).join('')}
            </div>
        `;
    }

    summary.innerHTML = `
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div class="bg-ecs-green/5 border border-ecs-green/20 rounded-xl p-5">
                <h5 class="font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                    <i class="ti ti-file-description text-ecs-green"></i> Season Details
                </h5>
                <div class="space-y-3 text-sm">
                    <div class="flex justify-between">
                        <span class="text-gray-500 dark:text-gray-400">Name:</span>
                        <span class="font-medium text-gray-900 dark:text-white">${state.seasonName || 'Not set'}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500 dark:text-gray-400">Type:</span>
                        <span class="font-medium text-gray-900 dark:text-white">${state.leagueType}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500 dark:text-gray-400">Start Date:</span>
                        <span class="font-medium text-gray-900 dark:text-white">${formattedDate}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500 dark:text-gray-400">Set as Current:</span>
                        <span class="font-medium ${state.setAsCurrent ? 'text-green-600' : 'text-gray-500'}">${state.setAsCurrent ? 'Yes' : 'No'}</span>
                    </div>
                </div>
            </div>
            <div class="bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl p-5">
                <h5 class="font-semibold text-gray-900 dark:text-white mb-4 flex items-center gap-2">
                    <i class="ti ti-users text-blue-500"></i> Teams & Fields
                </h5>
                <div class="space-y-3 text-sm">
                    <div class="flex justify-between">
                        <span class="text-gray-500 dark:text-gray-400">Teams:</span>
                        <span class="font-medium text-gray-900 dark:text-white">${teamsInfo}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500 dark:text-gray-400">Fields:</span>
                        <span class="font-medium text-gray-900 dark:text-white">${state.fields.join(', ')}</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500 dark:text-gray-400">Match Duration:</span>
                        <span class="font-medium text-gray-900 dark:text-white">${state.matchDuration} min</span>
                    </div>
                    <div class="flex justify-between">
                        <span class="text-gray-500 dark:text-gray-400">Time Rotation:</span>
                        <span class="font-medium text-gray-900 dark:text-white">${state.enableTimeRotation ? 'Enabled' : 'Disabled'}</span>
                    </div>
                </div>
            </div>
        </div>
        <div class="mt-4 bg-yellow-50 dark:bg-yellow-900/20 border border-yellow-200 dark:border-yellow-800 rounded-xl p-5">
            <h5 class="font-semibold text-gray-900 dark:text-white mb-3 flex items-center gap-2">
                <i class="ti ti-calendar-week text-yellow-500"></i> Schedule Breakdown
            </h5>
            ${scheduleBreakdown}
        </div>
    `;
}

function countWeekTypes(configs) {
    const counts = {};
    configs.forEach(c => {
        counts[c.type] = (counts[c.type] || 0) + 1;
    });
    return counts;
}

function updateDiscordPreview() {
    const preview = document.getElementById('discordPreview');
    if (!preview) return;

    const state = SeasonBuilderState;
    const isPubLeague = state.leagueType === 'Pub League';

    let channels = [];
    let roles = [];

    if (isPubLeague) {
        // Classic teams FIRST (A, B, C, D)
        for (let i = 0; i < state.classicTeams; i++) {
            const letter = String.fromCharCode(65 + i);
            channels.push(`#classic-team-${letter.toLowerCase()}`);
            roles.push(`Classic Team ${letter}`);
        }
        // Premier teams SECOND (E, F, G, H, etc. - continuing from Classic)
        for (let i = 0; i < state.premierTeams; i++) {
            const letter = String.fromCharCode(65 + state.classicTeams + i);
            channels.push(`#premier-team-${letter.toLowerCase()}`);
            roles.push(`Premier Team ${letter}`);
        }
    } else {
        for (let i = 0; i < state.ecsFcTeams; i++) {
            const letter = String.fromCharCode(65 + i);
            channels.push(`#ecs-fc-team-${letter.toLowerCase()}`);
            roles.push(`ECS FC Team ${letter}`);
        }
    }

    preview.innerHTML = `
        <div>
            <h6 class="font-medium text-gray-700 dark:text-gray-300 mb-2"><i class="ti ti-hash"></i> Channels (${channels.length})</h6>
            <div class="text-sm text-gray-500 dark:text-gray-400 space-y-1 max-h-32 overflow-y-auto">
                ${channels.map(c => `<div class="font-mono">${c}</div>`).join('')}
            </div>
        </div>
        <div>
            <h6 class="font-medium text-gray-700 dark:text-gray-300 mb-2"><i class="ti ti-at"></i> Roles (${roles.length * 2})</h6>
            <div class="text-sm text-gray-500 dark:text-gray-400 space-y-1 max-h-32 overflow-y-auto">
                ${roles.map(r => `<div>${r} (Player + Coach)</div>`).join('')}
            </div>
        </div>
    `;
}

// ============================================================================
// VALIDATION
// ============================================================================

function validateStep(step) {
    const state = SeasonBuilderState;

    switch (step) {
        case 1: // Basics
            if (!state.seasonName || state.seasonName.trim().length < 3) {
                showValidationError('Please enter a season name (at least 3 characters)');
                return false;
            }
            if (!state.leagueType) {
                showValidationError('Please select a league type');
                return false;
            }
            return true;

        case 2: // Teams
            // Team counts have valid defaults
            return true;

        case 3: // Schedule (date + week types combined)
            // Validate date first
            if (!state.seasonStartDate) {
                showValidationError('Please select a season start date');
                return false;
            }
            const selectedDate = new Date(state.seasonStartDate + 'T00:00:00');
            if (selectedDate.getDay() !== 0) {
                showValidationError('Season start date must be a Sunday');
                return false;
            }

            // Validate week configs
            const isPubLeague = state.leagueType === 'Pub League';
            if (isPubLeague) {
                if (state.premierWeekConfigs.length < 4) {
                    showValidationError('Premier division needs at least 4 weeks');
                    return false;
                }
                if (state.classicWeekConfigs.length < 4) {
                    showValidationError('Classic division needs at least 4 weeks');
                    return false;
                }
                // Check both divisions have the same number of weeks
                if (state.premierWeekConfigs.length !== state.classicWeekConfigs.length) {
                    showValidationError('Premier and Classic must have the same number of weeks');
                    return false;
                }
                // Check shared weeks (TST, BYE, FUN) are on the same week for both divisions
                for (let i = 0; i < state.premierWeekConfigs.length; i++) {
                    const premierType = state.premierWeekConfigs[i].type;
                    const classicType = state.classicWeekConfigs[i].type;
                    // TST, BYE, FUN must match
                    if (['TST', 'BYE', 'FUN'].includes(premierType) || ['TST', 'BYE', 'FUN'].includes(classicType)) {
                        if (premierType !== classicType) {
                            showValidationError(`Week ${i + 1}: TST, BYE, and FUN weeks must be the same for both divisions`);
                            return false;
                        }
                    }
                }
            } else {
                if (state.ecsFcWeekConfigs.length < 4) {
                    showValidationError('Season needs at least 4 weeks');
                    return false;
                }
            }
            return true;

        case 4: // Time & Fields
            if (state.fields.length < 2) {
                showValidationError('Please configure at least 2 fields');
                return false;
            }
            return true;

        case 5: // Review - Final validation
            // Verify all previous steps
            return validateStep(1) && validateStep(2) && validateStep(3) && validateStep(4);

        default:
            return true;
    }
}

// ============================================================================
// WIZARD NAVIGATION
// ============================================================================

function updateWizardUI() {
    const state = SeasonBuilderState;

    // Update progress bar
    const progressBar = document.getElementById('progressBar');
    if (progressBar) {
        const progress = (state.currentStep / state.totalSteps) * 100;
        progressBar.style.width = `${progress}%`;
    }

    // Update step counter
    const stepCounter = document.getElementById('stepCounter');
    if (stepCounter) {
        stepCounter.textContent = `Step ${state.currentStep}`;
    }

    // Update step indicators (5 steps: Basics, Teams, Schedule, Time&Fields, Review)
    const stepIcons = ['ti-file-description', 'ti-users', 'ti-list-tree', 'ti-clock', 'ti-check'];
    document.querySelectorAll('.wizard-step-label').forEach((label) => {
        const step = parseInt(label.dataset.step);
        const dot = label.querySelector('.wizard-step-dot');
        const text = label.querySelector('span:last-child');

        if (!dot || !text) return;

        if (step < state.currentStep) {
            // Completed step
            dot.className = 'wizard-step-dot w-8 h-8 mx-auto mb-1 rounded-full bg-ecs-green text-white flex items-center justify-center text-sm font-medium transition-all';
            dot.innerHTML = '<i class="ti ti-check text-sm"></i>';
            text.className = 'text-xs font-medium text-ecs-green';
        } else if (step === state.currentStep) {
            // Current step
            dot.className = 'wizard-step-dot w-8 h-8 mx-auto mb-1 rounded-full bg-ecs-green text-white flex items-center justify-center text-sm font-medium transition-all';
            dot.innerHTML = `<i class="ti ${stepIcons[step - 1]} text-sm"></i>`;
            text.className = 'text-xs font-medium text-ecs-green';
        } else {
            // Future step
            dot.className = 'wizard-step-dot w-8 h-8 mx-auto mb-1 rounded-full bg-gray-300 dark:bg-gray-600 text-gray-600 dark:text-gray-400 flex items-center justify-center text-sm font-medium transition-all';
            dot.innerHTML = `<i class="ti ${stepIcons[step - 1]} text-sm"></i>`;
            text.className = 'text-xs text-gray-500 dark:text-gray-400';
        }
    });

    // Show/hide steps
    document.querySelectorAll('.wizard-step').forEach((stepEl) => {
        const stepNum = parseInt(stepEl.dataset.step);
        stepEl.classList.toggle('hidden', stepNum !== state.currentStep);
    });

    // Update navigation buttons
    const prevBtn = document.getElementById('prevStepBtn');
    const nextBtn = document.getElementById('nextStepBtn');
    const createBtn = document.getElementById('createSeasonBtn');

    if (prevBtn) prevBtn.classList.toggle('invisible', state.currentStep === 1);
    if (nextBtn) nextBtn.classList.toggle('hidden', state.currentStep === state.totalSteps);
    if (createBtn) createBtn.classList.toggle('hidden', state.currentStep !== state.totalSteps);

    // Step-specific updates (5 steps: 1-Basics, 2-Teams, 3-Schedule, 4-Time&Fields, 5-Review)

    if (state.currentStep === 3) {
        // Step 3: Schedule (combined date picker + week builders)
        const isPubLeague = state.leagueType === 'Pub League';
        const pubLeagueBuilders = document.getElementById('pubLeagueWeekBuilders');
        const ecsFcBuilder = document.getElementById('ecsFcWeekBuilder');

        if (pubLeagueBuilders) pubLeagueBuilders.classList.toggle('hidden', !isPubLeague);
        if (ecsFcBuilder) ecsFcBuilder.classList.toggle('hidden', isPubLeague);

        // Render week builders with actual dates (if date is set)
        if (isPubLeague) {
            renderWeekBuilderWithDates('premier', state.premierWeekConfigs);
            renderWeekBuilderWithDates('classic', state.classicWeekConfigs);
        } else {
            renderWeekBuilderWithDates('ecs_fc', state.ecsFcWeekConfigs);
        }

        // Update calendar preview
        updateCalendarPreview();
    }

    if (state.currentStep === 5) {
        // Step 5: Review
        updateSeasonSummary();
        updateDiscordPreview();
    }
}

function syncStateFromDOM() {
    const state = SeasonBuilderState;

    // Step 1
    const seasonNameInput = document.getElementById('seasonName');
    if (seasonNameInput) state.seasonName = seasonNameInput.value.trim();

    const leagueTypeInput = document.querySelector('input[name="leagueType"]:checked');
    if (leagueTypeInput) state.leagueType = leagueTypeInput.value;

    const setAsCurrentInput = document.getElementById('setAsCurrent');
    if (setAsCurrentInput) state.setAsCurrent = setAsCurrentInput.checked;

    // Step 2
    const premierTeamsInput = document.getElementById('premierTeamCount');
    if (premierTeamsInput) state.premierTeams = parseInt(premierTeamsInput.value);

    const classicTeamsInput = document.getElementById('classicTeamCount');
    if (classicTeamsInput) state.classicTeams = parseInt(classicTeamsInput.value);

    const ecsFcTeamsInput = document.getElementById('ecsFcTeamCount');
    if (ecsFcTeamsInput) state.ecsFcTeams = parseInt(ecsFcTeamsInput.value);

    // Step 4
    const premierStartTimeInput = document.getElementById('premierStartTime');
    if (premierStartTimeInput) state.premierStartTime = premierStartTimeInput.value;

    const classicStartTimeInput = document.getElementById('classicStartTime');
    if (classicStartTimeInput) state.classicStartTime = classicStartTimeInput.value;

    const matchDurationInput = document.getElementById('matchDuration');
    if (matchDurationInput) state.matchDuration = parseInt(matchDurationInput.value);

    const breakDurationInput = document.getElementById('breakDuration');
    if (breakDurationInput) state.breakDuration = parseInt(breakDurationInput.value);

    const enableTimeRotationInput = document.getElementById('enableTimeRotation');
    if (enableTimeRotationInput) state.enableTimeRotation = enableTimeRotationInput.checked;

    // Fields
    const fieldInputs = document.querySelectorAll('.field-name-input');
    state.fields = Array.from(fieldInputs).map(i => i.value.trim()).filter(v => v);

    // Step 5
    const startDateInput = document.getElementById('seasonStartDate');
    if (startDateInput) state.seasonStartDate = startDateInput.value;
}

// ============================================================================
// EVENT HANDLERS
// ============================================================================

// Navigation
window.EventDelegation.register('sb-next-step', function(element, e) {
    console.log('[SeasonBuilder] sb-next-step clicked');
    e.preventDefault();
    syncStateFromDOM();
    console.log('[SeasonBuilder] Current step:', SeasonBuilderState.currentStep, 'State:', SeasonBuilderState);

    if (validateStep(SeasonBuilderState.currentStep)) {
        console.log('[SeasonBuilder] Validation passed, advancing step');
        if (SeasonBuilderState.currentStep < SeasonBuilderState.totalSteps) {
            SeasonBuilderState.currentStep++;
            updateWizardUI();
        }
    } else {
        console.log('[SeasonBuilder] Validation failed');
    }
});

console.log('[SeasonBuilder] sb-next-step handler registered');

window.EventDelegation.register('sb-prev-step', function(element, e) {
    e.preventDefault();
    syncStateFromDOM();

    if (SeasonBuilderState.currentStep > 1) {
        SeasonBuilderState.currentStep--;
        updateWizardUI();
    }
});

window.EventDelegation.register('sb-go-to-step', function(element, e) {
    e.preventDefault();
    const targetStep = parseInt(element.dataset.step);

    if (targetStep && targetStep >= 1 && targetStep <= SeasonBuilderState.totalSteps) {
        // Only allow going to previous steps or the next step after current
        if (targetStep <= SeasonBuilderState.currentStep || targetStep === SeasonBuilderState.currentStep + 1) {
            syncStateFromDOM();
            if (targetStep > SeasonBuilderState.currentStep && !validateStep(SeasonBuilderState.currentStep)) {
                return;
            }
            SeasonBuilderState.currentStep = targetStep;
            updateWizardUI();
        }
    }
});

// Step 1: League Type Selection
window.EventDelegation.register('sb-select-league-type', function(element, e) {
    const value = element.dataset.value;
    if (!value) return;

    // Update visual selection
    document.querySelectorAll('.league-type-option').forEach(opt => {
        opt.classList.remove('border-ecs-green', 'border-blue-500', 'bg-ecs-green/5', 'bg-blue-50', 'dark:bg-blue-900/20');
        opt.classList.add('border-gray-200', 'dark:border-gray-600');
        opt.querySelector('.check-icon')?.classList.add('hidden');
    });

    const radioInput = element.querySelector('input[type="radio"]');
    if (radioInput) radioInput.checked = true;
    element.querySelector('.check-icon')?.classList.remove('hidden');

    if (value === 'Pub League') {
        element.classList.add('border-ecs-green', 'bg-ecs-green/5');
    } else {
        element.classList.add('border-blue-500', 'bg-blue-50', 'dark:bg-blue-900/20');
    }
    element.classList.remove('border-gray-200', 'dark:border-gray-600');

    // Update state
    SeasonBuilderState.leagueType = value;

    // Update teams section visibility
    const pubLeagueTeamsSection = document.getElementById('pubLeagueTeamsSection');
    const ecsFcTeamsSection = document.getElementById('ecsFcTeamsSection');

    if (value === 'Pub League') {
        pubLeagueTeamsSection?.classList.remove('hidden');
        ecsFcTeamsSection?.classList.add('hidden');
    } else {
        pubLeagueTeamsSection?.classList.add('hidden');
        ecsFcTeamsSection?.classList.remove('hidden');
    }
});

// Step 3: Week Management
window.EventDelegation.register('sb-add-week', function(element, e) {
    e.preventDefault();
    const division = element.dataset.division;
    const configs = getWeekConfigs(division);

    // Add default week type based on division
    const defaultType = division === 'classic' ? 'REGULAR' : 'REGULAR';
    configs.push({ type: defaultType });

    renderWeekBuilderWithDates(division, configs);
    updateCalendarPreview(); // Update preview in real-time
});

window.EventDelegation.register('sb-remove-week', function(element, e) {
    e.preventDefault();
    const division = element.dataset.division;
    const weekIndex = parseInt(element.dataset.weekIndex);

    const configs = getWeekConfigs(division);
    if (configs.length > 1) {
        configs.splice(weekIndex, 1);
        renderWeekBuilderWithDates(division, configs);
        updateCalendarPreview(); // Update preview in real-time
    } else {
        showToast('Cannot remove the last week', 'warning');
    }
});

window.EventDelegation.register('sb-change-week-type', function(element, e) {
    updateWeekBadge(element);
    updateCalendarPreview(); // Update preview in real-time
});

window.EventDelegation.register('sb-apply-template', function(element, e) {
    e.preventDefault();
    const division = element.dataset.division;
    const templateName = element.dataset.template;

    const divisionTemplates = weekTemplates[division];
    if (!divisionTemplates || !divisionTemplates[templateName]) {
        showToast('Template not found', 'error');
        return;
    }

    const templateConfigs = divisionTemplates[templateName].map(c => ({ ...c }));
    setWeekConfigs(division, templateConfigs);
    renderWeekBuilderWithDates(division, templateConfigs);
    updateCalendarPreview(); // Update preview in real-time
    showToast(`Applied ${templateName} template to ${division}`, 'success');
});

// Step 4: Field Management
window.EventDelegation.register('sb-add-field', function(element, e) {
    e.preventDefault();
    const container = document.getElementById('fieldConfigurations');
    if (!container) return;

    const fieldItem = document.createElement('div');
    fieldItem.className = 'field-item flex items-center gap-3';
    fieldItem.innerHTML = `
        <input type="text" class="field-name-input flex-1 rounded-lg border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white" placeholder="Field name">
        <button type="button" class="remove-field-btn p-2 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg" data-action="sb-remove-field">
            <i class="ti ti-x"></i>
        </button>
    `;
    container.appendChild(fieldItem);
    updateFieldRemoveButtons();
});

window.EventDelegation.register('sb-remove-field', function(element, e) {
    e.preventDefault();
    const fieldItem = element.closest('.field-item');
    if (fieldItem) {
        fieldItem.remove();
        updateFieldRemoveButtons();
    }
});

function updateFieldRemoveButtons() {
    const items = document.querySelectorAll('.field-item');
    items.forEach(item => {
        const btn = item.querySelector('.remove-field-btn');
        if (btn) btn.disabled = items.length <= 2;
    });
}

// Step 3: Date Selection (combined with Schedule step)
window.EventDelegation.register('sb-change-start-date', function(element, e) {
    SeasonBuilderState.seasonStartDate = element.value;

    // Re-render week builders with new dates
    const isPubLeague = SeasonBuilderState.leagueType === 'Pub League';
    if (isPubLeague) {
        renderWeekBuilderWithDates('premier', SeasonBuilderState.premierWeekConfigs);
        renderWeekBuilderWithDates('classic', SeasonBuilderState.classicWeekConfigs);
    } else {
        renderWeekBuilderWithDates('ecs_fc', SeasonBuilderState.ecsFcWeekConfigs);
    }

    updateCalendarPreview();
});

// Step 5: Create Season
window.EventDelegation.register('sb-create-season', async function(element, e) {
    e.preventDefault();
    syncStateFromDOM();

    if (!validateStep(5)) return;

    const state = SeasonBuilderState;
    const isPubLeague = state.leagueType === 'Pub League';

    // Build payload
    const payload = {
        season_name: state.seasonName,
        league_type: state.leagueType,
        set_as_current: state.setAsCurrent,
        season_start_date: state.seasonStartDate,

        premier_teams: state.premierTeams,
        classic_teams: state.classicTeams,
        ecs_fc_teams: state.ecsFcTeams,

        premier_start_time: state.premierStartTime,
        classic_start_time: state.classicStartTime,
        match_duration: state.matchDuration,
        break_duration: state.breakDuration,
        fields: state.fields,
        enable_time_rotation: state.enableTimeRotation
    };

    // Add division-specific week configs
    if (isPubLeague) {
        payload.premier_week_configs = state.premierWeekConfigs.map((c, i) => ({
            week_number: i + 1,
            type: c.type
        }));
        payload.classic_week_configs = state.classicWeekConfigs.map((c, i) => ({
            week_number: i + 1,
            type: c.type
        }));
    } else {
        payload.ecs_fc_week_configs = state.ecsFcWeekConfigs.map((c, i) => ({
            week_number: i + 1,
            type: c.type
        }));
    }

    // Show loading
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Creating Season...',
            html: '<p>Setting up teams, schedules, and Discord resources.</p><p class="text-sm text-gray-500 mt-2">This may take a moment.</p>',
            allowOutsideClick: false,
            allowEscapeKey: false,
            didOpen: () => window.Swal.showLoading(),
            background: isDark() ? '#1f2937' : '#ffffff',
            color: isDark() ? '#f3f4f6' : '#111827'
        });
    }

    try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content')
            || document.querySelector('input[name="csrf_token"]')?.value
            || '';

        const response = await fetch('/auto-schedule/create-season-wizard', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify(payload)
        });

        const result = await response.json();

        if (result.success) {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire({
                    icon: 'success',
                    title: 'Season Created!',
                    text: result.message || 'Your season has been created successfully.',
                    background: isDark() ? '#1f2937' : '#ffffff',
                    color: isDark() ? '#f3f4f6' : '#111827',
                    confirmButtonColor: '#1a472a'
                }).then(() => {
                    if (result.redirect_url) {
                        window.location.href = result.redirect_url;
                    } else {
                        window.location.reload();
                    }
                });
            } else {
                window.location.reload();
            }
        } else {
            throw new Error(result.error || result.message || 'Failed to create season');
        }
    } catch (error) {
        console.error('[sb-create-season] Error:', error);
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                icon: 'error',
                title: 'Error',
                text: error.message,
                background: isDark() ? '#1f2937' : '#ffffff',
                color: isDark() ? '#f3f4f6' : '#111827',
                confirmButtonColor: '#1a472a'
            });
        }
    }
});

// ============================================================================
// INITIALIZATION
// ============================================================================

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Check if we're on the season builder page
    const wizardSection = document.getElementById('createWizardSection');
    if (!wizardSection) return;

    console.log('[SeasonBuilder] Initializing wizard...');

    // Apply default templates if empty
    if (SeasonBuilderState.premierWeekConfigs.length === 0) {
        SeasonBuilderState.premierWeekConfigs = weekTemplates.premier.standard.map(c => ({ ...c }));
    }
    if (SeasonBuilderState.classicWeekConfigs.length === 0) {
        SeasonBuilderState.classicWeekConfigs = weekTemplates.classic.standard.map(c => ({ ...c }));
    }
    if (SeasonBuilderState.ecsFcWeekConfigs.length === 0) {
        SeasonBuilderState.ecsFcWeekConfigs = weekTemplates.ecs_fc.standard.map(c => ({ ...c }));
    }

    // Initial UI update
    updateWizardUI();

    console.log('[SeasonBuilder] Wizard initialized');
});

// Export for external access if needed
window.SeasonBuilderState = SeasonBuilderState;
window.SeasonBuilderHelpers = {
    updateWizardUI,
    syncStateFromDOM,
    renderWeekBuilder,
    updateCalendarPreview,
    updateSeasonSummary,
    validateStep
};

console.log('[EventDelegation] Season Builder handlers loaded');
