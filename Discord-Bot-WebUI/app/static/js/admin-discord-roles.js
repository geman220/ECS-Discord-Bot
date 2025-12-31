/**
 * ============================================================================
 * ADMIN DISCORD ROLES - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles Discord role sync page interactions using data-attribute hooks
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

// Module state
let activeTaskId = null;

// Store configuration from data attributes
let massSyncUrl = '';
let checkStatusBaseUrl = '';

/**
 * Initialize Discord roles module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-discord-roles-config]');
    if (configEl) {
        massSyncUrl = configEl.dataset.massSyncUrl || '';
        checkStatusBaseUrl = configEl.dataset.checkStatusBaseUrl || '';
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
            case 'start-mass-sync':
                startMassSync();
                break;
            case 'sync-flagged':
                startMassSync(); // Same functionality for now
                break;
        }
    });

    // Also handle by ID for backward compatibility
    const massSyncBtn = document.getElementById('mass-sync-btn');
    if (massSyncBtn && !massSyncBtn.hasAttribute('data-action')) {
        massSyncBtn.addEventListener('click', startMassSync);
    }

    const syncFlaggedBtn = document.getElementById('sync-flagged-btn');
    if (syncFlaggedBtn && !syncFlaggedBtn.hasAttribute('data-action')) {
        syncFlaggedBtn.addEventListener('click', startMassSync);
    }
}

/**
 * Start mass role sync
 */
function startMassSync() {
    if (!confirm('This will sync Discord roles for all players. This may take several minutes. Continue?')) return;

    const btn = document.getElementById('mass-sync-btn');
    if (!btn) return;

    const originalHtml = btn.innerHTML;
    btn.innerHTML = '<i class="ti ti-loader spin me-2"></i>Starting...';
    btn.disabled = true;

    const url = massSyncUrl || window.discordRolesConfig?.massSyncUrl || '/admin_panel/discord/mass-sync-roles';

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
                activeTaskId = data.task_id;

                // Show progress section
                const progressSection = document.getElementById('sync-progress');
                if (progressSection) {
                    progressSection.classList.remove('d-none');
                }

                // Start polling for status
                if (activeTaskId) {
                    pollTaskStatus();
                }
            } else {
                showToast('Error: ' + data.error, 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showToast('Error starting sync', 'danger');
        })
        .finally(() => {
            btn.innerHTML = originalHtml;
            btn.disabled = false;
        });
}

/**
 * Poll task status
 */
function pollTaskStatus() {
    if (!activeTaskId) return;

    // Build URL for task status check
    let url = '';
    if (checkStatusBaseUrl) {
        url = checkStatusBaseUrl.replace('TASK_ID', activeTaskId);
    } else if (window.discordRolesConfig?.checkStatusBaseUrl) {
        url = window.discordRolesConfig.checkStatusBaseUrl.replace('TASK_ID', activeTaskId);
    } else {
        url = `/admin_panel/discord/check-role-status/${activeTaskId}`;
    }

    fetch(url)
        .then(response => response.json())
        .then(data => {
            const statusEl = document.getElementById('sync-status');
            const progressBar = document.getElementById('progress-bar');

            if (data.state === 'COMPLETE') {
                if (progressBar) {
                    progressBar.style.width = '100%';
                    progressBar.textContent = '100%';
                    progressBar.classList.remove('progress-bar-animated');
                }
                if (statusEl) {
                    statusEl.textContent = 'Sync completed successfully!';
                }
                showToast('Sync completed', 'success');
                activeTaskId = null;
            } else if (data.state === 'FAILED') {
                if (progressBar) {
                    progressBar.classList.remove('bg-primary');
                    progressBar.classList.add('bg-danger');
                }
                if (statusEl) {
                    statusEl.textContent = 'Sync failed: ' + data.error;
                }
                showToast('Sync failed', 'danger');
                activeTaskId = null;
            } else if (data.state === 'PENDING') {
                if (statusEl) {
                    statusEl.textContent = 'Processing...';
                }
                setTimeout(pollTaskStatus, 2000);
            }
        })
        .catch(error => {
            console.error('Error polling task status:', error);
            setTimeout(pollTaskStatus, 5000);
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

/**
 * Cleanup function
 */
function cleanup() {
    activeTaskId = null;
}

// Register with InitSystem
InitSystem.register('admin-discord-roles', init, {
    priority: 30,
    reinitializable: true,
    cleanup: cleanup,
    description: 'Admin Discord roles sync page functionality'
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
    cleanup,
    startMassSync,
    pollTaskStatus
};

// Backward compatibility
window.adminDiscordRolesInit = init;
window.startMassSync = startMassSync;
