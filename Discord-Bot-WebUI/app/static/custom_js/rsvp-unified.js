/**
 * RSVP Unified Script - v2.0
 * This is a completely rewritten version of the RSVP page JavaScript
 * designed to be extremely stable and avoid any syntax errors.
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
        console.error("Error initializing RSVP page:", e);
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
    console.error("Error fixing dropdowns:", e);
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
          console.error("Error showing SMS modal:", e);
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
          console.error("Error showing Discord modal:", e);
        }
      });
      
      // RSVP Update handling
      $('.update-rsvp-btn').on('click', function() {
        try {
          var playerId = $(this).data('player-id') || '';
          var matchId = $(this).data('match-id') || '';
          var response = $(this).data('response') || '';
          
          if (!playerId || !matchId || !response) {
            console.error("Missing required data for RSVP update");
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
                console.error('Error:', error);
                Swal.fire({
                  title: 'Error',
                  text: 'An error occurred while updating RSVP. Please try again.',
                  icon: 'error'
                });
              });
            }
          });
        } catch (e) {
          console.error("Error handling RSVP update:", e);
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
          console.error("Error counting SMS characters:", e);
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
          console.error("Error counting Discord characters:", e);
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
            console.error('Error:', error);
            if (window.toastr) {
              toastr.error('An error occurred while sending SMS.');
            }
          })
          .finally(function() {
            submitBtn.prop('disabled', false).html(originalText);
          });
        } catch (e) {
          console.error("Error sending SMS:", e);
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
            console.error('Error:', error);
            if (window.toastr) {
              toastr.error('An error occurred while sending Discord DM.');
            }
          })
          .finally(function() {
            submitBtn.prop('disabled', false).html(originalText);
          });
        } catch (e) {
          console.error("Error sending Discord DM:", e);
        }
      });
    }
  } catch (e) {
    console.error("Global error in bindEventHandlers:", e);
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
    console.error("Error binding tab handlers:", e);
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
      
      // When the modal is shown, fetch available subs
      $('#assignSubModalRSVP').on('shown.bs.modal', function() {
        var subPlayerSelect = $('#subPlayerRSVP');
        
        // Clear existing options except the default
        subPlayerSelect.find('option:not(:first)').remove();
        subPlayerSelect.append('<option value="loading" disabled>Loading available substitutes...</option>');
        
        // Fetch available subs using AJAX
        fetch('/admin/subs/available')
          .then(response => {
            if (!response.ok) {
              throw new Error('Network response was not ok');
            }
            return response.json();
          })
          .then(data => {
            // Get subs array from response
            var subData = data.subs || [];
            
            // Clear loading option
            subPlayerSelect.find('option[value="loading"]').remove();
            
            // Add subs to select
            if (subData.length > 0) {
              subData.forEach(function(sub) {
                subPlayerSelect.append(`<option value="${sub.id}">${sub.name}</option>`);
              });
            } else {
              subPlayerSelect.append('<option value="" disabled>No available substitutes found</option>');
            }
          })
          .catch(error => {
            console.error('Error fetching substitutes:', error);
            subPlayerSelect.find('option[value="loading"]').remove();
            subPlayerSelect.append('<option value="" disabled>Error loading substitutes</option>');
            
            // Show error toast if toastr is available
            if (window.toastr) {
              toastr.error('Failed to load available substitutes. Please try again.');
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
          console.error('Error assigning substitute:', error);
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
    console.error("Error loading available subs:", e);
  }
}