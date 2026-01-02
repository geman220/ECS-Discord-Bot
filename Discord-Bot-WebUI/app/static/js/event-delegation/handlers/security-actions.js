import { EventDelegation } from '../core.js';
import { ModalManager } from '../../modal-manager.js';

/**
 * Security Dashboard Action Handlers
 * Handles IP banning and security monitoring
 */

// SECURITY DASHBOARD ACTIONS
// ============================================================================

/**
 * Refresh Security Stats Action
 * Refreshes all security dashboard data (stats, events, logs)
 */
EventDelegation.register('refresh-stats', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.refreshAll === 'function') {
        await window.securityDashboard.refreshAll();
    } else {
        console.error('[refresh-stats] SecurityDashboard instance not available');
    }
});

/**
 * Refresh Security Events Action
 * Reloads recent security events list
 */
EventDelegation.register('refresh-events', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.loadSecurityEvents === 'function') {
        await window.securityDashboard.loadSecurityEvents();
    } else {
        console.error('[refresh-events] SecurityDashboard instance not available');
    }
});

/**
 * Refresh Security Logs Action
 * Reloads security logs display
 * Note: Renamed from 'refresh-logs' to avoid conflict with monitoring-handlers.js
 */
EventDelegation.register('refresh-security-logs', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.loadSecurityLogs === 'function') {
        await window.securityDashboard.loadSecurityLogs();
    } else {
        console.error('[refresh-security-logs] SecurityDashboard instance not available');
    }
});

/**
 * Unban IP Action
 * Removes an IP address from the blacklist
 */
EventDelegation.register('unban-ip', async function(element, e) {
    e.preventDefault();

    const ip = element.dataset.ip;

    if (!ip) {
        console.error('[unban-ip] Missing IP address');
        return;
    }

    if (window.securityDashboard && typeof window.securityDashboard.unbanIP === 'function') {
        await window.securityDashboard.unbanIP(ip, element);
    } else {
        console.error('[unban-ip] SecurityDashboard instance not available');
    }
});

/**
 * Quick Ban IP Action
 * Quickly bans an IP from the security events list
 */
EventDelegation.register('ban-ip-quick', async function(element, e) {
    e.preventDefault();

    const ip = element.dataset.ip;
    const reason = element.dataset.reason || 'Security event';

    if (!ip) {
        console.error('[ban-ip-quick] Missing IP address');
        return;
    }

    if (window.securityDashboard && typeof window.securityDashboard.quickBanIP === 'function') {
        await window.securityDashboard.quickBanIP(ip, reason);
    } else {
        console.error('[ban-ip-quick] SecurityDashboard instance not available');
    }
});

/**
 * Ban IP Confirm Action
 * Confirms and submits the ban IP form from the modal
 */
EventDelegation.register('ban-ip-confirm', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.banIP === 'function') {
        await window.securityDashboard.banIP();
    } else {
        console.error('[ban-ip-confirm] SecurityDashboard instance not available');
    }
});

/**
 * Clear All Bans Action
 * Removes all IP addresses from the blacklist
 */
EventDelegation.register('clear-all-bans', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.clearAllBans === 'function') {
        await window.securityDashboard.clearAllBans();
    } else if (typeof clearAllBans === 'function') {
        // Admin panel version
        await clearAllBans();
    } else {
        console.error('[clear-all-bans] No clearAllBans function available');
    }
});

/**
 * Show Ban IP Modal Action (Admin Panel)
 * Opens the modal to manually ban an IP address
 */
EventDelegation.register('show-ban-ip-modal', function(element, e) {
    e.preventDefault();

    if (typeof showBanIpModal === 'function') {
        showBanIpModal();
    } else if (window.bootstrap) {
        // Fallback: directly show the modal
        const modalElement = document.getElementById('banIpModal');
        if (modalElement) {
            ModalManager.show('banIpModal');
        }
    } else {
        console.error('[show-ban-ip-modal] No showBanIpModal function available');
    }
});

/**
 * Ban IP Action (Admin Panel)
 * Submits the ban IP form from the admin panel modal
 */
EventDelegation.register('ban-ip', async function(element, e) {
    e.preventDefault();

    if (typeof banIp === 'function') {
        await banIp();
    } else if (window.securityDashboard && typeof window.securityDashboard.banIP === 'function') {
        await window.securityDashboard.banIP();
    } else {
        console.error('[ban-ip] No banIp function available');
    }
});

/**
 * Clear Rate Limit Action
 * Clears rate limit counters for a specific IP address
 * This resets request counts and attack counts, allowing the IP to make requests again
 */
EventDelegation.register('clear-rate-limit', async function(element, e) {
    e.preventDefault();

    const ip = element.dataset.ip;

    if (!ip) {
        console.error('[clear-rate-limit] Missing IP address');
        return;
    }

    if (window.securityDashboard && typeof window.securityDashboard.clearRateLimit === 'function') {
        await window.securityDashboard.clearRateLimit(ip, element);
    } else {
        console.error('[clear-rate-limit] SecurityDashboard instance not available');
    }
});

/**
 * Clear All Rate Limits Action
 * Clears all rate limit counters for all IPs
 * This resets all request counts and attack counts (but not bans)
 */
EventDelegation.register('clear-all-rate-limits', async function(element, e) {
    e.preventDefault();

    if (window.securityDashboard && typeof window.securityDashboard.clearAllRateLimits === 'function') {
        await window.securityDashboard.clearAllRateLimits();
    } else {
        console.error('[clear-all-rate-limits] SecurityDashboard instance not available');
    }
});

// ============================================================================

console.log('[EventDelegation] Security handlers loaded');
