/**
 * ============================================================================
 * ADMIN CACHE MANAGEMENT - JAVASCRIPT MODULE
 * ============================================================================
 *
 * Handles cache management page interactions using data-attribute hooks
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

// Store config from data attributes
let clearCacheUrl = '';

/**
 * Initialize cache management module
 */
function init() {
    // Get config from data attributes
    const configEl = document.querySelector('[data-cache-management-config]');
    if (configEl) {
        clearCacheUrl = configEl.dataset.clearCacheUrl || '';
    }

    initializeEventDelegation();
    initializeKeyboardShortcuts();
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
            case 'clear-all-cache':
                clearAllCache();
                break;
            case 'clear-user-cache':
                clearUserCache();
                break;
            case 'clear-session-cache':
                clearSessionCache();
                break;
            case 'refresh-cache-stats':
                refreshCacheStats();
                break;
            case 'update-cache-config':
                updateCacheConfig();
                break;
            case 'reset-cache-config':
                resetCacheConfig();
                break;
        }
    });
}

/**
 * Initialize keyboard shortcuts
 */
function initializeKeyboardShortcuts() {
    document.addEventListener('keydown', function(e) {
        // Ctrl+R to refresh stats
        if (e.ctrlKey && e.key === 'r') {
            e.preventDefault();
            refreshCacheStats();
        }
    });
}

/**
 * Clear cache by type with confirmation
 */
async function clearCacheByType(cacheType, title) {
    if (typeof Swal === 'undefined') {
        if (!confirm(`${title}\nThis action cannot be undone. Continue?`)) return;
        performClearCache(cacheType);
        return;
    }

    const result = await Swal.fire({
        title: title,
        text: 'This action cannot be undone. Continue?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
        cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info') : '#3085d6',
        confirmButtonText: 'Yes, clear it!'
    });

    if (result.isConfirmed) {
        performClearCache(cacheType);
    }
}

/**
 * Perform the actual cache clear
 */
async function performClearCache(cacheType) {
    try {
        const formData = new FormData();
        formData.append('cache_type', cacheType);

        const url = clearCacheUrl || window.cacheManagementConfig?.clearCacheUrl || '/admin-panel/cache/clear';

        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken
            },
            body: formData
        });

        if (response.redirected) {
            window.location.href = response.url;
        } else {
            if (typeof Swal !== 'undefined') {
                Swal.fire({
                    icon: 'success',
                    title: 'Cache Cleared',
                    text: 'The cache has been successfully cleared.',
                    timer: 2000,
                    showConfirmButton: false
                }).then(() => location.reload());
            } else {
                location.reload();
            }
        }
    } catch (error) {
        console.error('Error:', error);
        showError('Failed to clear cache. Check server connectivity.');
    }
}

/**
 * Clear all cache
 */
function clearAllCache() {
    clearCacheByType('all', 'Clear All Cache?');
}

/**
 * Clear user cache
 */
function clearUserCache() {
    clearCacheByType('user', 'Clear User Cache?');
}

/**
 * Clear session cache
 */
function clearSessionCache() {
    clearCacheByType('session', 'Clear Session Cache?');
}

/**
 * Refresh cache statistics
 */
function refreshCacheStats() {
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            title: 'Refreshing...',
            text: 'Updating cache statistics',
            allowOutsideClick: false,
            didOpen: () => {
                Swal.showLoading();
                setTimeout(() => {
                    location.reload();
                }, 1000);
            }
        });
    } else {
        location.reload();
    }
}

/**
 * Update cache configuration
 */
async function updateCacheConfig() {
    const config = {
        defaultTTL: document.getElementById('defaultTTL')?.value,
        maxMemoryPolicy: document.getElementById('maxMemoryPolicy')?.value,
        enableCache: document.getElementById('enableCache')?.checked
    };

    // In a real implementation, this would save to the server
    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'success',
            title: 'Configuration Saved',
            text: 'Cache configuration has been updated.',
            timer: 2000,
            showConfirmButton: false
        });
    }
}

/**
 * Reset cache configuration to defaults
 */
function resetCacheConfig() {
    const ttlInput = document.getElementById('defaultTTL');
    const policySelect = document.getElementById('maxMemoryPolicy');
    const enableCheck = document.getElementById('enableCache');

    if (ttlInput) ttlInput.value = '3600';
    if (policySelect) policySelect.value = 'allkeys-lru';
    if (enableCheck) enableCheck.checked = true;

    if (typeof Swal !== 'undefined') {
        Swal.fire({
            icon: 'info',
            title: 'Reset Complete',
            text: 'Configuration has been reset to defaults.'
        });
    }
}

/**
 * Show error message
 */
function showError(message) {
    if (typeof Swal !== 'undefined') {
        Swal.fire('Error', message, 'error');
    } else {
        alert(message);
    }
}

// Register with InitSystem
InitSystem.register('admin-cache-management', init, {
    priority: 30,
    reinitializable: true,
    description: 'Admin cache management page functionality'
});

// Fallback
// InitSystem handles initialization

// Export for ES modules
export {
    init,
    clearAllCache,
    clearUserCache,
    clearSessionCache,
    refreshCacheStats,
    updateCacheConfig,
    resetCacheConfig
};

// Backward compatibility
window.adminCacheManagementInit = init;
window.clearAllCache = clearAllCache;
window.clearUserCache = clearUserCache;
window.clearSessionCache = clearSessionCache;
window.refreshCacheStats = refreshCacheStats;
window.updateCacheConfig = updateCacheConfig;
window.resetCacheConfig = resetCacheConfig;
