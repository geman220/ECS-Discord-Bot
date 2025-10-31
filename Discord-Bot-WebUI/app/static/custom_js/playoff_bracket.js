/**
 * Playoff Bracket Manager
 * Handles dynamic loading, updating, and interaction with the playoff bracket
 */

class PlayoffBracket {
    constructor(leagueId, seasonId, currentTeamId = null) {
        this.leagueId = leagueId;
        this.seasonId = seasonId;
        this.currentTeamId = currentTeamId;
        this.refreshInterval = null;
        this.autoRefreshEnabled = true;
        this.autoRefreshDelay = 30000; // 30 seconds

        // Cache for bracket data
        this.data = {
            groupA: { teams: [], matches: [], standings: [] },
            groupB: { teams: [], matches: [], standings: [] },
            placementMatches: [],
            status: 'not_started' // not_started, group_stage, placement_finals, completed
        };

        // Bind methods
        this.initialize = this.initialize.bind(this);
        this.fetchBracketData = this.fetchBracketData.bind(this);
        this.renderBracket = this.renderBracket.bind(this);
        this.handleMatchReport = this.handleMatchReport.bind(this);
    }

    /**
     * Initialize the bracket
     */
    async initialize() {
        console.log('Initializing playoff bracket...', {
            leagueId: this.leagueId,
            seasonId: this.seasonId,
            currentTeamId: this.currentTeamId
        });

        try {
            await this.fetchBracketData();
            this.renderBracket();
            this.startAutoRefresh();
        } catch (error) {
            console.error('Failed to initialize playoff bracket:', error);
            this.showError('Failed to load playoff bracket. Please refresh the page.');
        }
    }

    /**
     * Fetch bracket data from API
     */
    async fetchBracketData() {
        const url = `/api/playoffs/bracket/${this.leagueId}`;

        try {
            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }

            const data = await response.json();
            console.log('Fetched bracket data:', data);

            this.data = data;
            return data;
        } catch (error) {
            console.error('Error fetching bracket data:', error);
            throw error;
        }
    }

    /**
     * Render the bracket UI
     */
    renderBracket() {
        const container = document.querySelector('.playoff-bracket-container');
        if (!container) return;

        // Hide loading, show content
        const loading = container.querySelector('.bracket-loading');
        const error = container.querySelector('.bracket-error');
        const content = container.querySelector('.bracket-content');

        if (loading) loading.classList.add('d-none');

        if (!this.data || !this.data.groupA || !this.data.groupB) {
            if (error) {
                error.classList.remove('d-none');
                error.querySelector('.bracket-error-message').textContent =
                    'No playoff data available. Playoffs may not have been generated yet.';
            }
            return;
        }

        if (error) error.classList.add('d-none');
        if (content) content.classList.remove('d-none');

        // Update status badge
        this.updateStatusBadge();

        // Render groups
        this.renderGroup('A', this.data.groupA);
        this.renderGroup('B', this.data.groupB);

        // Render placement finals
        this.renderPlacementFinals(this.data.placementMatches);
    }

    /**
     * Update the status badge text
     */
    updateStatusBadge() {
        const statusText = document.querySelector('.bracket-status-text');
        if (!statusText) return;

        const statusMessages = {
            'not_started': 'Playoffs Not Started',
            'group_stage': 'Group Stage in Progress',
            'week2_morning': 'Week 2 Morning - Final Group Matches',
            'placement_finals': 'Placement Finals',
            'completed': 'Playoffs Completed'
        };

        statusText.textContent = statusMessages[this.data.status] || 'Unknown Status';
    }

    /**
     * Render a group (A or B)
     */
    renderGroup(groupName, groupData) {
        const matchesContainer = document.getElementById(`group${groupName}Matches`);
        const standingsContainer = document.getElementById(`group${groupName}Standings`);

        if (!matchesContainer || !standingsContainer) return;

        // Render matches
        matchesContainer.innerHTML = '';
        if (groupData.matches && groupData.matches.length > 0) {
            // Group by round
            const matchesByRound = this.groupMatchesByRound(groupData.matches);

            Object.keys(matchesByRound).sort().forEach(round => {
                const roundDiv = document.createElement('div');
                roundDiv.className = 'round-group mb-3';

                const roundLabel = document.createElement('div');
                roundLabel.className = 'round-label';
                roundLabel.innerHTML = `<i class="ti ti-calendar-event me-1"></i>${this.getRoundLabel(round, groupData.matches[0])}`;
                roundDiv.appendChild(roundLabel);

                matchesByRound[round].forEach(match => {
                    roundDiv.appendChild(this.createMatchCard(match));
                });

                matchesContainer.appendChild(roundDiv);
            });
        } else {
            matchesContainer.innerHTML = '<p class="text-muted text-center">No matches scheduled</p>';
        }

        // Render standings
        standingsContainer.innerHTML = '';
        const standingsTable = standingsContainer.querySelector('.standings-table');
        if (!standingsTable) {
            const table = document.createElement('div');
            table.className = 'standings-table';
            standingsContainer.appendChild(table);
        }

        const tableContainer = standingsContainer.querySelector('.standings-table');
        tableContainer.innerHTML = '';

        if (groupData.standings && groupData.standings.length > 0) {
            groupData.standings.forEach((standing, index) => {
                tableContainer.appendChild(this.createStandingRow(standing, index + 1));
            });
        } else {
            tableContainer.innerHTML = '<p class="text-muted text-center small">Standings will appear after matches are played</p>';
        }
    }

    /**
     * Get round label based on playoff_round and date
     */
    getRoundLabel(round, sampleMatch) {
        const roundNum = parseInt(round);
        if (roundNum === 1) {
            return 'Week 1';
        } else if (roundNum === 2) {
            return 'Week 2 Morning';
        }
        return `Round ${roundNum}`;
    }

    /**
     * Group matches by playoff round
     */
    groupMatchesByRound(matches) {
        const grouped = {};
        matches.forEach(match => {
            const round = match.playoff_round || 1;
            if (!grouped[round]) {
                grouped[round] = [];
            }
            grouped[round].push(match);
        });
        return grouped;
    }

    /**
     * Create a match card element
     */
    createMatchCard(match) {
        const card = document.createElement('div');
        card.className = 'bracket-match-card';
        card.dataset.matchId = match.id;

        // Check if match is reported
        const isReported = match.home_team_score !== null && match.away_team_score !== null;
        if (isReported) {
            card.classList.add('reported');
        }

        // Highlight current team
        if (this.currentTeamId &&
            (match.home_team_id == this.currentTeamId || match.away_team_id == this.currentTeamId)) {
            card.classList.add('current-team');
        }

        // Determine winner
        let homeWinner = false, awayWinner = false;
        if (isReported) {
            if (match.home_team_score > match.away_team_score) {
                homeWinner = true;
            } else if (match.away_team_score > match.home_team_score) {
                awayWinner = true;
            }
        }

        // Build match teams HTML
        const teamsHTML = `
            <div class="match-teams">
                <div class="team home-team ${homeWinner ? 'winner' : ''}">
                    <span class="team-name">${match.home_team_name || 'TBD'}</span>
                    <span class="team-score">${match.home_team_score !== null ? match.home_team_score : '-'}</span>
                </div>
                <div class="match-divider">vs</div>
                <div class="team away-team ${awayWinner ? 'winner' : ''}">
                    <span class="team-name">${match.away_team_name || 'TBD'}</span>
                    <span class="team-score">${match.away_team_score !== null ? match.away_team_score : '-'}</span>
                </div>
            </div>
        `;

        // Build match info HTML
        const matchDate = match.date ? new Date(match.date).toLocaleDateString() : 'TBD';
        const matchTime = match.time || 'TBD';
        const infoHTML = `
            <div class="match-info">
                <span class="match-time">
                    <i class="ti ti-clock"></i>
                    <span class="time-text">${matchDate} ${matchTime}</span>
                </span>
                <span class="match-location">
                    <i class="ti ti-map-pin"></i>
                    <span class="location-text">${match.location || 'TBD'}</span>
                </span>
            </div>
        `;

        // Build report button HTML
        const buttonHTML = `
            <button class="btn btn-sm btn-primary match-report-btn"
                    data-match-id="${match.id}"
                    onclick="window.playoffBracket.handleMatchReport(${match.id})">
                <i class="ti ti-pencil"></i>
                <span class="d-none d-md-inline">${isReported ? 'Edit' : 'Report'}</span>
            </button>
        `;

        card.innerHTML = teamsHTML + infoHTML + buttonHTML;

        return card;
    }

    /**
     * Create a standing row element
     */
    createStandingRow(standing, position) {
        const row = document.createElement('div');
        row.className = `standings-row position-${position}`;
        row.dataset.teamId = standing.team_id;

        // Highlight current team
        if (this.currentTeamId && standing.team_id == this.currentTeamId) {
            row.classList.add('current-team');
        }

        row.innerHTML = `
            <div class="position">${position}</div>
            <div class="team-name">${standing.team_name}</div>
            <div class="stats">
                <div class="stat">
                    <span class="stat-label">PTS</span>
                    <span class="stat-value">${standing.points || 0}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">GD</span>
                    <span class="stat-value">${standing.goal_difference || 0}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">GF</span>
                    <span class="stat-value">${standing.goals_for || 0}</span>
                </div>
            </div>
        `;

        return row;
    }

    /**
     * Render placement finals section
     */
    renderPlacementFinals(placementMatches) {
        if (!placementMatches || placementMatches.length === 0) {
            // Show TBD messages
            this.renderTBDPlacementMatch('championshipMatch', 'A1st vs B1st');
            this.renderTBDPlacementMatch('thirdPlaceMatch', 'A2nd vs B2nd');
            this.renderTBDPlacementMatch('fifthPlaceMatch', 'A3rd vs B3rd');
            this.renderTBDPlacementMatch('seventhPlaceMatch', 'A4th vs B4th');
            return;
        }

        // Match placement matches to their containers
        placementMatches.forEach(match => {
            const description = (match.description || '').toLowerCase();
            let containerId = null;

            if (description.includes('championship')) {
                containerId = 'championshipMatch';
            } else if (description.includes('3rd')) {
                containerId = 'thirdPlaceMatch';
            } else if (description.includes('5th')) {
                containerId = 'fifthPlaceMatch';
            } else if (description.includes('7th')) {
                containerId = 'seventhPlaceMatch';
            }

            if (containerId) {
                this.renderPlacementMatch(containerId, match);
            }
        });
    }

    /**
     * Render TBD message for placement match
     */
    renderTBDPlacementMatch(containerId, matchup) {
        const container = document.getElementById(containerId);
        if (!container) return;

        container.innerHTML = `
            <div class="tbd-message">
                <div class="text-center">
                    <i class="ti ti-help-circle mb-2" style="font-size: 2rem;"></i>
                    <p class="mb-1">${matchup}</p>
                    <small class="text-muted">To be determined after group stage</small>
                </div>
            </div>
        `;
    }

    /**
     * Render actual placement match
     */
    renderPlacementMatch(containerId, match) {
        const container = document.getElementById(containerId);
        if (!container) return;

        const matchCard = this.createMatchCard(match);
        container.innerHTML = '';
        container.appendChild(matchCard);
    }

    /**
     * Handle match report button click
     */
    handleMatchReport(matchId) {
        console.log('Opening match report modal for match:', matchId);

        // Try to open existing modal if it exists
        const modalId = `reportMatchModal-${matchId}`;
        const existingModal = document.getElementById(modalId);

        if (existingModal) {
            const modal = new bootstrap.Modal(existingModal);
            modal.show();
        } else {
            // If modal doesn't exist, redirect to a page where it does or show a message
            console.warn('Match report modal not found on page. You may need to load it first.');
            alert('Please navigate to the team page to report this match.');
        }
    }

    /**
     * Start auto-refresh of bracket data
     */
    startAutoRefresh() {
        if (!this.autoRefreshEnabled) return;

        this.refreshInterval = setInterval(async () => {
            console.log('Auto-refreshing bracket data...');
            try {
                await this.fetchBracketData();
                this.renderBracket();
            } catch (error) {
                console.error('Auto-refresh failed:', error);
            }
        }, this.autoRefreshDelay);
    }

    /**
     * Stop auto-refresh
     */
    stopAutoRefresh() {
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
            this.refreshInterval = null;
        }
    }

    /**
     * Manual refresh
     */
    async refresh() {
        console.log('Manual refresh triggered');
        try {
            await this.fetchBracketData();
            this.renderBracket();
        } catch (error) {
            console.error('Refresh failed:', error);
            this.showError('Failed to refresh bracket data.');
        }
    }

    /**
     * Show error message
     */
    showError(message) {
        const container = document.querySelector('.playoff-bracket-container');
        if (!container) return;

        const error = container.querySelector('.bracket-error');
        if (error) {
            error.classList.remove('d-none');
            error.querySelector('.bracket-error-message').textContent = message;
        }

        const loading = container.querySelector('.bracket-loading');
        const content = container.querySelector('.bracket-content');

        if (loading) loading.classList.add('d-none');
        if (content) content.classList.add('d-none');
    }

    /**
     * Cleanup
     */
    destroy() {
        this.stopAutoRefresh();
    }
}

// Export for use in other scripts
if (typeof window !== 'undefined') {
    window.PlayoffBracket = PlayoffBracket;
}
