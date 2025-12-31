/**
 * Mobile Tables - Simple table label injection
 * Adds data-label attributes to table cells for mobile responsive display
 */
import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function init() {
    if (_initialized) return;
    _initialized = true;

    addTableLabels();

    // Run after AJAX if jQuery exists
    if (typeof window.$ !== 'undefined') {
        window.$(document).on('ajaxComplete', addTableLabels);
    }
}

function addTableLabels() {
    const tables = document.querySelectorAll('.table-responsive table');

    tables.forEach(table => {
        if (table.dataset.labeled) return;

        const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());

        table.querySelectorAll('tbody tr').forEach(row => {
            Array.from(row.querySelectorAll('td')).forEach((cell, index) => {
                if (headers[index] && !cell.hasAttribute('data-label')) {
                    cell.setAttribute('data-label', headers[index]);
                }
            });
        });

        table.dataset.labeled = 'true';
    });
}

// Register with InitSystem (primary)
if (InitSystem && InitSystem.register) {
    InitSystem.register('mobile-tables', init, {
        priority: 40,
        reinitializable: true,
        description: 'Mobile table label injection'
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
window.addTableLabels = addTableLabels;
