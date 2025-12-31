/**
 * Manage Roles Page
 * Handles role permission management with Select2 integration
 */
import { InitSystem } from '../js/init-system.js';

export const ManageRoles = {
    init() {
        this.initializeSelect2();
        this.setupRoleChangeHandler();
    },

    initializeSelect2() {
        // Check if jQuery and Select2 are available
        if (typeof window.$ === 'undefined' || typeof window.$.fn.select2 === 'undefined') {
            console.warn('Select2 or jQuery not available. Using basic select.');
            return;
        }

        // Initialize Select2 for permissions select
        window.$('#permissions').select2({
            placeholder: 'Select permissions...',
            width: '100%',
            theme: 'bootstrap-5',
            closeOnSelect: false
        });
    },

    setupRoleChangeHandler() {
        const roleSelect = document.getElementById('role_id');
        if (!roleSelect) return;

        roleSelect.addEventListener('change', () => {
            const roleId = roleSelect.value;
            if (roleId) {
                this.loadRolePermissions(roleId);
            }
        });

        // Trigger change if a role is selected on page load
        if (roleSelect.value) {
            this.loadRolePermissions(roleSelect.value);
        }
    },

    loadRolePermissions(roleId) {
        // Get CSRF token
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') ||
                         document.querySelector('[name="csrf_token"]')?.value;

        fetch('/admin/get_role_permissions', {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            credentials: 'same-origin'
        })
        .then(response => {
            const url = new URL(response.url);
            url.searchParams.append('role_id', roleId);
            return fetch(url.toString());
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to load role permissions');
            }
            return response.json();
        })
        .then(data => {
            const permissionsSelect = document.getElementById('permissions');
            if (!permissionsSelect) return;

            // Update selected permissions
            if (typeof window.$ !== 'undefined' && typeof window.$.fn.select2 !== 'undefined') {
                // Use Select2 method
                window.$('#permissions').val(data.permissions).trigger('change');
            } else {
                // Vanilla JS fallback
                Array.from(permissionsSelect.options).forEach(option => {
                    option.selected = data.permissions.includes(option.value);
                });
            }
        })
        .catch(error => {
            console.error('Error loading role permissions:', error);
            this.showAlert('Failed to load permissions for the selected role.', 'danger');
        });
    },

    showAlert(message, category = 'info') {
        const alertsContainer = document.querySelector('[data-component="alerts"]');
        if (!alertsContainer) return;

        const alert = document.createElement('div');
        alert.className = `c-alert c-alert--${category}`;
        alert.setAttribute('role', 'alert');
        alert.setAttribute('data-alert', '');
        alert.innerHTML = `
            <i class="ti ti-${category === 'success' ? 'check-circle' : 'alert-circle'} c-alert__icon"></i>
            <span class="c-alert__text">${message}</span>
        `;

        alertsContainer.appendChild(alert);

        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            alert.remove();
        }, 5000);
    }
};

// Add _initialized guard to init method
const originalInit = ManageRoles.init;
let _initialized = false;
ManageRoles.init = function() {
    if (_initialized) return;
    _initialized = true;
    originalInit.call(this);
};

// Register with InitSystem (primary)
if (InitSystem && InitSystem.register) {
    InitSystem.register('manage-roles', () => ManageRoles.init(), {
        priority: 35,
        reinitializable: true,
        description: 'Manage roles page functionality'
    });
}

// Fallback
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => ManageRoles.init());
} else {
    ManageRoles.init();
}

// Backward compatibility
window.ManageRoles = ManageRoles;
