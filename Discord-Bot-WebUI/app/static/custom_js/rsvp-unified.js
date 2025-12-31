/**
 * RSVP Unified Script - v2.1
 * This is a completely rewritten version of the RSVP page JavaScript
 * designed to be extremely stable and avoid any syntax errors.
 *
 * Updates in v2.1:
 * - Added fallback solutions for team selection in sub request modal
 * - Fixed issue with Pub League Coaches not being able to request subs
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';
let _initialized = false;

  function init() {
    if (_initialized) return;
    _initialized = true;
  
  // Hide page loader
  setTimeout(function() {
    var loader = document.getElementById('page-loader');
    if (loader) {
      loader.classList.add('hidden');
      setTimeout(function() {
        if (loader && loader.parentNode) {
          loader.parentNode.removeChild(loader);
        }
      }, 500);
    }
  }, 800);
  
  // Load substitutes for the assign sub modal
  if (document.getElementById('assignSubModalRSVP')) {
    loadAvailableSubs();
  }
  
  // Emergency fix for the request sub modal - ensure team options are available
  if (document.getElementById('requestSubModal')) {
    fixTeamOptions();
  }
  
  // Setup Discord RSVP sync button
  var syncDiscordButton = document.getElementById('syncDiscordButton');
  if (syncDiscordButton) {
    syncDiscordButton.addEventListener('click', function() {
      // Change button to loading state
      const originalText = syncDiscordButton.innerHTML;
      syncDiscordButton.disabled = true;
      syncDiscordButton.innerHTML = '<i class="ti ti-loader ti-spin me-1"></i> Syncing...';
      
      // Get CSRF token from meta tag or hidden input
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || 
                         document.querySelector('input[name="csrf_token"]')?.value || '';
      
      // Call the API endpoint to force a sync
      fetch('/api/force_discord_sync', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Requested-With': 'XMLHttpRequest',
          'X-CSRFToken': csrfToken
        }
      })
      .then(response => response.json())
      .then(data => {
        // Reset button state
        syncDiscordButton.disabled = false;
        syncDiscordButton.innerHTML = originalText;
        
        // Show appropriate notification
        if (data.success) {
          if (window.toastr) {
            toastr.success('RSVP synchronization with Discord has been triggered.', 'Sync Started');
          } else if (window.Swal) {
            window.Swal.fire({
              title: 'Success!',
              text: 'RSVP synchronization with Discord has been triggered.',
              icon: 'success',
              timer: 3000,
              showConfirmButton: false
            });
          } else {
            alert('RSVP synchronization with Discord has been triggered.');
          }
        } else {
          if (window.toastr) {
            toastr.error(data.message || 'An error occurred syncing with Discord.', 'Sync Failed');
          } else if (window.Swal) {
            window.Swal.fire({
              title: 'Sync Failed',
              text: data.message || 'An error occurred syncing with Discord.',
              icon: 'error'
            });
          } else {
            alert('Sync Failed: ' + (data.message || 'An error occurred syncing with Discord.'));
          }
        }
      })
      .catch(error => {
        // Error syncing with Discord
        
        // Reset button state
        syncDiscordButton.disabled = false;
        syncDiscordButton.innerHTML = originalText;
        
        // Show error notification
        if (window.toastr) {
          toastr.error('Could not connect to the Discord sync service.', 'Connection Error');
        } else if (window.Swal) {
          window.Swal.fire({
            title: 'Connection Error',
            text: 'Could not connect to the Discord sync service.',
            icon: 'error'
          });
        } else {
          alert('Connection Error: Could not connect to the Discord sync service.');
        }
      });
    });
  }
  
  // Initialize when jQuery is ready
  if (window.jQuery) {
    jQuery(function($) {
      try {
        // Toastr configuration
        if (window.toastr) {
          toastr.options = {
            closeButton: true,
            newestOnTop: true,
            progressBar: true,
            positionClass: "toast-top-right",
            timeOut: 5000
          };
        }
        
        // Initialize tooltips
        if (window.bootstrap) {
          var tooltipElements = document.querySelectorAll('[data-bs-toggle="tooltip"]');
          for (var i = 0; i < tooltipElements.length; i++) {
            new window.bootstrap.Tooltip(tooltipElements[i]);
          }
        }
        
        // Initialize DataTables
        if (window.$.fn.DataTable) {
          // Simple table options without complex structures
          var tableOptions = {
            responsive: true,
            pageLength: 10,
            lengthMenu: [5, 10, 25, 50],
            language: {
              search: "",
              searchPlaceholder: "Search players..."
            },
            drawCallback: function() {
              // Rebind event handlers to rows after DataTable redraws
              bindEventHandlers();
              fixDropdownsAndOverflow();
              // FORCE REMOVE DEFAULT DATATABLES ARROWS
              removeDataTablesArrows();
            }
          };
          
          // Initialize each table
          if (window.$('#rsvpStatusTable').length) {
            window.$('#rsvpStatusTable').DataTable(tableOptions);
          }
          
          if (window.$('#homeTeamTable').length) {
            window.$('#homeTeamTable').DataTable(tableOptions);
          }
          
          if (window.$('#awayTeamTable').length) {
            window.$('#awayTeamTable').DataTable(tableOptions);
          }
          
          // FORCE REMOVE DATATABLES ARROWS AFTER INITIALIZATION
          setTimeout(function() {
            removeDataTablesArrows();
          }, 100);
          
          // Style improvements
          window.$('[data-datatable="filter"] input').removeClass('form-control-sm').addClass('rounded-pill');
          window.$('[data-datatable="length"] select').removeClass('form-select-sm').addClass('rounded-pill');
        }
        
        // Fix z-index and overflow issues
        fixDropdownsAndOverflow();
        
        // Bind event handlers
        bindEventHandlers();
        
        // Fix tabs
        bindTabHandlers();

      } catch (e) {
        // console.error("Error initializing RSVP page:", e);
      }
    });
  }

  // Apply DataTables arrow fix after initialization
  setTimeout(function() {
    removeDataTablesArrows();
  }, 1000);
  } // End of init function

/**
 * Fix dropdown menu z-index and container overflow issues
 *
 * REFACTORED APPROACH:
 * ====================
 * Previously used inline styles to fix DataTables dropdown clipping.
 * Now uses CSS utility classes from /static/css/utilities/datatable-utils.css
 *
 * CSS classes applied:
 * - .dt-dropdown: Sets z-index: 9999 and position: absolute on dropdown menus
 * - .dt-container-visible: Sets overflow: visible and position: relative on containers
 *
 * Benefits of CSS approach:
 * - No repeated style manipulation after each DataTable redraw
 * - Better performance (CSS declarations vs JavaScript DOM manipulation)
 * - More maintainable and declarative
 * - Works even if JavaScript is delayed or fails
 * - Uses !important to override DataTables inline styles
 *
 * Note: This function now only adds CSS classes instead of manipulating styles directly.
 * The heavy lifting is done by CSS, which is more performant and maintainable.
 */
export function fixDropdownsAndOverflow() {
  try {
    // Add utility classes to dropdown menus (exclude navbar dropdowns)
    var dropdowns = document.querySelectorAll('[data-dropdown]:not(.c-navbar-modern__actions [data-dropdown])');
    for (var i = 0; i < dropdowns.length; i++) {
      dropdowns[i].classList.add('dt-dropdown');
    }

    // Add utility classes to containers
    var containers = document.querySelectorAll('[data-container="table"], [data-container="card"], [data-container="tab"], div.dataTables_wrapper');
    for (var j = 0; j < containers.length; j++) {
      containers[j].classList.add('dt-container-visible');
    }
  } catch (e) {
    // console.error("Error fixing dropdowns:", e);
  }
}

/**
 * Format phone number for display
 */
export function formatPhoneNumber(phoneNumber) {
  if (!phoneNumber) return '';
  
  var cleaned = ('' + phoneNumber).replace(/\D/g, '');
  
  // Format for international numbers
  var match = cleaned.match(/^(\d{1})(\d{3})(\d{3})(\d{4})$/);
  if (match) {
    return '+' + match[1] + ' (' + match[2] + ') ' + match[3] + '-' + match[4];
  }
  
  // Format for US numbers
  var match2 = cleaned.match(/^(\d{3})(\d{3})(\d{4})$/);
  if (match2) {
    return '(' + match2[1] + ') ' + match2[2] + '-' + match2[3];
  }
  
  return phoneNumber;
}

/**
 * Bind all event handlers for the page
 */
export function bindEventHandlers() {
  try {
    // Using jQuery with defensive programming
    if (window.jQuery) {
      var $ = window.jQuery;
      
      // Initialize tooltips
      if (window.bootstrap) {
        var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function(tooltipTriggerEl) {
            return new window.bootstrap.Tooltip(tooltipTriggerEl, {
                delay: { show: 200, hide: 100 }
            });
        });
      }
      
      // SMS Modal handling - REMOVED
      // Now handled by event delegation via data-action="rsvp-request-sms"
      // Event delegation will call the handler registered in event-delegation.js
      // window.$('.send-sms-btn').on('click', function() { ... });
      
      // Discord DM Modal handling - REMOVED
      // Now handled by event delegation via data-action="rsvp-request-discord-dm"
      // Event delegation will call the handler registered in event-delegation.js
      // window.$('.send-discord-dm-btn').on('click', function() { ... });
      
      // RSVP Update handling - REMOVED
      // Now handled by event delegation via data-action="rsvp-update-status"
      // Event delegation will call the updateRSVPStatus function in event-delegation.js
      // window.$('.update-rsvp-btn').on('click', function() { ... });
      
      // Character counting for SMS
      window.$('#smsMessage').on('input', function() {
        try {
          var charCount = window.$(this).val().length;
          window.$('#smsCharCount').text(charCount);
          
          if (charCount > 160) {
            window.$('#smsCharCount').addClass('text-danger fw-bold');
          } else {
            window.$('#smsCharCount').removeClass('text-danger fw-bold');
          }
        } catch (e) {
          // console.error("Error counting SMS characters:", e);
        }
      });
      
      // Character counting for Discord
      window.$('#discordMessage').on('input', function() {
        try {
          var charCount = window.$(this).val().length;
          window.$('#discordCharCount').text(charCount);
          
          if (charCount > 2000) {
            window.$('#discordCharCount').addClass('text-danger fw-bold');
          } else {
            window.$('#discordCharCount').removeClass('text-danger fw-bold');
          }
        } catch (e) {
          // console.error("Error counting Discord characters:", e);
        }
      });
      
      // Form submission handlers for SMS
      window.$('#sendSmsForm').on('submit', function(e) {
        e.preventDefault();
        
        try {
          var charCount = window.$('#smsMessage').val().length;
          if (charCount > 160) {
            if (window.toastr) {
              toastr.warning('Your message exceeds the 160 character limit for SMS. Please shorten your message.');
            }
            return false;
          }
          
          var formData = new FormData(this);
          var submitBtn = window.$(this).find('button[type="submit"]');
          var originalText = submitBtn.html();
          
          submitBtn.prop('disabled', true).html('<i class="ti ti-loader ti-spin me-1"></i>Sending...');
          
          fetch(this.action, {
            method: 'POST',
            body: formData,
            headers: {
              'X-Requested-With': 'XMLHttpRequest'
            }
          })
          .then(function(response) { 
            return response.json(); 
          })
          .then(function(data) {
            if (data.success) {
              if (window.toastr) {
                toastr.success('SMS sent successfully.');
              }
              var smsModal = document.querySelector('[data-modal="send-sms"]');
              if (window.bootstrap && smsModal) {
                window.bootstrap.Modal.getInstance(smsModal).hide();
              }
            } else {
              if (window.toastr) {
                toastr.error(data.message || 'Error sending SMS.');
              }
            }
          })
          .catch(function(error) {
            // console.error('Error:', error);
            if (window.toastr) {
              toastr.error('An error occurred while sending SMS.');
            }
          })
          .finally(function() {
            submitBtn.prop('disabled', false).html(originalText);
          });
        } catch (e) {
          // console.error("Error sending SMS:", e);
        }
      });
      
      // Form submission handlers for Discord DM
      window.$('#sendDiscordDmForm').on('submit', function(e) {
        e.preventDefault();
        
        try {
          var charCount = window.$('#discordMessage').val().length;
          if (charCount > 2000) {
            if (window.toastr) {
              toastr.warning('Your message exceeds the 2000 character limit for Discord. Please shorten your message.');
            }
            return false;
          }
          
          var formData = new FormData(this);
          var submitBtn = window.$(this).find('button[type="submit"]');
          var originalText = submitBtn.html();
          
          submitBtn.prop('disabled', true).html('<i class="ti ti-loader ti-spin me-1"></i>Sending...');
          
          fetch(this.action, {
            method: 'POST',
            body: formData,
            headers: {
              'X-Requested-With': 'XMLHttpRequest'
            }
          })
          .then(function(response) { 
            return response.json(); 
          })
          .then(function(data) {
            if (data.success) {
              if (window.toastr) {
                toastr.success('Discord DM sent successfully.');
              }
              var discordModal = document.querySelector('[data-modal="send-discord-dm"]');
              if (window.bootstrap && discordModal) {
                window.bootstrap.Modal.getInstance(discordModal).hide();
              }
            } else {
              if (window.toastr) {
                toastr.error(data.message || 'Error sending Discord DM.');
              }
            }
          })
          .catch(function(error) {
            // console.error('Error:', error);
            if (window.toastr) {
              toastr.error('An error occurred while sending Discord DM.');
            }
          })
          .finally(function() {
            submitBtn.prop('disabled', false).html(originalText);
          });
        } catch (e) {
          // console.error("Error sending Discord DM:", e);
        }
      });
    }
  } catch (e) {
    // console.error("Global error in bindEventHandlers:", e);
  }
}

/**
 * Bind tab event handlers
 */
export function bindTabHandlers() {
  try {
    if (window.jQuery) {
      var $ = window.jQuery;
      
      // Handle tab switching
      window.$('a[data-bs-toggle="tab"]').on('shown.bs.tab', function() {
        // Fix overflow issues
        fixDropdownsAndOverflow();
        
        // Adjust DataTables
        if (window.$.fn.dataTable) {
          window.$.fn.dataTable.tables({ visible: true, api: true }).columns.adjust();
        }
      });
    }
  } catch (e) {
    // console.error("Error binding tab handlers:", e);
  }
}

/**
 * Load available substitutes for the assign sub modal
 */
export function loadAvailableSubs() {
  try {
    if (window.jQuery) {
      var $ = window.jQuery;
      
      // Check if the assign sub modal exists
      if (window.$('#assignSubModalRSVP').length === 0) {
        return;
      }
      
      // When the modal is shown, fetch substitute responses
      window.$('#assignSubModalRSVP').on('shown.bs.modal', function() {
        var subPlayerSelect = window.$('#subPlayerRSVP');
        
        // Clear existing options except the default
        subPlayerSelect.find('option:not(:first)').remove();
        subPlayerSelect.append('<option value="loading" disabled>Loading substitute responses...</option>');
        
        // Determine match type and ID from the form
        var matchIdValue = window.$('input[name="match_id"]').val();
        var matchType, matchId;
        
        if (matchIdValue.startsWith('ecs_')) {
          matchType = 'ecs';
          matchId = matchIdValue.substring(4); // Remove 'ecs_' prefix
        } else {
          matchType = 'regular';
          matchId = matchIdValue;
        }
        
        // Fetch substitute responses with color coding
        fetch(`/api/substitute-pools/responses/${matchType}/${matchId}`)
          .then(response => {
            if (!response.ok) {
              throw new Error('Network response was not ok');
            }
            return response.json();
          })
          .then(data => {
            // Clear loading option
            subPlayerSelect.find('option[value="loading"]').remove();
            
            if (data.success && data.substitutes && data.substitutes.length > 0) {
              // Update form text to show response status
              if (data.has_responses) {
                window.$('.form-text').html('<i class="ti ti-info-circle me-1"></i> <span class="text-success">Green = Available</span>, <span class="text-muted">Gray = No Response</span>, <span class="text-danger">Red = Not Available</span>');
              }
              
              // Add substitutes to select with color coding
              data.substitutes.forEach(function(sub) {
                var option = new Option(sub.name, sub.id);
                
                // Add CSS classes for color coding
                if (sub.response_status === 'available') {
                  option.className = 'text-success fw-bold';
                  option.textContent = `✓ ${sub.name}`;
                } else if (sub.response_status === 'not_available') {
                  option.className = 'text-danger';
                  option.textContent = `✗ ${sub.name}`;
                } else {
                  option.className = 'text-muted';
                  option.textContent = `- ${sub.name}`;
                }
                
                subPlayerSelect.append(option);
              });
            } else {
              subPlayerSelect.append('<option value="" disabled>No substitutes found</option>');
            }
          })
          .catch(error => {
            console.error('Error fetching substitute responses:', error);
            subPlayerSelect.find('option[value="loading"]').remove();
            subPlayerSelect.append('<option value="" disabled>Error loading substitutes</option>');
            
            // Show error toast if toastr is available
            if (window.toastr) {
              toastr.error('Failed to load substitute responses. Please try again.');
            }
          });
      });
      
      // Handle form submission for assigning subs
      window.$('#assignSubFormRSVP').on('submit', function(e) {
        e.preventDefault();
        
        var formData = new FormData(this);
        var submitBtn = window.$(this).find('button[type="submit"]');
        var originalText = submitBtn.html();
        
        // Disable button and show loading
        submitBtn.prop('disabled', true).html('<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Assigning...');
        
        fetch(this.action, {
          method: 'POST',
          body: formData,
          headers: {
            'X-Requested-With': 'XMLHttpRequest'
          }
        })
        .then(response => response.json())
        .then(data => {
          if (data.success) {
            // Show success message
            if (window.Swal) {
              window.Swal.fire({
                title: 'Success!',
                text: data.message || 'Substitute assigned successfully.',
                icon: 'success',
                timer: 1500,
                showConfirmButton: false
              }).then(() => {
                // Reload the page to show the updated RSVP list
                window.location.reload();
              });
            } else if (window.toastr) {
              toastr.success(data.message || 'Substitute assigned successfully.');
              setTimeout(() => window.location.reload(), 1500);
            } else {
              alert('Substitute assigned successfully.');
              window.location.reload();
            }
            
            // Hide modal
            var assignModal = document.querySelector('[data-modal="assign-sub"]');
            if (window.bootstrap && assignModal) {
              var modal = window.bootstrap.Modal.getInstance(assignModal);
              modal.hide();
            }
          } else {
            // Show error message
            if (window.Swal) {
              window.Swal.fire({
                title: 'Error',
                text: data.message || 'Failed to assign substitute.',
                icon: 'error'
              });
            } else if (window.toastr) {
              toastr.error(data.message || 'Failed to assign substitute.');
            } else {
              alert('Error: ' + (data.message || 'Failed to assign substitute.'));
            }
          }
        })
        .catch(error => {
          // console.error('Error assigning substitute:', error);
          if (window.toastr) {
            toastr.error('An error occurred while assigning the substitute.');
          } else {
            alert('An error occurred while assigning the substitute.');
          }
        })
        .finally(() => {
          // Re-enable button
          submitBtn.prop('disabled', false).html(originalText);
        });
      });
    }
  } catch (e) {
    // console.error("Error loading available subs:", e);
  }
}

/**
 * Fix team options in the request sub modal for Pub League Coaches
 * This function provides a client-side fallback that ensures the team selection
 * dropdown shows the teams that a coach is associated with for a match.
 */
export function fixTeamOptions() {
  try {
    // Get required DOM elements
    var requestSubModal = document.getElementById('requestSubModal');
    var teamSelect = document.getElementById('team_id');
    
    if (!requestSubModal || !teamSelect) {
      return;
    }
    
    // First check if the team select already has options (other than the default placeholder)
    if (teamSelect.options.length > 1) {
      // console.log("Team options already present, no fix needed");
      return;
    } else {
      // console.log("Team select has no options, applying fix");
    }
    
    // Get match information from the page
    var matchInfoText = document.querySelector('#requestSubModal .alert-info .mb-0');
    if (!matchInfoText) {
      // console.log("Could not find match info text");
      return;
    }
    
    var matchText = matchInfoText.textContent || '';
    var matchParts = matchText.split(' vs ');
    
    if (matchParts.length < 2) {
      // console.log("Could not parse match text:", matchText);
      return;
    }
    
    var homeTeamName = matchParts[0].trim();
    var awayTeamName = matchParts[1].split(' - ')[0].trim();
    // console.log("Parsed team names:", homeTeamName, awayTeamName);
    
    // Get team IDs from the modal data attributes
    var homeTeamId = requestSubModal.dataset.homeTeamId;
    var awayTeamId = requestSubModal.dataset.awayTeamId;
    
    // If data attributes are available, use them to add options immediately
    if (homeTeamId && awayTeamId) {
      // console.log("Found team IDs in data attributes:", homeTeamId, awayTeamId);
      
      // For coaches, we need to determine which team they coach
      var isAdmin = false;
      var userRoles = document.body.dataset.userRoles || '';
      
      if (userRoles.includes('Global Admin') || userRoles.includes('Pub League Admin')) {
        isAdmin = true;
      }
      
      // Always add both teams for admins
      if (isAdmin) {
        var homeOption = document.createElement('option');
        homeOption.value = homeTeamId;
        homeOption.text = homeTeamName;
        teamSelect.appendChild(homeOption);
        
        var awayOption = document.createElement('option');
        awayOption.value = awayTeamId;
        awayOption.text = awayTeamName;
        teamSelect.appendChild(awayOption);
        
        // console.log("Added both team options for admin");
        return;
      } else {
        // For coaches, try to determine which team they coach
        // This is the most aggressive approach - just add both teams and let the server validate
        var homeOption = document.createElement('option');
        homeOption.value = homeTeamId;
        homeOption.text = homeTeamName;
        teamSelect.appendChild(homeOption);
        
        var awayOption = document.createElement('option');
        awayOption.value = awayTeamId;
        awayOption.text = awayTeamName;
        teamSelect.appendChild(awayOption);
        
        // console.log("Added both team options as fallback");
        return;
      }
    }
    
    // If we didn't have data attributes, try to find team IDs in other ways
    // console.log("Data attributes not found, trying alternate methods");
    
    // Try to find team IDs from other parts of the page
    var assignSubForm = document.getElementById('assignSubFormRSVP');
    if (assignSubForm) {
      var subTeamSelect = document.getElementById('subTeamRSVP');
      if (subTeamSelect && subTeamSelect.options.length > 1) {
        // Copy options from the assign sub form
        for (var i = 1; i < subTeamSelect.options.length; i++) {
          var option = subTeamSelect.options[i];
          var newOption = document.createElement('option');
          newOption.value = option.value;
          newOption.text = option.text;
          teamSelect.appendChild(newOption);
        }
        // console.log("Copied options from assign sub form");
        return; // Successfully added options, no need to continue
      }
    }
    
    // Extract match ID from the form
    var matchIdInput = document.querySelector('#requestSubForm input[name="match_id"]');
    var matchId = matchIdInput ? matchIdInput.value : '';
    
    if (!matchId) {
      // console.log("Could not find match ID");
      return;
    }
    
    // console.log("Making request to find match details for match ID:", matchId);
    
    // Make a direct request to get match data
    fetch('/admin/rsvp_status/' + matchId)
      .then(response => {
        if (!response.ok) {
          // console.log("Response not OK:", response.status);
          return null;
        }
        return response.text();
      })
      .then(html => {
        if (!html) return;
        
        // console.log("Received HTML response, parsing for team data");
        
        // Create a temporary element to parse the HTML
        var tempDiv = document.createElement('div');
        tempDiv.innerHTML = html;
        
        // Look for team IDs in the page content
        var teamOptions = tempDiv.querySelectorAll('#subTeamRSVP option');
        if (teamOptions.length > 1) {
          // Copy options to our select
          for (var i = 1; i < teamOptions.length; i++) {
            var option = teamOptions[i];
            var newOption = document.createElement('option');
            newOption.value = option.value;
            newOption.text = option.text;
            teamSelect.appendChild(newOption);
          }
          // console.log("Added options from parsed HTML response");
        } else {
          // Last resort: create options based on the match text we parsed earlier
          // console.log("Creating options based on parsed match text");
          
          // Just add both teams as options and let the server handle validation
          var homeOption = document.createElement('option');
          homeOption.value = "home_team";  // Use placeholder values
          homeOption.text = homeTeamName;
          teamSelect.appendChild(homeOption);
          
          var awayOption = document.createElement('option');
          awayOption.value = "away_team";  // Use placeholder values
          awayOption.text = awayTeamName;
          teamSelect.appendChild(awayOption);
        }
      })
      .catch(error => {
        // console.error('Error fetching match details:', error);
        
        // Last resort fallback: create options with placeholder values
        // console.log("Error occurred, creating fallback options");
        
        var homeOption = document.createElement('option');
        homeOption.value = "home_team";  // Use placeholder values
        homeOption.text = homeTeamName;
        teamSelect.appendChild(homeOption);
        
        var awayOption = document.createElement('option');
        awayOption.value = "away_team";  // Use placeholder values
        awayOption.text = awayTeamName;
        teamSelect.appendChild(awayOption);
      });
  } catch (e) {
    // console.error("Error fixing team options:", e);
  }
}

// Function to ensure DataTables arrows work correctly
export function removeDataTablesArrows() {
  try {
    // Get sorting elements (this DOM query might be essential)
    var sortingElements = document.querySelectorAll('table.dataTable thead th.sorting, table.dataTable thead th.sorting_asc, table.dataTable thead th.sorting_desc');
    
    // Force browser reflow by accessing computed styles (this might be the key!)
    // The browser needs to recalculate styles after DataTables changes
    sortingElements.forEach(function(el) {
      // These DOM operations might be triggering the reflow that makes CSS work
      var beforeStyle = window.getComputedStyle(el, '::before');
      var afterStyle = window.getComputedStyle(el, '::after');
      // Force the browser to process the style calculations
      beforeStyle.content; 
      afterStyle.content;
    });
    
  } catch (e) {
    // Silent fail
  }
}

  // Register with InitSystem (primary)
  if (true && InitSystem.register) {
    InitSystem.register('rsvp-unified', init, {
      priority: 50,
      reinitializable: false,
      description: 'RSVP unified page functionality'
    });
  }

  // Fallback
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

// Backward compatibility
window.init = init;

// Backward compatibility
window.fixDropdownsAndOverflow = fixDropdownsAndOverflow;

// Backward compatibility
window.formatPhoneNumber = formatPhoneNumber;

// Backward compatibility
window.bindEventHandlers = bindEventHandlers;

// Backward compatibility
window.bindTabHandlers = bindTabHandlers;

// Backward compatibility
window.loadAvailableSubs = loadAvailableSubs;

// Backward compatibility
window.fixTeamOptions = fixTeamOptions;

// Backward compatibility
window.removeDataTablesArrows = removeDataTablesArrows;
