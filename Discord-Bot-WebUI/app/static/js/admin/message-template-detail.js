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
 *
 * ============================================================================
 */

(function() {
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
    function viewTemplate(id, name, content) {
        const titleEl = document.getElementById('view_template_title');
        const contentEl = document.getElementById('view_template_content');

        if (titleEl) titleEl.textContent = name;
        if (contentEl) contentEl.textContent = content;

        // Show modal
        const modalEl = document.getElementById('viewTemplateModal');
        if (modalEl) {
            ModalManager.show('viewTemplateModal');
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
    function editTemplate(id, name, description, content, channelType, usageContext, isActive) {
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
            ModalManager.show('editTemplateModal');
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
    function toggleTemplate(id, name, currentStatus, toggleUrl, csrfToken) {
        const action = currentStatus ? 'deactivate' : 'activate';
        const newStatus = !currentStatus;

        Swal.fire({
            title: `${action.charAt(0).toUpperCase() + action.slice(1)} Template?`,
            text: `Are you sure you want to ${action} "${name}"?`,
            icon: 'question',
            showCancelButton: true,
            confirmButtonColor: newStatus ?
                (getComputedStyle(document.documentElement).getPropertyValue('--ecs-success').trim() || '#198754') :
                (getComputedStyle(document.documentElement).getPropertyValue('--ecs-warning').trim() || '#ffc107'),
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ?
                ECSTheme.getColor('secondary') :
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
    function deleteTemplate(id, name, deleteUrl, csrfToken) {
        Swal.fire({
            title: 'Delete Template?',
            text: `Are you sure you want to delete "${name}"? This action cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ?
                ECSTheme.getColor('danger') :
                (getComputedStyle(document.documentElement).getPropertyValue('--ecs-danger').trim() || '#dc3545'),
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ?
                ECSTheme.getColor('info') :
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
    function insertVariable(variable, targetId) {
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
    function initVariableButtons() {
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
    // EVENT DELEGATION
    // ========================================================================

    /**
     * Initialize event delegation for template actions
     */
    function initEventDelegation() {
        document.addEventListener('click', function(e) {
            const actionElement = e.target.closest('[data-action]');
            if (!actionElement) return;

            const action = actionElement.dataset.action;

            switch(action) {
                case 'go-back':
                    e.preventDefault();
                    window.history.back();
                    break;

                case 'view-template':
                    e.preventDefault();
                    const viewId = actionElement.dataset.templateId;
                    const viewName = actionElement.dataset.templateName;
                    const viewContent = actionElement.dataset.templateContent;
                    viewTemplate(viewId, viewName, viewContent);
                    break;

                case 'edit-template':
                    e.preventDefault();
                    const editId = actionElement.dataset.templateId;
                    const editName = actionElement.dataset.templateName;
                    const editDesc = actionElement.dataset.templateDescription;
                    const editContent = actionElement.dataset.templateContent;
                    const editChannel = actionElement.dataset.templateChannel;
                    const editContext = actionElement.dataset.templateContext;
                    const editActive = actionElement.dataset.templateActive === 'true';
                    editTemplate(editId, editName, editDesc, editContent, editChannel, editContext, editActive);
                    break;

                case 'toggle-template':
                    e.preventDefault();
                    const toggleId = actionElement.dataset.templateId;
                    const toggleName = actionElement.dataset.templateName;
                    const toggleActive = actionElement.dataset.templateActive === 'true';
                    const toggleUrl = actionElement.dataset.toggleUrl;
                    const toggleCsrf = actionElement.dataset.csrfToken;
                    toggleTemplate(toggleId, toggleName, toggleActive, toggleUrl, toggleCsrf);
                    break;

                case 'delete-template':
                    e.preventDefault();
                    const deleteId = actionElement.dataset.templateId;
                    const deleteName = actionElement.dataset.templateName;
                    const deleteUrl = actionElement.dataset.deleteUrl;
                    const deleteCsrf = actionElement.dataset.csrfToken;
                    deleteTemplate(deleteId, deleteName, deleteUrl, deleteCsrf);
                    break;
            }
        });
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initialize all template detail functionality
     */
    function init() {
        console.log('[Template Detail] Initializing...');
        initEventDelegation();
        initVariableButtons();
        console.log('[Template Detail] Initialization complete');
    }

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

})();
