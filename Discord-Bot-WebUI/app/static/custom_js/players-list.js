/**
 * Players List Page JavaScript
 * ==============================
 * Event delegation and interaction logic for view_players.html
 *
 * Features:
 * - Search and filter functionality
 * - Player deletion with confirmation
 * - WooCommerce sync with progress tracking
 * - Modal interactions
 * - Responsive table enhancements
 *
 * Architecture: Event delegation pattern, no inline handlers, data-action attributes
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

  /**
   * Initialize on DOM ready
   */
  function init() {
    if (_initialized) return;
    _initialized = true;

    initializeEventDelegation();
    initializeSyncHandler();
    initializeFeatherIcons();
  }

  /**
   * Set up event delegation for all player list interactions
   */
  function initializeEventDelegation() {
    document.addEventListener('click', function(e) {
      const target = e.target.closest('[data-action]');
      if (!target) return;

      const action = target.dataset.action;

      switch(action) {
        case 'clear-search':
          handleClearSearch(e);
          break;
        case 'delete-player':
          handleDeletePlayer(target);
          break;
        case 'view-player':
          // Link click - browser handles navigation
          break;
        case 'create-player':
          // Modal trigger - Bootstrap handles this
          break;
        case 'close-modal':
          // Modal close - Bootstrap handles this
          break;
      }
    });
  }

  /**
   * Handle clear search action
   */
  function handleClearSearch(e) {
    e.preventDefault();

    // Get the search form
    const form = document.querySelector('[data-form="search-players"]');
    if (!form) return;

    // Clear the search input
    const searchInput = form.querySelector('[data-input="search"]');
    if (searchInput) {
      searchInput.value = '';
    }

    // Redirect to base URL without search parameter
    window.location.href = form.action;
  }

  /**
   * Handle player deletion with SweetAlert confirmation
   */
  function handleDeletePlayer(target) {
    const playerId = target.dataset.playerId;
    const playerName = target.dataset.playerName;

    if (!playerId) {
      console.error('No player ID found for deletion');
      return;
    }

    // Check if SweetAlert is available
    if (typeof window.Swal === 'undefined') {
      // Fallback to native confirm
      if (confirm(`Are you sure you want to delete ${playerName}? This will delete the player and associated user account.`)) {
        submitDeleteForm(playerId);
      }
      return;
    }

    // Show SweetAlert confirmation
    window.Swal.fire({
      title: 'Are you sure?',
      html: `This will delete <strong>${playerName}</strong> and their associated user account.`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: getThemeColor('danger', '#dc3545'),
      cancelButtonColor: getThemeColor('secondary', '#6c757d'),
      confirmButtonText: 'Yes, delete them!',
      cancelButtonText: 'Cancel',
      focusCancel: true
    }).then((result) => {
      if (result.isConfirmed) {
        submitDeleteForm(playerId);
      }
    });
  }

  /**
   * Submit the delete player form
   */
  function submitDeleteForm(playerId) {
    // Create a temporary form to submit the deletion
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = `/players/delete_player/${playerId}`;

    // Add CSRF token
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');
    if (csrfToken) {
      const csrfInput = document.createElement('input');
      csrfInput.type = 'hidden';
      csrfInput.name = 'csrf_token';
      csrfInput.value = csrfToken;
      form.appendChild(csrfInput);
    }

    document.body.appendChild(form);
    form.submit();
  }

  /**
   * Initialize WooCommerce sync handler
   */
  function initializeSyncHandler() {
    const syncForm = document.querySelector('[data-form="update-players"]');
    if (!syncForm) return;

    syncForm.addEventListener('submit', function(e) {
      e.preventDefault();

      if (typeof window.Swal === 'undefined') {
        // No SweetAlert available, just submit
        this.submit();
        return;
      }

      // Show confirmation dialog
      window.Swal.fire({
        title: 'Sync with WooCommerce?',
        text: 'This will synchronize player data with WooCommerce orders. Continue?',
        icon: 'warning',
        showCancelButton: true,
        confirmButtonText: 'Yes, sync now',
        cancelButtonText: 'Cancel',
        confirmButtonColor: getThemeColor('success', '#28a745'),
        cancelButtonColor: getThemeColor('secondary', '#6c757d')
      }).then((result) => {
        if (result.isConfirmed) {
          startSyncProcess(syncForm);
        }
      });
    });
  }

  /**
   * Start the WooCommerce sync process with progress tracking
   */
  function startSyncProcess(form) {
    // Show progress modal
    window.Swal.fire({
      title: 'Syncing with WooCommerce',
      html: `
        <div class="text-center">
          <div class="mb-3 progress-stage">Initializing...</div>
          <div class="progress mb-3">
            <div class="progress-bar progress-bar-striped progress-bar-animated"
                 role="progressbar"
                 aria-valuenow="0"
                 aria-valuemin="0"
                 aria-valuemax="100"
                 style="width: 0%">
            </div>
          </div>
          <div class="small text-muted progress-message">Starting...</div>
        </div>
      `,
      allowOutsideClick: false,
      allowEscapeKey: false,
      showConfirmButton: false
    });

    let taskId = '';
    let progressInterval = null;

    // Function to check progress
    const checkProgress = () => {
      if (!taskId) return;

      fetch(`/players/update_status/${taskId}`)
        .then(response => response.json())
        .then(data => {
          const progressBar = document.querySelector('.progress-bar');
          const messageDiv = document.querySelector('.progress-message');

          if (progressBar && messageDiv) {
            const progress = data.progress || 0;
            progressBar.style.width = `${progress}%`;
            progressBar.setAttribute('aria-valuenow', progress);
            messageDiv.textContent = data.message || 'Processing...';
          }
        })
        .catch(error => {
          console.error('Error fetching progress:', error);
        });
    };

    // Get CSRF token
    const csrfToken = form.querySelector('[name="csrf_token"]')?.value;

    // Start the sync process
    fetch(form.action, {
      method: 'POST',
      headers: {
        'X-CSRFToken': csrfToken
      }
    })
    .then(response => response.json())
    .then(data => {
      taskId = data.task_id;

      // Start polling for progress
      progressInterval = setInterval(checkProgress, 1000);

      // Check for completion
      const checkCompletion = setInterval(() => {
        if (!taskId) return;

        fetch(`/players/update_status/${taskId}`)
          .then(response => response.json())
          .then(statusData => {
            if (statusData.stage === 'complete') {
              clearInterval(checkCompletion);
              clearInterval(progressInterval);
              showSyncResults(statusData, taskId, csrfToken);
            }
          })
          .catch(error => {
            console.error('Error checking completion:', error);
          });
      }, 1000);
    })
    .catch(error => {
      console.error('Error starting sync:', error);
      window.Swal.fire({
        title: 'Error!',
        text: error.message || 'An error occurred during synchronization.',
        icon: 'error'
      });
    });
  }

  /**
   * Show sync results and confirmation dialog
   */
  function showSyncResults(statusData, taskId, csrfToken) {
    const newPlayers = statusData.new_players || 0;
    const potentialInactive = statusData.potential_inactive || 0;

    window.Swal.fire({
      title: 'Sync Results',
      html: `
        <p><strong>${newPlayers}</strong> new players found</p>
        <p><strong>${potentialInactive}</strong> players without current orders</p>
        <div class="mb-3 form-check">
          <input type="checkbox" class="form-check-input" id="processNew" checked>
          <label class="form-check-label" for="processNew">Import new players</label>
        </div>
        <div class="mb-3 form-check">
          <input type="checkbox" class="form-check-input" id="processInactive" checked>
          <label class="form-check-label" for="processInactive">Mark inactive players</label>
        </div>
      `,
      showCancelButton: true,
      confirmButtonText: 'Proceed',
      cancelButtonText: 'Cancel',
      confirmButtonColor: getThemeColor('success', '#28a745'),
      cancelButtonColor: getThemeColor('secondary', '#6c757d')
    }).then((result) => {
      if (result.isConfirmed) {
        confirmSync(taskId, csrfToken);
      }
    });
  }

  /**
   * Confirm and process the sync
   */
  function confirmSync(taskId, csrfToken) {
    const processNew = document.getElementById('processNew')?.checked || false;
    const processInactive = document.getElementById('processInactive')?.checked || false;

    fetch('/players/confirm_update', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrfToken
      },
      body: JSON.stringify({
        task_id: taskId,
        process_new: processNew,
        process_inactive: processInactive
      })
    })
    .then(response => response.json())
    .then(data => {
      if (data.status === 'success') {
        window.Swal.fire({
          title: 'Success!',
          text: 'Player data has been synchronized.',
          icon: 'success',
          confirmButtonColor: getThemeColor('success', '#28a745')
        }).then(() => {
          window.location.reload();
        });
      } else {
        throw new Error(data.message || 'Unknown error');
      }
    })
    .catch(error => {
      window.Swal.fire({
        title: 'Error!',
        text: error.message || 'An error occurred during synchronization.',
        icon: 'error',
        confirmButtonColor: getThemeColor('danger', '#dc3545')
      });
    });
  }

  /**
   * Get theme color from ECSTheme if available, with fallback
   */
  function getThemeColor(colorName, fallback) {
    if (typeof window.ECSTheme !== 'undefined' && window.ECSTheme.getColor) {
      return window.ECSTheme.getColor(colorName);
    }

    // Try to get from CSS custom properties
    const root = getComputedStyle(document.documentElement);
    const cssVar = root.getPropertyValue(`--ecs-${colorName}`).trim();

    return cssVar || fallback;
  }

  /**
   * Initialize Feather icons
   */
  function initializeFeatherIcons() {
    if (typeof window.feather !== 'undefined') {
      window.feather.replace();
    }
  }

  /**
   * Debounce function for search input
   */
  function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
      const later = () => {
        clearTimeout(timeout);
        func(...args);
      };
      clearTimeout(timeout);
      timeout = setTimeout(later, wait);
    };
  }

  /**
   * Add live search functionality (optional enhancement)
   */
  function initializeLiveSearch() {
    const searchInput = document.querySelector('[data-input="search"]');
    if (!searchInput) return;

    const debouncedSearch = debounce(function() {
      const form = searchInput.closest('form');
      if (form && searchInput.value.length >= 3) {
        // Auto-submit after 3 characters
        form.submit();
      }
    }, 500);

    searchInput.addEventListener('input', debouncedSearch);
  }

  // Uncomment to enable live search
  // initializeLiveSearch();

  // Register with InitSystem (primary)
  if (true && InitSystem.register) {
    InitSystem.register('players-list', init, {
      priority: 35,
      reinitializable: true,
      description: 'Players list page functionality'
    });
  }

  // Fallback
  // InitSystem handles initialization

// Backward compatibility
window.init = init;

// Backward compatibility
window.initializeEventDelegation = initializeEventDelegation;

// Backward compatibility
window.handleClearSearch = handleClearSearch;

// Backward compatibility
window.handleDeletePlayer = handleDeletePlayer;

// Backward compatibility
window.submitDeleteForm = submitDeleteForm;

// Backward compatibility
window.initializeSyncHandler = initializeSyncHandler;

// Backward compatibility
window.startSyncProcess = startSyncProcess;

// Backward compatibility
window.showSyncResults = showSyncResults;

// Backward compatibility
window.confirmSync = confirmSync;

// Backward compatibility
window.getThemeColor = getThemeColor;

// Backward compatibility
window.initializeFeatherIcons = initializeFeatherIcons;

// Backward compatibility
window.debounce = debounce;

// Backward compatibility
window.initializeLiveSearch = initializeLiveSearch;
