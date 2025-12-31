/**
 * ECS FC Multi-Team Manager
 * Handles multi-select dropdown for ECS FC team assignments in user management modal.
 * Allows ECS FC players to be on multiple teams within the same ECS FC league.
 *
 * Uses InitSystem with priority 30 (after form selects).
 */

(function() {
    'use strict';

    const EcsFcTeamManager = {
        selectors: {
            section: '#ecsFcTeamsSection',
            multiSelect: '#editEcsFcTeams',
            primaryLeague: '#editLeague',
            secondaryLeague: '#editSecondaryLeague',
            playerFields: '#playerFields'
        },

        /**
         * Initialize the ECS FC team manager
         * @param {Element} context - The context element (document or container)
         */
        init(context) {
            const root = context || document;

            // Only initialize if we're on a page with the ECS FC section
            if (!root.querySelector(this.selectors.section)) {
                return;
            }

            this.setupLeagueChangeListeners(root);
            this.extendPopulateEditForm();
            this.extendFormSubmission(root);
        },

        /**
         * Set up listeners for league dropdown changes
         * @param {Element} root - Root element to search within
         */
        setupLeagueChangeListeners(root) {
            const primaryLeague = root.querySelector(this.selectors.primaryLeague);
            const secondaryLeague = root.querySelector(this.selectors.secondaryLeague);

            if (primaryLeague) {
                primaryLeague.addEventListener('change', () => this.updateVisibility());
            }

            if (secondaryLeague) {
                secondaryLeague.addEventListener('change', () => this.updateVisibility());
            }
        },

        /**
         * Extend the existing populateEditForm function to handle ECS FC teams
         */
        extendPopulateEditForm() {
            // Store reference to original function if it exists
            if (typeof window.populateEditForm === 'function') {
                const originalPopulateEditForm = window.populateEditForm;
                const self = this;

                window.populateEditForm = function(user) {
                    // Call original function first
                    originalPopulateEditForm(user);

                    // Then handle ECS FC teams
                    self.handleUserData(user);
                };
            }
        },

        /**
         * Extend form submission to include ECS FC team IDs as an array
         * @param {Element} root - Root element to search within
         */
        extendFormSubmission(root) {
            const form = root.querySelector('#editUserForm');
            if (!form) return;

            form.addEventListener('formdata', (event) => {
                // Remove existing ecs_fc_team_ids entries
                event.formData.delete('ecs_fc_team_ids');

                // Get selected ECS FC teams
                const selectedTeams = this.getSelectedTeams();

                // Add each team ID as a separate form entry (for array handling)
                selectedTeams.forEach(teamId => {
                    event.formData.append('ecs_fc_team_ids[]', teamId);
                });
            });
        },

        /**
         * Handle user data when modal opens
         * @param {Object} user - User data from API
         */
        handleUserData(user) {
            // Check if user has player data with ECS FC teams
            if (user.has_player && user.player && user.player.ecs_fc_team_ids) {
                this.setSelectedTeams(user.player.ecs_fc_team_ids);
            } else {
                // Clear selection if no ECS FC teams
                this.clearSelection();
            }

            // Update visibility based on selected leagues
            this.updateVisibility();
        },

        /**
         * Update visibility of ECS FC section based on league selection
         * Uses classList for toggling instead of inline styles
         */
        updateVisibility() {
            const section = document.querySelector(this.selectors.section);
            const playerFields = document.querySelector(this.selectors.playerFields);

            if (!section) return;

            // Don't show if player fields are hidden
            if (playerFields && playerFields.classList.contains('d-none')) {
                section.classList.add('d-none');
                return;
            }

            const primarySelect = document.querySelector(this.selectors.primaryLeague);
            const secondarySelect = document.querySelector(this.selectors.secondaryLeague);

            const primaryText = primarySelect?.selectedOptions[0]?.text || '';
            const secondaryText = secondarySelect?.selectedOptions[0]?.text || '';

            // Show section if either league is ECS FC
            const hasEcsFc = primaryText.includes('ECS FC') || secondaryText.includes('ECS FC');

            if (hasEcsFc) {
                section.classList.remove('d-none');
            } else {
                section.classList.add('d-none');
                // Clear selection when hiding
                this.clearSelection();
            }
        },

        /**
         * Set selected teams in the multi-select dropdown
         * @param {Array<number>} teamIds - Array of team IDs to select
         */
        setSelectedTeams(teamIds) {
            const select = document.querySelector(this.selectors.multiSelect);
            if (!select || !Array.isArray(teamIds)) return;

            // Clear existing selections
            Array.from(select.options).forEach(opt => {
                opt.selected = false;
            });

            // Select the specified teams
            teamIds.forEach(id => {
                const option = select.querySelector(`option[value="${id}"]`);
                if (option) {
                    option.selected = true;
                }
            });
        },

        /**
         * Get currently selected team IDs
         * @returns {Array<number>} Array of selected team IDs
         */
        getSelectedTeams() {
            const select = document.querySelector(this.selectors.multiSelect);
            if (!select) return [];

            return Array.from(select.selectedOptions).map(opt => parseInt(opt.value, 10));
        },

        /**
         * Clear all selections in the multi-select
         */
        clearSelection() {
            const select = document.querySelector(this.selectors.multiSelect);
            if (!select) return;

            Array.from(select.options).forEach(opt => {
                opt.selected = false;
            });
        }
    };

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    // Expose for external use (MUST be before any callbacks or registrations)
    window.EcsFcTeamManager = EcsFcTeamManager;

    // Register with InitSystem if available
    if (typeof window.InitSystem !== 'undefined') {
        window.InitSystem.register('EcsFcTeamManager', function(context) {
            window.EcsFcTeamManager.init(context);
        }, {
            priority: 30 // After form selects
        });
    } else {
        // Fallback to DOMContentLoaded
        if (document.readyState === 'loading') {
            document.addEventListener('DOMContentLoaded', function() {
                window.EcsFcTeamManager.init(document);
            });
        } else {
            window.EcsFcTeamManager.init(document);
        }
    }

})();
