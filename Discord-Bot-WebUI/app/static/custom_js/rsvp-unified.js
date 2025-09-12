/**
 * RSVP Unified Script - v2.1
 * This is a completely rewritten version of the RSVP page JavaScript
 * designed to be extremely stable and avoid any syntax errors.
 * 
 * Updates in v2.1:
 * - Added fallback solutions for team selection in sub request modal
 * - Fixed issue with Pub League Coaches not being able to request subs
 */

// Wait for DOM content to be fully loaded
document.addEventListener('DOMContentLoaded', function() {
  'use strict';
  
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
            Swal.fire({
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
            Swal.fire({
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
          Swal.fire({
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
            new bootstrap.Tooltip(tooltipElements[i]);
          }
        }
        
        // Initialize DataTables
        if ($.fn.DataTable) {
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
          if ($('#rsvpStatusTable').length) {
            $('#rsvpStatusTable').DataTable(tableOptions);
          }
          
          if ($('#homeTeamTable').length) {
            $('#homeTeamTable').DataTable(tableOptions);
          }
          
          if ($('#awayTeamTable').length) {
            $('#awayTeamTable').DataTable(tableOptions);
          }
          
          // FORCE REMOVE DATATABLES ARROWS AFTER INITIALIZATION
          setTimeout(function() {
            removeDataTablesArrows();
          }, 100);
          
          // Style improvements
          $('.dataTables_filter .form-control').removeClass('form-control-sm');
          $('.dataTables_length .form-select').removeClass('form-select-sm');
          $('.dataTables_filter input').addClass('rounded-pill');
          $('.dataTables_length select').addClass('rounded-pill');
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
});

/**
 * Fix dropdown menu z-index and container overflow issues
 */
function fixDropdownsAndOverflow() {
  try {
    // Fix dropdowns
    var dropdowns = document.querySelectorAll('.dropdown-menu');
    for (var i = 0; i < dropdowns.length; i++) {
      dropdowns[i].style.zIndex = '9999';
      dropdowns[i].style.position = 'absolute';
    }
    
    // Fix containers
    var containers = document.querySelectorAll('.table-responsive, .card-body, .tab-content, .tab-pane, div.dataTables_wrapper');
    for (var j = 0; j < containers.length; j++) {
      containers[j].style.overflow = 'visible';
      containers[j].style.position = 'relative';
    }
  } catch (e) {
    // console.error("Error fixing dropdowns:", e);
  }
}

/**
 * Format phone number for display
 */
function formatPhoneNumber(phoneNumber) {
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
function bindEventHandlers() {
  try {
    // Using jQuery with defensive programming
    if (window.jQuery) {
      var $ = window.jQuery;
      
      // Initialize tooltips
      if (window.bootstrap) {
        var tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function(tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl, {
                delay: { show: 200, hide: 100 }
            });
        });
      }
      
      // SMS Modal handling
      $('.send-sms-btn').on('click', function() {
        try {
          var playerName = $(this).data('player-name') || 'Player';
          var playerId = $(this).data('player-id') || '';
          var phone = $(this).data('phone') || '';
          
          $('#smsPlayerName').text(playerName);
          $('#smsPlayerId').val(playerId);
          $('#smsPlayerPhone').val(phone);
          $('#smsPlayerPhoneDisplay').text(formatPhoneNumber(phone));
          $('#smsMessage').val('');
          $('#smsCharCount').text('0');
          
          if (window.bootstrap && document.getElementById('sendSmsModal')) {
            var modal = new bootstrap.Modal(document.getElementById('sendSmsModal'));
            modal.show();
          }
        } catch (e) {
          // console.error("Error showing SMS modal:", e);
        }
      });
      
      // Discord DM Modal handling
      $('.send-discord-dm-btn').on('click', function() {
        try {
          var playerName = $(this).data('player-name') || 'Player';
          var playerId = $(this).data('player-id') || '';
          var discordId = $(this).data('discord-id') || '';
          
          $('#discordPlayerName').text(playerName);
          $('#discordPlayerId').val(playerId);
          $('#discordId').val(discordId);
          $('#discordMessage').val('');
          $('#discordCharCount').text('0');
          
          if (window.bootstrap && document.getElementById('sendDiscordDmModal')) {
            var modal = new bootstrap.Modal(document.getElementById('sendDiscordDmModal'));
            modal.show();
          }
        } catch (e) {
          // console.error("Error showing Discord modal:", e);
        }
      });
      
      // RSVP Update handling
      $('.update-rsvp-btn').on('click', function() {
        try {
          var playerId = $(this).data('player-id') || '';
          var matchId = $(this).data('match-id') || '';
          var response = $(this).data('response') || '';
          
          if (!playerId || !matchId || !response) {
            // console.error("Missing required data for RSVP update");
            return;
          }
          
          // Use SweetAlert2 instead of the native confirm dialog
          Swal.fire({
            title: 'Update RSVP Status?',
            text: 'Are you sure you want to update this player\'s RSVP status?',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, update it',
            cancelButtonText: 'Cancel',
            confirmButtonColor: '#696cff',
            customClass: {
              confirmButton: 'btn btn-primary',
              cancelButton: 'btn btn-outline-secondary'
            },
            buttonsStyling: false
          }).then((result) => {
            if (result.isConfirmed) {
              var formData = new FormData();
              var csrfToken = $('input[name="csrf_token"]').val() || '';
              
              formData.append('csrf_token', csrfToken);
              formData.append('player_id', playerId);
              formData.append('match_id', matchId);
              formData.append('response', response);
              
              // Show loading state
              Swal.fire({
                title: 'Updating...',
                allowOutsideClick: false,
                didOpen: () => {
                  Swal.showLoading();
                }
              });
              
              // Simple fetch with improved error handling
              fetch('/admin/update_rsvp', {
                method: 'POST',
                body: formData,
                headers: {
                  'X-Requested-With': 'XMLHttpRequest'
                }
              })
              .then(function(response) {
                if (!response.ok) {
                  throw new Error('Network response was not ok');
                }
                return response.json(); 
              })
              .then(function(data) {
                if (data.success) {
                  Swal.fire({
                    title: 'Success!',
                    text: 'RSVP updated successfully.',
                    icon: 'success',
                    timer: 1500,
                    showConfirmButton: false
                  }).then(() => {
                    window.location.reload();
                  });
                } else {
                  Swal.fire({
                    title: 'Error',
                    text: data.message || 'Error updating RSVP.',
                    icon: 'error'
                  });
                }
              })
              .catch(function(error) {
                // console.error('Error:', error);
                Swal.fire({
                  title: 'Error',
                  text: 'An error occurred while updating RSVP. Please try again.',
                  icon: 'error'
                });
              });
            }
          });
        } catch (e) {
          // console.error("Error handling RSVP update:", e);
        }
      });
      
      // Character counting for SMS
      $('#smsMessage').on('input', function() {
        try {
          var charCount = $(this).val().length;
          $('#smsCharCount').text(charCount);
          
          if (charCount > 160) {
            $('#smsCharCount').addClass('text-danger fw-bold');
          } else {
            $('#smsCharCount').removeClass('text-danger fw-bold');
          }
        } catch (e) {
          // console.error("Error counting SMS characters:", e);
        }
      });
      
      // Character counting for Discord
      $('#discordMessage').on('input', function() {
        try {
          var charCount = $(this).val().length;
          $('#discordCharCount').text(charCount);
          
          if (charCount > 2000) {
            $('#discordCharCount').addClass('text-danger fw-bold');
          } else {
            $('#discordCharCount').removeClass('text-danger fw-bold');
          }
        } catch (e) {
          // console.error("Error counting Discord characters:", e);
        }
      });
      
      // Form submission handlers for SMS
      $('#sendSmsForm').on('submit', function(e) {
        e.preventDefault();
        
        try {
          var charCount = $('#smsMessage').val().length;
          if (charCount > 160) {
            if (window.toastr) {
              toastr.warning('Your message exceeds the 160 character limit for SMS. Please shorten your message.');
            }
            return false;
          }
          
          var formData = new FormData(this);
          var submitBtn = $(this).find('button[type="submit"]');
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
              if (window.bootstrap && document.getElementById('sendSmsModal')) {
                bootstrap.Modal.getInstance(document.getElementById('sendSmsModal')).hide();
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
      $('#sendDiscordDmForm').on('submit', function(e) {
        e.preventDefault();
        
        try {
          var charCount = $('#discordMessage').val().length;
          if (charCount > 2000) {
            if (window.toastr) {
              toastr.warning('Your message exceeds the 2000 character limit for Discord. Please shorten your message.');
            }
            return false;
          }
          
          var formData = new FormData(this);
          var submitBtn = $(this).find('button[type="submit"]');
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
              if (window.bootstrap && document.getElementById('sendDiscordDmModal')) {
                bootstrap.Modal.getInstance(document.getElementById('sendDiscordDmModal')).hide();
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
function bindTabHandlers() {
  try {
    if (window.jQuery) {
      var $ = window.jQuery;
      
      // Handle tab switching
      $('a[data-bs-toggle="tab"]').on('shown.bs.tab', function() {
        // Fix overflow issues
        fixDropdownsAndOverflow();
        
        // Adjust DataTables
        if ($.fn.dataTable) {
          $.fn.dataTable.tables({ visible: true, api: true }).columns.adjust();
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
function loadAvailableSubs() {
  try {
    if (window.jQuery) {
      var $ = window.jQuery;
      
      // Check if the assign sub modal exists
      if ($('#assignSubModalRSVP').length === 0) {
        return;
      }
      
      // When the modal is shown, fetch substitute responses
      $('#assignSubModalRSVP').on('shown.bs.modal', function() {
        var subPlayerSelect = $('#subPlayerRSVP');
        
        // Clear existing options except the default
        subPlayerSelect.find('option:not(:first)').remove();
        subPlayerSelect.append('<option value="loading" disabled>Loading substitute responses...</option>');
        
        // Determine match type and ID from the form
        var matchIdValue = $('input[name="match_id"]').val();
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
                $('.form-text').html('<i class="ti ti-info-circle me-1"></i> <span class="text-success">Green = Available</span>, <span class="text-muted">Gray = No Response</span>, <span class="text-danger">Red = Not Available</span>');
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
      $('#assignSubFormRSVP').on('submit', function(e) {
        e.preventDefault();
        
        var formData = new FormData(this);
        var submitBtn = $(this).find('button[type="submit"]');
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
              Swal.fire({
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
            if (window.bootstrap && document.getElementById('assignSubModalRSVP')) {
              var modal = bootstrap.Modal.getInstance(document.getElementById('assignSubModalRSVP'));
              modal.hide();
            }
          } else {
            // Show error message
            if (window.Swal) {
              Swal.fire({
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
function fixTeamOptions() {
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
function removeDataTablesArrows() {
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

// Apply the fix immediately after DataTables initialization
document.addEventListener('DOMContentLoaded', function() {
  setTimeout(function() {
    removeDataTablesArrows();
  }, 1000);
});