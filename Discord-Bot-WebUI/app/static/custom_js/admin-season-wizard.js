/**
 * Admin Season Wizard
 * Handles the season creation wizard functionality
 */
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

/**
 * Season Wizard Manager Class
 */
class AdminSeasonWizardManager {
    constructor() {
        this.currentStep = 0;
        this.totalSteps = 5;
        this.stepIcons = ['ti-file-description', 'ti-users-group', 'ti-calendar-event', 'ti-brand-discord', 'ti-check'];
        this.stepTitles = [
            'Step 1 of 5: Basic Information',
            'Step 2 of 5: Team Configuration',
            'Step 3 of 5: Schedule Configuration',
            'Step 4 of 5: Discord Preview',
            'Step 5 of 5: Review & Create'
        ];
        this.stepDescriptions = [
            'Select the league type and name your season',
            'Configure the teams for this season',
            'Set up the schedule structure',
            'Preview Discord channels and roles to be created',
            'Review your configuration before creating'
        ];
    }

    /**
     * Initialize the wizard
     */
    init() {
        this.setupStepNavigation();
        this.setupNavigationButtons();
        this.setupLeagueTypeChange();
        this.setupSetAsCurrentCheckbox();
        this.setupCustomNamesToggles();
        this.initFromUrlParams();
        this.updateUI();
    }

    /**
     * Setup step navigation clicks
     */
    setupStepNavigation() {
        document.querySelectorAll('.js-goto-step').forEach(btn => {
            btn.addEventListener('click', () => {
                const step = parseInt(btn.dataset.step);
                this.goToStep(step);
            });
        });
    }

    /**
     * Setup navigation buttons
     */
    setupNavigationButtons() {
        document.querySelectorAll('.js-wizard-prev').forEach(btn => {
            btn.addEventListener('click', () => this.wizardPrev());
        });

        document.querySelectorAll('.js-wizard-next').forEach(btn => {
            btn.addEventListener('click', () => this.wizardNext());
        });

        document.querySelectorAll('.js-create-season').forEach(btn => {
            btn.addEventListener('click', () => this.createSeason());
        });
    }

    /**
     * Setup league type change handler
     */
    setupLeagueTypeChange() {
        document.querySelectorAll('input[name="league_type"]').forEach(radio => {
            radio.addEventListener('change', () => this.handleLeagueTypeChange());
        });
    }

    /**
     * Setup set as current checkbox handler
     */
    setupSetAsCurrentCheckbox() {
        const setAsCurrent = document.getElementById('setAsCurrent');
        if (setAsCurrent) {
            setAsCurrent.addEventListener('change', function() {
                const rolloverWarning = document.getElementById('rolloverWarning');
                if (rolloverWarning) {
                    rolloverWarning.classList.toggle('u-hidden', !this.checked);
                }
            });
        }
    }

    /**
     * Setup custom names toggle handlers
     */
    setupCustomNamesToggles() {
        const premierCustomNames = document.getElementById('premierCustomNames');
        if (premierCustomNames) {
            premierCustomNames.addEventListener('change', function() {
                const div = document.getElementById('premierCustomNamesDiv');
                if (div) div.classList.toggle('u-hidden', !this.checked);
            });
        }

        const classicCustomNames = document.getElementById('classicCustomNames');
        if (classicCustomNames) {
            classicCustomNames.addEventListener('change', function() {
                const div = document.getElementById('classicCustomNamesDiv');
                if (div) div.classList.toggle('u-hidden', !this.checked);
            });
        }

        const ecsFcCustomNames = document.getElementById('ecsFcCustomNames');
        if (ecsFcCustomNames) {
            ecsFcCustomNames.addEventListener('change', function() {
                const div = document.getElementById('ecsFcCustomNamesDiv');
                if (div) div.classList.toggle('u-hidden', !this.checked);
            });
        }
    }

    /**
     * Initialize from URL parameters
     */
    initFromUrlParams() {
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('type') === 'ecs_fc') {
            const typeEcsFc = document.getElementById('typeEcsFc');
            if (typeEcsFc) {
                typeEcsFc.checked = true;
                this.handleLeagueTypeChange();
            }
        }
    }

    /**
     * Handle league type change
     */
    handleLeagueTypeChange() {
        const typePubLeague = document.getElementById('typePubLeague');
        const isPubLeague = typePubLeague ? typePubLeague.checked : true;

        const pubLeagueTeams = document.getElementById('pubLeagueTeams');
        const ecsFcTeams = document.getElementById('ecsFcTeams');
        const specialWeeksSection = document.getElementById('specialWeeksSection');

        if (pubLeagueTeams) pubLeagueTeams.classList.toggle('u-hidden', !isPubLeague);
        if (ecsFcTeams) ecsFcTeams.classList.toggle('u-hidden', isPubLeague);
        if (specialWeeksSection) specialWeeksSection.classList.toggle('u-hidden', !isPubLeague);
    }

    /**
     * Update the UI to reflect current step
     */
    updateUI() {
        // Update step indicators
        for (let i = 0; i < this.totalSteps; i++) {
            const stepEl = document.getElementById(`wizardStep${i}`);
            if (!stepEl) continue;

            const circle = stepEl.querySelector('.c-wizard__step-circle');

            stepEl.classList.remove('c-wizard__step--active', 'c-wizard__step--done', 'c-wizard__step--pending');

            if (i < this.currentStep) {
                stepEl.classList.add('c-wizard__step--done');
                if (circle) circle.innerHTML = '<i class="ti ti-check"></i>';
            } else if (i === this.currentStep) {
                stepEl.classList.add('c-wizard__step--active');
                if (circle) circle.innerHTML = `<i class="ti ${this.stepIcons[i]}"></i>`;
            } else {
                stepEl.classList.add('c-wizard__step--pending');
                if (circle) circle.innerHTML = `<i class="ti ${this.stepIcons[i]}"></i>`;
            }
        }

        // Update step content visibility
        for (let i = 0; i < this.totalSteps; i++) {
            const content = document.getElementById(`step-${i}`);
            if (content) {
                content.classList.toggle('c-wizard__panel--active', i === this.currentStep);
            }
        }

        // Update header info
        const stepIcon = document.getElementById('stepIcon');
        const stepTitle = document.getElementById('stepTitle');
        const stepDescription = document.getElementById('stepDescription');

        if (stepIcon) stepIcon.className = `ti ${this.stepIcons[this.currentStep]} c-wizard__info-icon`;
        if (stepTitle) stepTitle.textContent = this.stepTitles[this.currentStep];
        if (stepDescription) stepDescription.textContent = this.stepDescriptions[this.currentStep];

        // Update navigation buttons
        const prevBtn = document.getElementById('prevBtn');
        const nextBtn = document.getElementById('nextBtn');
        const createBtn = document.getElementById('createBtn');

        if (prevBtn) prevBtn.classList.toggle('u-hidden', this.currentStep === 0);
        if (nextBtn) nextBtn.classList.toggle('u-hidden', this.currentStep === this.totalSteps - 1);
        if (createBtn) createBtn.classList.toggle('u-hidden', this.currentStep !== this.totalSteps - 1);
    }

    /**
     * Go to a specific step (only allows going backwards)
     * @param {number} step - Step number
     */
    goToStep(step) {
        if (step < this.currentStep) {
            this.currentStep = step;
            this.updateUI();
        }
    }

    /**
     * Go to next step
     */
    wizardNext() {
        if (!this.validateStep(this.currentStep)) return;

        if (this.currentStep < this.totalSteps - 1) {
            this.currentStep++;
            this.updateUI();

            // Special handling for Discord preview step
            if (this.currentStep === 3) {
                this.loadDiscordPreview();
            }

            // Special handling for review step
            if (this.currentStep === 4) {
                this.populateReview();
            }
        }
    }

    /**
     * Go to previous step
     */
    wizardPrev() {
        if (this.currentStep > 0) {
            this.currentStep--;
            this.updateUI();
        }
    }

    /**
     * Validate current step
     * @param {number} step - Step number
     * @returns {boolean} Whether step is valid
     */
    validateStep(step) {
        if (step === 0) {
            const seasonName = document.getElementById('seasonName')?.value?.trim();
            if (!seasonName) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast('Please enter a season name', 'warning');
                }
                return false;
            }
            if (seasonName.length < 3) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast('Season name must be at least 3 characters', 'warning');
                }
                return false;
            }
        }
        return true;
    }

    /**
     * Get wizard form data
     * @returns {Object} Form data
     */
    getWizardData() {
        const typePubLeague = document.getElementById('typePubLeague');
        const isPubLeague = typePubLeague ? typePubLeague.checked : true;

        const data = {
            league_type: isPubLeague ? 'Pub League' : 'ECS FC',
            season_name: document.getElementById('seasonName')?.value?.trim() || '',
            start_date: document.getElementById('startDate')?.value || '',
            set_as_current: document.getElementById('setAsCurrent')?.checked || false,
            skip_team_creation: document.getElementById('skipTeamCreation')?.checked || false,
            regular_weeks: parseInt(document.getElementById('regularWeeks')?.value) || 7,
            playoff_weeks: parseInt(document.getElementById('playoffWeeks')?.value) || 2
        };

        if (isPubLeague) {
            data.premier_team_count = parseInt(document.getElementById('premierTeamCount')?.value) || 8;
            data.classic_team_count = parseInt(document.getElementById('classicTeamCount')?.value) || 4;

            if (document.getElementById('premierCustomNames')?.checked) {
                data.premier_teams = (document.getElementById('premierTeamNames')?.value || '')
                    .split('\n')
                    .map(n => n.trim())
                    .filter(n => n.length > 0);
            }
            if (document.getElementById('classicCustomNames')?.checked) {
                data.classic_teams = (document.getElementById('classicTeamNames')?.value || '')
                    .split('\n')
                    .map(n => n.trim())
                    .filter(n => n.length > 0);
            }

            data.has_fun_week = document.getElementById('hasFunWeek')?.checked || false;
            data.has_tst_week = document.getElementById('hasTstWeek')?.checked || false;
            data.has_bonus_week = document.getElementById('hasBonusWeek')?.checked || false;
        } else {
            data.team_count = parseInt(document.getElementById('ecsFcTeamCount')?.value) || 8;
            if (document.getElementById('ecsFcCustomNames')?.checked) {
                data.teams = (document.getElementById('ecsFcTeamNames')?.value || '')
                    .split('\n')
                    .map(n => n.trim())
                    .filter(n => n.length > 0);
            }
        }

        return data;
    }

    /**
     * Load Discord preview
     */
    loadDiscordPreview() {
        const loadingEl = document.getElementById('discordPreviewLoading');
        const contentEl = document.getElementById('discordPreviewContent');

        if (loadingEl) loadingEl.classList.remove('u-hidden');
        if (contentEl) contentEl.classList.add('u-hidden');

        const data = this.getWizardData();
        const previewUrl = window.WIZARD_CONFIG?.previewDiscordUrl || '/admin-panel/league-management/season-wizard/preview-discord';

        fetch(previewUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (loadingEl) loadingEl.classList.add('u-hidden');
            if (contentEl) contentEl.classList.remove('u-hidden');

            if (result.success) {
                const preview = result.preview;

                // Populate categories
                const categoriesList = document.getElementById('previewCategories');
                if (categoriesList) {
                    categoriesList.innerHTML = preview.categories.map(c =>
                        `<li><i class="ti ti-folder text-warning me-1"></i>${c}</li>`
                    ).join('');
                }

                // Populate channels
                const channelsList = document.getElementById('previewChannels');
                if (channelsList) {
                    channelsList.innerHTML = preview.channels.map(c =>
                        `<li><i class="ti ti-hash text-primary me-1"></i>${c.name}</li>`
                    ).join('');
                }

                // Populate roles
                const rolesList = document.getElementById('previewRoles');
                if (rolesList) {
                    rolesList.innerHTML = preview.roles.map(r =>
                        `<li><i class="ti ti-shield text-success me-1"></i>${r}</li>`
                    ).join('');
                }

                const apiCallsEl = document.getElementById('estimatedApiCalls');
                if (apiCallsEl) apiCallsEl.textContent = preview.estimated_api_calls;
            }
        })
        .catch(error => {
            console.error('[AdminSeasonWizardManager] Error:', error);
            if (loadingEl) loadingEl.style.display = 'none';
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('Failed to load Discord preview', 'danger');
            }
        });
    }

    /**
     * Populate review step
     */
    populateReview() {
        const data = this.getWizardData();

        const reviewLeagueType = document.getElementById('reviewLeagueType');
        const reviewSeasonName = document.getElementById('reviewSeasonName');
        const reviewStartDate = document.getElementById('reviewStartDate');
        const reviewSetAsCurrent = document.getElementById('reviewSetAsCurrent');
        const reviewRegularWeeks = document.getElementById('reviewRegularWeeks');
        const reviewPlayoffWeeks = document.getElementById('reviewPlayoffWeeks');
        const reviewTeams = document.getElementById('reviewTeams');

        if (reviewLeagueType) reviewLeagueType.textContent = data.league_type;
        if (reviewSeasonName) reviewSeasonName.textContent = data.season_name;
        if (reviewStartDate) reviewStartDate.textContent = data.start_date || 'Not set';
        if (reviewSetAsCurrent) reviewSetAsCurrent.textContent = data.set_as_current ? 'Yes' : 'No';
        if (reviewRegularWeeks) reviewRegularWeeks.textContent = data.regular_weeks;
        if (reviewPlayoffWeeks) reviewPlayoffWeeks.textContent = data.playoff_weeks;

        // Teams summary
        let teamsHtml = '';
        if (data.skip_team_creation) {
            teamsHtml = '<p class="text-muted mb-0">Teams will be created manually later</p>';
        } else if (data.league_type === 'Pub League') {
            teamsHtml = `
                <p class="mb-1">Premier: <strong>${data.premier_teams ? data.premier_teams.length : data.premier_team_count}</strong> teams</p>
                <p class="mb-0">Classic: <strong>${data.classic_teams ? data.classic_teams.length : data.classic_team_count}</strong> teams</p>
            `;
        } else {
            teamsHtml = `<p class="mb-0">ECS FC: <strong>${data.teams ? data.teams.length : data.team_count}</strong> teams</p>`;
        }
        if (reviewTeams) reviewTeams.innerHTML = teamsHtml;
    }

    /**
     * Create the season
     */
    createSeason() {
        const btn = document.getElementById('createBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Creating...';
        }

        const data = this.getWizardData();
        const createUrl = window.WIZARD_CONFIG?.createSeasonUrl || '/admin-panel/league-management/season-wizard/create';
        const dashboardUrl = window.WIZARD_CONFIG?.dashboardUrl || '/admin-panel/league-management';

        fetch(createUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(result => {
            if (result.success) {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message, 'success');
                }
                setTimeout(() => {
                    window.location.href = result.redirect_url || dashboardUrl;
                }, 1500);
            } else {
                if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                    AdminPanel.showMobileToast(result.message || 'Failed to create season', 'danger');
                }
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = '<i class="ti ti-check me-1"></i> Create Season';
                }
            }
        })
        .catch(error => {
            console.error('[AdminSeasonWizardManager] Error:', error);
            if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
                AdminPanel.showMobileToast('An error occurred', 'danger');
            }
            if (btn) {
                btn.disabled = false;
                btn.innerHTML = '<i class="ti ti-check me-1"></i> Create Season';
            }
        });
    }
}

// Create singleton instance
let wizardManager = null;

/**
 * Get or create manager instance
 */
function getManager() {
    if (!wizardManager) {
        wizardManager = new AdminSeasonWizardManager();
    }
    return wizardManager;
}

/**
 * Initialize function
 */
function init() {
    if (_initialized) return;
    _initialized = true;

    const manager = getManager();
    manager.init();

    // Expose methods globally for backward compatibility
    window.handleLeagueTypeChange = () => manager.handleLeagueTypeChange();
    window.updateUI = () => manager.updateUI();
    window.goToStep = (step) => manager.goToStep(step);
    window.wizardNext = () => manager.wizardNext();
    window.wizardPrev = () => manager.wizardPrev();
    window.validateStep = (step) => manager.validateStep(step);
    window.getWizardData = () => manager.getWizardData();
    window.loadDiscordPreview = () => manager.loadDiscordPreview();
    window.populateReview = () => manager.populateReview();
    window.createSeason = () => manager.createSeason();
}

// Register with InitSystem
if (InitSystem && InitSystem.register) {
    InitSystem.register('admin-season-wizard', init, {
        priority: 40,
        reinitializable: false,
        description: 'Admin season wizard'
    });
}

// Fallback for direct script loading
// InitSystem handles initialization

// Export for ES modules
export { AdminSeasonWizardManager, getManager, init };
