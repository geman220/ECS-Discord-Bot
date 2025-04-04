/**
 * DataTables Dropdown Fix
 * 
 * This script fixes issues with Bootstrap dropdowns in DataTables
 * where the dropdown menu is constrained within its parent container.
 */

(function($) {
    'use strict';
    
    // Run on document ready
    $(document).ready(function() {
        // Override default DataTables initialization
        $.extend(true, $.fn.dataTable.defaults, {
            // Add a callback after table draw
            "drawCallback": function(settings) {
                // Fix overflow on all parent containers
                $(this).closest('.dataTables_wrapper').css('overflow', 'visible');
                $(this).closest('.table-responsive').css('overflow', 'visible');
                $(this).closest('.card-body').css('overflow', 'visible');
                $(this).closest('.card').css('overflow', 'visible');
                $(this).closest('.tab-pane').css('overflow', 'visible');
                $(this).closest('.tab-content').css('overflow', 'visible');
                
                // Ensure dropdown toggles work correctly
                $(this).find('.dropdown-toggle').off('click.fixDropdown').on('click.fixDropdown', function() {
                    // Get the dropdown menu
                    const $dropdownMenu = $(this).next('.dropdown-menu');
                    
                    // When dropdown is shown, ensure it's positioned correctly
                    $dropdownMenu.css({
                        'position': 'fixed',
                        'z-index': '9999'
                    });
                    
                    // Calculate position
                    setTimeout(function() {
                        const buttonRect = $(this)[0].getBoundingClientRect();
                        $dropdownMenu.css({
                            'top': (buttonRect.bottom + window.scrollY) + 'px',
                            'left': (buttonRect.left + window.scrollX) + 'px',
                            'right': 'auto',
                            'transform': 'none'
                        });
                    }.bind(this), 0);
                });
            }
        });
        
        // Global event handler for tab switching
        $('a[data-bs-toggle="tab"]').on('shown.bs.tab', function (e) {
            // Reinitialize all tables when tab is switched
            setTimeout(function() {
                $.fn.dataTable.tables({ visible: true, api: true }).columns.adjust();
                
                // Fix overflow issues
                $('.dataTables_wrapper, .table-responsive, .card-body, .tab-pane, .tab-content')
                    .css('overflow', 'visible');
            }, 10);
        });
    });
    
    // Handle document events to ensure dropdowns remain visible
    $(document).on('shown.bs.dropdown', '.dropdown', function() {
        const $dropdown = $(this);
        const $menu = $dropdown.find('.dropdown-menu');
        
        // Fix position for dropdown menus
        $menu.css({
            'z-index': '9999',
            'position': 'absolute',
            'transform': 'none'
        });
        
        // Ensure parent containers don't clip the dropdown
        $dropdown.parents().each(function() {
            $(this).css('overflow', 'visible');
        });
    });
    
})(jQuery);