/**
 * RSVP Form Handlers
 * 
 * Handles form submission and other interactive elements for the RSVP page
 */

$(document).ready(function() {
    "use strict";
    
    // Configure Toastr notifications
    toastr.options = {
        "closeButton": true,
        "debug": false,
        "newestOnTop": true,
        "progressBar": true,
        "positionClass": "toast-top-right",
        "preventDuplicates": false,
        "onclick": null,
        "showDuration": "300",
        "hideDuration": "1000",
        "timeOut": "5000",
        "extendedTimeOut": "1000",
        "showEasing": "swing",
        "hideEasing": "linear",
        "showMethod": "fadeIn",
        "hideMethod": "fadeOut"
    };

    // Initialize tooltips
    try {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    } catch (e) {
        // console.error("Error initializing tooltips:", e);
    }
    
    // Initialize DataTables
    try {
        const tableOptions = {
            responsive: true,
            pageLength: 10,
            lengthMenu: [5, 10, 25, 50],
            language: {
                search: "",
                searchPlaceholder: "Search players..."
            },
            dom: '<"row d-flex justify-content-between align-items-center m-1"' +
                 '<"col-lg-6 d-flex align-items-center"l<"dt-action-buttons text-xl-end text-lg-start text-md-end text-start mt-md-0 mt-3"B>>' +
                 '<"col-lg-6 d-flex align-items-center justify-content-lg-end flex-lg-nowrap flex-wrap pe-lg-1 p-0"f>' +
                 '>t<"d-flex justify-content-between mx-2 row"<"col-sm-12 col-md-6"i><"col-sm-12 col-md-6"p>>',
            buttons: [
                {
                    extend: 'collection',
                    className: 'd-none',
                    text: 'Export',
                    buttons: [
                        {
                            extend: 'copy',
                            className: 'dropdown-item',
                            text: '<i class="ti ti-copy me-1"></i>Copy',
                            exportOptions: { columns: [0, 1, 2, 3] }
                        },
                        {
                            extend: 'excel',
                            className: 'dropdown-item',
                            text: '<i class="ti ti-file-spreadsheet me-1"></i>Excel',
                            exportOptions: { columns: [0, 1, 2, 3] }
                        },
                        {
                            extend: 'csv',
                            className: 'dropdown-item',
                            text: '<i class="ti ti-file-text me-1"></i>CSV',
                            exportOptions: { columns: [0, 1, 2, 3] }
                        },
                        {
                            extend: 'pdf',
                            className: 'dropdown-item',
                            text: '<i class="ti ti-file-description me-1"></i>PDF',
                            exportOptions: { columns: [0, 1, 2, 3] }
                        }
                    ]
                }
            ],
            drawCallback: function() {
                // Fix overflow issues
                $(this).closest('.card-body').css('overflow', 'visible');
                $(this).closest('.table-responsive').css('overflow', 'visible');
            }
        };
        
        // Initialize all DataTables with the same options
        $('#rsvpStatusTable').DataTable(tableOptions);
        $('#homeTeamTable').DataTable(tableOptions);
        $('#awayTeamTable').DataTable(tableOptions);
        
        // Make search input look nicer
        $('.dataTables_filter .form-control').removeClass('form-control-sm');
        $('.dataTables_length .form-select').removeClass('form-select-sm');
        
        // Add proper Bootstrap styling
        $('.dataTables_filter input').addClass('rounded-pill');
        $('.dataTables_length select').addClass('rounded-pill');
        
        // Tab switching behavior - make sure DataTables resize correctly
        $('a[data-bs-toggle="tab"]').on('shown.bs.tab', function(e) {
            $.fn.dataTable.tables({ visible: true, api: true }).columns.adjust();
        });
    } catch (e) {
        // console.error("Error initializing DataTables:", e);
    }
    
    // Helper function to format phone number
    function formatPhoneNumber(phoneNumber) {
        if (!phoneNumber) return '';
        
        // Remove all non-numeric characters
        const cleaned = ('' + phoneNumber).replace(/\D/g, '');
        
        // Format the phone number
        const match = cleaned.match(/^(\d{1})(\d{3})(\d{3})(\d{4})$/);
        if (match) {
            return `+${match[1]} (${match[2]}) ${match[3]}-${match[4]}`;
        }
        
        const match2 = cleaned.match(/^(\d{3})(\d{3})(\d{4})$/);
        if (match2) {
            return `(${match2[1]}) ${match2[2]}-${match2[3]}`;
        }
        
        return phoneNumber;
    }

    // Function to initialize event handlers
    function initializeEventHandlers() {
        try {
            // SMS Modal handling
            $('.send-sms-btn').off('click').on('click', function() {
                const playerName = $(this).data('player-name');
                const playerId = $(this).data('player-id');
                const phone = $(this).data('phone');
                
                $('#smsPlayerName').text(playerName);
                $('#smsPlayerId').val(playerId);
                $('#smsPlayerPhone').val(phone);
                $('#smsPlayerPhoneDisplay').text(formatPhoneNumber(phone));
                $('#smsMessage').val('');
                $('#smsCharCount').text('0');
                
                const modal = new bootstrap.Modal(document.getElementById('sendSmsModal'));
                modal.show();
            });
            
            // Discord DM Modal handling
            $('.send-discord-dm-btn').off('click').on('click', function() {
                const playerName = $(this).data('player-name');
                const playerId = $(this).data('player-id');
                const discordId = $(this).data('discord-id');
                
                $('#discordPlayerName').text(playerName);
                $('#discordPlayerId').val(playerId);
                $('#discordId').val(discordId);
                $('#discordMessage').val('');
                $('#discordCharCount').text('0');
                
                const modal = new bootstrap.Modal(document.getElementById('sendDiscordDmModal'));
                modal.show();
            });
            
            // RSVP Update handling
            $('.update-rsvp-btn').off('click').on('click', function() {
                const playerId = $(this).data('player-id');
                const matchId = $(this).data('match-id');
                const response = $(this).data('response');
                
                if (confirm('Are you sure you want to update this player\'s RSVP status?')) {
                    const formData = new FormData();
                    formData.append('csrf_token', $('input[name="csrf_token"]').val());
                    formData.append('player_id', playerId);
                    formData.append('match_id', matchId);
                    formData.append('response', response);
                    
                    fetch('/admin/update_rsvp', {
                        method: 'POST',
                        body: formData,
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            toastr.success('RSVP updated successfully.');
                            window.location.reload();
                        } else {
                            toastr.error(data.message || 'Error updating RSVP.');
                        }
                    })
                    .catch(error => {
                        // console.error('Error:', error);
                        toastr.error('An error occurred while updating RSVP.');
                    });
                }
            });
            
            // Character counting for SMS
            $('#smsMessage').off('input').on('input', function() {
                const charCount = $(this).val().length;
                $('#smsCharCount').text(charCount);
                
                // Visual feedback for SMS character limit
                if (charCount > 160) {
                    $('#smsCharCount').addClass('text-danger fw-bold');
                } else {
                    $('#smsCharCount').removeClass('text-danger fw-bold');
                }
            });
            
            // Character counting for Discord
            $('#discordMessage').off('input').on('input', function() {
                const charCount = $(this).val().length;
                $('#discordCharCount').text(charCount);
                
                // Visual feedback for Discord character limit
                if (charCount > 2000) {
                    $('#discordCharCount').addClass('text-danger fw-bold');
                } else {
                    $('#discordCharCount').removeClass('text-danger fw-bold');
                }
            });
        } catch (e) {
            // console.error("Error initializing event handlers:", e);
        }
    }
    
    // Initialize all event handlers
    try {
        initializeEventHandlers();
        
        // Re-initialize handlers when switching tabs
        $('a[data-bs-toggle="tab"]').on('shown.bs.tab', function(e) {
            initializeEventHandlers();
        });
    } catch (e) {
        // console.error("Error setting up tab handlers:", e);
    }
    
    // Form submission handlers
    try {
        $('#sendSmsForm').on('submit', function(e) {
            e.preventDefault();
            
            // Check character count
            const charCount = $('#smsMessage').val().length;
            if (charCount > 160) {
                toastr.warning('Your message exceeds the 160 character limit for SMS. Please shorten your message.');
                return false;
            }
            
            const formData = new FormData(this);
            
            // Disable submit button and show loading state
            const submitBtn = $(this).find('button[type="submit"]');
            const originalText = submitBtn.html();
            submitBtn.prop('disabled', true).html('<i class="ti ti-loader ti-spin me-1"></i>Sending...');
            
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
                    toastr.success('SMS sent successfully.');
                    bootstrap.Modal.getInstance(document.getElementById('sendSmsModal')).hide();
                } else {
                    toastr.error(data.message || 'Error sending SMS.');
                }
            })
            .catch(error => {
                // console.error('Error:', error);
                toastr.error('An error occurred while sending SMS.');
            })
            .finally(() => {
                // Restore button state
                submitBtn.prop('disabled', false).html(originalText);
            });
        });
        
        $('#sendDiscordDmForm').on('submit', function(e) {
            e.preventDefault();
            
            // Check character count
            const charCount = $('#discordMessage').val().length;
            if (charCount > 2000) {
                toastr.warning('Your message exceeds the 2000 character limit for Discord. Please shorten your message.');
                return false;
            }
            
            const formData = new FormData(this);
            
            // Disable submit button and show loading state
            const submitBtn = $(this).find('button[type="submit"]');
            const originalText = submitBtn.html();
            submitBtn.prop('disabled', true).html('<i class="ti ti-loader ti-spin me-1"></i>Sending...');
            
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
                    toastr.success('Discord DM sent successfully.');
                    bootstrap.Modal.getInstance(document.getElementById('sendDiscordDmModal')).hide();
                } else {
                    toastr.error(data.message || 'Error sending Discord DM.');
                }
            })
            .catch(error => {
                // console.error('Error:', error);
                toastr.error('An error occurred while sending Discord DM.');
            })
            .finally(() => {
                // Restore button state
                submitBtn.prop('disabled', false).html(originalText);
            });
        });
    } catch (e) {
        // console.error("Error setting up form handlers:", e);
    }
});