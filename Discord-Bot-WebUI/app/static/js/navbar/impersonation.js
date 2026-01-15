/**
 * Navbar - Role Impersonation
 * Role impersonation management for testing
 *
 * @module navbar/impersonation
 */

import { getCSRFToken, showToast } from './config.js';
import { closeDropdown } from './dropdown-manager.js';

/**
 * Initialize role impersonation
 */
export function initRoleImpersonation() {
  if (!document.querySelector('[data-dropdown="impersonation"]')) {
    return;
  }

  // Load current status
  loadImpersonationStatus();

  // Attach refresh button listener
  const refreshBtn = document.querySelector('[data-action="refresh-roles"]');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', () => loadAvailableRoles());
  }

  // Attach checkbox change listeners
  const checkboxes = document.querySelectorAll('input[name="impersonate_roles"]');
  checkboxes.forEach(checkbox => {
    checkbox.addEventListener('change', () => validateRoleSelection());
  });

  // Attach clear selection listener
  const clearBtn = document.querySelector('[data-action="clear-role-selection"]');
  if (clearBtn) {
    clearBtn.addEventListener('click', (e) => {
      e.preventDefault();
      clearRoleSelection();
    });
  }

  // Initial validation
  validateRoleSelection();
}

/**
 * Start role impersonation
 */
export async function startRoleImpersonation() {
  // Get selected roles from checkboxes
  const checkboxes = document.querySelectorAll('input[name="impersonate_roles"]:checked');
  const selectedRoles = Array.from(checkboxes).map(cb => cb.value);

  if (selectedRoles.length === 0) {
    showToast('Please select at least one role', 'warning');
    return;
  }

  try {
    const response = await fetch('/api/role-impersonation/start', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      },
      body: JSON.stringify({ roles: selectedRoles })
    });

    const data = await response.json();

    if (data.success) {
      // Update UI to show impersonation is active
      const button = document.querySelector('[data-dropdown="impersonation"]');
      if (button) {
        button.classList.add('c-navbar-modern__impersonation-active');
      }

      // Show badge
      const badge = button?.querySelector('.c-navbar-modern__badge');
      if (badge) {
        badge.classList.remove('u-hidden');
      }

      // Hide normal status, show active status
      const normalStatus = document.getElementById('currentRoleStatus');
      const activeStatus = document.getElementById('activeImpersonationStatus');
      const activeRolesList = document.getElementById('activeRolesList');

      if (normalStatus) normalStatus.classList.add('u-hidden');
      if (activeStatus) {
        activeStatus.classList.remove('u-hidden');
        if (activeRolesList) {
          activeRolesList.innerHTML = selectedRoles.map(role =>
            `<span class="c-role-status__role-tag">${role}</span>`
          ).join('');
        }
      }

      closeDropdown('impersonation');
      showToast('Role testing started', 'success');

      // Reload page to apply new permissions
      setTimeout(() => window.location.reload(), 1000);
    } else {
      showToast(data.message || 'Failed to start role testing', 'error');
    }
  } catch (error) {
    console.error('Impersonation error:', error);
    showToast('An error occurred', 'error');
  }
}

/**
 * Stop role impersonation
 */
export async function stopRoleImpersonation() {
  try {
    const response = await fetch('/api/role-impersonation/stop', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCSRFToken(),
      }
    });

    const data = await response.json();

    if (data.success) {
      showToast('Impersonation stopped', 'success');
      setTimeout(() => window.location.reload(), 1000);
    }
  } catch (error) {
    console.error('Stop impersonation error:', error);
  }
}

/**
 * Load impersonation status
 */
export async function loadImpersonationStatus() {
  try {
    const response = await fetch('/api/role-impersonation/status');
    if (!response.ok) throw new Error('Failed to load status');

    const data = await response.json();
    updateImpersonationStatus(data);
  } catch (error) {
    console.error('Error loading impersonation status:', error);
  }
}

/**
 * Load available roles (refresh from server)
 */
export async function loadAvailableRoles() {
  const refreshBtn = document.querySelector('[data-action="refresh-roles"]');
  if (refreshBtn) {
    refreshBtn.classList.add('is-loading');
    const icon = refreshBtn.querySelector('i');
    if (icon) icon.style.animation = 'spin 1s linear infinite';
  }

  try {
    const response = await fetch('/api/role-impersonation/available-roles');
    if (!response.ok) throw new Error('Failed to load roles');

    const data = await response.json();
    showToast('Roles refreshed', 'success');
    updateImpersonationStatus(data.current_impersonation);
  } catch (error) {
    console.error('Error loading available roles:', error);
    showToast('Failed to refresh roles', 'error');
  } finally {
    if (refreshBtn) {
      refreshBtn.classList.remove('is-loading');
      const icon = refreshBtn.querySelector('i');
      if (icon) icon.style.animation = '';
    }
  }
}

/**
 * Update impersonation status display
 * @param {Object} data - Impersonation status data
 */
export function updateImpersonationStatus(data) {
  const isActive = data && data.active || false;
  const normalStatus = document.getElementById('currentRoleStatus');
  const activeStatus = document.getElementById('activeImpersonationStatus');
  const activeRolesList = document.getElementById('activeRolesList');
  const badge = document.querySelector('[data-badge="impersonation"]');

  if (isActive && data.roles && data.roles.length > 0) {
    // Hide normal status, show active status
    if (normalStatus) normalStatus.classList.add('u-hidden');
    if (activeStatus) {
      activeStatus.classList.remove('u-hidden');
      if (activeRolesList) {
        activeRolesList.innerHTML = data.roles.map(role =>
          `<span class="c-role-status__role-tag">${role}</span>`
        ).join('');
      }
    }

    // Show badge
    if (badge) badge.classList.remove('u-hidden');
  } else {
    // Show normal status, hide active status
    if (normalStatus) normalStatus.classList.remove('u-hidden');
    if (activeStatus) activeStatus.classList.add('u-hidden');

    // Hide badge
    if (badge) badge.classList.add('u-hidden');
  }
}

/**
 * Clear all role selections
 */
export function clearRoleSelection() {
  const checkboxes = document.querySelectorAll('input[name="impersonate_roles"]');
  checkboxes.forEach(checkbox => {
    checkbox.checked = false;
  });
  validateRoleSelection();
}

/**
 * Validate role selection
 */
export function validateRoleSelection() {
  const checkboxes = document.querySelectorAll('input[name="impersonate_roles"]:checked');
  const startBtn = document.getElementById('startImpersonationBtn');
  const countDisplay = document.getElementById('selectedRoleCount');

  const selectedCount = checkboxes.length;

  // Update count display
  if (countDisplay) {
    countDisplay.textContent = selectedCount;
  }

  // Enable/disable start button
  if (startBtn) {
    startBtn.disabled = selectedCount === 0;
  }
}

export default {
  initRoleImpersonation,
  startRoleImpersonation,
  stopRoleImpersonation,
  loadImpersonationStatus,
  loadAvailableRoles,
  updateImpersonationStatus,
  clearRoleSelection,
  validateRoleSelection
};
