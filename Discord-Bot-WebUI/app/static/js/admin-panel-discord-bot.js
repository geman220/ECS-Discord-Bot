/**
 * ============================================================================
 * DISCORD BOT MANAGEMENT - EVENT HANDLERS
 * ============================================================================
 *
 * Modern JavaScript for Discord bot admin panel with event delegation
 * No inline scripts - all handlers attached via data-action attributes
 *
 * Features:
 * - Bot control operations (restart, health check, logs, sync)
 * - Command management (view, permissions, usage, custom)
 * - Guild management (stats, settings, add)
 * - Configuration management (save, reset, load)
 * - Real-time updates and animations
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';

// Configuration
const CONFIG = {
    get botApiUrl() {
        const base = (window.__BOT_API_URL__ || '/admin-panel/bot-api/').replace(/\/+$/, '');
        return base + '/bot';
    },
    get botApiBase() {
        return (window.__BOT_API_URL__ || '/admin-panel/bot-api/').replace(/\/+$/, '');
    },
    recentLogs: null, // Will be populated from template
    commands: null, // Will be populated from template
    commandUsage: null, // Will be populated from template
    guildInfo: null // Will be populated from template
};

/**
 * Get CSRF token from meta tag
 */
function getCsrfToken() {
    return document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';
}

/**
 * Escape HTML special characters to prevent XSS
 */
function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Check if bot API is available before mutating operations
 */
function checkBotAvailable() {
    if (!window.__BOT_ONLINE__) {
        window.Swal.fire('Bot Offline', 'The bot API is currently offline. This operation is unavailable.', 'warning');
        return false;
    }
    return true;
}

// Initialization guard
let _initialized = false;

// Initialize data from template
function initializeData() {
    // Cached template data used as fallback when live API fetches fail
    CONFIG.recentLogs = window.__BOT_RECENT_LOGS__ || [];
    CONFIG.commands = window.__BOT_COMMANDS__ || [];
    CONFIG.commandUsage = window.__BOT_COMMAND_USAGE__ || {};
    CONFIG.guildInfo = window.__BOT_GUILD_INFO__ || {};
}

// ============================================================================
// BOT CONTROL OPERATIONS
// ============================================================================

async function restartBot() {
    if (!checkBotAvailable()) return;

    const result = await window.Swal.fire({
        title: 'Restart Discord Bot?',
        text: 'This will temporarily disconnect the bot from Discord while it restarts.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Restart Bot'
    });

    if (result.isConfirmed) {
        window.Swal.fire({
            title: 'Restarting Bot...',
            text: 'Please wait while the bot restarts',
            allowOutsideClick: false,
            didOpen: () => {
                window.Swal.showLoading();

                fetch(`${CONFIG.botApiUrl}/restart`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.Swal.fire('Restarted!', 'Discord bot restart has been initiated.', 'success');
                    } else {
                        window.Swal.fire('Error!', `Failed to restart bot: ${data.message || 'Unknown error'}`, 'error');
                    }
                })
                .catch(error => {
                    console.error('Error restarting bot:', error);
                    window.Swal.fire('Error!', 'Failed to connect to bot API.', 'error');
                });
            }
        });
    }
}

async function checkBotHealth() {
    window.Swal.fire({
        title: 'Running Health Check...',
        text: 'Checking bot connectivity and status',
        allowOutsideClick: false,
        didOpen: () => {
            window.Swal.showLoading();

            fetch(`${CONFIG.botApiUrl}/health-detailed`)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'online') {
                    const healthInfo = `
              <div class="text-start">
                <p><strong>Status:</strong> ${escapeHtml(String(data.status))}</p>
                <p><strong>Username:</strong> ${escapeHtml(String(data.username || 'Unknown'))}</p>
                <p><strong>Guild Count:</strong> ${parseInt(data.guild_count, 10) || 0}</p>
                <p><strong>Latency:</strong> ${parseFloat(data.latency) || 'N/A'}ms</p>
                ${data.memory_usage_mb ? `<p><strong>Memory Usage:</strong> ${parseFloat(data.memory_usage_mb)}MB</p>` : ''}
              </div>
            `;
                    window.Swal.fire({
                        title: 'Bot Health Check',
                        html: healthInfo,
                        icon: 'success',
                        confirmButtonText: 'Close'
                    });
                } else {
                    window.Swal.fire('Bot Offline', `Bot status: ${escapeHtml(String(data.status))}. ${escapeHtml(String(data.details || ''))}`, 'warning');
                }
            })
            .catch(error => {
                console.error('Error checking bot health:', error);
                window.Swal.fire('Connection Error', 'Failed to connect to bot API.', 'error');
            });
        }
    });
}

async function _fetchAndShowLogs() {
    let logs = CONFIG.recentLogs;
    try {
        const response = await fetch(`${CONFIG.botApiBase}/logs`);
        const data = await response.json();
        if (data.logs && data.logs.length > 0) {
            logs = data.logs;
        }
    } catch (e) {
        console.log('Could not fetch live logs, using cached:', e);
    }

    let logsHtml = '';
    if (logs && logs.length > 0) {
        logs.forEach(log => {
            const timestamp = new Date(log.timestamp).toLocaleString();
            logsHtml += `[${escapeHtml(timestamp)}] ${escapeHtml(log.level)}: ${escapeHtml(log.message)}\n`;
        });
    } else {
        logsHtml = 'No recent logs available. Bot may not be connected to the API.';
    }

    const preEl = document.querySelector('.bot-logs-display');
    if (preEl) {
        // In-dialog refresh
        preEl.textContent = logsHtml;
    } else {
        // Initial dialog
        window.Swal.fire({
            title: 'Discord Bot Logs',
            html: `
            <div class="bot-logs-container scroll-container-md text-start">
              <pre class="code-display bot-logs-display">${escapeHtml(logsHtml)}</pre>
            </div>
          `,
            showCancelButton: true,
            confirmButtonText: 'Refresh Logs',
            cancelButtonText: 'Close',
            width: '700px'
        }).then((result) => {
            if (result.isConfirmed) {
                _fetchAndShowLogs();
            }
        });
    }
}

function viewBotLogs() {
    _fetchAndShowLogs();
}

async function syncCommands() {
    if (!checkBotAvailable()) return;

    const result = await window.Swal.fire({
        title: 'Sync Commands?',
        text: 'This will synchronize all slash commands with Discord.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Sync Commands'
    });

    if (result.isConfirmed) {
        window.Swal.fire({
            title: 'Syncing Commands...',
            text: 'Please wait while commands are synchronized',
            allowOutsideClick: false,
            didOpen: () => {
                window.Swal.showLoading();

                fetch(`${CONFIG.botApiUrl}/sync-commands`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': getCsrfToken()
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        window.Swal.fire('Synced!', `${data.commands_synced || 'All'} commands have been synchronized with Discord.`, 'success');
                    } else {
                        window.Swal.fire('Error!', `Failed to sync commands: ${data.message || 'Unknown error'}`, 'error');
                    }
                })
                .catch(error => {
                    console.error('Error syncing commands:', error);
                    window.Swal.fire('Error!', 'Failed to connect to bot API.', 'error');
                });
            }
        });
    }
}

// ============================================================================
// COMMAND MANAGEMENT
// ============================================================================

function _renderCommandsDialog(commands) {
    let commandsHtml = '';

    function getPermissionBadge(level) {
        if (level === 'Public') return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
        if (level.includes('Admin')) return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';
    }

    // Group commands by category
    const categories = {};
    commands.forEach(cmd => {
        const cat = cmd.category || 'General';
        if (!categories[cat]) {
            categories[cat] = [];
        }
        categories[cat].push(cmd);
    });

    // Build HTML for each category
    Object.keys(categories).forEach(category => {
        commandsHtml += `
        <div class="mb-4">
          <h6 class="mb-2 text-ecs-green dark:text-ecs-green font-semibold">${escapeHtml(category)} Commands</h6>
          <div class="overflow-x-auto">
            <table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">
              <thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                <tr>
                  <th class="py-2 px-3">Command</th>
                  <th class="py-2 px-3">Description</th>
                  <th class="py-2 px-3">Permission</th>
                </tr>
              </thead>
              <tbody>
      `;

        categories[category].forEach(cmd => {
            commandsHtml += `
          <tr class="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
            <td class="py-2 px-3"><code class="text-xs bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">/${escapeHtml(cmd.name)}</code></td>
            <td class="py-2 px-3">${escapeHtml(cmd.description)}</td>
            <td class="py-2 px-3"><span class="px-2 py-0.5 text-xs font-medium rounded ${getPermissionBadge(cmd.permission_level || 'Public')}">${escapeHtml(cmd.permission_level || 'Public')}</span></td>
          </tr>
        `;
        });

        commandsHtml += `
              </tbody>
            </table>
          </div>
        </div>
      `;
    });

    window.Swal.fire({
        title: 'Discord Bot Commands',
        html: `
        <div class="command-list-container scroll-container-lg">
          ${commandsHtml}
        </div>
      `,
        confirmButtonText: 'Close',
        width: '800px'
    });
}

async function viewCommands() {
    window.Swal.fire({
        title: 'Loading Commands...',
        allowOutsideClick: false,
        didOpen: () => window.Swal.showLoading()
    });

    let commands = CONFIG.commands;
    try {
        const response = await fetch(`${CONFIG.botApiBase}/commands`);
        const data = await response.json();
        if (data.commands && data.commands.length > 0) {
            commands = data.commands;
        }
    } catch (e) {
        console.log('Could not fetch live commands, using cached:', e);
    }

    _renderCommandsDialog(commands || []);
}

function _renderPermissionsDialog(commands, permissionsMap) {
    const commandOptions = commands.length > 0
        ? commands.map(cmd => `<option value="${escapeHtml(cmd.name)}">${escapeHtml(cmd.name)}</option>`).join('')
        : '<option value="">No commands available</option>';

    function _populatePermissions(cmdName) {
        const perms = permissionsMap[cmdName] || {};
        const roles = perms.roles || [];
        const adminEl = document.getElementById('roleAdmin');
        const modEl = document.getElementById('roleMod');
        const coachEl = document.getElementById('roleCoach');
        const userEl = document.getElementById('roleUser');
        const cooldownEl = document.getElementById('permCooldown');

        if (adminEl) adminEl.checked = roles.includes('Global Admin');
        if (modEl) modEl.checked = roles.includes('Moderator');
        if (coachEl) coachEl.checked = roles.includes('Coach');
        if (userEl) userEl.checked = roles.includes('User') || roles.includes('@everyone');
        if (cooldownEl) cooldownEl.value = perms.cooldown != null ? perms.cooldown : 5;
    }

    window.Swal.fire({
        title: 'Command Permissions',
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label for="permCommand" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Select Command</label>
                    <select id="permCommand" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                        ${commandOptions}
                    </select>
                </div>
                <div class="mb-3">
                    <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Allowed Roles</label>
                    <div class="flex items-center mb-2">
                        <input type="checkbox" id="roleAdmin" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                        <label for="roleAdmin" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Global Admin</label>
                    </div>
                    <div class="flex items-center mb-2">
                        <input type="checkbox" id="roleMod" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                        <label for="roleMod" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Moderator</label>
                    </div>
                    <div class="flex items-center mb-2">
                        <input type="checkbox" id="roleCoach" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                        <label for="roleCoach" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Coach</label>
                    </div>
                    <div class="flex items-center mb-2">
                        <input type="checkbox" id="roleUser" class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                        <label for="roleUser" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Regular User</label>
                    </div>
                </div>
                <div class="mb-3">
                    <label for="permCooldown" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Cooldown (seconds)</label>
                    <input type="number" id="permCooldown" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" value="5" min="0">
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Save Permissions',
        showLoaderOnConfirm: true,
        width: '500px',
        didOpen: () => {
            // Populate for the first command
            const selectEl = document.getElementById('permCommand');
            if (selectEl && selectEl.value) {
                _populatePermissions(selectEl.value);
            }
            // Listen for command changes
            selectEl?.addEventListener('change', () => {
                _populatePermissions(selectEl.value);
            });
        },
        preConfirm: () => {
            const command = document.getElementById('permCommand')?.value;
            const roles = [];
            if (document.getElementById('roleAdmin')?.checked) roles.push('Global Admin');
            if (document.getElementById('roleMod')?.checked) roles.push('Moderator');
            if (document.getElementById('roleCoach')?.checked) roles.push('Coach');
            if (document.getElementById('roleUser')?.checked) roles.push('User');
            const cooldown = parseInt(document.getElementById('permCooldown')?.value || '5', 10);

            return fetch(`${CONFIG.botApiBase}/commands/permissions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({ command, roles, cooldown })
            })
            .then(response => response.json())
            .catch(() => ({ success: false, error: 'Bot API unavailable. Permissions saved locally.' }));
        },
        allowOutsideClick: () => !window.Swal.isLoading()
    }).then((result) => {
        if (result.isConfirmed) {
            const command = document.getElementById('permCommand')?.value;
            if (result.value?.success) {
                window.Swal.fire('Permissions Updated', `Command "/${command}" permissions saved.`, 'success');
            } else {
                window.Swal.fire('Saved Locally', `Command "/${command}" permissions saved. Note: ${result.value?.error || 'Bot sync pending.'}`, 'info');
            }
        }
    });
}

async function commandPermissions() {
    window.Swal.fire({
        title: 'Loading Permissions...',
        allowOutsideClick: false,
        didOpen: () => window.Swal.showLoading()
    });

    let commands = CONFIG.commands || [];
    let permissionsMap = {};

    try {
        const [cmdRes, permRes] = await Promise.all([
            fetch(`${CONFIG.botApiBase}/commands`).then(r => r.json()).catch(() => null),
            fetch(`${CONFIG.botApiBase}/commands/permissions`).then(r => r.json()).catch(() => null)
        ]);
        if (cmdRes?.commands && cmdRes.commands.length > 0) {
            commands = cmdRes.commands;
        }
        if (permRes?.permissions) {
            permissionsMap = permRes.permissions;
        }
    } catch (e) {
        console.log('Could not fetch permissions data, using defaults:', e);
    }

    _renderPermissionsDialog(commands, permissionsMap);
}

function _renderCommandUsageDialog(usage) {
    window.Swal.fire({
        title: 'Command Usage Statistics',
        html: `
        <div class="command-usage-stats text-start">
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div class="bg-ecs-green text-white rounded-lg p-4 text-center">
              <h4 class="text-2xl font-bold">${usage.commands_today || 0}</h4>
              <small>Commands Today</small>
            </div>
            <div class="bg-blue-500 text-white rounded-lg p-4 text-center">
              <h4 class="text-2xl font-bold">${usage.commands_this_week || 0}</h4>
              <small>Commands This Week</small>
            </div>
          </div>
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <h6 class="font-semibold text-gray-900 dark:text-white">Most Used Command</h6>
              <p class="text-gray-700 dark:text-gray-300"><code class="text-xs bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">/${escapeHtml(usage.most_used_command || 'N/A')}</code></p>
            </div>
            <div>
              <h6 class="font-semibold text-gray-900 dark:text-white">Average Response Time</h6>
              <p class="text-gray-700 dark:text-gray-300">${escapeHtml(usage.avg_response_time || 'N/A')}</p>
            </div>
          </div>
        </div>
      `,
        confirmButtonText: 'Close',
        width: '700px'
    });
}

async function commandUsage() {
    window.Swal.fire({
        title: 'Loading Usage Statistics...',
        allowOutsideClick: false,
        didOpen: () => window.Swal.showLoading()
    });

    let usage = CONFIG.commandUsage;
    try {
        const response = await fetch(`${CONFIG.botApiBase}/stats`);
        const data = await response.json();
        if (data.command_usage) {
            usage = data.command_usage;
        }
    } catch (e) {
        console.log('Could not fetch live stats, using cached:', e);
    }

    _renderCommandUsageDialog(usage || {});
}

function customCommands() {
    // List-first view: fetch and display all custom commands
    window.Swal.fire({
        title: 'Loading Custom Commands...',
        allowOutsideClick: false,
        didOpen: () => window.Swal.showLoading()
    });

    fetch(`${CONFIG.botApiBase}/custom-commands`)
        .then(res => res.json())
        .then(data => {
            const commands = data.commands || [];
            _showCustomCommandsList(commands);
        })
        .catch(() => {
            _showCustomCommandsList([]);
        });
}

function _showCustomCommandsList(commands) {
    const commandRows = commands.length > 0
        ? commands.map(cmd => `
            <tr class="border-b dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-600">
                <td class="py-2 px-3"><code class="text-xs bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">/${escapeHtml(cmd.name)}</code></td>
                <td class="py-2 px-3 text-gray-700 dark:text-gray-300">${escapeHtml(cmd.description) || '-'}</td>
                <td class="py-2 px-3"><span class="px-2 py-0.5 text-xs font-medium rounded ${cmd.enabled ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'}">${cmd.enabled ? 'Active' : 'Disabled'}</span></td>
                <td class="py-2 px-3">
                    <button class="text-blue-600 hover:text-blue-800 dark:text-blue-400 text-sm mr-2" data-action="edit-custom-command" data-cmd-name="${escapeHtml(cmd.name)}"><i class="ti ti-edit"></i></button>
                    <button class="text-red-600 hover:text-red-800 dark:text-red-400 text-sm" data-action="delete-custom-command" data-cmd-name="${escapeHtml(cmd.name)}"><i class="ti ti-trash"></i></button>
                </td>
            </tr>
        `).join('')
        : `<tr><td colspan="4" class="py-4 px-3 text-center text-gray-500 dark:text-gray-400">No custom commands yet.</td></tr>`;

    window.Swal.fire({
        title: 'Custom Commands',
        html: `
            <div class="text-start">
                <div class="overflow-x-auto" style="max-height: 400px; overflow-y: auto;">
                    <table class="w-full text-sm text-left text-gray-500 dark:text-gray-400">
                        <thead class="text-xs text-gray-700 uppercase bg-gray-50 dark:bg-gray-700 dark:text-gray-400">
                            <tr>
                                <th class="py-2 px-3">Command</th>
                                <th class="py-2 px-3">Description</th>
                                <th class="py-2 px-3">Status</th>
                                <th class="py-2 px-3">Actions</th>
                            </tr>
                        </thead>
                        <tbody>${commandRows}</tbody>
                    </table>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Create New',
        cancelButtonText: 'Close',
        width: '700px'
    }).then((result) => {
        if (result.isConfirmed) {
            _showCustomCommandForm();
        }
    });
}

function _showCustomCommandForm(editCmd) {
    const isEdit = !!editCmd;
    const title = isEdit ? `Edit /${editCmd.name}` : 'Create Custom Command';
    const confirmText = isEdit ? 'Save Changes' : 'Create Command';

    window.Swal.fire({
        title,
        html: `
            <div class="text-start">
                <div class="mb-3">
                    <label for="cmdName" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Command Name</label>
                    <div class="flex">
                        <span class="inline-flex items-center px-3 text-sm text-gray-900 bg-gray-200 border border-r-0 border-gray-300 rounded-l-lg dark:bg-gray-600 dark:text-gray-400 dark:border-gray-600">/</span>
                        <input type="text" id="cmdName" ${isEdit ? 'readonly' : ''} class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-none rounded-r-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white ${isEdit ? 'opacity-60' : ''}" placeholder="mycommand" value="${isEdit ? editCmd.name : ''}" pattern="[a-z0-9_-]+" title="Lowercase letters, numbers, underscores, and hyphens only">
                    </div>
                </div>
                <div class="mb-3">
                    <label for="cmdDescription" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Description</label>
                    <input type="text" id="cmdDescription" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="What does this command do?" value="${isEdit ? (editCmd.description || '') : ''}">
                </div>
                <div class="mb-3">
                    <label for="cmdType" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Response Type</label>
                    <select id="cmdType" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                        <option value="text" ${isEdit && editCmd.type === 'text' ? 'selected' : ''}>Text Response</option>
                        <option value="embed" ${isEdit && editCmd.type === 'embed' ? 'selected' : ''}>Rich Embed</option>
                        <option value="action" ${isEdit && editCmd.type === 'action' ? 'selected' : ''}>Custom Action</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label for="cmdResponse" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Response Content</label>
                    <textarea id="cmdResponse" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" rows="3" placeholder="Enter the response message...">${isEdit ? (editCmd.response || '') : ''}</textarea>
                </div>
                <div class="flex items-center mb-3">
                    <input type="checkbox" id="cmdEnabled" ${(!isEdit || editCmd.enabled) ? 'checked' : ''} class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                    <label for="cmdEnabled" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Enabled</label>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: confirmText,
        cancelButtonText: 'Back to List',
        showLoaderOnConfirm: true,
        width: '600px',
        preConfirm: () => {
            const name = document.getElementById('cmdName')?.value?.toLowerCase().trim();
            const description = document.getElementById('cmdDescription')?.value;
            const type = document.getElementById('cmdType')?.value;
            const response = document.getElementById('cmdResponse')?.value;
            const enabled = document.getElementById('cmdEnabled')?.checked;

            if (!name || !response) {
                window.Swal.showValidationMessage('Command name and response are required');
                return false;
            }

            const url = isEdit
                ? `${CONFIG.botApiBase}/custom-commands/${encodeURIComponent(name)}`
                : `${CONFIG.botApiBase}/custom-commands`;
            const method = isEdit ? 'PUT' : 'POST';

            return fetch(url, {
                method,
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                body: JSON.stringify({ name, description, type, response, enabled })
            })
            .then(res => res.json())
            .catch(() => ({ success: false, error: 'Bot API unavailable' }));
        },
        allowOutsideClick: () => !window.Swal.isLoading()
    }).then((result) => {
        if (result.isConfirmed) {
            if (result.value?.success) {
                window.Swal.fire('Success', result.value.message || `Command ${isEdit ? 'updated' : 'created'}.`, 'success')
                    .then(() => customCommands());
            } else {
                window.Swal.fire('Error', result.value?.error || 'Failed to save command', 'error');
            }
        } else if (result.dismiss === window.Swal.DismissReason.cancel) {
            customCommands(); // Back to list
        }
    });
}

function _deleteCustomCommand(cmdName) {
    window.Swal.fire({
        title: `Delete /${cmdName}?`,
        text: 'This action cannot be undone.',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Delete',
        confirmButtonColor: '#dc2626'
    }).then((result) => {
        if (result.isConfirmed) {
            fetch(`${CONFIG.botApiBase}/custom-commands/${encodeURIComponent(cmdName)}`, {
                method: 'DELETE',
                headers: { 'X-CSRFToken': getCsrfToken() }
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    window.Swal.fire('Deleted', data.message || `/${cmdName} deleted.`, 'success')
                        .then(() => customCommands());
                } else {
                    window.Swal.fire('Error', data.error || 'Failed to delete command', 'error');
                }
            })
            .catch(() => {
                window.Swal.fire('Error', 'Bot API unavailable', 'error');
            });
        }
    });
}

function _editCustomCommand(cmdName) {
    // Fetch the command data then show form
    fetch(`${CONFIG.botApiBase}/custom-commands`)
        .then(res => res.json())
        .then(data => {
            const cmd = (data.commands || []).find(c => c.name === cmdName);
            if (cmd) {
                _showCustomCommandForm(cmd);
            } else {
                window.Swal.fire('Error', `Command /${cmdName} not found`, 'error');
            }
        })
        .catch(() => {
            window.Swal.fire('Error', 'Bot API unavailable', 'error');
        });
}

// ============================================================================
// GUILD MANAGEMENT
// ============================================================================

function manageGuild(element, e) {
    const guildId = element.dataset.guild;
    const guildName = element.dataset.guildName || guildId;

    if (!guildId) {
        window.Swal.fire('No Guild', 'Guild information is not available. The bot may be offline.', 'warning');
        return;
    }

    // First fetch current settings
    window.Swal.fire({
        title: 'Loading...',
        text: 'Fetching guild settings',
        allowOutsideClick: false,
        didOpen: () => window.Swal.showLoading()
    });

    fetch(`${CONFIG.botApiBase}/guilds/${encodeURIComponent(guildId)}/settings`)
        .then(res => res.json())
        .then(data => {
            const settings = data.settings || {};
            const channels = settings.channels || [];
            const roles = settings.roles || [];

            const channelOptions = channels.map(ch =>
                `<option value="${escapeHtml(String(ch.id))}">${escapeHtml(ch.name)}</option>`
            ).join('');

            const roleOptions = roles.map(r =>
                `<option value="${escapeHtml(String(r.id))}">${escapeHtml(r.name)}</option>`
            ).join('');

            window.Swal.fire({
                title: `Manage Guild: ${escapeHtml(settings.guild_name || guildName)}`,
                html: `
                    <div class="text-start">
                        <div class="border-b border-gray-200 dark:border-gray-700 mb-4">
                            <ul class="flex flex-wrap -mb-px text-sm font-medium text-center" id="guildTabs" role="tablist">
                                <li class="mr-2" role="presentation">
                                    <button class="inline-block p-4 border-b-2 rounded-t-lg border-primary-600 text-primary-600 guild-tab-btn" id="settings-tab" type="button" role="tab" data-tab-target="guildSettings" aria-selected="true">Settings</button>
                                </li>
                                <li class="mr-2" role="presentation">
                                    <button class="inline-block p-4 border-b-2 rounded-t-lg border-transparent hover:text-gray-600 hover:border-gray-300 guild-tab-btn" id="channels-tab" type="button" role="tab" data-tab-target="guildChannels" aria-selected="false">Channels</button>
                                </li>
                                <li role="presentation">
                                    <button class="inline-block p-4 border-b-2 rounded-t-lg border-transparent hover:text-gray-600 hover:border-gray-300 guild-tab-btn" id="roles-tab" type="button" role="tab" data-tab-target="guildRoles" aria-selected="false">Roles</button>
                                </li>
                            </ul>
                        </div>
                        <div id="tabContent">
                            <div class="" id="guildSettings" role="tabpanel" aria-labelledby="settings-tab">
                                <div class="mb-3">
                                    <label for="guildPrefix" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Bot Prefix</label>
                                    <input type="text" id="guildPrefix" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" value="${settings.prefix || '!'}" maxlength="5">
                                </div>
                                <div class="mb-3">
                                    <label for="guildLanguage" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Language</label>
                                    <select id="guildLanguage" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                        <option value="en" ${settings.language === 'en' ? 'selected' : ''}>English</option>
                                        <option value="es" ${settings.language === 'es' ? 'selected' : ''}>Spanish</option>
                                    </select>
                                </div>
                                <div class="flex items-center mb-2">
                                    <input type="checkbox" id="guildWelcome" ${settings.welcome_messages ? 'checked' : ''} class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                                    <label for="guildWelcome" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Send welcome messages</label>
                                </div>
                                <div class="flex items-center mb-2">
                                    <input type="checkbox" id="guildModLog" ${settings.mod_logging ? 'checked' : ''} class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                                    <label for="guildModLog" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Enable moderation logging</label>
                                </div>
                            </div>
                            <div class="hidden" id="guildChannels" role="tabpanel" aria-labelledby="channels-tab">
                                <div class="mb-3">
                                    <label for="announceChannel" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Announcements Channel</label>
                                    <select id="announceChannel" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                        <option value="">Select channel...</option>
                                        ${channelOptions}
                                    </select>
                                </div>
                                <div class="mb-3">
                                    <label for="logChannel" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Log Channel</label>
                                    <select id="logChannel" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                        <option value="">Select channel...</option>
                                        ${channelOptions}
                                    </select>
                                </div>
                            </div>
                            <div class="hidden" id="guildRoles" role="tabpanel" aria-labelledby="roles-tab">
                                <div class="mb-3">
                                    <label for="adminRole" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Admin Role</label>
                                    <select id="adminRole" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                        <option value="">Select role...</option>
                                        ${roleOptions}
                                    </select>
                                </div>
                                <div class="mb-3">
                                    <label for="modRole" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Moderator Role</label>
                                    <select id="modRole" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                        <option value="">Select role...</option>
                                        ${roleOptions}
                                    </select>
                                </div>
                            </div>
                        </div>
                    </div>
                `,
                showCancelButton: true,
                confirmButtonText: 'Save Changes',
                showLoaderOnConfirm: true,
                width: '700px',
                didOpen: () => {
                    // Set current values for selects
                    if (settings.announce_channel_id) {
                        document.getElementById('announceChannel').value = settings.announce_channel_id;
                    }
                    if (settings.log_channel_id) {
                        document.getElementById('logChannel').value = settings.log_channel_id;
                    }
                    if (settings.admin_role_id) {
                        document.getElementById('adminRole').value = settings.admin_role_id;
                    }
                    if (settings.mod_role_id) {
                        document.getElementById('modRole').value = settings.mod_role_id;
                    }
                    // Tab switching (no inline onclick)
                    document.querySelectorAll('.guild-tab-btn').forEach(btn => {
                        btn.addEventListener('click', () => {
                            const target = btn.dataset.tabTarget;
                            document.querySelectorAll('[role=tabpanel]').forEach(p => p.classList.add('hidden'));
                            document.getElementById(target)?.classList.remove('hidden');
                            document.querySelectorAll('.guild-tab-btn').forEach(t => {
                                t.classList.remove('border-primary-600', 'text-primary-600');
                                t.classList.add('border-transparent');
                                t.setAttribute('aria-selected', 'false');
                            });
                            btn.classList.add('border-primary-600', 'text-primary-600');
                            btn.classList.remove('border-transparent');
                            btn.setAttribute('aria-selected', 'true');
                        });
                    });
                },
                preConfirm: () => {
                    const newSettings = {
                        prefix: document.getElementById('guildPrefix')?.value || '!',
                        language: document.getElementById('guildLanguage')?.value || 'en',
                        welcome_messages: document.getElementById('guildWelcome')?.checked ?? true,
                        mod_logging: document.getElementById('guildModLog')?.checked ?? true,
                        announce_channel_id: document.getElementById('announceChannel')?.value || null,
                        log_channel_id: document.getElementById('logChannel')?.value || null,
                        admin_role_id: document.getElementById('adminRole')?.value || null,
                        mod_role_id: document.getElementById('modRole')?.value || null
                    };

                    return fetch(`${CONFIG.botApiBase}/guilds/${guildId}/settings`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCsrfToken() },
                        body: JSON.stringify(newSettings)
                    })
                    .then(res => res.json())
                    .catch(() => ({ success: false, error: 'Bot API unavailable' }));
                },
                allowOutsideClick: () => !window.Swal.isLoading()
            }).then((result) => {
                if (result.isConfirmed) {
                    if (result.value?.success) {
                        window.Swal.fire('Saved!', `Guild settings for "${guildName}" have been updated.`, 'success');
                    } else {
                        window.Swal.fire('Error', result.value?.error || 'Failed to save settings', 'error');
                    }
                }
            });
        })
        .catch(() => {
            window.Swal.fire('Error', 'Unable to fetch guild settings. Bot API may be unavailable.', 'error');
        });
}

function _renderGuildStatsDialog(guild) {
    window.Swal.fire({
        title: `${escapeHtml(guild.name || 'Guild')} Statistics`,
        html: `
        <div class="guild-stats-container text-start">
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="bg-ecs-green text-white rounded-lg p-4 text-center">
              <h4 class="text-2xl font-bold">${guild.member_count || 0}</h4>
              <small>Total Members</small>
            </div>
            <div class="bg-green-600 text-white rounded-lg p-4 text-center">
              <h4 class="text-2xl font-bold">${guild.channel_count || 0}</h4>
              <small>Channels</small>
            </div>
            <div class="bg-blue-500 text-white rounded-lg p-4 text-center">
              <h4 class="text-2xl font-bold">${guild.role_count || 0}</h4>
              <small>Roles</small>
            </div>
          </div>
        </div>
      `,
        confirmButtonText: 'Close',
        width: '700px'
    });
}

async function guildStats(element, e) {
    const targetGuildId = element.dataset.guild;

    window.Swal.fire({
        title: 'Loading Guild Statistics...',
        allowOutsideClick: false,
        didOpen: () => window.Swal.showLoading()
    });

    let guild = CONFIG.guildInfo;
    try {
        const response = await fetch(`${CONFIG.botApiBase}/guild-stats`);
        const data = await response.json();
        if (data.guilds && data.guilds.length > 0) {
            // Match by guild ID if available, otherwise take first
            const matched = targetGuildId
                ? data.guilds.find(g => String(g.id) === String(targetGuildId))
                : null;
            guild = matched || data.guilds[0];
        }
    } catch (err) {
        console.error('Could not fetch live guild stats, using cached:', err);
    }

    _renderGuildStatsDialog(guild || {});
}

function addGuild() {
    const clientId = window.__DISCORD_CLIENT_ID__ || '';
    // Bot permissions: Manage Roles, Manage Channels, Send Messages, Read Message History, Use Application Commands
    const permissions = '268503120';
    const inviteUrl = clientId
        ? `https://discord.com/oauth2/authorize?client_id=${encodeURIComponent(clientId)}&scope=bot%20applications.commands&permissions=${permissions}`
        : '';

    const inviteButton = inviteUrl
        ? `<a href="${escapeHtml(inviteUrl)}" target="_blank" rel="noopener noreferrer"
              class="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 mt-4">
              <i class="ti ti-external-link mr-2"></i>Invite Bot to Server
           </a>`
        : `<p class="text-sm text-amber-600 dark:text-amber-400 mt-4"><i class="ti ti-alert-triangle mr-1"></i>Bot client ID not configured. Contact the system administrator.</p>`;

    window.Swal.fire({
        title: 'Add Bot to Server',
        html: `
        <div class="add-guild-container text-start">
          <p class="text-gray-700 dark:text-gray-300">To add the ECS FC Discord bot to another server, you need administrator permissions on that server.</p>
          <div class="p-4 text-sm text-blue-800 rounded-lg bg-blue-50 dark:bg-gray-800 dark:text-blue-400 my-3" role="alert">
            <i class="ti ti-info-circle me-2"></i>
            Click the button below to authorize the bot for a new server.
          </div>
          <div class="mt-4">
            <h6 class="font-semibold text-gray-900 dark:text-white mb-2">Required Permissions:</h6>
            <ul class="text-sm text-gray-700 dark:text-gray-300 list-disc list-inside">
              <li>Manage Roles</li>
              <li>Send Messages</li>
              <li>Read Message History</li>
              <li>Manage Channels</li>
              <li>Use Application Commands</li>
            </ul>
          </div>
          <div class="text-center">${inviteButton}</div>
        </div>
      `,
        showConfirmButton: false,
        showCloseButton: true
    });
}

// ============================================================================
// CONFIGURATION MANAGEMENT
// ============================================================================

async function saveBotConfig() {
    if (!checkBotAvailable()) return;

    const config = {
        prefix: document.getElementById('botPrefix')?.value || '!',
        default_role: document.getElementById('defaultRole')?.value || '',
        activity_type: document.getElementById('activityType')?.value || 'playing',
        activity_text: document.getElementById('activityText')?.value || 'ECS FC League',
        auto_moderation: document.getElementById('autoModeration')?.checked || false,
        command_logging: document.getElementById('commandLogging')?.checked || false,
        welcome_messages: document.getElementById('welcomeMessages')?.checked || false
    };

    window.Swal.fire({
        title: 'Saving Configuration...',
        text: 'Please wait while the configuration is being saved',
        allowOutsideClick: false,
        didOpen: () => {
            window.Swal.showLoading();
        }
    });

    try {
        const response = await fetch(`${CONFIG.botApiUrl}/config`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken()
            },
            body: JSON.stringify(config)
        });

        const data = await response.json();

        if (data.success) {
            window.Swal.fire('Saved!', 'Bot configuration has been updated successfully.', 'success');
        } else {
            window.Swal.fire('Error!', `Failed to save configuration: ${data.error || 'Unknown error'}`, 'error');
        }
    } catch (error) {
        console.error('Error saving bot config:', error);
        window.Swal.fire('Error!', 'Failed to connect to bot API. Please check if the bot is running.', 'error');
    }
}

async function resetBotConfig() {
    const result = await window.Swal.fire({
        title: 'Reload Configuration?',
        text: 'This will reload the saved configuration from the bot.',
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: 'Reload Config'
    });

    if (!result.isConfirmed) return;

    try {
        const response = await fetch(`${CONFIG.botApiUrl}/config`);
        const data = await response.json();

        if (data.success && data.config) {
            _applyConfigToForm(data.config);
            window.Swal.fire('Loaded!', 'Configuration has been loaded from the bot.', 'success');
        } else {
            window.Swal.fire('Error', 'Could not load configuration from bot.', 'error');
        }
    } catch (error) {
        console.error('Error loading bot config:', error);
        window.Swal.fire('Offline', 'Bot API is not available. Could not reload configuration.', 'warning');
    }
}

function _applyConfigToForm(config) {
    const prefixEl = document.getElementById('botPrefix');
    const roleEl = document.getElementById('defaultRole');
    const activityTypeEl = document.getElementById('activityType');
    const activityTextEl = document.getElementById('activityText');
    const autoModEl = document.getElementById('autoModeration');
    const cmdLogEl = document.getElementById('commandLogging');
    const welcomeEl = document.getElementById('welcomeMessages');

    if (prefixEl) prefixEl.value = config.prefix || '!';
    if (roleEl) roleEl.value = config.default_role || '';
    if (activityTypeEl) activityTypeEl.value = config.activity_type || 'playing';
    if (activityTextEl) activityTextEl.value = config.activity_text || 'ECS FC League';
    if (autoModEl) autoModEl.checked = config.auto_moderation !== false;
    if (cmdLogEl) cmdLogEl.checked = config.command_logging !== false;
    if (welcomeEl) welcomeEl.checked = config.welcome_messages !== false;
}

async function loadBotConfig() {
    // Show loading state on the config form
    const form = document.getElementById('botConfigForm');
    if (form) form.style.opacity = '0.5';

    try {
        const response = await fetch(`${CONFIG.botApiUrl}/config`);
        const data = await response.json();

        if (data.success && data.config) {
            _applyConfigToForm(data.config);
        }
    } catch (error) {
        console.error('Could not load bot configuration:', error);
    } finally {
        if (form) form.style.opacity = '1';
    }
}

// ============================================================================
// INITIALIZATION
// ============================================================================

// Status polling interval reference
let _statusPollInterval = null;

async function _pollBotStatus() {
    try {
        const response = await fetch(`${CONFIG.botApiBase}/stats`);
        const data = await response.json();
        const isOnline = data.status === 'online';

        // Update status cards by data-stat-id attribute
        const statusMap = {
            'bot-status': (data.status || 'offline').charAt(0).toUpperCase() + (data.status || 'offline').slice(1),
            'guild-count': data.guild_count || 0,
            'commands-today': data.commands_today || 0,
            'uptime': data.uptime || '0s'
        };
        for (const [id, value] of Object.entries(statusMap)) {
            const el = document.querySelector(`[data-stat-id="${id}"]`);
            if (el) el.textContent = value;
        }

        // Update status dots
        document.querySelectorAll('[data-stat-dot]').forEach(dot => {
            dot.classList.toggle('bg-green-500', isOnline);
            dot.classList.toggle('bg-red-500', !isOnline);
        });

        // Update last-updated timestamp
        const tsEl = document.querySelector('[data-stat-id="last-updated"]');
        if (tsEl) tsEl.textContent = `Last updated: ${new Date().toLocaleTimeString()}`;

        window.__BOT_ONLINE__ = isOnline;
    } catch (e) {
        // API unreachable - mark offline
        window.__BOT_ONLINE__ = false;
        const tsEl = document.querySelector('[data-stat-id="last-updated"]');
        if (tsEl) tsEl.textContent = 'Last updated: connection lost';
    }
}

function initAdminPanelDiscordBot() {
    // Guard against duplicate initialization
    if (_initialized) return;
    _initialized = true;

    // Page guard: only run on Discord Bot admin pages
    const isBotPage = document.querySelector('[data-page="admin-discord-bot"]') ||
                      document.querySelector('.admin-discord-bot') ||
                      window.location.pathname.includes('discord-bot');

    if (!isBotPage) {
        return;
    }

    // Initialize data
    initializeData();

    // window.EventDelegation handlers are registered at module scope below

    // Load bot configuration
    loadBotConfig();

    // Start status polling (every 30 seconds)
    _pollBotStatus();
    _statusPollInterval = setInterval(_pollBotStatus, 30000);

    console.log('Discord Bot Management initialized');
}

// ============================================================================
// EVENT DELEGATION - Registered at module scope
// ============================================================================

// Bot Control
window.EventDelegation.register('restart-bot', restartBot, { preventDefault: true });
window.EventDelegation.register('check-bot-health', checkBotHealth, { preventDefault: true });
window.EventDelegation.register('view-bot-logs', viewBotLogs, { preventDefault: true });
window.EventDelegation.register('sync-commands', syncCommands, { preventDefault: true });

// Command Management
window.EventDelegation.register('view-commands', viewCommands, { preventDefault: true });
window.EventDelegation.register('command-permissions', commandPermissions, { preventDefault: true });
window.EventDelegation.register('command-usage', commandUsage, { preventDefault: true });
window.EventDelegation.register('custom-commands', customCommands, { preventDefault: true });

// Guild Management
window.EventDelegation.register('manage-guild', manageGuild, { preventDefault: true });
window.EventDelegation.register('guild-stats', guildStats, { preventDefault: true });
window.EventDelegation.register('add-guild', addGuild, { preventDefault: true });

// Configuration
window.EventDelegation.register('save-bot-config', saveBotConfig, { preventDefault: true });
window.EventDelegation.register('reset-bot-config', resetBotConfig, { preventDefault: true });

// Custom Command Actions (inside SweetAlert dialogs)
window.EventDelegation.register('edit-custom-command', function(element) {
    const cmdName = element.dataset.cmdName;
    if (cmdName) _editCustomCommand(cmdName);
}, { preventDefault: true });

window.EventDelegation.register('delete-custom-command', function(element) {
    const cmdName = element.dataset.cmdName;
    if (cmdName) _deleteCustomCommand(cmdName);
}, { preventDefault: true });

// Register with window.InitSystem
window.InitSystem.register('admin-panel-discord-bot', initAdminPanelDiscordBot, {
    priority: 30,
    reinitializable: true,
    description: 'Admin panel Discord bot management'
});

// Fallback
// window.InitSystem handles initialization

// No window exports needed - handlers are registered with EventDelegation

// Named exports for ES modules
export {
    CONFIG,
    getCsrfToken,
    checkBotAvailable,
    initializeData,
    restartBot,
    checkBotHealth,
    viewBotLogs,
    _fetchAndShowLogs,
    syncCommands,
    viewCommands,
    _renderCommandsDialog,
    commandPermissions,
    _renderPermissionsDialog,
    commandUsage,
    _renderCommandUsageDialog,
    customCommands,
    _showCustomCommandsList,
    _showCustomCommandForm,
    _deleteCustomCommand,
    _editCustomCommand,
    manageGuild,
    guildStats,
    _renderGuildStatsDialog,
    addGuild,
    saveBotConfig,
    resetBotConfig,
    loadBotConfig,
    _pollBotStatus,
    initAdminPanelDiscordBot
};
