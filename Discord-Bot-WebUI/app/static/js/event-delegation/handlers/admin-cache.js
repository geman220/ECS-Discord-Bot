import { EventDelegation } from '../core.js';
import { InitSystem } from '../../init-system.js';

/**
 * Admin Cache Action Handlers
 * Handles draft cache statistics and cache management
 */

// DRAFT CACHE ACTIONS
// ============================================================================

let autoRefreshInterval = null;

/**
 * Update draft cache statistics
 * Fetches and updates cache statistics display
 */
function updateDraftCacheStats() {
    fetch('/admin/redis/api/draft-cache-stats')
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                console.error('Error fetching draft cache stats:', data.error);
                return;
            }

            // Update overall statistics
            const totalKeys = Object.values(data.draft_cache_keys || {}).reduce((a, b) => a + b, 0);
            const totalKeysEl = document.getElementById('total-cache-keys');
            if (totalKeysEl) totalKeysEl.textContent = totalKeys;

            // Update cache type breakdown
            const playerCount = document.getElementById('player-cache-count');
            const analyticsCount = document.getElementById('analytics-cache-count');
            const teamCount = document.getElementById('team-cache-count');
            const availabilityCount = document.getElementById('availability-cache-count');

            if (playerCount) playerCount.textContent = data.draft_cache_keys?.players || 0;
            if (analyticsCount) analyticsCount.textContent = data.draft_cache_keys?.analytics || 0;
            if (teamCount) teamCount.textContent = data.draft_cache_keys?.teams || 0;
            if (availabilityCount) availabilityCount.textContent = data.draft_cache_keys?.availability || 0;

            // Update connection pool stats
            if (data.connection_pool?.pool_stats) {
                const poolUtil = document.getElementById('redis-pool-utilization');
                const maxConn = document.getElementById('max-connections');
                const inUse = document.getElementById('connections-in-use');
                const available = document.getElementById('connections-available');
                const created = document.getElementById('connections-created');

                if (poolUtil) poolUtil.textContent = (data.connection_pool.pool_stats.utilization_percent || 0) + '%';
                if (maxConn) maxConn.textContent = data.connection_pool.pool_stats.max_connections || 'N/A';
                if (inUse) inUse.textContent = data.connection_pool.pool_stats.in_use_connections || 'N/A';
                if (available) available.textContent = data.connection_pool.pool_stats.available_connections || 'N/A';
                if (created) created.textContent = data.connection_pool.pool_stats.created_connections || 'N/A';
            }

            // Update last updated time
            const lastUpdated = document.getElementById('draft-cache-last-updated');
            if (lastUpdated) lastUpdated.textContent = 'Last updated: ' + new Date().toLocaleTimeString();
        })
        .catch(error => {
            console.error('Error updating draft cache stats:', error);
        });
}

/**
 * Warm cache for a specific league
 */
function warmCache(leagueName) {
    fetch(`/admin/redis/warm-draft-cache/${encodeURIComponent(leagueName)}`)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Error', 'Error warming cache: ' + data.error, 'error');
                }
            } else {
                if (typeof window.Swal !== 'undefined') {
                    window.Swal.fire('Success', `Cache warming initiated for ${leagueName}`, 'success');
                }
                updateDraftCacheStats();
            }
        })
        .catch(error => {
            if (typeof window.Swal !== 'undefined') {
                window.Swal.fire('Error', 'Error warming cache: ' + error, 'error');
            }
        });
}

/**
 * Invalidate all draft cache
 */
function invalidateAllCache() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Clear All Draft Cache?',
            text: 'This will cause temporary performance impact during the next draft loads.',
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: '#d33',
            cancelButtonColor: '#6c757d',
            confirmButtonText: 'Yes, clear cache'
        }).then((result) => {
            if (result.isConfirmed) {
                window.Swal.fire({
                    title: 'Clearing Cache...',
                    allowOutsideClick: false,
                    didOpen: () => {
                        window.Swal.showLoading();

                        fetch('/admin-panel/cache-management/clear', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-Requested-With': 'XMLHttpRequest'
                            },
                            body: JSON.stringify({ cache_type: 'all' })
                        })
                        .then(response => response.json())
                        .then(data => {
                            if (data.success) {
                                window.Swal.fire('Cache Cleared!', data.message || 'All cache has been invalidated.', 'success');
                                updateDraftCacheStats();
                            } else {
                                window.Swal.fire('Error', data.message || 'Failed to clear cache', 'error');
                            }
                        })
                        .catch(error => {
                            console.error('[invalidateAllCache] Error:', error);
                            window.Swal.fire('Error', 'Failed to clear cache. Check server connectivity.', 'error');
                        });
                    }
                });
            }
        });
    }
}

/**
 * Toggle auto-refresh for draft cache stats
 */
function toggleAutoRefresh(enabled) {
    if (enabled) {
        autoRefreshInterval = setInterval(updateDraftCacheStats, 10000);
    } else {
        if (autoRefreshInterval) {
            clearInterval(autoRefreshInterval);
            autoRefreshInterval = null;
        }
    }
}

// EVENT DELEGATION HANDLERS
// ============================================================================

/**
 * Refresh Draft Cache Stats
 */
window.EventDelegation.register('refresh-draft-cache', function(element, e) {
    e.preventDefault();
    updateDraftCacheStats();
}, { preventDefault: true });

/**
 * Invalidate All Cache
 */
window.EventDelegation.register('invalidate-all-cache', function(element, e) {
    e.preventDefault();
    invalidateAllCache();
}, { preventDefault: true });

/**
 * Warm Cache for League
 */
window.EventDelegation.register('warm-cache', function(element, e) {
    e.preventDefault();
    const leagueName = element.dataset.league;
    if (leagueName) {
        warmCache(leagueName);
    } else {
        console.error('[warm-cache] Missing league name');
    }
}, { preventDefault: true });

/**
 * Toggle Auto Refresh
 */
window.EventDelegation.register('toggle-draft-cache-auto-refresh', function(element, e) {
    const enabled = element.checked;
    toggleAutoRefresh(enabled);
});

// INITIALIZATION
// ============================================================================

window.InitSystem.register('draftCacheStats', function() {
    // Check if we're on the draft cache stats page
    const refreshBtn = document.getElementById('draft-cache-refresh-btn');
    const invalidateBtn = document.getElementById('invalidate-all-btn');
    const autoRefreshCheckbox = document.getElementById('draft-cache-auto-refresh');

    if (!refreshBtn && !invalidateBtn) {
        return; // Not on this page
    }

    // Add data-action to buttons if they don't have them
    if (refreshBtn && !refreshBtn.dataset.action) {
        refreshBtn.dataset.action = 'refresh-draft-cache';
    }

    if (invalidateBtn && !invalidateBtn.dataset.action) {
        invalidateBtn.dataset.action = 'invalidate-all-cache';
    }

    if (autoRefreshCheckbox && !autoRefreshCheckbox.dataset.action) {
        autoRefreshCheckbox.dataset.action = 'toggle-draft-cache-auto-refresh';
    }

    // Add data-action to warm cache buttons
    document.querySelectorAll('.warm-cache-btn').forEach(btn => {
        if (!btn.dataset.action) {
            btn.dataset.action = 'warm-cache';
        }
    });

    // Initialize auto-refresh if checkbox is checked
    if (autoRefreshCheckbox && autoRefreshCheckbox.checked) {
        toggleAutoRefresh(true);
    }

    // Initial load
    updateDraftCacheStats();

    console.log('[draftCacheStats] Initialized');
}, { priority: 50 });

// Export functions for global access
window.updateDraftCacheStats = updateDraftCacheStats;
window.warmCache = warmCache;
window.invalidateAllCache = invalidateAllCache;

// Handlers loaded
