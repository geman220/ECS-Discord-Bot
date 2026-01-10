import { EventDelegation } from '../core.js';

/**
 * Roles Management Action Handlers
 * =================================
 * Handles role management actions (view, manage permissions, view users)
 * using centralized event delegation.
 *
 * Migrated from inline scripts in roles.html
 *
 * @version 1.0.0
 */

// ============================================================================
// CONFIGURATION - URLs injected from template via data attributes or globals
// ============================================================================

/**
 * Get URL for fetching role details
 * Falls back to a pattern-based URL if not configured
 */
function getRoleDetailsUrl(roleId) {
    if (typeof window.ROLES_CONFIG !== 'undefined' && window.ROLES_CONFIG.roleDetailsUrl) {
        return `${window.ROLES_CONFIG.roleDetailsUrl}?role_id=${roleId}`;
    }
    return `/admin-panel/api/role-details?role_id=${roleId}`;
}

/**
 * Get URL for feature toggles page
 */
function getFeatureTogglesUrl() {
    if (typeof window.ROLES_CONFIG !== 'undefined' && window.ROLES_CONFIG.featureTogglesUrl) {
        return window.ROLES_CONFIG.featureTogglesUrl;
    }
    return '/admin-panel/settings/feature-toggles';
}

/**
 * Get URL for user approvals page
 */
function getUserApprovalsUrl(roleId) {
    if (typeof window.ROLES_CONFIG !== 'undefined' && window.ROLES_CONFIG.userApprovalsUrl) {
        return `${window.ROLES_CONFIG.userApprovalsUrl}?role=${roleId}`;
    }
    return `/admin-panel/user-management/approvals?role=${roleId}`;
}

// ============================================================================
// VIEW ROLE DETAILS
// ============================================================================

/**
 * Handle View Role button click
 * Opens the role details modal and loads role information via AJAX
 */
window.EventDelegation.register('view-role', function(element, e) {
    e.preventDefault();

    const roleId = element.dataset.roleId;
    const roleName = element.dataset.roleName;

    if (!roleId) {
        console.error('[view-role] Missing role ID');
        return;
    }

    // Update modal title
    const titleElement = document.getElementById('role_details_title');
    if (titleElement) {
        titleElement.textContent = `Details for ${roleName || 'Role'}`;
    }

    // Show loading state in modal content
    const contentElement = document.getElementById('role_details_content');
    if (contentElement) {
        contentElement.innerHTML = '<div class="flex justify-center"><div class="w-8 h-8 border-4 border-ecs-green border-t-transparent rounded-full animate-spin" role="status" data-spinner></div></div>';
    }

    // Show the modal
    if (typeof window.ModalManager !== 'undefined') {
        window.ModalManager.show('roleDetailsModal');
    } else {
        // Fallback to Flowbite modal if window.ModalManager not available
        const modalEl = document.getElementById('roleDetailsModal');
        if (modalEl) {
            const modal = modalEl._flowbiteModal || (modalEl._flowbiteModal = new window.Modal(modalEl, { backdrop: 'dynamic', closable: true }));
            modal.show();
        }
    }

    // Load role details via AJAX
    fetch(getRoleDetailsUrl(roleId))
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (contentElement) {
                    contentElement.innerHTML = data.html;
                }
            } else {
                if (contentElement) {
                    contentElement.innerHTML = '<div class="alert alert-danger" data-alert>Error loading role details</div>';
                }
            }
        })
        .catch(error => {
            console.error('[view-role] Error loading role details:', error);
            if (contentElement) {
                contentElement.innerHTML = '<div class="alert alert-danger" data-alert>Error loading role details</div>';
            }
        });
}, { preventDefault: true });

// ============================================================================
// MANAGE ROLE PERMISSIONS
// ============================================================================

/**
 * Handle Manage Permissions button click
 * Redirects to the feature toggles page with roles section selected
 */
window.EventDelegation.register('manage-permissions', function(element, e) {
    e.preventDefault();

    const roleId = element.dataset.roleId;
    const roleName = element.dataset.roleName;

    if (!roleId) {
        console.error('[manage-permissions] Missing role ID');
        return;
    }

    // Redirect to the role settings with the role pre-selected
    window.location.href = `${getFeatureTogglesUrl()}#roles`;
}, { preventDefault: true });

// ============================================================================
// VIEW ROLE USERS
// ============================================================================

/**
 * Handle View Users button click
 * Redirects to user approvals page filtered by the selected role
 */
window.EventDelegation.register('view-users', function(element, e) {
    e.preventDefault();

    const roleId = element.dataset.roleId;
    const roleName = element.dataset.roleName;

    if (!roleId) {
        console.error('[view-users] Missing role ID');
        return;
    }

    // Redirect to user approvals filtered by this role
    window.location.href = getUserApprovalsUrl(roleId);
}, { preventDefault: true });

// Handlers loaded
