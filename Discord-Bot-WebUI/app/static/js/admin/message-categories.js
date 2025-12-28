/**
 * ============================================================================
 * MESSAGE CATEGORIES - Category Management for Message Templates
 * ============================================================================
 *
 * Handles message template category management in the admin panel.
 * Replaces 43-line inline script from messages.html.
 *
 * Features:
 * - Edit message categories
 * - Delete message categories with confirmation
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

(function() {
    'use strict';

    // ========================================================================
    // EDIT CATEGORY
    // ========================================================================

    /**
     * Edit a message category
     * Opens modal with pre-filled category data
     * @param {number} id - Category ID
     * @param {string} name - Category name
     * @param {string} description - Category description
     */
    function editCategory(id, name, description) {
        const idInput = document.getElementById('edit_category_id');
        const nameInput = document.getElementById('edit_category_name');
        const descInput = document.getElementById('edit_category_description');

        if (idInput) idInput.value = id;
        if (nameInput) nameInput.value = name;
        if (descInput) descInput.value = description || '';

        // Show edit modal
        const modalEl = document.getElementById('editCategoryModal');
        if (modalEl) {
            ModalManager.show('editCategoryModal');
        }
    }

    // ========================================================================
    // DELETE CATEGORY
    // ========================================================================

    /**
     * Delete a message category
     * Shows confirmation dialog before deletion
     * @param {number} id - Category ID
     * @param {string} name - Category name for display
     * @param {string} deleteUrl - URL to submit delete request
     * @param {string} csrfToken - CSRF token for form submission
     */
    function deleteCategory(id, name, deleteUrl, csrfToken) {
        Swal.fire({
            title: 'Delete Category?',
            text: `Are you sure you want to delete "${name}"? This action cannot be undone.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#dc3545',
            cancelButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('info') : '#3085d6',
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

                const categoryIdInput = document.createElement('input');
                categoryIdInput.type = 'hidden';
                categoryIdInput.name = 'category_id';
                categoryIdInput.value = id;

                form.appendChild(csrfInput);
                form.appendChild(categoryIdInput);
                document.body.appendChild(form);
                form.submit();
            }
        });
    }

    // ========================================================================
    // ACTION HANDLERS
    // ========================================================================

    /**
     * Handle edit category action
     * @param {Event} e - The event object
     */
    function handleEditCategory(e) {
        const editId = e.target.dataset.categoryId;
        const editName = e.target.dataset.categoryName;
        const editDesc = e.target.dataset.categoryDescription;
        editCategory(editId, editName, editDesc);
    }

    /**
     * Handle delete category action
     * @param {Event} e - The event object
     */
    function handleDeleteCategory(e) {
        const deleteId = e.target.dataset.categoryId;
        const deleteName = e.target.dataset.categoryName;
        const deleteUrl = e.target.dataset.deleteUrl;
        const csrfToken = e.target.dataset.csrfToken;
        deleteCategory(deleteId, deleteName, deleteUrl, csrfToken);
    }

    // ========================================================================
    // EVENT DELEGATION
    // ========================================================================

    /**
     * Initialize event delegation for category actions
     */
    function initEventDelegation() {
        if (!window.EventDelegation || typeof window.EventDelegation.register !== 'function') {
            console.error('[Message Categories] EventDelegation not available');
            return;
        }

        window.EventDelegation.register('edit-category', handleEditCategory, { preventDefault: true });
        window.EventDelegation.register('delete-category', handleDeleteCategory, { preventDefault: true });
    }

    // ========================================================================
    // INITIALIZATION
    // ========================================================================

    /**
     * Initialize all message category functionality
     */
    function init() {
        // Page guard: only run on message categories page
        if (!document.getElementById('editCategoryModal')) {
            return;
        }

        console.log('[Message Categories] Initializing...');
        initEventDelegation();
        console.log('[Message Categories] Initialization complete');
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
    window.MessageCategories = {
        version: '1.0.0',
        editCategory,
        deleteCategory,
        init
    };

})();
