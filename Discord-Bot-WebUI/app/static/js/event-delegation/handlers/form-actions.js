/**
 * ============================================================================
 * FORM ACTIONS - Event Delegation Handlers
 * ============================================================================
 *
 * Common form-related actions:
 * - auto-submit-form: Submit the closest parent form on change
 * - toggle-select-all: Toggle all checkboxes in a group
 * - filter-by-value: Redirect with query parameter
 *
 * ============================================================================
 */
'use strict';

import { EventDelegation } from '../core.js';

// ============================================================================
// AUTO-SUBMIT FORM
// ============================================================================

/**
 * Automatically submit the closest parent form when an input changes
 * Usage: <select data-action="auto-submit-form">
 */
function handleAutoSubmitForm(event, element) {
    const form = element.closest('form');
    if (form) {
        form.submit();
    }
}

// ============================================================================
// TOGGLE SELECT ALL
// ============================================================================

/**
 * Toggle all checkboxes within a specified container
 * Usage: <input type="checkbox" data-action="toggle-select-all" data-target=".item-checkbox">
 */
function handleToggleSelectAll(event, element) {
    const targetSelector = element.dataset.target || '.item-checkbox';
    const container = element.closest('table') || element.closest('form') || document;
    const checkboxes = container.querySelectorAll(targetSelector);

    checkboxes.forEach(cb => {
        if (cb !== element) {
            cb.checked = element.checked;
            // Trigger change event for any dependent handlers
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        }
    });
}

// ============================================================================
// FILTER BY VALUE
// ============================================================================

/**
 * Redirect to current URL with a query parameter
 * Usage: <select data-action="filter-by-value" data-param="status">
 */
function handleFilterByValue(event, element) {
    const paramName = element.dataset.param || 'filter';
    const value = element.value;
    const url = new URL(window.location);

    if (value && value !== 'all') {
        url.searchParams.set(paramName, value);
    } else {
        url.searchParams.delete(paramName);
    }

    window.location = url;
}

// ============================================================================
// UPDATE SELECTION COUNT
// ============================================================================

/**
 * Update a selection count display when checkboxes change
 * Usage: <input type="checkbox" data-action="update-selection" data-count="#selectedCount" data-bar="#bulkActionsBar">
 */
function handleUpdateSelection(event, element) {
    const countSelector = element.dataset.count || '#selectedCount';
    const barSelector = element.dataset.bar || '#bulkActionsBar';
    const checkboxSelector = element.dataset.items || '.item-checkbox:checked';

    const container = element.closest('table') || element.closest('form') || document;
    const checkedBoxes = container.querySelectorAll(checkboxSelector);
    const count = checkedBoxes.length;

    const countEl = document.querySelector(countSelector);
    const barEl = document.querySelector(barSelector);

    if (countEl) {
        countEl.textContent = count;
    }

    if (barEl) {
        if (count > 0) {
            barEl.classList.remove('hidden');
        } else {
            barEl.classList.add('hidden');
        }
    }
}

// ============================================================================
// CLEAR SELECTION
// ============================================================================

/**
 * Clear all checkboxes in a group
 * Usage: <button data-action="clear-selection" data-target=".item-checkbox">
 */
function handleClearSelection(event, element) {
    const targetSelector = element.dataset.target || '.item-checkbox';
    const selectAllSelector = element.dataset.selectAll || '.select-all-checkbox';
    const container = element.closest('table') || element.closest('form') || document;

    const checkboxes = container.querySelectorAll(targetSelector);
    checkboxes.forEach(cb => {
        cb.checked = false;
    });

    // Also uncheck the "select all" checkbox
    const selectAll = container.querySelector(selectAllSelector);
    if (selectAll) {
        selectAll.checked = false;
    }

    // Trigger update-selection to hide the bulk actions bar
    const firstCheckbox = checkboxes[0];
    if (firstCheckbox) {
        firstCheckbox.dispatchEvent(new Event('change', { bubbles: true }));
    }
}

// ============================================================================
// REGISTER HANDLERS
// ============================================================================

window.EventDelegation.register('auto-submit-form', handleAutoSubmitForm, {
    preventDefault: false,
    events: ['change']
});

window.EventDelegation.register('toggle-select-all', handleToggleSelectAll, {
    preventDefault: false,
    events: ['change']
});

window.EventDelegation.register('filter-by-value', handleFilterByValue, {
    preventDefault: false,
    events: ['change']
});

window.EventDelegation.register('update-selection', handleUpdateSelection, {
    preventDefault: false,
    events: ['change']
});

window.EventDelegation.register('clear-selection', handleClearSelection, {
    preventDefault: true
});

// ============================================================================
// EXPORTS
// ============================================================================

export {
    handleAutoSubmitForm,
    handleToggleSelectAll,
    handleFilterByValue,
    handleUpdateSelection,
    handleClearSelection
};
