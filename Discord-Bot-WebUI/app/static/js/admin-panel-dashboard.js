/**
 * ============================================================================
 * ADMIN PANEL DASHBOARD - JAVASCRIPT CONTROLLER
 * ============================================================================
 *
 * Handles all interactions for the admin panel dashboard.
 * Uses the centralized window.EventDelegation system for all click handling.
 *
 * Features:
 * - Navigation handling
 * - Modal dialogs (navigation settings, registration settings, etc.)
 * - Task monitoring
 * - Database monitoring
 * - Match reports
 *
 * Architecture:
 * - Registers handlers with window.EventDelegation (no duplicate listeners)
 * - Data-action attribute driven
 * - No inline event handlers
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';

let _initialized = false;
let _navCardsSetup = false;

// ============================================================================
// INITIALIZATION
// ============================================================================

function initAdminPanelDashboard() {
    // Guard against duplicate initialization
    if (_initialized) return;

    // Only initialize if we're on the admin dashboard page
    if (!document.querySelector('.admin-panel-dashboard, [data-page="admin-dashboard"]')) {
        return;
    }

    _initialized = true;

    registerEventHandlers();
    highlightActiveNav();
    setupNavigationCards();

    console.log('[AdminDashboard] Initialized');
}

// ============================================================================
// EVENT REGISTRATION - Now a no-op, handlers registered at module scope
// ============================================================================

function registerEventHandlers() {
    // Handlers are now registered at module scope for proper timing
    // See bottom of file for window.EventDelegation.register() calls
}

function setupNavigationCards() {
    if (_navCardsSetup) return;
    _navCardsSetup = true;

    // Add pointer cursor to navigation cards
    document.querySelectorAll('[data-action="navigate"]').forEach(card => {
        card.style.cursor = 'pointer';
    });
}

// ============================================================================
// NAVIGATION
// ============================================================================

function handleNavigate(element) {
    const url = element.dataset.url;
    if (url) {
        window.location.href = url;
    }
}

function highlightActiveNav() {
    const currentPath = window.location.pathname;
    const navLinks = document.querySelectorAll('.nav-pills .nav-link');

    navLinks.forEach(link => {
        if (currentPath.includes(link.getAttribute('href'))) {
            link.classList.add('active');
        }
    });
}

// ============================================================================
// MODAL: NAVIGATION SETTINGS
// ============================================================================

function openNavigationSettings() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Navigation Settings',
            html: '<div class="flex flex-col items-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status"></div><p class="mt-2 text-gray-600 dark:text-gray-400">Loading navigation settings...</p></div>',
            showConfirmButton: false,
            allowOutsideClick: false
        });

        fetch('/admin-panel/navigation-settings')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showNavigationSettingsModal(data.settings);
                } else {
                    window.Swal.fire('Error', data.message || 'Failed to load navigation settings', 'error');
                }
            })
            .catch(error => {
                console.error('Navigation settings error:', error);
                window.Swal.fire('Error', 'Failed to load navigation settings', 'error');
            });
    }
}

function showNavigationSettingsModal(settings) {
    const html = `
      <div class="text-start">
        <p class="text-blue-600 dark:text-blue-400 mb-3"><i class="ti ti-info-circle me-1"></i>Control which navigation items are visible to non-admin users. Admins can always see all navigation items.</p>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            ${createToggle('teamsNav', 'Teams Navigation', 'Team rosters and management for pl-premier, pl-classic roles', settings.teams_navigation_enabled)}
            ${createToggle('storeNav', 'Store Navigation', 'League store for coaches and admins', settings.store_navigation_enabled)}
            ${createToggle('matchesNav', 'Matches Navigation', 'Match schedules and results', settings.matches_navigation_enabled)}
            ${createToggle('leaguesNav', 'Leagues Navigation', 'League standings and information', settings.leagues_navigation_enabled)}
          </div>
          <div>
            ${createToggle('draftsNav', 'Drafts Navigation', 'Draft system for coaches', settings.drafts_navigation_enabled)}
            ${createToggle('playersNav', 'Players Navigation', 'Player profiles and statistics', settings.players_navigation_enabled)}
            ${createToggle('messagingNav', 'Messaging Navigation', 'Communication tools', settings.messaging_navigation_enabled)}
            ${createToggle('mobileFeaturesNav', 'Mobile Features Navigation', 'Mobile app integration', settings.mobile_features_navigation_enabled)}
          </div>
        </div>
      </div>
    `;

    window.Swal.fire({
        title: 'Navigation Settings',
        html: html,
        width: '800px',
        showCancelButton: true,
        confirmButtonText: 'Save Settings',
        cancelButtonText: 'Cancel',
        showLoaderOnConfirm: true,
        preConfirm: () => saveNavigationSettings(),
        allowOutsideClick: () => !window.Swal.isLoading()
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Settings Saved!',
                text: 'Navigation settings have been updated successfully. Changes will take effect immediately.',
                icon: 'success'
            }).then(() => {
                location.reload();
            });
        }
    });
}

function saveNavigationSettings() {
    const formData = {
        teams_navigation_enabled: document.getElementById('teamsNav').checked,
        store_navigation_enabled: document.getElementById('storeNav').checked,
        matches_navigation_enabled: document.getElementById('matchesNav').checked,
        leagues_navigation_enabled: document.getElementById('leaguesNav').checked,
        drafts_navigation_enabled: document.getElementById('draftsNav').checked,
        players_navigation_enabled: document.getElementById('playersNav').checked,
        messaging_navigation_enabled: document.getElementById('messagingNav').checked,
        mobile_features_navigation_enabled: document.getElementById('mobileFeaturesNav').checked
    };

    return fetch('/admin-panel/navigation-settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify(formData)
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            throw new Error(data.message);
        }
        return data;
    });
}

// ============================================================================
// MODAL: REGISTRATION SETTINGS
// ============================================================================

function openRegistrationSettings() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Registration Settings',
            html: '<div class="flex flex-col items-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status"></div><p class="mt-2 text-gray-600 dark:text-gray-400">Loading registration settings...</p></div>',
            showConfirmButton: false,
            allowOutsideClick: false
        });

        fetch('/admin-panel/registration-settings')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    showRegistrationSettingsModal(data.settings, data.available_roles);
                } else {
                    window.Swal.fire('Error', data.message || 'Failed to load registration settings', 'error');
                }
            })
            .catch(error => {
                console.error('Registration settings error:', error);
                window.Swal.fire('Error', 'Failed to load registration settings', 'error');
            });
    }
}

function showRegistrationSettingsModal(settings, roles) {
    const roleOptions = roles.map(role =>
        `<option value="${role.name}" ${settings.default_user_role === role.name ? 'selected' : ''}>${role.name}</option>`
    ).join('');

    const html = `
      <div class="text-start">
        <p class="text-blue-600 dark:text-blue-400 mb-3"><i class="ti ti-info-circle me-1"></i>Configure registration settings based on your actual onboarding flow. Discord OAuth is the primary login method.</p>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <h6 class="text-ecs-green dark:text-ecs-green mb-3 font-semibold">Registration Control</h6>
            ${createToggle('registrationEnabled', 'Allow New Registration', 'Enable/disable new user registration', settings.registration_enabled)}
            ${createToggle('waitlistEnabled', 'Enable Waitlist', 'Allow waitlist registration when full', settings.waitlist_registration_enabled)}
            ${createToggle('adminApproval', 'Admin Approval Required', 'All new users need admin approval', settings.admin_approval_required)}
            ${createToggle('discordOnly', 'Discord Only Login', 'Only Discord OAuth allowed (FIXED)', true, true)}

            <div class="mb-3">
              <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Default User Role</label>
              <select class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" id="defaultRole">
                ${roleOptions}
              </select>
              <small class="text-gray-500 dark:text-gray-400">Role assigned to new registered users</small>
            </div>
          </div>
          <div>
            <h6 class="text-ecs-green dark:text-ecs-green mb-3 font-semibold">Registration Fields</h6>
            ${createToggle('requireRealName', 'Require Real Name', '', settings.require_real_name)}
            ${createToggle('requireEmail', 'Require Email', '', settings.require_email)}
            ${createToggle('requirePhone', 'Require Phone Number', '', settings.require_phone)}
            ${createToggle('requireLocation', 'Require Location', '', settings.require_location)}
            ${createToggle('requireJerseySize', 'Require Jersey Size', '', settings.require_jersey_size)}
            ${createToggle('requirePositions', 'Require Position Preferences', '', settings.require_position_preferences)}
            ${createToggle('requireAvailability', 'Require Availability Info', '', settings.require_availability)}
            ${createToggle('requireReferee', 'Require Referee Willingness', '', settings.require_referee_willingness)}
          </div>
        </div>
        <div class="p-4 text-sm text-blue-800 rounded-lg bg-blue-50 dark:bg-gray-800 dark:text-blue-400 mt-3" role="alert">
          <small><i class="ti ti-info-circle me-1"></i>These settings reflect your real onboarding form fields. Discord OAuth is your primary authentication method.</small>
        </div>
      </div>
    `;

    window.Swal.fire({
        title: 'Registration Settings',
        html: html,
        width: '900px',
        showCancelButton: true,
        confirmButtonText: 'Save Settings',
        cancelButtonText: 'Cancel',
        showLoaderOnConfirm: true,
        preConfirm: () => saveRegistrationSettings(),
        allowOutsideClick: () => !window.Swal.isLoading()
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire({
                title: 'Settings Saved!',
                text: 'Registration settings have been updated successfully. Changes will affect new registrations immediately.',
                icon: 'success'
            });
        }
    });
}

function saveRegistrationSettings() {
    const formData = {
        registration_enabled: document.getElementById('registrationEnabled').checked,
        waitlist_registration_enabled: document.getElementById('waitlistEnabled').checked,
        admin_approval_required: document.getElementById('adminApproval').checked,
        discord_only_login: true,
        default_user_role: document.getElementById('defaultRole').value,
        require_real_name: document.getElementById('requireRealName').checked,
        require_email: document.getElementById('requireEmail').checked,
        require_phone: document.getElementById('requirePhone').checked,
        require_location: document.getElementById('requireLocation').checked,
        require_jersey_size: document.getElementById('requireJerseySize').checked,
        require_position_preferences: document.getElementById('requirePositions').checked,
        require_availability: document.getElementById('requireAvailability').checked,
        require_referee_willingness: document.getElementById('requireReferee').checked
    };

    return fetch('/admin-panel/registration-settings', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCSRFToken()
        },
        body: JSON.stringify(formData)
    })
    .then(response => response.json())
    .then(data => {
        if (!data.success) {
            throw new Error(data.message);
        }
        return data;
    });
}

// ============================================================================
// MODAL: TASK MONITOR
// ============================================================================

function openTaskMonitor() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Task Monitor',
            html: '<div class="flex flex-col items-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status"></div><p class="mt-2 text-gray-600 dark:text-gray-400">Loading task information...</p></div>',
            width: '800px',
            showConfirmButton: false,
            allowOutsideClick: false
        });

        fetch('/admin-panel/api/task-monitor')
            .then(response => response.json())
            .then(data => {
                showTaskMonitorModal(data);
            })
            .catch(error => {
                console.error('Error loading task monitor:', error);
                window.Swal.fire('Error', 'Failed to load task monitor data', 'error');
            });
    }
}

function showTaskMonitorModal(data) {
    function getTaskStatusBadge(status) {
        if (status === 'active') {
            return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
        }
        return 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
    }

    let tasksHtml = '';
    if (data.tasks && data.tasks.length > 0) {
        data.tasks.forEach(task => {
            tasksHtml += `
          <tr class="border-b dark:border-gray-700">
            <td class="py-2 px-3">${task.name}</td>
            <td class="py-2 px-3"><span class="px-2 py-0.5 text-xs font-medium rounded ${getTaskStatusBadge(task.status)}">${task.status}</span></td>
            <td class="py-2 px-3">${task.started || '-'}</td>
            <td class="py-2 px-3">${task.worker || '-'}</td>
            <td class="py-2 px-3 truncate max-w-xs">${task.args || '-'}</td>
          </tr>
        `;
        });
    } else {
        tasksHtml = '<tr><td colspan="5" class="text-center text-gray-500 dark:text-gray-400 py-4">No active tasks found</td></tr>';
    }

    const html = `
      <div class="text-start">
        <div class="grid grid-cols-1 md:grid-cols-3 gap-4 mb-4">
          <div class="bg-green-600 text-white rounded-lg p-4 text-center">
            <h4 class="text-2xl font-bold">${data.active_count || 0}</h4>
            <small>Active Tasks</small>
          </div>
          <div class="bg-yellow-500 text-white rounded-lg p-4 text-center">
            <h4 class="text-2xl font-bold">${data.scheduled_count || 0}</h4>
            <small>Scheduled Tasks</small>
          </div>
          <div class="bg-blue-500 text-white rounded-lg p-4 text-center">
            <h4 class="text-2xl font-bold">${data.worker_count || 0}</h4>
            <small>Workers</small>
          </div>
        </div>
        <div class="overflow-x-auto">
          <table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">
            <thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
              <tr>
                <th class="py-2 px-3">Task Name</th>
                <th class="py-2 px-3">Status</th>
                <th class="py-2 px-3">Started</th>
                <th class="py-2 px-3">Worker</th>
                <th class="py-2 px-3">Arguments</th>
              </tr>
            </thead>
            <tbody>
              ${tasksHtml}
            </tbody>
          </table>
        </div>
        ${data.message ? `<div class="p-4 text-sm text-blue-800 rounded-lg bg-blue-50 dark:bg-gray-800 dark:text-blue-400 mt-3" role="alert"><small>${data.message}</small></div>` : ''}
        <p class="text-gray-500 dark:text-gray-400 mt-3"><small>Task monitoring shows real-time background processes and scheduled jobs.</small></p>
      </div>
    `;

    window.Swal.fire({
        title: 'Task Monitor',
        html: html,
        width: '900px',
        confirmButtonText: 'Close'
    });
}

// ============================================================================
// MODAL: DATABASE MONITOR
// ============================================================================

function openDatabaseMonitor() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Database Monitor',
            html: '<div class="flex flex-col items-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status"></div><p class="mt-2 text-gray-600 dark:text-gray-400">Loading system information...</p></div>',
            width: '900px',
            showConfirmButton: false,
            allowOutsideClick: false
        });

        fetch('/admin-panel/api/system-status')
            .then(response => response.json())
            .then(data => {
                showDatabaseMonitorModal(data);
            })
            .catch(error => {
                console.error('Error loading database monitor:', error);
                window.Swal.fire('Error', 'Failed to load system monitor data', 'error');
            });
    }
}

function showDatabaseMonitorModal(data) {
    const redisStatusClass = data.services.redis.status === 'online' ? 'bg-green-600' : 'bg-red-600';
    const html = `
      <div class="text-start">
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
          <div class="bg-blue-500 text-white rounded-lg p-4 text-center">
            <h4 class="text-2xl font-bold">${data.system.cpu_percent}%</h4>
            <small>CPU Usage</small>
          </div>
          <div class="bg-green-600 text-white rounded-lg p-4 text-center">
            <h4 class="text-2xl font-bold">${data.system.memory_percent}%</h4>
            <small>Memory Usage</small>
          </div>
          <div class="bg-ecs-green text-white rounded-lg p-4 text-center">
            <h4 class="text-2xl font-bold">${data.services.database.response_time_ms}ms</h4>
            <small>DB Response Time</small>
          </div>
          <div class="${redisStatusClass} text-white rounded-lg p-4 text-center">
            <h4 class="text-2xl font-bold">${data.services.redis.response_time_ms}ms</h4>
            <small>Redis Response</small>
          </div>
        </div>
        <p class="text-gray-500 dark:text-gray-400 mt-3"><small>Real-time system monitoring data updated at ${new Date(data.timestamp).toLocaleString()}.</small></p>
      </div>
    `;

    window.Swal.fire({
        title: 'System Monitor',
        html: html,
        width: '900px',
        confirmButtonText: 'Close'
    });
}

// ============================================================================
// MODAL: MATCH REPORTS
// ============================================================================

function openMatchReports() {
    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
            title: 'Match Reports',
            html: `
            <div class="text-start">
              <p class="text-blue-600 dark:text-blue-400 mb-3"><i class="ti ti-info-circle me-1"></i>Access match reports and statistics.</p>
              <div class="mb-3">
                <strong class="text-gray-900 dark:text-white">Available Reports:</strong>
                <ul class="mt-2 text-gray-700 dark:text-gray-300 list-disc list-inside">
                  <li>Match results are available on the Matches page</li>
                  <li>Team statistics are on individual Team pages</li>
                  <li>Season standings on the Leagues page</li>
                </ul>
              </div>
              <div class="flex gap-2 flex-wrap">
                <a href="/matches" class="px-3 py-2 text-sm font-medium text-ecs-green border border-ecs-green rounded-lg hover:bg-ecs-green hover:text-white transition-colors">
                  <i class="ti ti-calendar me-1"></i>Matches
                </a>
                <a href="/teams" class="px-3 py-2 text-sm font-medium text-blue-600 border border-blue-600 rounded-lg hover:bg-blue-600 hover:text-white transition-colors dark:text-blue-400 dark:border-blue-400">
                  <i class="ti ti-users me-1"></i>Teams
                </a>
                <a href="/leagues" class="px-3 py-2 text-sm font-medium text-green-600 border border-green-600 rounded-lg hover:bg-green-600 hover:text-white transition-colors dark:text-green-400 dark:border-green-400">
                  <i class="ti ti-trophy me-1"></i>Leagues
                </a>
              </div>
            </div>
          `,
            width: '600px',
            confirmButtonText: 'Close'
        });
    }
}

function generateReport() {
    // Navigate to matches page for match-related reports
    window.location.href = '/matches';
}

// ============================================================================
// UTILITIES
// ============================================================================

function createToggle(id, label, description, checked, disabled = false) {
    return `
      <div class="mb-3">
        <label class="relative inline-flex items-start cursor-pointer">
          <input type="checkbox" id="${id}" class="sr-only peer" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
          <div class="w-11 h-6 bg-gray-200 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-ecs-green/25 dark:peer-focus:ring-ecs-green/50 rounded-full peer dark:bg-gray-700 peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all dark:border-gray-600 peer-checked:bg-ecs-green ${disabled ? 'opacity-50 cursor-not-allowed' : ''}"></div>
          <span class="ml-3 text-sm">
            <strong class="font-medium text-gray-900 dark:text-white">${label}</strong>
            ${description ? `<br><small class="text-gray-500 dark:text-gray-400">${description}</small>` : ''}
          </span>
        </label>
      </div>
    `;
}

// getCSRFToken is provided globally by csrf-fetch.js

// ============================================================================
// EVENT DELEGATION - Registered at module scope
// ============================================================================

window.EventDelegation.register('navigate', handleNavigate);
window.EventDelegation.register('open-navigation-settings', openNavigationSettings, { preventDefault: true });
window.EventDelegation.register('open-registration-settings', openRegistrationSettings, { preventDefault: true });
window.EventDelegation.register('open-task-monitor', openTaskMonitor, { preventDefault: true });
window.EventDelegation.register('open-database-monitor', openDatabaseMonitor, { preventDefault: true });
window.EventDelegation.register('open-match-reports', openMatchReports, { preventDefault: true });
window.EventDelegation.register('generate-report', generateReport, { preventDefault: true });

// ============================================================================
// AUTO-INITIALIZE
// ============================================================================

// Register with window.InitSystem
window.InitSystem.register('admin-panel-dashboard', initAdminPanelDashboard, {
    priority: 30,
    reinitializable: true,
    description: 'Admin panel dashboard'
});

// Fallback
// window.InitSystem handles initialization

// No window exports needed - handlers are registered with EventDelegation

// Named exports for ES modules
export {
    initAdminPanelDashboard,
    registerEventHandlers,
    setupNavigationCards,
    handleNavigate,
    highlightActiveNav,
    openNavigationSettings,
    showNavigationSettingsModal,
    saveNavigationSettings,
    openRegistrationSettings,
    showRegistrationSettingsModal,
    saveRegistrationSettings,
    openTaskMonitor,
    showTaskMonitorModal,
    openDatabaseMonitor,
    showDatabaseMonitorModal,
    openMatchReports,
    generateReport,
    createToggle
};
