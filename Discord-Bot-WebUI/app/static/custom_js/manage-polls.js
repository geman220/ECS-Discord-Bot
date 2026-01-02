/**
 * Manage Polls Page
 * Initializes DataTable for polls listing
 */
import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function init() {
    if (_initialized) return;

    // Page guard - only run if polls table exists
    const pollsTable = document.getElementById('pollsTable');
    if (!pollsTable) return;

    // Check jQuery and DataTables are available
    if (typeof window.$ === 'undefined' || typeof window.$.fn.DataTable === 'undefined') {
        console.warn('[Manage Polls] jQuery or DataTables not available');
        return;
    }

    _initialized = true;

    // Destroy existing DataTable if it exists
    if (window.$.fn.DataTable.isDataTable('#pollsTable')) {
        window.$('#pollsTable').DataTable().destroy();
    }

    // Initialize DataTable
    window.$('#pollsTable').DataTable({
        "order": [[ 3, "desc" ]], // Order by created date, newest first
        "pageLength": 25,
        "responsive": true,
        "columnDefs": [
            { "orderable": false, "targets": [5] } // Disable sorting on actions column
        ]
    });
}

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('manage-polls', init, {
        priority: 35,
        reinitializable: true,
        description: 'Manage polls DataTable'
    });
}

// Fallback for non-module usage
// window.InitSystem handles initialization
