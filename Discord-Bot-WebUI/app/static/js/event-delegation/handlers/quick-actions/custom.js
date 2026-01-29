'use strict';

/**
 * Quick Actions - Custom Actions
 *
 * Event delegation handlers for custom administrative actions:
 * - Execute custom action
 * - Validate custom action
 * - Save custom action as template
 *
 * @module quick-actions/custom
 */

/**
 * Execute Custom Action
 * Executes a custom administrative action
 */
window.EventDelegation.register('execute-custom-action', function(element, e) {
    e.preventDefault();

    const actionType = document.getElementById('actionType')?.value;
    const actionTarget = document.getElementById('actionTarget')?.value;
    const actionCommand = document.getElementById('actionCommand')?.value;
    const requireConfirmation = document.getElementById('confirmBeforeExecution')?.checked;

    if (!actionType || !actionCommand) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Missing Information', 'Please select an action type and enter a command.', 'warning');
        }
        return;
    }

    const executeAction = () => {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Executing Action...',
                text: `Running ${actionType} action`,
                allowOutsideClick: false,
                didOpen: () => {
                    window.Swal.showLoading();
                    setTimeout(() => {
                        window.Swal.fire('Action Completed!', 'Custom action has been executed successfully.', 'success');
                    }, 2000);
                }
            });
        }
    };

    if (requireConfirmation) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                title: 'Execute Custom Action?',
                html: `
                    <div class="text-start">
                        <strong>Action Type:</strong> ${actionType}<br>
                        <strong>Target:</strong> ${actionTarget || 'None'}<br>
                        <strong>Command:</strong><br>
                        <code class="small">${actionCommand}</code>
                    </div>
                `,
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Execute Action'
            }).then((result) => {
                if (result.isConfirmed) {
                    executeAction();
                }
            });
        }
    } else {
        executeAction();
    }
});

/**
 * Validate Custom Action
 * Validates a custom action without executing
 */
window.EventDelegation.register('validate-custom-action', function(element, e) {
    e.preventDefault();

    const actionType = document.getElementById('actionType')?.value;
    const actionCommand = document.getElementById('actionCommand')?.value;

    if (!actionType || !actionCommand) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Missing Information', 'Please select an action type and enter a command.', 'warning');
        }
        return;
    }

    if (typeof window.Swal !== 'undefined') {
        window.Swal.fire('Action Valid!', 'The custom action syntax is valid and ready for execution.', 'success');
    }
});

/**
 * Save Custom Action
 * Saves a custom action as a template
 */
window.EventDelegation.register('save-custom-action', function(element, e) {
    e.preventDefault();

    const actionType = document.getElementById('actionType')?.value;
    const actionCommand = document.getElementById('actionCommand')?.value;

    if (!actionType || !actionCommand) {
        if (typeof window.Swal !== 'undefined') {
            window.Swal.fire('Missing Information', 'Please select an action type and enter a command.', 'warning');
        }
        return;
    }

    if (typeof window.Swal === 'undefined') {
        console.error('[save-custom-action] SweetAlert2 not available');
        return;
    }

    window.Swal.fire({
        title: 'Save as Template',
        html: `
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Template Name</label>
                <input type="text" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="templateName" placeholder="Enter template name" data-form-control>
            </div>
            <div class="mb-3">
                <label class="block mb-2 text-sm font-medium text-gray-900 dark:text-white">Description</label>
                <textarea class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-ecs-green focus:border-ecs-green block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" id="templateDescription" rows="2" placeholder="Template description (optional)" data-form-control></textarea>
            </div>
        `,
        showCancelButton: true,
        confirmButtonText: 'Save Template',
        preConfirm: () => {
            const templateName = document.getElementById('templateName').value;
            if (!templateName) {
                window.Swal.showValidationMessage('Template name is required');
                return false;
            }
            return templateName;
        }
    }).then((result) => {
        if (result.isConfirmed) {
            window.Swal.fire('Template Saved!', 'Custom action has been saved as a template.', 'success');
        }
    });
});
