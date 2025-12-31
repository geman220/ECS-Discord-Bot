/**
 * ============================================================================
 * MESSAGE TEMPLATE DETAIL - Template Management in Categories
 * ============================================================================
 *
 * Handles message template management within categories in the admin panel.
 * Replaces 90-line inline script from category_detail.html.
 *
 * Features:
 * - View template content
 * - Edit templates
 * - Toggle template active status
 * - Delete templates with confirmation
 * - Event delegation for dynamic actions
 *
 * NO INLINE STYLES - Uses CSS classes and data attributes instead.
 *
 * Dependencies:
 * - Bootstrap 5.x (modals)
 * - SweetAlert2 (confirmations)
 * - EventDelegation (centralized event handling)
 *
 * ============================================================================
 */
// ES Module
'use strict';

// ========================================================================
    // VIEW TEMPLATE
    // ========================================================================

    /**
     * View template content in modal
     * @param {number} id - Template ID
     * @param {string} name - Template name
     * @param {string} content - Template content
     */
    export function viewTemplate(id, name, content) {
        const titleEl = document.getElementById('view_template_title');
        const contentEl = document.getElementById('view_template_content');

        if (titleEl) titleEl.textContent = name;
        if (contentEl) contentEl.textContent = content;

        // Show modal
        const modalEl = document.getElementById('viewTemplateModal');
        if (modalEl) {
            window.ModalManager.show('viewTemplateModal');
        }
    }

    // ========================================================================
    // EDIT TEMPLATE
    // ========================================================================

    /**
     * Edit a template
     * Opens modal with pre-filled template data
     * @param {number} id - Template ID
     * @param {string} name - Template name
     * @param {string} description - Template description
     * @param {string} content - Template content
     * @param {string} channelType - Channel type (discord_dm, sms, etc.)
     * @param {string} usageContext - Usage context description
     * @param {boolean} isActive - Template active status
     */
    export function editTemplate(id, name, description, content, channelType, usageContext, isActive) {
        const idInput = document.getElementById('edit_template_id');
        const nameInput = document.getElementById('edit_template_name');
        const descInput = document.getElementById('edit_template_description');
        const contentInput = document.getElementById('edit_template_content');
        const channelSelect = document.getElementById('edit_channel_type');
        const contextInput = document.getElementById('edit_usage_context');
        const activeCheckbox = document.getElementById('edit_template_active');

        if (idInput) idInput.value = id;
        if (nameInput) nameInput.value = name;
        if (descInput) descInput.value = description || '';
        if (contentInput) contentInput.value = content;
        if (channelSelect) channelSelect.value = channelType || '';
        if (contextInput) contextInput.value = usageContext || '';
        if (activeCheckbox) activeCheckbox.checked = isActive;

        // Show edit modal
        const modalEl = document.getElementById('editTemplateModal');
        if (modalEl) {
            window.ModalManager.show('editTemplateModal');
        }
    }

    // ========================================================================
    // TOGGLE TEMPLATE STATUS
    // ========================================================================

    /**
     * Toggle template active/inactive status
     * @param {number} id - Template ID
     * @param {string} name - Template name for display
     * @param {boolean} currentStatus - Current active status
     * @param {string} toggleUrl - URL to submit toggle request
     * @param {string} csrfToken - CSRF token for form submission
     */
    export function toggleTemplate(id, name, currentStatus, toggleUrl, csrfToken) {
        const action = currentStatus ? 'deactivate' : 'activate';
        const newStatus = !currentStatus;

        window.Swal.fire({
            title: `${action.charAt(0).toUpperCase() + action.slice(1)} Template?`,
            text: `Are you sure you want to ${action} "${name}"?`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: newStatus ?
                (getComputedStyle(document.documentElement).getPropertyValue('--ecs-success').trim() || '#198754') :
                (getComputedStyle(document.documentElement).getPropertyValue('--ecs-warning').trim() || '#ffc107'),
            cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ?
                window.ECSTheme.getColor('secondary') :
                (getComputedStyle(document.documentElement).getPropertyValue('--ecs-neutral-50').trim() || '#6c757d'),
            confirmButtonText: `Yes, ${action} it!`
        }).then((result) => {
            if (result.isConfirmed) {
                // Create form and submit
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = toggleUrl;

                const csrfInput = document.createElement('input');
                csrfInput.type = 'hidden';
                csrfInput.name = 'csrf_token';
                csrfInput.value = csrfToken;

                const templateIdInput = document.createElement('input');
                templateIdInput.type = 'hidden';
                templateIdInput.name = 'template_id';
                templateIdInput.value = id;

                form.appendChild(csrfInput);
                form.appendChild(templateIdInput);
                document.body.appendChild(form);
                form.submit();
            }
        });
    }

    // ========================================================================
    // DELETE TEMPLATE
    // ========================================================================

    /**
     * Delete a template
     * Shows confirmation dialog before deletion
     * @param {number} id - Template ID
     * @param {string} name - Template name for display
     * @param {string} deleteUrl - URL to submit delete request
     * @param {string} csrfToken - CSRF token for form submission
     */
    export function deleteTemplate(id, name, deleteUrl, csrfToken) {
        window.Swal.fire({
            title: 'Delete Template?',
            text: `Are you sure you want to delete "${name}"? This action cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof window.ECSTheme !== 'undefined') ?
                window.ECSTheme.getColor('danger') :
                (getComputedStyle(document.documentElement).getPropertyValue('--ecs-danger').trim() || '#dc3545'),
            cancelButtonColor: (typeof window.ECSTheme !== 'undefined') ?
                window.ECSTheme.getColor('info') :
                (getComputedStyle(document.documentElement).getPropertyValue('--ecs-info').trim() || '#0dcaf0'),
            confirmButtonText: 'Yes, delete it!'
        }).then((result) => {
            if (result.isConfirmed) {
                // Create form and submit
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = deleteUrl;

                const csrfInput = document.createElement('input');
                csrfInput.type = 'hidden';
                csrfInput.name = 'csrf_token';
                csrfInput.value = csrfToken;

                const templateIdInput = document.createElement('input');
                templateIdInput.type = 'hidden';
                templateIdInput.name = 'template_id';
                templateIdInput.value = id;

                form.appendChild(csrfInput);
                form.appendChild(templateIdInput);
                document.body.appendChild(form);
                form.submit();
            }
        });
    }

    // ========================================================================
    // VARIABLE INSERTION
    // ========================================================================

    /**
     * Insert variable into textarea at cursor position
     * @param {string} variable - Variable string to insert
     * @param {string} targetId - ID of textarea to insert into
     */
    export function insertVariable(variable, targetId) {
        const textarea = document.getElementById(targetId);
        if (!textarea) return;

        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const text = textarea.value;

        // Insert variable at cursor position
        textarea.value = text.substring(0, start) + variable + text.substring(end);

        // Move cursor to after inserted variable
        const newPos = start + variable.length;
        textarea.setSelectionRange(newPos, newPos);
        textarea.focus();
    }

    /**
     * Initialize variable button click handlers
     */
    export function initVariableButtons() {
        document.addEventListener('click', function(e) {
            const varBtn = e.target.closest('.var-btn');
            if (!varBtn) return;

            e.preventDefault();
            const variable = varBtn.dataset.var;
            const targetId = varBtn.dataset.target || 'template_content';

            // Determine target based on which modal is open
            let actualTarget = targetId;
            const editModal = document.getElementById('editTemplateModal');
            const createModal = document.getElementById('createTemplateModal');

            if (editModal && editModal.classList.contains('show')) {
                actualTarget = 'edit_template_content';
            } else if (createModal && createModal.classList.contains('show')) {
                actualTarget = 'template_content';
            }

            insertVariable(variable, actualTarget);

            // Visual feedback
            varBtn.classList.add('inserted');
            setTimeout(() => varBtn.classList.remove('inserted'), 300);
        });
    }

    // ========================================================================
    // ACTION HANDLERS
    // ========================================================================

    /**
     * Handle go back action
     * @param {Event} e - The event object
     */
    export function handleGoBack(e) {
        window.history.back();
    }

    /**
     * Handle view template action
     * @param {Event} e - The event object
     */
    export function handleViewTemplate(e) {
        const viewId = e.target.dataset.templateId;
        const viewName = e.target.dataset.templateName;
        const viewContent = e.target.dataset.templateContent;
        viewTemplate(viewId, viewName, viewContent);
    }

    /**
     * Handle edit template action
     * @param {Event} e - The event object
     */
    export function handleEditTemplate(e) {
        const editId = e.target.dataset.templateId;
        const editName = e.target.dataset.templateName;
        const editDesc = e.target.dataset.templateDescription;
        const editContent = e.target.dataset.templateContent;
        const editChannel = e.target.dataset.templateChannel;
        const editContext = e.target.dataset.templateContext;
        const editActive = e.target.dataset.templateActive === 'true';
        window.editTemplate(editId, editName, editDesc, editContent, editChannel, editContext, editActive);
    }

    /**
     * Handle toggle template action
     * @param {Event} e - The event object
     */
    export function handleToggleTemplate(e) {
        const toggleId = e.target.dataset.templateId;
        const toggleName = e.target.dataset.templateName;
        const toggleActive = e.target.dataset.templateActive === 'true';
        const toggleUrl = e.target.dataset.toggleUrl;
        const toggleCsrf = e.target.dataset.csrfToken;
        toggleTemplate(toggleId, toggleName, toggleActive, toggleUrl, toggleCsrf);
    }

    /**
     * Handle delete template action
     * @param {Event} e - The event object
     */
    export function handleDeleteTemplate(e) {
        const deleteId = e.target.dataset.templateId;
        const deleteName = e.target.dataset.templateName;
        const deleteUrl = e.target.dataset.deleteUrl;
        const deleteCsrf = e.target.dataset.csrfToken;
        deleteTemplate(deleteId, deleteName, deleteUrl, deleteCsrf);
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initialize all template detail functionality
     */
    function init() {
        // Page guard: only run on template detail page
        if (!document.getElementById('viewTemplateModal') && !document.getElementById('editTemplateModal')) {
            return;
        }

        console.log('[Template Detail] Initializing...');
        // EventDelegation handlers are registered at module scope below
        initVariableButtons();
        console.log('[Template Detail] Initialization complete');
    }

    // ========================================================================
    // EVENT DELEGATION - Registered at module scope
    // ========================================================================
    // Handlers registered when IIFE executes, ensuring EventDelegation is available

    window.EventDelegation.register('go-back-templates', handleGoBack, { preventDefault: true });
    window.EventDelegation.register('view-template', handleViewTemplate, { preventDefault: true });
    window.EventDelegation.register('edit-template', handleEditTemplate, { preventDefault: true });
    window.EventDelegation.register('toggle-template', handleToggleTemplate, { preventDefault: true });
    window.EventDelegation.register('delete-template', handleDeleteTemplate, { preventDefault: true });

    // ========================================================================
    // DOM READY
    // ========================================================================

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        // DOM already loaded
        init();
    }

    // Expose public API
    window.MessageTemplateDetail = {
        version: '1.1.0',
        viewTemplate,
        editTemplate,
        toggleTemplate,
        deleteTemplate,
        insertVariable,
        init
    };

// Backward compatibility
window.viewTemplate = viewTemplate;

// Backward compatibility
window.editTemplate = editTemplate;

// Backward compatibility
window.toggleTemplate = toggleTemplate;

// Backward compatibility
window.deleteTemplate = deleteTemplate;

// Backward compatibility
window.insertVariable = insertVariable;

// Backward compatibility
window.initVariableButtons = initVariableButtons;

// Backward compatibility
window.handleGoBack = handleGoBack;

// Backward compatibility
window.handleViewTemplate = handleViewTemplate;

// Backward compatibility
window.handleEditTemplate = handleEditTemplate;

// Backward compatibility
window.handleToggleTemplate = handleToggleTemplate;

// Backward compatibility
window.handleDeleteTemplate = handleDeleteTemplate;

// Backward compatibility
window.init = init;
