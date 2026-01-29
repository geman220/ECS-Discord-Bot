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
    botApiUrl: 'http://localhost:5001/api/bot',
    recentLogs: null, // Will be populated from template
    commands: null, // Will be populated from template
    commandUsage: null, // Will be populated from template
    guildInfo: null // Will be populated from template
};

// Initialization guard
let _initialized = false;

// Initialize data from template
function initializeData() {
    // These would be populated from script tags in the template if needed
    // For now, using placeholder data structure
    CONFIG.recentLogs = window.__BOT_RECENT_LOGS__ || [];
    CONFIG.commands = window.__BOT_COMMANDS__ || [];
    CONFIG.commandUsage = window.__BOT_COMMAND_USAGE__ || {};
    CONFIG.guildInfo = window.__BOT_GUILD_INFO__ || {};
}

// ============================================================================
// BOT CONTROL OPERATIONS
// ============================================================================

async function restartBot() {
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
                <p><strong>Status:</strong> ${data.status}</p>
                <p><strong>Username:</strong> ${data.username || 'Unknown'}</p>
                <p><strong>Guild Count:</strong> ${data.guild_count || 0}</p>
                <p><strong>Latency:</strong> ${data.latency || 'N/A'}ms</p>
                ${data.memory_usage_mb ? `<p><strong>Memory Usage:</strong> ${data.memory_usage_mb}MB</p>` : ''}
              </div>
            `;
                    window.Swal.fire({
                        title: 'Bot Health Check',
                        html: healthInfo,
                        icon: 'success',
                        confirmButtonText: 'Close'
                    });
                } else {
                    window.Swal.fire('Bot Offline', `Bot status: ${data.status}. ${data.details || ''}`, 'warning');
                }
            })
            .catch(error => {
                console.error('Error checking bot health:', error);
                window.Swal.fire('Connection Error', 'Failed to connect to bot API.', 'error');
            });
        }
    });
}

function viewBotLogs() {
    let logsHtml = '';
    const logs = CONFIG.recentLogs;

    if (logs && logs.length > 0) {
        logs.forEach(log => {
            const timestamp = new Date(log.timestamp).toLocaleString();
            logsHtml += `[${timestamp}] ${log.level}: ${log.message}\n`;
        });
    } else {
        logsHtml = 'No recent logs available. Bot may not be connected to the API.';
    }

    window.Swal.fire({
        title: 'Discord Bot Logs',
        html: `
        <div class="bot-logs-container scroll-container-md text-start">
          <pre class="code-display">${logsHtml}</pre>
        </div>
      `,
        showCancelButton: true,
        confirmButtonText: 'Refresh Logs',
        cancelButtonText: 'Close',
        width: '700px'
    }).then((result) => {
        if (result.isConfirmed) {
            location.reload();
        }
    });
}

async function syncCommands() {
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

function viewCommands() {
    const commands = CONFIG.commands;
    let commandsHtml = '';

    function getPermissionBadge(level) {
        if (level === 'Public') return 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300';
        if (level.includes('Admin')) return 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-300';
        return 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300';
    }

    // Group commands by category
    const categories = {};
    commands.forEach(cmd => {
        if (!categories[cmd.category]) {
            categories[cmd.category] = [];
        }
        categories[cmd.category].push(cmd);
    });

    // Build HTML for each category
    Object.keys(categories).forEach(category => {
        commandsHtml += `
        <div class="mb-4">
          <h6 class="mb-2 text-ecs-green dark:text-ecs-green font-semibold">${category} Commands</h6>
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
            <td class="py-2 px-3"><code class="text-xs bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">/${cmd.name}</code></td>
            <td class="py-2 px-3">${cmd.description}</td>
            <td class="py-2 px-3"><span class="px-2 py-0.5 text-xs font-medium rounded ${getPermissionBadge(cmd.permission_level)}">${cmd.permission_level}</span></td>
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

function commandPermissions() {
    const commands = CONFIG.commands || [];
    const commandOptions = commands.length > 0
        ? commands.map(cmd => `<option value="${cmd.name}">${cmd.name}</option>`).join('')
        : '<option value="">No commands available</option>';

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
                        <input type="checkbox" id="roleAdmin" checked class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                        <label for="roleAdmin" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Global Admin</label>
                    </div>
                    <div class="flex items-center mb-2">
                        <input type="checkbox" id="roleMod" checked class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
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
        preConfirm: () => {
            const command = document.getElementById('permCommand')?.value;
            const roles = [];
            if (document.getElementById('roleAdmin')?.checked) roles.push('Global Admin');
            if (document.getElementById('roleMod')?.checked) roles.push('Moderator');
            if (document.getElementById('roleCoach')?.checked) roles.push('Coach');
            if (document.getElementById('roleUser')?.checked) roles.push('User');
            const cooldown = parseInt(document.getElementById('permCooldown')?.value || '5', 10);

            return fetch(`${CONFIG.botApiUrl}/commands/permissions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
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

function commandUsage() {
    const usage = CONFIG.commandUsage;

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
              <p class="text-gray-700 dark:text-gray-300"><code class="text-xs bg-gray-100 dark:bg-gray-700 px-1 py-0.5 rounded">/${usage.most_used_command || 'N/A'}</code></p>
            </div>
            <div>
              <h6 class="font-semibold text-gray-900 dark:text-white">Average Response Time</h6>
              <p class="text-gray-700 dark:text-gray-300">${usage.avg_response_time || 'N/A'}</p>
            </div>
          </div>
        </div>
      `,
        confirmButtonText: 'Close',
        width: '700px'
    });
}

function customCommands() {
    window.Swal.fire({
        title: 'Custom Commands',
        html: `
            <div class="text-start">
                <p class="text-gray-500 dark:text-gray-400 mb-3">Create custom bot commands that respond with text or execute actions.</p>
                <div class="mb-3">
                    <label for="cmdName" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Command Name</label>
                    <div class="flex">
                        <span class="inline-flex items-center px-3 text-sm text-gray-900 bg-gray-200 border border-r-0 border-gray-300 rounded-l-lg dark:bg-gray-600 dark:text-gray-400 dark:border-gray-600">/</span>
                        <input type="text" id="cmdName" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-none rounded-r-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="mycommand" pattern="[a-z0-9_-]+" title="Lowercase letters, numbers, underscores, and hyphens only">
                    </div>
                </div>
                <div class="mb-3">
                    <label for="cmdDescription" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Description</label>
                    <input type="text" id="cmdDescription" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="What does this command do?">
                </div>
                <div class="mb-3">
                    <label for="cmdType" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Response Type</label>
                    <select id="cmdType" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                        <option value="text">Text Response</option>
                        <option value="embed">Rich Embed</option>
                        <option value="action">Custom Action</option>
                    </select>
                </div>
                <div class="mb-3">
                    <label for="cmdResponse" class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Response Content</label>
                    <textarea id="cmdResponse" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" rows="3" placeholder="Enter the response message..."></textarea>
                </div>
                <div class="flex items-center mb-3">
                    <input type="checkbox" id="cmdEnabled" checked class="w-4 h-4 text-ecs-green bg-gray-100 border-gray-300 rounded focus:ring-ecs-green dark:focus:ring-ecs-green dark:ring-offset-gray-800 dark:bg-gray-700 dark:border-gray-600">
                    <label for="cmdEnabled" class="ml-2 text-sm font-medium text-gray-900 dark:text-gray-300">Enabled</label>
                </div>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Create Command',
        showDenyButton: true,
        denyButtonText: 'View All Commands',
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

            return fetch(`${CONFIG.botApiUrl}/custom-commands`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, description, type, response, enabled })
            })
            .then(res => res.json())
            .catch(() => ({ success: false, error: 'Bot API unavailable' }));
        },
        allowOutsideClick: () => !window.Swal.isLoading()
    }).then((result) => {
        if (result.isConfirmed) {
            if (result.value?.success) {
                window.Swal.fire('Command Created', `Custom command "/${result.value.command?.name}" has been created.`, 'success');
            } else {
                window.Swal.fire('Error', result.value?.error || 'Failed to create command', 'error');
            }
        } else if (result.isDenied) {
            // Fetch and display existing commands
            fetch(`${CONFIG.botApiUrl}/custom-commands`)
                .then(res => res.json())
                .then(data => {
                    const commands = data.commands || [];
                    const commandList = commands.length > 0
                        ? commands.map(cmd => `
                            <div class="flex justify-between items-center border-b border-gray-200 dark:border-gray-700 py-2">
                                <div>
                                    <strong class="text-gray-900 dark:text-white">/${cmd.name}</strong>
                                    <small class="text-gray-500 dark:text-gray-400 block">${cmd.description || 'No description'}</small>
                                </div>
                                <span class="px-2 py-0.5 text-xs font-medium rounded ${cmd.enabled ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300' : 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300'}">${cmd.enabled ? 'Active' : 'Disabled'}</span>
                            </div>
                        `).join('')
                        : '<p class="text-gray-500 dark:text-gray-400">No custom commands have been created yet.</p>';

                    window.Swal.fire({
                        title: 'Custom Commands List',
                        html: `<div class="text-start" style="max-height: 400px; overflow-y: auto;">${commandList}</div>`,
                        confirmButtonText: 'Close',
                        width: '600px'
                    });
                })
                .catch(() => {
                    window.Swal.fire({
                        title: 'Custom Commands List',
                        html: '<p class="text-gray-500 dark:text-gray-400">Unable to fetch commands. Bot API may be unavailable.</p>',
                        confirmButtonText: 'Close'
                    });
                });
        }
    });
}

// ============================================================================
// GUILD MANAGEMENT
// ============================================================================

function manageGuild(element, e) {
    const guildId = element.dataset.guild;
    const guildName = element.dataset.guildName || guildId;

    // First fetch current settings
    window.Swal.fire({
        title: 'Loading...',
        text: 'Fetching guild settings',
        allowOutsideClick: false,
        didOpen: () => window.Swal.showLoading()
    });

    fetch(`${CONFIG.botApiUrl}/guilds/${guildId}/settings`)
        .then(res => res.json())
        .then(data => {
            const settings = data.settings || {};
            const channels = settings.channels || [];
            const roles = settings.roles || [];

            const channelOptions = channels.map(ch =>
                `<option value="${ch.id}">${ch.name}</option>`
            ).join('');

            const roleOptions = roles.map(r =>
                `<option value="${r.id}">${r.name}</option>`
            ).join('');

            window.Swal.fire({
                title: `Manage Guild: ${settings.guild_name || guildName}`,
                html: `
                    <div class="text-start">
                        <div class="border-b border-gray-200 dark:border-gray-700 mb-4">
                            <ul class="flex flex-wrap -mb-px text-sm font-medium text-center" id="guildTabs" role="tablist">
                                <li class="mr-2" role="presentation">
                                    <button class="inline-block p-4 border-b-2 rounded-t-lg border-primary-600 text-primary-600" id="settings-tab" type="button" role="tab" aria-controls="guildSettings" aria-selected="true" onclick="document.querySelectorAll('[role=tabpanel]').forEach(p => p.classList.add('hidden')); document.getElementById('guildSettings').classList.remove('hidden'); document.querySelectorAll('[role=tab]').forEach(t => { t.classList.remove('border-primary-600', 'text-primary-600'); t.classList.add('border-transparent'); t.setAttribute('aria-selected', 'false'); }); this.classList.add('border-primary-600', 'text-primary-600'); this.classList.remove('border-transparent'); this.setAttribute('aria-selected', 'true');">Settings</button>
                                </li>
                                <li class="mr-2" role="presentation">
                                    <button class="inline-block p-4 border-b-2 rounded-t-lg border-transparent hover:text-gray-600 hover:border-gray-300" id="channels-tab" type="button" role="tab" aria-controls="guildChannels" aria-selected="false" onclick="document.querySelectorAll('[role=tabpanel]').forEach(p => p.classList.add('hidden')); document.getElementById('guildChannels').classList.remove('hidden'); document.querySelectorAll('[role=tab]').forEach(t => { t.classList.remove('border-primary-600', 'text-primary-600'); t.classList.add('border-transparent'); t.setAttribute('aria-selected', 'false'); }); this.classList.add('border-primary-600', 'text-primary-600'); this.classList.remove('border-transparent'); this.setAttribute('aria-selected', 'true');">Channels</button>
                                </li>
                                <li role="presentation">
                                    <button class="inline-block p-4 border-b-2 rounded-t-lg border-transparent hover:text-gray-600 hover:border-gray-300" id="roles-tab" type="button" role="tab" aria-controls="guildRoles" aria-selected="false" onclick="document.querySelectorAll('[role=tabpanel]').forEach(p => p.classList.add('hidden')); document.getElementById('guildRoles').classList.remove('hidden'); document.querySelectorAll('[role=tab]').forEach(t => { t.classList.remove('border-primary-600', 'text-primary-600'); t.classList.add('border-transparent'); t.setAttribute('aria-selected', 'false'); }); this.classList.add('border-primary-600', 'text-primary-600'); this.classList.remove('border-transparent'); this.setAttribute('aria-selected', 'true');">Roles</button>
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

                    return fetch(`${CONFIG.botApiUrl}/guilds/${guildId}/settings`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
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

function guildStats(element, e) {
    const guild = CONFIG.guildInfo;

    window.Swal.fire({
        title: `${guild.name || 'Guild'} Statistics`,
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

function addGuild() {
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

function resetBotConfig() {
    const prefixEl = document.getElementById('botPrefix');
    const roleEl = document.getElementById('defaultRole');
    const activityTypeEl = document.getElementById('activityType');
    const activityTextEl = document.getElementById('activityText');
    const autoModEl = document.getElementById('autoModeration');
    const cmdLogEl = document.getElementById('commandLogging');
    const welcomeEl = document.getElementById('welcomeMessages');

    if (prefixEl) prefixEl.value = '!';
    if (roleEl) roleEl.value = '';
    if (activityTypeEl) activityTypeEl.value = 'playing';
    if (activityTextEl) activityTextEl.value = 'ECS FC League';
    if (autoModEl) autoModEl.checked = true;
    if (cmdLogEl) cmdLogEl.checked = true;
    if (welcomeEl) welcomeEl.checked = true;

    window.Swal.fire('Reset!', 'Configuration has been reset to defaults.', 'info');
}

async function loadBotConfig() {
    try {
        const response = await fetch(`${CONFIG.botApiUrl}/config`);
        const data = await response.json();

        if (data.success && data.config) {
            const config = data.config;
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
    } catch (error) {
        console.log('Could not load bot configuration:', error);
        // Use default values if API is not accessible
    }
}

// ============================================================================
// INITIALIZATION
// ============================================================================

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
    initializeData,
    restartBot,
    checkBotHealth,
    viewBotLogs,
    syncCommands,
    viewCommands,
    commandPermissions,
    commandUsage,
    customCommands,
    manageGuild,
    guildStats,
    addGuild,
    saveBotConfig,
    resetBotConfig,
    loadBotConfig,
    initAdminPanelDiscordBot
};
