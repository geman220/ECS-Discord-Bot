'use strict';

/**
 * Balanced-draft client state + balance math.
 *
 * Mirrors app/services/classic_draft_service.py: per-metric team TOTALS over
 * non-coach players with the configured unrated_default imputed for unrated
 * players; gap = max total - min total per metric. Events mutate this state
 * deterministically; a debounced /classic-draft/state.json resync remains the
 * authority (see socket.js).
 */

export const METRICS = ['intensity', 'on_ball_skill', 'spirit', 'knowledge_movement'];
// Display order matches the legacy "spreadsheet of doom" (OBS, I / S, K/M) so
// draft-night muscle memory carries over.
export const DISPLAY_ORDER = ['on_ball_skill', 'intensity', 'spirit', 'knowledge_movement'];
export const METRIC_SHORT = {
    intensity: 'I', on_ball_skill: 'OBS', spirit: 'S', knowledge_movement: 'K/M',
};

export const state = {
    teams: [],          // [{id, name, roster: [player]}]
    pool: [],           // [player]
    metrics: [],        // metric guide rows (key,label,weight,...)
    config: { max_metric_gap: 3, unrated_default: 3, suggestion_count: 10, gender_balance_enabled: true },
    seasonName: null,
    activeTeamId: null, // click-to-target team
    railTab: 'pool',
    suggestTeamId: null,
    filters: {},
    selectedIds: new Set(),  // multi-select in the pool
};

export function loadInitial(payload) {
    state.teams = (payload.teams || []).map(t => ({ id: t.id, name: t.name, roster: t.roster || [] }));
    state.pool = payload.pool || [];
    state.metrics = payload.metrics || [];
    state.config = payload.config || state.config;
    state.seasonName = payload.season_name || null;
    if (state.suggestTeamId === null && state.teams.length) {
        state.suggestTeamId = state.teams[0].id;
    }
    // Prune selections for players no longer in the pool (drafted elsewhere).
    const poolIds = new Set(state.pool.map(p => p.id));
    state.selectedIds.forEach(id => { if (!poolIds.has(id)) state.selectedIds.delete(id); });
}

export function metricValue(player, metric) {
    const value = player?.ratings?.metrics?.[metric];
    return (value === null || value === undefined) ? Number(state.config.unrated_default) : Number(value);
}

export function isRated(player) {
    return Boolean(player?.ratings?.is_rated);
}

export function teamTotals(team) {
    const players = team.roster.filter(p => !p.is_coach);
    const totals = {};
    METRICS.forEach(metric => {
        let total = 0;
        const rated = [];
        players.forEach(p => {
            const value = metricValue(p, metric);
            total += value;
            if (p?.ratings?.metrics?.[metric] !== null && p?.ratings?.metrics?.[metric] !== undefined) {
                rated.push(value);
            }
        });
        totals[metric] = {
            total,
            avg: rated.length ? rated.reduce((a, b) => a + b, 0) / rated.length : null,
        };
    });
    const genders = { M: 0, F: 0, X: 0 };
    players.forEach(p => { genders[p.gender || 'X'] = (genders[p.gender || 'X'] || 0) + 1; });
    return {
        metrics: totals,
        size: players.length,
        coachCount: team.roster.length - players.length,
        unratedCount: players.filter(p => !isRated(p)).length,
        newCount: players.filter(p => p.is_new).length,
        gkCount: players.filter(p => p.wants_gk).length,
        genders,
    };
}

export function computeGaps() {
    const perTeam = state.teams.map(team => ({ id: team.id, totals: teamTotals(team) }));
    const gaps = {};
    METRICS.forEach(metric => {
        if (!perTeam.length) {
            gaps[metric] = { gap: 0, withinLimit: true, maxTeamId: null, minTeamId: null };
            return;
        }
        let max = perTeam[0], min = perTeam[0];
        perTeam.forEach(entry => {
            if (entry.totals.metrics[metric].total > max.totals.metrics[metric].total) max = entry;
            if (entry.totals.metrics[metric].total < min.totals.metrics[metric].total) min = entry;
        });
        const gap = max.totals.metrics[metric].total - min.totals.metrics[metric].total;
        gaps[metric] = {
            gap,
            withinLimit: gap <= Number(state.config.max_metric_gap) + 1e-9,
            maxTeamId: max.id,
            minTeamId: min.id,
        };
    });
    return gaps;
}

export function findTeam(teamId) {
    return state.teams.find(t => t.id === Number(teamId)) || null;
}

/** Move a player pool -> roster (socket player_drafted_enhanced). Returns true if changed. */
export function applyDrafted(playerId, teamId) {
    const team = findTeam(teamId);
    if (!team) return false;
    if (team.roster.some(p => p.id === Number(playerId))) return false;
    const index = state.pool.findIndex(p => p.id === Number(playerId));
    let player = null;
    if (index >= 0) {
        player = state.pool.splice(index, 1)[0];
    } else {
        // Player might be on another team (move) — pull from any roster.
        for (const other of state.teams) {
            const i = other.roster.findIndex(p => p.id === Number(playerId));
            if (i >= 0) { player = other.roster.splice(i, 1)[0]; break; }
        }
    }
    if (!player) return false;   // unknown player — resync will reconcile
    // Drafted (by any surface) means no longer multi-selectable.
    state.selectedIds.delete(Number(playerId));
    player.team_id = team.id;
    player.team_name = team.name;
    team.roster.push(player);
    team.roster.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
    return true;
}

/** Move a player roster -> pool (socket player_removed_enhanced). */
export function applyRemoved(playerId) {
    for (const team of state.teams) {
        const i = team.roster.findIndex(p => p.id === Number(playerId));
        if (i >= 0) {
            const player = team.roster.splice(i, 1)[0];
            player.team_id = null;
            player.team_name = null;
            state.pool.push(player);
            state.pool.sort((a, b) => (a.name || '').localeCompare(b.name || ''));
            return true;
        }
    }
    return false;
}

export function draftedCount() {
    return state.teams.reduce((total, t) => total + t.roster.filter(p => !p.is_coach).length, 0);
}

export function totalPlayers() {
    return draftedCount() + state.pool.filter(p => !p.is_coach).length;
}
