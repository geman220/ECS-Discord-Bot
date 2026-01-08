/**
 * Manage Roles Page
 * Handles role permission management with native HTML5 selects
 */
import { InitSystem } from '../js/init-system.js';

export const ManageRoles = {
    init() {
        this.setupRoleChangeHandler();
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

            // Update selected permissions using native select
            Array.from(permissionsSelect.options).forEach(option => {
                option.selected = data.permissions.includes(option.value);
            });
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

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('manage-roles', () => ManageRoles.init(), {
        priority: 35,
        reinitializable: true,
        description: 'Manage roles page functionality'
    });
}

// window.InitSystem handles initialization

// Backward compatibility
window.ManageRoles = ManageRoles;
