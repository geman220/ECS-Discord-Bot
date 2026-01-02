/**
 * ============================================================================
 * ADMIN DISCORD OVERVIEW - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles Discord overview page interactions using data-attribute hooks
 * Follows event delegation pattern with window.InitSystem registration
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';

// CSRF Token
const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

// Store URLs from data attributes
let statsApiUrl = '';
let refreshUnknownUrl = '';
let massSyncUrl = '';

/**
 * Initialize Discord overview module
 */
function init() {
    // Get URLs from data attributes on body or config element
    const configEl = document.querySelector('[data-discord-overview-config]');
    if (configEl) {
        statsApiUrl = configEl.dataset.statsApiUrl || '';
        refreshUnknownUrl = configEl.dataset.refreshUnknownUrl || '';
        massSyncUrl = configEl.dataset.massSyncUrl || '';
    }

    injectSpinAnimation();
    initializeEventDelegation();
}

/**
 * Inject spin animation CSS
 */
function injectSpinAnimation() {
    if (document.getElementById('spin-animation-style')) return;

    const style = document.createElement('style');
    style.id = 'spin-animation-style';
    style.textContent = `
        .spin { animation: spin 1s linear infinite; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
    `;
    document.head.appendChild(style);
}

/**
 * Initialize event delegation for all interactive elements
 */
function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;

        switch (action) {
            case 'refresh-stats':
                refreshStats();
                break;
            case 'refresh-unknown-status':
                refreshUnknownStatus();
                break;
            case 'mass-sync-roles':
                massSyncRoles();
                break;
        }
    });

    // Also handle by ID for backward compatibility
    const refreshStatsBtn = document.getElementById('refresh-stats');
    if (refreshStatsBtn && !refreshStatsBtn.hasAttribute('data-action')) {
        refreshStatsBtn.addEventListener('click', refreshStats);
    }

    const refreshUnknownBtn = document.getElementById('refresh-unknown-btn');
    if (refreshUnknownBtn && !refreshUnknownBtn.hasAttribute('data-action')) {
        refreshUnknownBtn.addEventListener('click', refreshUnknownStatus);
    }

    const massSyncBtn = document.getElementById('mass-sync-btn');
    if (massSyncBtn && !massSyncBtn.hasAttribute('data-action')) {
        massSyncBtn.addEventListener('click', massSyncRoles);
    }
}

/**
 * Refresh Discord stats
 */
function refreshStats() {
    const btn = document.getElementById('refresh-stats');
    if (!btn) return;

    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="ti ti-loader spin me-2"></i>Refreshing...';
    btn.disabled = true;

    const url = statsApiUrl || window.discordOverviewConfig?.statsApiUrl || '/admin_panel/discord/stats-api';

    fetch(url)
        .then(response => response.json())
        .then(data => {
            if (data.error) {
                showToast('Error: ' + data.error, 'danger');
                return;
            }

            // Update stat elements
            updateStatElement('total-players', data.total_players);
            updateStatElement('in-server', data.in_server);
            updateStatElement('not-in-server', data.not_in_server);
            updateStatElement('unknown-status', data.unknown_status);
            updateStatElement('needs-sync', data.needs_sync);

            const lastUpdated = document.getElementById('last-updated');
            if (lastUpdated) {
                lastUpdated.textContent = 'Updated: ' + new Date().toLocaleTimeString();
            }

            showToast('Stats refreshed', 'success');
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Error refreshing stats', 'danger');
        })
        .finally(() => {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        });
}

/**
 * Update a stat element by ID
 */
function updateStatElement(id, value) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = value;
    }
}

/**
 * Refresh unknown Discord status
 */
function refreshUnknownStatus() {
    const btn = document.getElementById('refresh-unknown-btn');
    if (!btn) return;

    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="ti ti-loader spin me-2"></i>Checking...';
    btn.disabled = true;

    const url = refreshUnknownUrl || window.discordOverviewConfig?.refreshUnknownUrl || '/admin_panel/discord/refresh-unknown-status';

    fetch(url, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        }
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(data.message, 'success');
                refreshStats();
            } else {
                showToast('Error: ' + data.error, 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Error checking status', 'danger');
        })
        .finally(() => {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        });
}

/**
 * Mass sync Discord roles
 */
function massSyncRoles() {
    if (!confirm('This will sync Discord roles for all players. Continue?')) return;

    const btn = document.getElementById('mass-sync-btn');
    if (!btn) return;

    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="ti ti-loader spin me-2"></i>Syncing...';
    btn.disabled = true;

    const url = massSyncUrl || window.discordOverviewConfig?.massSyncUrl || '/admin_panel/discord/mass-sync-roles';

    fetch(url, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        }
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast(data.message, 'success');
            } else {
                showToast('Error: ' + data.error, 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Error syncing roles', 'danger');
        })
        .finally(() => {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        });
}

/**
 * Show toast notification
 */
function showToast(message, type) {
    if (typeof AdminPanel !== 'undefined' && AdminPanel.showMobileToast) {
        AdminPanel.showMobileToast(message, type);
    } else if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            toast: true,
            position: 'top-end',
            icon: type === 'danger' ? 'error' : 'success',
            title: message,
            showConfirmButton: false,
            timer: 3000
        });
    }
}

// Register with window.InitSystem
window.InitSystem.register('admin-discord-overview', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin Discord overview page functionality'
});

// Fallback
// window.InitSystem handles initialization

// Export for ES modules
export {
    init,
    refreshStats,
    refreshUnknownStatus,
    massSyncRoles
};

// Backward compatibility
window.adminDiscordOverviewInit = init;
window.refreshStats = refreshStats;
window.refreshUnknownStatus = refreshUnknownStatus;
window.massSyncRoles = massSyncRoles;
