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

(function() {
  'use strict';

  // Configuration
  const CONFIG = {
    botApiUrl: 'http://localhost:5001/api/bot',
    recentLogs: null, // Will be populated from template
    commands: null, // Will be populated from template
    commandUsage: null, // Will be populated from template
    guildInfo: null // Will be populated from template
  };

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
    const result = await Swal.fire({
      title: 'Restart Discord Bot?',
      text: 'This will temporarily disconnect the bot from Discord while it restarts.',
      icon: 'warning',
      showCancelButton: true,
      confirmButtonText: 'Restart Bot'
    });

    if (result.isConfirmed) {
      Swal.fire({
        title: 'Restarting Bot...',
        text: 'Please wait while the bot restarts',
        allowOutsideClick: false,
        didOpen: () => {
          Swal.showLoading();

          fetch(`${CONFIG.botApiUrl}/restart`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            }
          })
          .then(response => response.json())
          .then(data => {
            if (data.success) {
              Swal.fire('Restarted!', 'Discord bot restart has been initiated.', 'success');
            } else {
              Swal.fire('Error!', `Failed to restart bot: ${data.message || 'Unknown error'}`, 'error');
            }
          })
          .catch(error => {
            console.error('Error restarting bot:', error);
            Swal.fire('Error!', 'Failed to connect to bot API.', 'error');
          });
        }
      });
    }
  }

  async function checkBotHealth() {
    Swal.fire({
      title: 'Running Health Check...',
      text: 'Checking bot connectivity and status',
      allowOutsideClick: false,
      didOpen: () => {
        Swal.showLoading();

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
            Swal.fire({
              title: 'Bot Health Check',
              html: healthInfo,
              icon: 'success',
              confirmButtonText: 'Close'
            });
          } else {
            Swal.fire('Bot Offline', `Bot status: ${data.status}. ${data.details || ''}`, 'warning');
          }
        })
        .catch(error => {
          console.error('Error checking bot health:', error);
          Swal.fire('Connection Error', 'Failed to connect to bot API.', 'error');
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

    Swal.fire({
      title: 'Discord Bot Logs',
      html: `
        <div class="bot-logs-container" style="max-height: 400px; overflow-y: auto; text-align: left;">
          <pre style="font-family: var(--font-mono); font-size: 0.875rem; white-space: pre-wrap;">${logsHtml}</pre>
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
    const result = await Swal.fire({
      title: 'Sync Commands?',
      text: 'This will synchronize all slash commands with Discord.',
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: 'Sync Commands'
    });

    if (result.isConfirmed) {
      Swal.fire({
        title: 'Syncing Commands...',
        text: 'Please wait while commands are synchronized',
        allowOutsideClick: false,
        didOpen: () => {
          Swal.showLoading();

          fetch(`${CONFIG.botApiUrl}/sync-commands`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
            }
          })
          .then(response => response.json())
          .then(data => {
            if (data.success) {
              Swal.fire('Synced!', `${data.commands_synced || 'All'} commands have been synchronized with Discord.`, 'success');
            } else {
              Swal.fire('Error!', `Failed to sync commands: ${data.message || 'Unknown error'}`, 'error');
            }
          })
          .catch(error => {
            console.error('Error syncing commands:', error);
            Swal.fire('Error!', 'Failed to connect to bot API.', 'error');
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
          <h6 class="mb-2 text-primary">${category} Commands</h6>
          <div class="table-responsive">
            <table class="table table-sm table-hover">
              <thead class="table-light">
                <tr>
                  <th>Command</th>
                  <th>Description</th>
                  <th>Permission</th>
                </tr>
              </thead>
              <tbody>
      `;

      categories[category].forEach(cmd => {
        const permissionColor = cmd.permission_level === 'Public' ? 'success' :
                               cmd.permission_level.includes('Admin') ? 'danger' : 'warning';
        commandsHtml += `
          <tr>
            <td><code>/${cmd.name}</code></td>
            <td>${cmd.description}</td>
            <td><span class="badge bg-${permissionColor}">${cmd.permission_level}</span></td>
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

    Swal.fire({
      title: 'Discord Bot Commands',
      html: `
        <div class="command-list-container" style="max-height: 500px; overflow-y: auto;">
          ${commandsHtml}
        </div>
      `,
      confirmButtonText: 'Close',
      width: '800px'
    });
  }

  function commandPermissions() {
    // Placeholder - would implement permissions management
    Swal.fire('Command Permissions', 'Command permissions management interface would appear here.', 'info');
  }

  function commandUsage() {
    const usage = CONFIG.commandUsage;

    Swal.fire({
      title: 'Command Usage Statistics',
      html: `
        <div class="command-usage-stats" style="text-align: left;">
          <div class="row mb-3">
            <div class="col-md-6">
              <div class="card bg-primary text-white">
                <div class="card-body text-center">
                  <h4>${usage.commands_today || 0}</h4>
                  <small>Commands Today</small>
                </div>
              </div>
            </div>
            <div class="col-md-6">
              <div class="card bg-info text-white">
                <div class="card-body text-center">
                  <h4>${usage.commands_this_week || 0}</h4>
                  <small>Commands This Week</small>
                </div>
              </div>
            </div>
          </div>
          <div class="row">
            <div class="col-md-6">
              <h6>Most Used Command</h6>
              <p><code>/${usage.most_used_command || 'N/A'}</code></p>
            </div>
            <div class="col-md-6">
              <h6>Average Response Time</h6>
              <p>${usage.avg_response_time || 'N/A'}</p>
            </div>
          </div>
        </div>
      `,
      confirmButtonText: 'Close',
      width: '700px'
    });
  }

  function customCommands() {
    // Placeholder - would implement custom commands interface
    Swal.fire('Custom Commands', 'Custom commands management interface would appear here.', 'info');
  }

  // ============================================================================
  // GUILD MANAGEMENT
  // ============================================================================

  function manageGuild(element, e) {
    const guildId = element.dataset.guild;
    Swal.fire('Guild Management', `Guild management interface for ${guildId} would appear here.`, 'info');
  }

  function guildStats(element, e) {
    const guild = CONFIG.guildInfo;

    Swal.fire({
      title: `${guild.name || 'Guild'} Statistics`,
      html: `
        <div class="guild-stats-container" style="text-align: left;">
          <div class="row mb-3">
            <div class="col-md-4">
              <div class="card bg-primary text-white">
                <div class="card-body text-center">
                  <h4>${guild.member_count || 0}</h4>
                  <small>Total Members</small>
                </div>
              </div>
            </div>
            <div class="col-md-4">
              <div class="card bg-success text-white">
                <div class="card-body text-center">
                  <h4>${guild.channel_count || 0}</h4>
                  <small>Channels</small>
                </div>
              </div>
            </div>
            <div class="col-md-4">
              <div class="card bg-info text-white">
                <div class="card-body text-center">
                  <h4>${guild.role_count || 0}</h4>
                  <small>Roles</small>
                </div>
              </div>
            </div>
          </div>
        </div>
      `,
      confirmButtonText: 'Close',
      width: '700px'
    });
  }

  function addGuild() {
    Swal.fire({
      title: 'Add Bot to Server',
      html: `
        <div class="add-guild-container">
          <p>To add the ECS FC Discord bot to another server, you need administrator permissions on that server.</p>
          <div class="alert alert-info">
            <i class="ti ti-info-circle me-2"></i>
            Click the button below to authorize the bot for a new server.
          </div>
          <div class="mt-4">
            <h6>Required Permissions:</h6>
            <ul class="small" style="text-align: left;">
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

    Swal.fire({
      title: 'Saving Configuration...',
      text: 'Please wait while the configuration is being saved',
      allowOutsideClick: false,
      didOpen: () => {
        Swal.showLoading();
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
        Swal.fire('Saved!', 'Bot configuration has been updated successfully.', 'success');
      } else {
        Swal.fire('Error!', `Failed to save configuration: ${data.error || 'Unknown error'}`, 'error');
      }
    } catch (error) {
      console.error('Error saving bot config:', error);
      Swal.fire('Error!', 'Failed to connect to bot API. Please check if the bot is running.', 'error');
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

    Swal.fire('Reset!', 'Configuration has been reset to defaults.', 'info');
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

  function init() {
    // Page guard: only run on Discord Bot admin pages
    const isBotPage = document.querySelector('[data-page="admin-discord-bot"]') ||
                      document.querySelector('.admin-discord-bot') ||
                      window.location.pathname.includes('discord-bot');

    if (!isBotPage) {
      return;
    }

    // Initialize data
    initializeData();

    // Register all event handlers with EventDelegation
    if (typeof EventDelegation !== 'undefined') {
      // Bot Control
      EventDelegation.register('restart-bot', restartBot, { preventDefault: true });
      EventDelegation.register('check-bot-health', checkBotHealth, { preventDefault: true });
      EventDelegation.register('view-bot-logs', viewBotLogs, { preventDefault: true });
      EventDelegation.register('sync-commands', syncCommands, { preventDefault: true });

      // Command Management
      EventDelegation.register('view-commands', viewCommands, { preventDefault: true });
      EventDelegation.register('command-permissions', commandPermissions, { preventDefault: true });
      EventDelegation.register('command-usage', commandUsage, { preventDefault: true });
      EventDelegation.register('custom-commands', customCommands, { preventDefault: true });

      // Guild Management
      EventDelegation.register('manage-guild', manageGuild, { preventDefault: true });
      EventDelegation.register('guild-stats', guildStats, { preventDefault: true });
      EventDelegation.register('add-guild', addGuild, { preventDefault: true });

      // Configuration
      EventDelegation.register('save-bot-config', saveBotConfig, { preventDefault: true });
      EventDelegation.register('reset-bot-config', resetBotConfig, { preventDefault: true });
    }

    // Load bot configuration
    loadBotConfig();

    console.log('Discord Bot Management initialized');
  }

  // Run initialization when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
