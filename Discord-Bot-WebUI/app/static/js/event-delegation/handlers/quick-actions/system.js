'use strict';

/**
 * Quick Actions - System Operations
 *
 * Event delegation handlers for system-level quick actions:
 * - Cache clearing
 * - Database health checks
 * - Settings initialization
 * - Bot restart
 *
 * @module quick-actions/system
 */

/**
 * Quick Clear All Cache
 * Clears all cached data from the system (quick actions menu)
 * Note: Renamed from 'clear-cache' to avoid conflict with monitoring-handlers.js
 */
window.EventDelegation.register('quick-clear-cache', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[quick-clear-cache] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Clear All Cache?',
        text: 'This will remove all cached data from the system.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ? window.ECSTheme.getColor('warning') : '#f39c12',
        confirmButtonText: 'Clear All Cache'
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
                            window.Swal.fire('Cleared!', data.message, 'success');
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to clear cache', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[quick-clear-cache] Error:', error);
                        window.Swal.fire('Error', 'Failed to clear cache. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Check Database Health
 * Runs database health checks
 */
window.EventDelegation.register('check-db-health', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[check-db-health] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Checking Database...',
        text: 'Running database health checks',
        allowOutsideClick: false,
        didOpen: () => {
            window.Swal.showLoading();

            fetch('/admin-panel/monitoring/database/health-check', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(response => response.json())
            .then(data => {
                if (data.success || data.status === 'healthy') {
                    window.Swal.fire({
                        title: 'Database Healthy!',
                        html: data.message || 'All database systems are operational.',
                        icon: 'success'
                    });
                } else {
                    window.Swal.fire({
                        title: 'Database Issues Detected',
                        html: data.message || 'Some database checks failed.',
                        icon: 'warning'
                    });
                }
            })
            .catch(error => {
                console.error('[check-db-health] Error:', error);
                window.Swal.fire('Error', 'Failed to check database health.', 'error');
            });
        }
    });
});

/**
 * Initialize Settings
 * Resets admin settings to defaults
 */
window.EventDelegation.register('initialize-settings', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[initialize-settings] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Initialize Admin Settings?',
        text: 'This will reset all admin settings to their default values. This action cannot be undone.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#f39c12',
        confirmButtonText: 'Reset to Defaults'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Initializing Settings...',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/initialize-settings', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire({
                                title: 'Settings Initialized!',
                                html: `<p>${data.message}</p><p class="text-muted small mt-2">${data.settings_count} settings reset to defaults</p>`,
                                icon: 'success'
                            });
                        } else {
                            window.Swal.fire('Error', data.message || 'Failed to initialize settings', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[initialize-settings] Error:', error);
                        window.Swal.fire('Error', 'Failed to initialize settings. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});

/**
 * Restart Bot (Quick Actions)
 * Restarts the Discord bot
 * Note: Renamed from 'restart-bot' to avoid conflict with admin-panel-discord-bot.js
 */
window.EventDelegation.register('quick-restart-bot', function(element, e) {
    e.preventDefault();

    if (typeof window.Swal === 'undefined') {
        console.error('[quick-restart-bot] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Restart Discord Bot?',
        text: 'The bot will be temporarily offline during restart. This may take up to 30 seconds.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonColor: '#dc3545',
        confirmButtonText: 'Restart Bot'
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Restarting Bot...',
                html: '<p>Sending restart signal to Discord bot...</p><p class="text-muted small">This may take a moment</p>',
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();

                    fetch('/admin-panel/api/quick-actions/restart-bot', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            window.Swal.fire({
                                title: 'Bot Restart Initiated!',
                                html: `<p>${data.message}</p><p class="text-muted small mt-2">Method: ${data.method || 'signal'}</p>`,
                                icon: 'success'
                            });
                        } else {
                            window.Swal.fire('Restart Failed', data.message || 'Failed to restart bot', 'error');
                        }
                    })
                    .catch(error => {
                        console.error('[quick-restart-bot] Error:', error);
                        window.Swal.fire('Error', 'Failed to restart bot. Check server connectivity.', 'error');
                    });
                }
            });
        }
    });
});
