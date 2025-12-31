/**
 * ============================================================================
 * ADMIN DISCORD PLAYERS - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles Discord players page interactions using data-attribute hooks
 * Follows event delegation pattern with InitSystem registration
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

// Store configuration from data attributes
let updateRolesBaseUrl = '';
let statusFilter = 'all';

/**
 * Initialize Discord players module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-discord-players-config]');
    if (configEl) {
        updateRolesBaseUrl = configEl.dataset.updateRolesBaseUrl || '';
        statusFilter = configEl.dataset.statusFilter || 'all';
    }

    injectSpinAnimation();
    initializeEventDelegation();
    initializePerPageSelect();
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
            case 'update-player-roles':
                const playerId = target.dataset.playerId;
                if (playerId) {
                    updatePlayerRoles(playerId, target);
                }
                break;
        }
    });
}

/**
 * Initialize per-page select handler
 */
function initializePerPageSelect() {
    const perPageSelect = document.getElementById('per-page-select');
    if (perPageSelect) {
        perPageSelect.addEventListener('change', function() {
            const perPage = this.value;
            const baseUrl = window.discordPlayersConfig?.baseUrl || '/admin_panel/discord/players';
            window.location.href = `${baseUrl}?status=${statusFilter}&per_page=${perPage}`;
        });
    }
}

/**
 * Update player Discord roles
 */
function updatePlayerRoles(playerId, btn) {
    if (!btn) return;

    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="ti ti-loader spin"></i>';
    btn.disabled = true;

    // Build URL - try from config first, then data attribute, then default pattern
    let url = '';
    if (updateRolesBaseUrl) {
        url = updateRolesBaseUrl.replace('0', playerId);
    } else if (window.discordPlayersConfig?.updateRolesBaseUrl) {
        url = window.discordPlayersConfig.updateRolesBaseUrl.replace('0', playerId);
    } else {
        url = `/admin_panel/discord/update-player-roles/${playerId}`;
    }

    fetch(url, {
        method: 'POST',
        headers: {
            'X-CSRFToken': csrfToken
        }
    })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showToast('Roles updated successfully', 'success');
            } else {
                showToast('Error: ' + data.error, 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Error updating roles', 'danger');
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
    } else if (typeof Swal !== 'undefined') {
        Swal.fire({
            toast: true,
            position: 'top-end',
            icon: type === 'danger' ? 'error' : 'success',
            title: message,
            showConfirmButton: false,
            timer: 3000
        });
    }
}

// Register with InitSystem
InitSystem.register('admin-discord-players', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin Discord players page functionality'
});

// Fallback for non-module usage
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// Export for ES modules
export {
    init,
    updatePlayerRoles
};

// Backward compatibility
window.adminDiscordPlayersInit = init;
window.updatePlayerRoles = updatePlayerRoles;
