/**
 * ============================================================================
 * ADMIN PANEL DASHBOARD - JAVASCRIPT CONTROLLER
 * ============================================================================
 *
 * Handles all interactions for the admin panel dashboard.
 * Uses the centralized EventDelegation system for all click handling.
 *
 * Features:
 * - Navigation handling
 * - Modal dialogs (navigation settings, registration settings, etc.)
 * - Task monitoring
 * - Database monitoring
 * - Match reports
 *
 * Architecture:
 * - Registers handlers with EventDelegation (no duplicate listeners)
 * - Data-action attribute driven
 * - No inline event handlers
 *
 * ============================================================================
 */

(function() {
  'use strict';

  let _initialized = false;

  // ============================================================================
  // INITIALIZATION
  // ============================================================================

  function init() {
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
    // See bottom of file for EventDelegation.register() calls
  }

  let _navCardsSetup = false;

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
    if (typeof Swal === 'undefined') {
      alert('SweetAlert2 is required for this feature');
      return;
    }

    Swal.fire({
      title: 'Navigation Settings',
      html: '<div class="text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-2">Loading navigation settings...</p></div>',
      showConfirmButton: false,
      allowOutsideClick: false
    });

    fetch('/admin-panel/api/navigation-settings')
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          showNavigationSettingsModal(data.settings);
        } else {
          Swal.fire('Error', data.message || 'Failed to load navigation settings', 'error');
        }
      })
      .catch(error => {
        console.error('Navigation settings error:', error);
        Swal.fire('Error', 'Failed to load navigation settings', 'error');
      });
  }

  function showNavigationSettingsModal(settings) {
    const html = `
      <div class="text-start">
        <p class="text-info mb-3"><i class="ti ti-info-circle me-1"></i>Control which navigation items are visible to non-admin users. Admins can always see all navigation items.</p>

        <div class="row">
          <div class="col-md-6">
            ${createToggle('teamsNav', 'Teams Navigation', 'Team rosters and management for pl-premier, pl-classic roles', settings.teams_navigation_enabled)}
            ${createToggle('storeNav', 'Store Navigation', 'League store for coaches and admins', settings.store_navigation_enabled)}
            ${createToggle('matchesNav', 'Matches Navigation', 'Match schedules and results', settings.matches_navigation_enabled)}
            ${createToggle('leaguesNav', 'Leagues Navigation', 'League standings and information', settings.leagues_navigation_enabled)}
          </div>
          <div class="col-md-6">
            ${createToggle('draftsNav', 'Drafts Navigation', 'Draft system for coaches', settings.drafts_navigation_enabled)}
            ${createToggle('playersNav', 'Players Navigation', 'Player profiles and statistics', settings.players_navigation_enabled)}
            ${createToggle('messagingNav', 'Messaging Navigation', 'Communication tools', settings.messaging_navigation_enabled)}
            ${createToggle('mobileFeaturesNav', 'Mobile Features Navigation', 'Mobile app integration', settings.mobile_features_navigation_enabled)}
          </div>
        </div>
      </div>
    `;

    Swal.fire({
      title: 'Navigation Settings',
      html: html,
      width: '800px',
      showCancelButton: true,
      confirmButtonText: 'Save Settings',
      cancelButtonText: 'Cancel',
      showLoaderOnConfirm: true,
      preConfirm: () => saveNavigationSettings(),
      allowOutsideClick: () => !Swal.isLoading()
    }).then((result) => {
      if (result.isConfirmed) {
        Swal.fire({
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

    return fetch('/admin-panel/api/navigation-settings', {
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
    if (typeof Swal === 'undefined') {
      alert('SweetAlert2 is required for this feature');
      return;
    }

    Swal.fire({
      title: 'Registration Settings',
      html: '<div class="text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-2">Loading registration settings...</p></div>',
      showConfirmButton: false,
      allowOutsideClick: false
    });

    fetch('/admin-panel/api/registration-settings')
      .then(response => response.json())
      .then(data => {
        if (data.success) {
          showRegistrationSettingsModal(data.settings, data.available_roles);
        } else {
          Swal.fire('Error', data.message || 'Failed to load registration settings', 'error');
        }
      })
      .catch(error => {
        console.error('Registration settings error:', error);
        Swal.fire('Error', 'Failed to load registration settings', 'error');
      });
  }

  function showRegistrationSettingsModal(settings, roles) {
    const roleOptions = roles.map(role =>
      `<option value="${role.name}" ${settings.default_user_role === role.name ? 'selected' : ''}>${role.name}</option>`
    ).join('');

    const html = `
      <div class="text-start">
        <p class="text-info mb-3"><i class="ti ti-info-circle me-1"></i>Configure registration settings based on your actual onboarding flow. Discord OAuth is the primary login method.</p>

        <div class="row">
          <div class="col-md-6">
            <h6 class="text-primary mb-3">Registration Control</h6>
            ${createToggle('registrationEnabled', 'Allow New Registration', 'Enable/disable new user registration', settings.registration_enabled)}
            ${createToggle('waitlistEnabled', 'Enable Waitlist', 'Allow waitlist registration when full', settings.waitlist_registration_enabled)}
            ${createToggle('adminApproval', 'Admin Approval Required', 'All new users need admin approval', settings.admin_approval_required)}
            ${createToggle('discordOnly', 'Discord Only Login', 'Only Discord OAuth allowed (FIXED)', true, true)}

            <div class="mb-3">
              <label class="form-label">Default User Role</label>
              <select class="form-select" id="defaultRole">
                ${roleOptions}
              </select>
              <small class="text-muted">Role assigned to new registered users</small>
            </div>
          </div>
          <div class="col-md-6">
            <h6 class="text-primary mb-3">Registration Fields</h6>
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
        <div class="alert alert-info mt-3">
          <small><i class="ti ti-info-circle me-1"></i>These settings reflect your real onboarding form fields. Discord OAuth is your primary authentication method.</small>
        </div>
      </div>
    `;

    Swal.fire({
      title: 'Registration Settings',
      html: html,
      width: '900px',
      showCancelButton: true,
      confirmButtonText: 'Save Settings',
      cancelButtonText: 'Cancel',
      showLoaderOnConfirm: true,
      preConfirm: () => saveRegistrationSettings(),
      allowOutsideClick: () => !Swal.isLoading()
    }).then((result) => {
      if (result.isConfirmed) {
        Swal.fire({
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

    return fetch('/admin-panel/api/registration-settings', {
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
    if (typeof Swal === 'undefined') {
      alert('SweetAlert2 is required for this feature');
      return;
    }

    Swal.fire({
      title: 'Task Monitor',
      html: '<div class="text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-2">Loading task information...</p></div>',
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
        Swal.fire('Error', 'Failed to load task monitor data', 'error');
      });
  }

  function showTaskMonitorModal(data) {
    let tasksHtml = '';
    if (data.tasks && data.tasks.length > 0) {
      data.tasks.forEach(task => {
        const statusClass = task.status === 'active' ? 'success' : 'secondary';
        tasksHtml += `
          <tr>
            <td>${task.name}</td>
            <td><span class="badge bg-${statusClass}">${task.status}</span></td>
            <td>${task.started || '-'}</td>
            <td>${task.worker || '-'}</td>
            <td class="text-truncate">${task.args || '-'}</td>
          </tr>
        `;
      });
    } else {
      tasksHtml = '<tr><td colspan="5" class="text-center text-muted">No active tasks found</td></tr>';
    }

    const html = `
      <div class="text-start">
        <div class="row mb-3">
          <div class="col-md-4">
            <div class="card bg-success text-white">
              <div class="card-body text-center">
                <h4>${data.active_count || 0}</h4>
                <small>Active Tasks</small>
              </div>
            </div>
          </div>
          <div class="col-md-4">
            <div class="card bg-warning text-white">
              <div class="card-body text-center">
                <h4>${data.scheduled_count || 0}</h4>
                <small>Scheduled Tasks</small>
              </div>
            </div>
          </div>
          <div class="col-md-4">
            <div class="card bg-info text-white">
              <div class="card-body text-center">
                <h4>${data.worker_count || 0}</h4>
                <small>Workers</small>
              </div>
            </div>
          </div>
        </div>
        <div class="table-responsive">
          <table class="table table-sm">
            <thead>
              <tr>
                <th>Task Name</th>
                <th>Status</th>
                <th>Started</th>
                <th>Worker</th>
                <th>Arguments</th>
              </tr>
            </thead>
            <tbody>
              ${tasksHtml}
            </tbody>
          </table>
        </div>
        ${data.message ? `<div class="alert alert-info"><small>${data.message}</small></div>` : ''}
        <p class="text-muted mt-3"><small>Task monitoring shows real-time background processes and scheduled jobs.</small></p>
      </div>
    `;

    Swal.fire({
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
    if (typeof Swal === 'undefined') {
      alert('SweetAlert2 is required for this feature');
      return;
    }

    Swal.fire({
      title: 'Database Monitor',
      html: '<div class="text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-2">Loading system information...</p></div>',
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
        Swal.fire('Error', 'Failed to load system monitor data', 'error');
      });
  }

  function showDatabaseMonitorModal(data) {
    const html = `
      <div class="text-start">
        <div class="row mb-3">
          <div class="col-md-3">
            <div class="card bg-info text-white">
              <div class="card-body text-center">
                <h4>${data.system.cpu_percent}%</h4>
                <small>CPU Usage</small>
              </div>
            </div>
          </div>
          <div class="col-md-3">
            <div class="card bg-success text-white">
              <div class="card-body text-center">
                <h4>${data.system.memory_percent}%</h4>
                <small>Memory Usage</small>
              </div>
            </div>
          </div>
          <div class="col-md-3">
            <div class="card bg-primary text-white">
              <div class="card-body text-center">
                <h4>${data.services.database.response_time_ms}ms</h4>
                <small>DB Response Time</small>
              </div>
            </div>
          </div>
          <div class="col-md-3">
            <div class="card bg-${data.services.redis.status === 'online' ? 'success' : 'danger'} text-white">
              <div class="card-body text-center">
                <h4>${data.services.redis.response_time_ms}ms</h4>
                <small>Redis Response</small>
              </div>
            </div>
          </div>
        </div>
        <p class="text-muted mt-3"><small>Real-time system monitoring data updated at ${new Date(data.timestamp).toLocaleString()}.</small></p>
      </div>
    `;

    Swal.fire({
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
    if (typeof Swal === 'undefined') {
      alert('SweetAlert2 is required for this feature');
      return;
    }

    Swal.fire({
      title: 'Match Reports',
      html: `
        <div class="text-start">
          <p class="text-info mb-3"><i class="ti ti-info-circle me-1"></i>Generate comprehensive match reports with various options.</p>
          <div class="alert alert-warning">
            <strong>Note:</strong> This feature is currently in development. Report generation will be available soon.
          </div>
        </div>
      `,
      width: '600px',
      confirmButtonText: 'Close'
    });
  }

  function generateReport() {
    console.log('Generate report functionality coming soon');
  }

  // ============================================================================
  // UTILITIES
  // ============================================================================

  function createToggle(id, label, description, checked, disabled = false) {
    return `
      <div class="mb-3">
        <div class="form-check form-switch">
          <input class="form-check-input" type="checkbox" id="${id}" ${checked ? 'checked' : ''} ${disabled ? 'disabled' : ''}>
          <label class="form-check-label" for="${id}">
            <strong>${label}</strong>
            ${description ? `<br><small class="text-muted">${description}</small>` : ''}
          </label>
        </div>
      </div>
    `;
  }

  function getCSRFToken() {
    const metaToken = document.querySelector('meta[name="csrf-token"]');
    if (metaToken) {
      return metaToken.getAttribute('content');
    }

    const formToken = document.querySelector('input[name="csrf_token"]');
    if (formToken) {
      return formToken.value;
    }

    console.error('CSRF token not found');
    return '';
  }

  // ============================================================================
  // EVENT DELEGATION - Registered at module scope
  // ============================================================================
  // Handlers registered when IIFE executes, ensuring EventDelegation is available

  EventDelegation.register('navigate', handleNavigate);
  EventDelegation.register('open-navigation-settings', openNavigationSettings, { preventDefault: true });
  EventDelegation.register('open-registration-settings', openRegistrationSettings, { preventDefault: true });
  EventDelegation.register('open-task-monitor', openTaskMonitor, { preventDefault: true });
  EventDelegation.register('open-database-monitor', openDatabaseMonitor, { preventDefault: true });
  EventDelegation.register('open-match-reports', openMatchReports, { preventDefault: true });
  EventDelegation.register('generate-report', generateReport, { preventDefault: true });

  // ============================================================================
  // AUTO-INITIALIZE
  // ============================================================================

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('admin-panel-dashboard', init, {
      priority: 30,
      reinitializable: true,
      description: 'Admin panel dashboard'
    });
  }

  // Fallback
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
