# Custom JavaScript Files

This directory contains custom JavaScript files that extend, fix, or enhance the application's functionality.

## RSVP Page Scripts

### design-system-override.js
Safely overrides problematic methods in the main design-system.js file without modifying the original. Fixes JavaScript syntax errors and ensures that crucial functionality continues to work correctly.

### page-loader.js
Manages the loading indicator that's displayed while the page is loading. Ensures a smooth transition from the loading state to the fully loaded page.

### rsvp-page-fixes.js
Contains fixes specific to the RSVP status page, focusing on dropdown positioning, z-index issues, and other layout concerns.

### rsvp-form-handlers.js
Handles form submission and other interactive elements on the RSVP page, including form validation, character counting, and AJAX requests.

## Usage

These scripts are loaded in a specific order to ensure proper functionality:

1. `design-system-override.js` - Loaded first to patch any issues with the core design system
2. `page-loader.js` - Manages the page loading experience
3. `rsvp-page-fixes.js` - Applies specific fixes to the page layout
4. `rsvp-form-handlers.js` - Initializes interactive elements and form handlers

## Enhancements

The scripts provide the following enhancements:

- Modern, polished modal designs for SMS and Discord messaging
- Character counters for message composition (160 chars for SMS, 2000 for Discord)
- Visual feedback during message submission
- Proper dropdown menu positioning that works with DataTables
- Smooth loading transitions
- Fixed JavaScript syntax errors from the original codebase

## Maintenance Notes

When updating the main application code, be aware that these custom scripts might need to be updated as well to remain compatible. Specifically, check for:

- Changes to modal structure or identifiers
- Updates to the core design-system.js file
- Changes to the DataTables initialization
- Modifications to CSS that might affect z-index or positioning