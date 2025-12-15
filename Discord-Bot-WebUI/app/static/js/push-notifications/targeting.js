/**
 * Push Notification Targeting Module
 *
 * Handles dynamic target selection for push notifications:
 * - Loading teams, leagues, roles, pools from API
 * - Managing multi-select dropdowns
 * - Calculating recipient estimates
 */

const PushTargeting = {
    // Configuration
    config: {
        baseUrl: '/admin-panel',
        selectors: {
            targetType: '#target_type',
            teamSelector: '#team_selector',
            leagueSelector: '#league_selector',
            roleSelector: '#role_selector',
            poolSelector: '#pool_selector',
            groupSelector: '#notification_group_selector',
            platformSelector: '#platform_selector',
            recipientCount: '#recipient_count'
        }
    },

    // Cached data
    cache: {
        teams: null,
        leagues: null,
        roles: null,
        pools: null,
        groups: null
    },

    /**
     * Initialize targeting module
     * @param {Object} options - Configuration options
     */
    init(options = {}) {
        this.config = { ...this.config, ...options };
        this.bindEvents();
        this.loadInitialData();
    },

    /**
     * Bind event listeners
     */
    bindEvents() {
        const targetTypeEl = document.querySelector(this.config.selectors.targetType);
        if (targetTypeEl) {
            targetTypeEl.addEventListener('change', (e) => this.onTargetTypeChange(e.target.value));
        }

        // Bind change events for all selectors to update recipient count
        const selectors = [
            this.config.selectors.teamSelector,
            this.config.selectors.leagueSelector,
            this.config.selectors.roleSelector,
            this.config.selectors.poolSelector,
            this.config.selectors.groupSelector,
            this.config.selectors.platformSelector
        ];

        selectors.forEach(selector => {
            const el = document.querySelector(selector);
            if (el) {
                el.addEventListener('change', () => this.updateRecipientEstimate());
            }
        });
    },

    /**
     * Load initial data (teams, leagues, roles, etc.)
     */
    async loadInitialData() {
        try {
            await Promise.all([
                this.loadTeams(),
                this.loadLeagues(),
                this.loadRoles(),
                this.loadPools(),
                this.loadGroups()
            ]);
        } catch (error) {
            console.error('Error loading targeting data:', error);
        }
    },

    /**
     * Handle target type change
     * @param {string} targetType - Selected target type
     */
    onTargetTypeChange(targetType) {
        // Hide all sub-selectors
        this.hideAllSelectors();

        // Show relevant selector
        switch (targetType) {
            case 'team':
                this.showSelector('teamSelector');
                break;
            case 'league':
                this.showSelector('leagueSelector');
                break;
            case 'role':
                this.showSelector('roleSelector');
                break;
            case 'pool':
                this.showSelector('poolSelector');
                break;
            case 'group':
                this.showSelector('groupSelector');
                break;
            case 'platform':
                this.showSelector('platformSelector');
                break;
        }

        this.updateRecipientEstimate();
    },

    /**
     * Hide all sub-selectors
     */
    hideAllSelectors() {
        const selectorNames = ['teamSelector', 'leagueSelector', 'roleSelector', 'poolSelector', 'groupSelector'];
        selectorNames.forEach(name => {
            const container = document.querySelector(`${this.config.selectors[name]}_container`);
            if (container) {
                container.style.display = 'none';
            }
        });
    },

    /**
     * Show a specific selector
     * @param {string} selectorName - Selector name
     */
    showSelector(selectorName) {
        const container = document.querySelector(`${this.config.selectors[selectorName]}_container`);
        if (container) {
            container.style.display = 'block';
        }
    },

    /**
     * Load teams from API
     * @param {number} leagueId - Optional league filter
     */
    async loadTeams(leagueId = null) {
        try {
            let url = `${this.config.baseUrl}/api/push/teams`;
            if (leagueId) {
                url += `?league_id=${leagueId}`;
            }

            const response = await fetch(url);
            const data = await response.json();

            if (data.success) {
                this.cache.teams = data.teams;
                this.populateTeamSelector(data.teams);
            }
        } catch (error) {
            console.error('Error loading teams:', error);
        }
    },

    /**
     * Load leagues from API
     */
    async loadLeagues() {
        try {
            const response = await fetch(`${this.config.baseUrl}/api/push/leagues`);
            const data = await response.json();

            if (data.success) {
                this.cache.leagues = data.leagues;
                this.populateLeagueSelector(data.leagues);
            }
        } catch (error) {
            console.error('Error loading leagues:', error);
        }
    },

    /**
     * Load roles from API
     */
    async loadRoles() {
        try {
            const response = await fetch(`${this.config.baseUrl}/api/push/roles`);
            const data = await response.json();

            if (data.success) {
                this.cache.roles = data.roles;
                this.populateRoleSelector(data.roles);
            }
        } catch (error) {
            console.error('Error loading roles:', error);
        }
    },

    /**
     * Load substitute pools from API
     */
    async loadPools() {
        try {
            const response = await fetch(`${this.config.baseUrl}/api/push/substitute-pools`);
            const data = await response.json();

            if (data.success) {
                this.cache.pools = data.pools;
                this.populatePoolSelector(data.pools);
            }
        } catch (error) {
            console.error('Error loading pools:', error);
        }
    },

    /**
     * Load notification groups from API
     */
    async loadGroups() {
        try {
            const response = await fetch(`${this.config.baseUrl}/api/notification-groups`);
            const data = await response.json();

            if (data.success) {
                this.cache.groups = data.groups;
                this.populateGroupSelector(data.groups);
            }
        } catch (error) {
            console.error('Error loading groups:', error);
        }
    },

    /**
     * Populate team selector
     * @param {Array} teams - Teams data
     */
    populateTeamSelector(teams) {
        const selector = document.querySelector(this.config.selectors.teamSelector);
        if (!selector) return;

        selector.innerHTML = '<option value="">Select teams...</option>';
        teams.forEach(team => {
            const option = document.createElement('option');
            option.value = team.id;
            option.textContent = `${team.name} (${team.league_name || 'No league'})`;
            selector.appendChild(option);
        });
    },

    /**
     * Populate league selector
     * @param {Array} leagues - Leagues data
     */
    populateLeagueSelector(leagues) {
        const selector = document.querySelector(this.config.selectors.leagueSelector);
        if (!selector) return;

        selector.innerHTML = '<option value="">Select leagues...</option>';
        leagues.forEach(league => {
            const option = document.createElement('option');
            option.value = league.id;
            option.textContent = `${league.name} (${league.team_count} teams)`;
            selector.appendChild(option);
        });
    },

    /**
     * Populate role selector
     * @param {Array} roles - Roles data
     */
    populateRoleSelector(roles) {
        const selector = document.querySelector(this.config.selectors.roleSelector);
        if (!selector) return;

        selector.innerHTML = '<option value="">Select roles...</option>';
        roles.forEach(role => {
            const option = document.createElement('option');
            option.value = role.name;
            option.textContent = role.name;
            selector.appendChild(option);
        });
    },

    /**
     * Populate pool selector
     * @param {Array} pools - Pools data
     */
    populatePoolSelector(pools) {
        const selector = document.querySelector(this.config.selectors.poolSelector);
        if (!selector) return;

        selector.innerHTML = '';
        pools.forEach(pool => {
            const option = document.createElement('option');
            option.value = pool.id;
            option.textContent = `${pool.name} (${pool.member_count} members)`;
            selector.appendChild(option);
        });
    },

    /**
     * Populate notification group selector
     * @param {Array} groups - Groups data
     */
    populateGroupSelector(groups) {
        const selector = document.querySelector(this.config.selectors.groupSelector);
        if (!selector) return;

        selector.innerHTML = '<option value="">Select a notification group...</option>';
        groups.forEach(group => {
            const option = document.createElement('option');
            option.value = group.id;
            option.textContent = `${group.name} (${group.group_type})`;
            selector.appendChild(option);
        });
    },

    /**
     * Get currently selected targets
     * @returns {Object} Target configuration
     */
    getSelectedTargets() {
        const targetTypeEl = document.querySelector(this.config.selectors.targetType);
        const platformEl = document.querySelector(this.config.selectors.platformSelector);

        const targetType = targetTypeEl ? targetTypeEl.value : 'all';
        const platform = platformEl ? platformEl.value : 'all';

        let targetIds = null;

        switch (targetType) {
            case 'team':
                targetIds = this.getMultiSelectValues(this.config.selectors.teamSelector);
                break;
            case 'league':
                targetIds = this.getMultiSelectValues(this.config.selectors.leagueSelector);
                break;
            case 'role':
                targetIds = this.getMultiSelectValues(this.config.selectors.roleSelector);
                break;
            case 'pool':
                const poolEl = document.querySelector(this.config.selectors.poolSelector);
                targetIds = poolEl ? [poolEl.value] : null;
                break;
            case 'group':
                const groupEl = document.querySelector(this.config.selectors.groupSelector);
                targetIds = groupEl && groupEl.value ? [parseInt(groupEl.value)] : null;
                break;
        }

        return {
            target_type: targetType,
            target_ids: targetIds,
            platform: platform
        };
    },

    /**
     * Get values from multi-select element
     * @param {string} selector - Element selector
     * @returns {Array} Selected values
     */
    getMultiSelectValues(selector) {
        const el = document.querySelector(selector);
        if (!el) return [];

        const selected = Array.from(el.selectedOptions || []).map(opt => opt.value);
        return selected.length > 0 ? selected : null;
    },

    /**
     * Update recipient estimate display
     */
    async updateRecipientEstimate() {
        const targets = this.getSelectedTargets();

        try {
            const response = await fetch(`${this.config.baseUrl}/communication/push-notifications/preview`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(targets)
            });

            const data = await response.json();

            if (data.success) {
                this.displayRecipientCount(data.preview);
            }
        } catch (error) {
            console.error('Error getting recipient estimate:', error);
        }
    },

    /**
     * Display recipient count
     * @param {Object} preview - Preview data
     */
    displayRecipientCount(preview) {
        const countEl = document.querySelector(this.config.selectors.recipientCount);
        if (countEl) {
            countEl.textContent = preview.total_tokens || 0;
        }

        // Update breakdown if elements exist
        const iosEl = document.querySelector('#recipient_count_ios');
        const androidEl = document.querySelector('#recipient_count_android');
        const webEl = document.querySelector('#recipient_count_web');

        if (preview.breakdown) {
            if (iosEl) iosEl.textContent = preview.breakdown.ios || 0;
            if (androidEl) androidEl.textContent = preview.breakdown.android || 0;
            if (webEl) webEl.textContent = preview.breakdown.web || 0;
        }
    }
};

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PushTargeting;
}
