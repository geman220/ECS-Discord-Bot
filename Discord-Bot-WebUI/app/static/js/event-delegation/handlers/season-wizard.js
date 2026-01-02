import { EventDelegation } from '../core.js';

/**
 * Season/Schedule Wizard Action Handlers
 * Handles season creation and auto-scheduling
 */

// AUTO SCHEDULE WIZARD ACTIONS
// ============================================================================

/**
 * Start Season Wizard Action
 * Opens the season builder wizard modal
 */
window.EventDelegation.register('start-season-wizard', function(element, e) {
    e.preventDefault();

    if (typeof startSeasonWizard === 'function') {
        startSeasonWizard();
    } else {
        console.error('[start-season-wizard] startSeasonWizard function not found');
    }
});

/**
 * Show Existing Seasons Action
 * Displays the list of existing seasons
 */
window.EventDelegation.register('show-existing-seasons', function(element, e) {
    e.preventDefault();

    if (typeof showExistingSeasons === 'function') {
        showExistingSeasons();
    } else {
        console.error('[show-existing-seasons] showExistingSeasons function not found');
    }
});

/**
 * Show Main View Action
 * Returns to main season builder view
 */
window.EventDelegation.register('show-main-view', function(element, e) {
    e.preventDefault();

    if (typeof showMainView === 'function') {
        showMainView();
    } else {
        console.error('[show-main-view] showMainView function not found');
    }
});

/**
 * Next Step Action (Wizard Navigation)
 * Advances to the next step in the wizard
 */
window.EventDelegation.register('next-step', function(element, e) {
    e.preventDefault();

    if (typeof nextStep === 'function') {
        nextStep();
    } else {
        console.error('[next-step] nextStep function not found');
    }
});

/**
 * Previous Step Action (Wizard Navigation)
 * Goes back to the previous step in the wizard
 */
window.EventDelegation.register('previous-step', function(element, e) {
    e.preventDefault();

    if (typeof previousStep === 'function') {
        previousStep();
    } else {
        console.error('[previous-step] previousStep function not found');
    }
});

/**
 * Create Season Action
 * Submits the wizard and creates the season
 */
window.EventDelegation.register('create-season', function(element, e) {
    e.preventDefault();

    if (typeof createSeason === 'function') {
        createSeason();
    } else {
        console.error('[create-season] createSeason function not found');
    }
});

/**
 * Update Season Structure Action
 * Updates season breakdown based on total weeks selection
 */
window.EventDelegation.register('update-season-structure', function(element, e) {
    if (typeof updateSeasonStructure === 'function') {
        updateSeasonStructure();
    } else {
        console.error('[update-season-structure] updateSeasonStructure function not found');
    }
});

/**
 * Apply Wizard Template Action
 * Applies a configuration template (standard, classic-practice, custom)
 */
window.EventDelegation.register('apply-wizard-template', function(element, e) {
    e.preventDefault();

    const templateType = element.dataset.templateType;

    if (!templateType) {
        console.error('[apply-wizard-template] Missing template type');
        return;
    }

    if (typeof applyWizardTemplate === 'function') {
        applyWizardTemplate(templateType);
    } else {
        console.error('[apply-wizard-template] applyWizardTemplate function not found');
    }
});

/**
 * Add Wizard Field Action
 * Adds a new field configuration row in the wizard
 */
window.EventDelegation.register('add-wizard-field', function(element, e) {
    e.preventDefault();

    if (typeof addWizardField === 'function') {
        addWizardField();
    } else {
        console.error('[add-wizard-field] addWizardField function not found');
    }
});

/**
 * Remove Wizard Field Action
 * Removes a field configuration row from the wizard
 */
window.EventDelegation.register('remove-wizard-field', function(element, e) {
    e.preventDefault();

    if (typeof removeWizardField === 'function') {
        removeWizardField(element);
    } else {
        console.error('[remove-wizard-field] removeWizardField function not found');
    }
});

/**
 * Set Active Season Action
 * Sets a season as the current active season
 */
window.EventDelegation.register('set-active-season', function(element, e) {
    e.preventDefault();

    const seasonId = element.dataset.seasonId;
    const seasonType = element.dataset.seasonType;

    if (!seasonId || !seasonType) {
        console.error('[set-active-season] Missing season ID or type');
        return;
    }

    if (typeof setActiveSeason === 'function') {
        setActiveSeason(seasonId, seasonType);
    } else {
        console.error('[set-active-season] setActiveSeason function not found');
    }
});

/**
 * Confirm Delete Season Action
 * Shows confirmation dialog before deleting a season
 */
window.EventDelegation.register('confirm-delete-season', function(element, e) {
    e.preventDefault();

    const seasonId = element.dataset.seasonId;
    const seasonName = element.dataset.seasonName;

    if (!seasonId || !seasonName) {
        console.error('[confirm-delete-season] Missing season ID or name');
        return;
    }

    if (typeof confirmDeleteSeason === 'function') {
        confirmDeleteSeason(seasonId, seasonName);
    } else {
        console.error('[confirm-delete-season] confirmDeleteSeason function not found');
    }
});

/**
 * Recreate Discord Resources Action
 * Recreates Discord channels and roles for a season
 */
window.EventDelegation.register('recreate-discord-resources', function(element, e) {
    e.preventDefault();

    const seasonId = element.dataset.seasonId;
    const seasonName = element.dataset.seasonName;

    if (!seasonId || !seasonName) {
        console.error('[recreate-discord-resources] Missing season ID or name');
        return;
    }

    if (typeof recreateDiscordResources === 'function') {
        recreateDiscordResources(seasonId, seasonName);
    } else {
        console.error('[recreate-discord-resources] recreateDiscordResources function not found');
    }
});

/**
 * Toggle Settings Action (Schedule Preview)
 * Toggles visibility of schedule settings panel
 */
window.EventDelegation.register('toggle-settings', function(element, e) {
    e.preventDefault();

    if (typeof toggleScheduleSettings === 'function') {
        toggleScheduleSettings();
    } else {
        console.error('[toggle-settings] toggleScheduleSettings function not found');
    }
});

/**
 * Delete Schedule Action (Schedule Preview)
 * Deletes the generated schedule
 */
window.EventDelegation.register('delete-schedule', function(element, e) {
    e.preventDefault();

    if (typeof deleteSchedule === 'function') {
        deleteSchedule();
    } else {
        console.error('[delete-schedule] deleteSchedule function not found');
    }
});

/**
 * Commit Schedule Action (Schedule Preview)
 * Commits the schedule and creates matches
 */
window.EventDelegation.register('commit-schedule', function(element, e) {
    e.preventDefault();

    if (typeof commitSchedule === 'function') {
        commitSchedule();
    } else {
        console.error('[commit-schedule] commitSchedule function not found');
    }
});

/**
 * Select for Swap Action (Schedule Preview)
 * Selects a match for team swapping
 */
window.EventDelegation.register('select-for-swap', function(element, e) {
    e.preventDefault();

    const matchId = parseInt(element.dataset.matchId);
    const matchDesc = element.dataset.matchDesc;

    if (!matchId || !matchDesc) {
        console.error('[select-for-swap] Missing match ID or description');
        return;
    }

    if (typeof selectForSwap === 'function') {
        selectForSwap(matchId, matchDesc);
    } else {
        console.error('[select-for-swap] selectForSwap function not found');
    }
});

/**
 * Execute Swap Action (Schedule Preview)
 * Executes the team swap
 */
window.EventDelegation.register('execute-swap', function(element, e) {
    e.preventDefault();

    if (typeof executeSwap === 'function') {
        executeSwap();
    } else {
        console.error('[execute-swap] executeSwap function not found');
    }
});

/**
 * Remove from Swap Action (Schedule Preview)
 * Removes a match from swap selection
 */
window.EventDelegation.register('remove-from-swap', function(element, e) {
    e.preventDefault();

    const swapIndex = parseInt(element.dataset.swapIndex);

    if (swapIndex === undefined || swapIndex === null) {
        console.error('[remove-from-swap] Missing swap index');
        return;
    }

    if (typeof removeFromSwap === 'function') {
        removeFromSwap(swapIndex);
    } else {
        console.error('[remove-from-swap] removeFromSwap function not found');
    }
});

/**
 * Remove Field Action (Config Page)
 * Removes a field from the configuration
 */
window.EventDelegation.register('remove-field', function(element, e) {
    e.preventDefault();

    if (typeof removeField === 'function') {
        removeField(element);
    } else {
        console.error('[remove-field] removeField function not found');
    }
});

/**
 * Add Config Field Action (Config Page)
 * Adds a new field to the configuration
 */
window.EventDelegation.register('add-config-field', function(element, e) {
    e.preventDefault();

    if (typeof addField === 'function') {
        addField();
    } else {
        console.error('[add-config-field] addField function not found');
    }
});

/**
 * Apply Template Action (Config Page)
 * Applies a configuration template
 */
window.EventDelegation.register('apply-template', function(element, e) {
    e.preventDefault();

    const template = element.dataset.template;

    if (!template) {
        console.error('[apply-template] Missing template type');
        return;
    }

    if (typeof applyTemplate === 'function') {
        applyTemplate(template);
    } else {
        console.error('[apply-template] applyTemplate function not found');
    }
});

/**
 * Add Week Config Action (Config Page)
 * Adds a new week configuration
 */
window.EventDelegation.register('add-week-config', function(element, e) {
    e.preventDefault();

    if (typeof addWeekConfig === 'function') {
        addWeekConfig();
    } else {
        console.error('[add-week-config] addWeekConfig function not found');
    }
});

/**
 * Generate Default Weeks Action (Config Page)
 * Auto-generates default week configuration
 */
window.EventDelegation.register('generate-default-weeks', function(element, e) {
    e.preventDefault();

    if (typeof generateDefaultWeeks === 'function') {
        generateDefaultWeeks();
    } else {
        console.error('[generate-default-weeks] generateDefaultWeeks function not found');
    }
});

/**
 * Clear Weeks Action (Config Page)
 * Clears all week configurations
 */
window.EventDelegation.register('clear-weeks', function(element, e) {
    e.preventDefault();

    if (typeof clearWeeks === 'function') {
        clearWeeks();
    } else {
        console.error('[clear-weeks] clearWeeks function not found');
    }
});

/**
 * Update Week Card Action (Config Page)
 * Updates week type when dropdown changes
 */
window.EventDelegation.register('update-week-card', function(element, e) {
    if (typeof updateWeekCard === 'function') {
        updateWeekCard(element);
    } else {
        console.error('[update-week-card] updateWeekCard function not found');
    }
});

/**
 * Remove Week Card Action (Config Page)
 * Removes a week configuration
 */
window.EventDelegation.register('remove-week-card', function(element, e) {
    e.preventDefault();

    if (typeof removeWeekCard === 'function') {
        removeWeekCard(element);
    } else {
        console.error('[remove-week-card] removeWeekCard function not found');
    }
});

/**
 * Close Toast Action
 * Closes/removes a toast notification
 */
window.EventDelegation.register('close-toast', function(element, e) {
    e.preventDefault();

    // Remove the toast (parent element)
    if (element.parentElement) {
        element.parentElement.remove();
    }
});

// ============================================================================

// Handlers loaded
