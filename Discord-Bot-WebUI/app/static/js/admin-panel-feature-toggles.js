/**
 * ============================================================================
 * FEATURE TOGGLES PAGE - JAVASCRIPT
 * ============================================================================
 *
 * Handles feature toggle interactions using data-attribute hooks
 * Follows event delegation pattern with state-driven styling
 *
 * ARCHITECTURAL COMPLIANCE:
 * - Event delegation pattern
 * - Data-attribute based hooks (never bind to styling classes)
 * - State-driven styling with classList
 * - No inline event handlers
 *
 * ============================================================================
 */

(function() {
  'use strict';

  // CSRF Token
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

  /**
   * Initialize feature toggles
   */
  function init() {
    initializeToggleHandlers();
    initializeFormHandlers();
  }

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('admin-panel-feature-toggles', init, {
      priority: 30,
      reinitializable: true,
      description: 'Admin panel feature toggles'
    });
  }

  // Fallback
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  /**
   * Initialize toggle switch handlers
   */
  function initializeToggleHandlers() {
    // Event delegation for all toggle switches
    document.addEventListener('change', function(e) {
      const toggle = e.target.closest('[data-setting-toggle]');
      if (!toggle) return;

      const settingKey = toggle.dataset.settingKey;
      const isEnabled = toggle.checked;

      handleToggleChange(toggle, settingKey, isEnabled);
    });
  }

  /**
   * Handle toggle switch change
   */
  function handleToggleChange(toggle, settingKey, isEnabled) {
    const statusLabel = toggle.parentElement.querySelector('[data-toggle-status]');
    const iconElement = document.querySelector(`[data-setting-row][data-setting-key="${settingKey}"] .c-setting-row__status-icon`);

    // Show loading state
    toggle.disabled = true;
    if (statusLabel) {
      statusLabel.textContent = 'Updating...';
    }

    // Send request to server
    fetch('/admin_panel/toggle_setting', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      },
      body: JSON.stringify({
        key: settingKey
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.success) {
        // Update toggle and status to match server state
        toggle.checked = data.new_value;
        if (statusLabel) {
          statusLabel.textContent = data.new_value ? 'Enabled' : 'Disabled';
        }

        // Update the icon in the left column
        if (iconElement) {
          if (data.new_value) {
            iconElement.classList.remove('ti-toggle-left', 'c-setting-row__status-icon--disabled');
            iconElement.classList.add('ti-toggle-right', 'c-setting-row__status-icon--enabled');
          } else {
            iconElement.classList.remove('ti-toggle-right', 'c-setting-row__status-icon--enabled');
            iconElement.classList.add('ti-toggle-left', 'c-setting-row__status-icon--disabled');
          }
        }

        // Show success message
        showToast('success', 'Setting Updated', data.message);
      } else {
        // Revert the toggle and status
        toggle.checked = !isEnabled;
        if (statusLabel) {
          statusLabel.textContent = !isEnabled ? 'Enabled' : 'Disabled';
        }

        // Show error message
        showToast('error', 'Error', data.message || 'Failed to update setting');
      }
    })
    .catch(error => {
      console.error('Error:', error);

      // Revert the toggle and status
      toggle.checked = !isEnabled;
      if (statusLabel) {
        statusLabel.textContent = !isEnabled ? 'Enabled' : 'Disabled';
      }

      showToast('error', 'Network Error', 'Failed to communicate with server');
    })
    .finally(() => {
      toggle.disabled = false;
    });
  }

  /**
   * Initialize form submission handlers
   */
  function initializeFormHandlers() {
    // Event delegation for form submissions
    document.addEventListener('submit', function(e) {
      const form = e.target.closest('[data-setting-form]');
      if (!form) return;

      const submitBtn = form.querySelector('.c-setting-form__submit');
      if (!submitBtn) return;

      const originalIcon = submitBtn.innerHTML;

      // Show loading state
      submitBtn.disabled = true;
      submitBtn.innerHTML = '<div class="spinner-border spinner-border-sm" role="status"><span class="visually-hidden">Loading...</span></div>';

      // Note: Form will submit normally, this is just for UI feedback
      // The backend will handle the actual update
    });
  }

  /**
   * Show toast notification
   * Uses SweetAlert2 if available, falls back to alert
   */
  function showToast(icon, title, text) {
    if (typeof window.Swal !== 'undefined') {
      window.Swal.fire({
        icon: icon,
        title: title,
        text: text,
        timer: 2000,
        showConfirmButton: false,
        toast: true,
        position: 'top-end'
      });
    } else {
      // Fallback to alert if SweetAlert2 not available
      alert(`${title}: ${text}`);
    }
  }

})();
