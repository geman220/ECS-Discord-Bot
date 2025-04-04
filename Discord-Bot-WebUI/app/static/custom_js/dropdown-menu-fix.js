/**
 * Simple Dropdown Menu Fix
 * This minimal script fixes dropdown menus being hidden behind tables
 */

document.addEventListener('DOMContentLoaded', function() {
    // We're not going to add complex event listeners
    // Just add the necessary class to problem tables
    
    // Find tables in user management page
    const userManagementTables = document.querySelectorAll('.table');
    userManagementTables.forEach(table => {
        table.classList.add('user-management-table');
    });
    
    // Add class to RSVP status page
    if (window.location.href.includes('rsvp_status')) {
        document.body.classList.add('rsvp-status-page');
    }
});