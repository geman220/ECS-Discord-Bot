/**
 * ============================================================================
 * ADMIN DASHBOARD MODULE
 * ============================================================================
 *
 * Main controller for the admin dashboard page.
 * Handles:
 *   - Docker container status management
 *   - Task management (Celery tasks)
 *   - Role permissions management
 *   - Event delegation for dynamic elements
 *
 * Uses InitSystem for registration and data-* selectors for JS hooks.
 *
 * ============================================================================
 */
// ES Module
'use strict';

import { InitSystem } from '../init-system.js';
/* ========================================================================
       CONFIGURATION
       ======================================================================== */

    const CONFIG = {
        selectors: {
            // Containers
            dockerStatusContainer: '#dockerStatusContainer',
            taskManagementContainer: '#taskManagementContainer',
            toastContainer: '#toastContainer',

            // Permissions
            roleSelect: '#role_id',
            permissionsSelect: '#permissions',
            currentPermissionsList: '#current-permissions-list',

            // Modal
            dockerLogsContent: '#dockerLogsContent',
            dockerLogsModalLabel: '#dockerLogsModalLabel',

            // Actions (data-action attribute values)
            actions: {
                refreshContainers: 'refresh-containers',
                openTaskManagement: 'open-task-management',
                refreshTaskList: 'refresh-task-list',
                cleanupOldTasks: 'cleanup-old-tasks',
                loadTaskManagement: 'load-task-management',
                showLogs: 'show-logs',
                containerAction: 'container-action',
                revokeTask: 'revoke-task',
                viewTaskDetails: 'view-task-details',
                removeTask: 'remove-task',
                closeModal: 'close-modal'
            }
        },
        endpoints: {
            dockerStatus: '/admin/docker-status',
            dockerLogs: '/admin/docker-logs/',
            dockerAction: '/admin/docker-',
            taskManagement: '/admin/task-management',
            taskDetails: '/admin/task-details/',
            revokeTask: '/admin/revoke-task/',
            removeTask: '/admin/remove-task/',
            cleanupTasks: '/admin/cleanup-tasks',
            rolePermissions: '/admin/role-permissions/'
        }
    };

    /* ========================================================================
       ADMIN DASHBOARD CONTROLLER
       ======================================================================== */

    const AdminDashboard = {
        /**
         * Initialize the admin dashboard
         */
        init: function(context = document) {
            console.log('[AdminDashboard] Initializing...');

            this.initEventDelegation(context);
            this.initPermissionsTab(context);
            this.initDockerStatus(context);

            console.log('[AdminDashboard] Initialized');
        },

        /**
         * Event delegation for dynamic elements using data-action attributes
         */
        initEventDelegation: function(context) {
            context.addEventListener('click', (e) => {
                const actionElement = e.target.closest('[data-action]');
                if (!actionElement) return;

                const action = actionElement.dataset.action;

                switch(action) {
                    case CONFIG.selectors.actions.refreshContainers:
                        e.preventDefault();
                        this.handleRefreshContainers(actionElement);
                        break;

                    case CONFIG.selectors.actions.openTaskManagement:
                        e.preventDefault();
                        this.openTaskManagement();
                        break;

                    case CONFIG.selectors.actions.refreshTaskList:
                        this.refreshTaskList();
                        break;

                    case CONFIG.selectors.actions.cleanupOldTasks:
                        this.cleanupOldTasks();
                        break;

                    case CONFIG.selectors.actions.loadTaskManagement:
                        this.loadTaskManagement();
                        break;

                    case CONFIG.selectors.actions.showLogs:
                        this.showLogs(actionElement.dataset.containerName);
                        break;

                    case CONFIG.selectors.actions.containerAction:
                        this.containerAction(
                            actionElement.dataset.containerName,
                            actionElement.dataset.containerActionType,
                            actionElement
                        );
                        break;

                    case CONFIG.selectors.actions.revokeTask:
                        this.revokeTask(actionElement.dataset.taskId);
                        break;

                    case CONFIG.selectors.actions.viewTaskDetails:
                        this.viewTaskDetails(actionElement.dataset.taskId);
                        break;

                    case CONFIG.selectors.actions.removeTask:
                        this.removeTask(actionElement.dataset.taskId);
                        break;

                    case CONFIG.selectors.actions.closeModal:
                        if (window.ModernComponents?.Modal && actionElement.dataset.modalId) {
                            window.ModernComponents.Modal.close(actionElement.dataset.modalId);
                        }
                        break;
                }
            });
        },

        /**
         * Handle refresh containers button click
         */
        handleRefreshContainers: function(target) {
            target.classList.add('is-loading');
            target.disabled = true;

            this.fetchDockerStatus().finally(() => {
                target.classList.remove('is-loading');
                target.disabled = false;
            });
        },

        /* ====================================================================
           PERMISSIONS TAB
           ==================================================================== */

        initPermissionsTab: function(context) {
            const roleSelect = context.querySelector(CONFIG.selectors.roleSelect);
            const permissionsSelect = context.querySelector(CONFIG.selectors.permissionsSelect);
            const currentPermissionsList = context.querySelector(CONFIG.selectors.currentPermissionsList);

            // Initialize Select2 for permissions dropdown
            if (permissionsSelect && typeof window.$ !== 'undefined' && window.$.fn.select2) {
                $(permissionsSelect).select2({
                    theme: 'bootstrap-5',
                    placeholder: 'Select permissions...',
                    allowClear: true,
                    width: '100%'
                });
            }

            if (roleSelect) {
                roleSelect.addEventListener('change', () => {
                    const roleId = roleSelect.value;
                    if (roleId) {
                        this.fetchRolePermissions(roleId, permissionsSelect, currentPermissionsList);
                    } else {
                        if (currentPermissionsList) {
                            currentPermissionsList.innerHTML = '<li class="c-permissions-list__item c-permissions-list__item--empty">Select a role to view permissions.</li>';
                        }
                        if (permissionsSelect) {
                            if ($(permissionsSelect).hasClass('select2-hidden-accessible')) {
                                $(permissionsSelect).val([]).trigger('change');
                            } else {
                                Array.from(permissionsSelect.options).forEach(option => option.selected = false);
                            }
                        }
                    }
                });
            }
        },

        fetchRolePermissions: function(roleId, permissionsSelect, currentPermissionsList) {
            fetch(`${CONFIG.endpoints.rolePermissions}${roleId}`)
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        this.updateCurrentPermissionsList(data.permissions, currentPermissionsList);

                        if (permissionsSelect) {
                            const currentPermissionIds = data.permissions.map(p => p.id.toString());

                            if ($(permissionsSelect).hasClass('select2-hidden-accessible')) {
                                $(permissionsSelect).val(currentPermissionIds).trigger('change');
                            } else {
                                Array.from(permissionsSelect.options).forEach(option => {
                                    option.selected = currentPermissionIds.includes(option.value);
                                });
                            }
                        }
                    } else {
                        currentPermissionsList.innerHTML = '<li class="c-permissions-list__item c-permissions-list__item--error">Error loading permissions</li>';
                    }
                })
                .catch(error => {
                    console.error('Error fetching role permissions:', error);
                    currentPermissionsList.innerHTML = '<li class="c-permissions-list__item c-permissions-list__item--error">Error loading permissions</li>';
                });
        },

        updateCurrentPermissionsList: function(permissions, listElement) {
            if (!listElement) return;

            if (permissions.length === 0) {
                listElement.innerHTML = '<li class="c-permissions-list__item c-permissions-list__item--empty">No permissions assigned.</li>';
            } else {
                const permissionsHTML = permissions.map(permission =>
                    `<li class="c-permissions-list__item">${permission.name}</li>`
                ).join('');
                listElement.innerHTML = permissionsHTML;
            }
        },

        /* ====================================================================
           DOCKER STATUS
           ==================================================================== */

        initDockerStatus: function(context) {
            const container = context.querySelector(CONFIG.selectors.dockerStatusContainer);
            if (!container) return;

            this.fetchDockerStatus();
        },

        fetchDockerStatus: async function() {
            const container = document.querySelector(CONFIG.selectors.dockerStatusContainer);
            if (!container) return;

            try {
                const response = await fetch(CONFIG.endpoints.dockerStatus);
                const data = await response.json();

                if (data.success && data.containers) {
                    this.renderContainers(data.containers);
                } else {
                    container.innerHTML = `
                        <div class="col-12">
                            <div class="c-empty-state c-empty-state--warning">
                                <i class="ti ti-alert-triangle c-empty-state__icon"></i>
                                <p class="c-empty-state__text">${data.error || 'Unable to load container status'}</p>
                            </div>
                        </div>
                    `;
                }
            } catch (error) {
                console.error('Error fetching Docker status:', error);
                container.innerHTML = `
                    <div class="col-12">
                        <div class="c-empty-state c-empty-state--error">
                            <i class="ti ti-alert-circle c-empty-state__icon"></i>
                            <p class="c-empty-state__text">Failed to load container status</p>
                        </div>
                    </div>
                `;
            }
        },

        renderContainers: function(containers) {
            const container = document.querySelector(CONFIG.selectors.dockerStatusContainer);
            if (!container) return;

            if (containers.length === 0) {
                container.innerHTML = `
                    <div class="col-12">
                        <div class="c-empty-state">
                            <i class="ti ti-info-circle c-empty-state__icon"></i>
                            <p class="c-empty-state__text">No containers found</p>
                        </div>
                    </div>
                `;
                return;
            }

            const containersHTML = containers.map(cont => {
                const statusClass = cont.status === 'running' ? 'success' : 'danger';
                const statusIcon = cont.status === 'running' ? 'ti-check' : 'ti-x';

                return `
                    <div class="col-xl-4 col-lg-6 mb-3">
                        <div class="c-container-card" data-component="container-card" data-container-name="${cont.name}">
                            <div class="c-container-card__header">
                                <div class="c-container-card__info">
                                    <h6 class="c-container-card__name">${cont.name}</h6>
                                    <small class="c-container-card__image">${cont.image}</small>
                                </div>
                                <span class="c-badge c-badge--${statusClass}">
                                    <i class="ti ${statusIcon}"></i>
                                    <span>${cont.status}</span>
                                </span>
                            </div>

                            <div class="c-container-card__body">
                                <div class="c-container-card__stat">
                                    <small class="c-container-card__stat-label">Uptime:</small>
                                    <small class="c-container-card__stat-value">${cont.uptime || 'N/A'}</small>
                                </div>
                                <div class="c-container-card__stat">
                                    <small class="c-container-card__stat-label">CPU:</small>
                                    <small class="c-container-card__stat-value">${cont.cpu_usage || 'N/A'}</small>
                                </div>
                                <div class="c-container-card__stat">
                                    <small class="c-container-card__stat-label">Memory:</small>
                                    <small class="c-container-card__stat-value">${cont.memory_usage || 'N/A'}</small>
                                </div>
                            </div>

                            <div class="c-container-card__actions">
                                ${cont.status === 'running' ?
                                    `<button class="btn btn-outline-warning btn-sm" data-action="container-action" data-container-name="${cont.name}" data-container-action-type="restart">
                                        <i class="ti ti-refresh"></i> <span>Restart</span>
                                    </button>
                                    <button class="btn btn-outline-danger btn-sm" data-action="container-action" data-container-name="${cont.name}" data-container-action-type="stop">
                                        <i class="ti ti-stop"></i> <span>Stop</span>
                                    </button>` :
                                    `<button class="btn btn-outline-success btn-sm" data-action="container-action" data-container-name="${cont.name}" data-container-action-type="start">
                                        <i class="ti ti-play"></i> <span>Start</span>
                                    </button>`
                                }
                                <button class="btn btn-outline-primary btn-sm" data-action="show-logs" data-container-name="${cont.name}" title="View Logs">
                                    <i class="ti ti-file-text"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            container.innerHTML = containersHTML;
        },

        showLogs: async function(containerName) {
            const content = document.querySelector(CONFIG.selectors.dockerLogsContent);
            const title = document.querySelector(CONFIG.selectors.dockerLogsModalLabel);

            if (title) title.textContent = `${containerName} - Logs`;
            if (content) content.textContent = 'Loading logs...';

            if (window.ModernComponents?.Modal) {
                window.ModernComponents.Modal.open('dockerLogsModal');
            }

            try {
                const response = await fetch(`${CONFIG.endpoints.dockerLogs}${containerName}`);
                const data = await response.json();

                if (data.success) {
                    if (content) content.textContent = data.logs || 'No logs available';
                } else {
                    if (content) content.textContent = `Error: ${data.error || 'Failed to load logs'}`;
                }
            } catch (error) {
                console.error('Error fetching logs:', error);
                if (content) content.textContent = 'Error loading logs';
            }
        },

        containerAction: async function(containerName, action, btn) {
            if (!btn) return;

            btn.classList.add('is-loading');
            btn.disabled = true;

            try {
                const response = await fetch(`${CONFIG.endpoints.dockerAction}${action}/${containerName}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' }
                });

                if (response.ok) {
                    this.showComponentToast('success', 'Success', `Container ${action}ed successfully`);
                    setTimeout(() => this.fetchDockerStatus(), 1000);
                } else {
                    const errorData = await response.json();
                    this.showComponentToast('error', 'Error', errorData.error || `Failed to ${action} container`);
                    btn.classList.remove('is-loading');
                    btn.disabled = false;
                }
            } catch (error) {
                console.error(`Error during ${action}:`, error);
                this.showComponentToast('error', 'Error', `Failed to ${action} container`);
                btn.classList.remove('is-loading');
                btn.disabled = false;
            }
        },

        /* ====================================================================
           TASK MANAGEMENT
           ==================================================================== */

        openTaskManagement: function() {
            this.loadTaskManagement();
            const container = document.querySelector(CONFIG.selectors.taskManagementContainer);
            if (container) {
                container.scrollIntoView({ behavior: 'smooth' });
            }
        },

        loadTaskManagement: function() {
            const container = document.querySelector(CONFIG.selectors.taskManagementContainer);
            if (!container) return;

            container.innerHTML = `
                <div class="text-center py-4">
                    <div class="c-loading-spinner" role="status"></div>
                    <p class="c-loading-text">Loading task management...</p>
                </div>
            `;

            this.fetchTaskList();
        },

        fetchTaskList: async function() {
            const container = document.querySelector(CONFIG.selectors.taskManagementContainer);
            if (!container) return;

            try {
                const response = await fetch(CONFIG.endpoints.taskManagement);
                const data = await response.json();

                if (data.success) {
                    this.renderTaskManagement(data);
                } else {
                    container.innerHTML = `
                        <div class="alert alert-warning" role="alert">
                            <i class="ti ti-alert-triangle me-2"></i>
                            ${data.error || 'Unable to load task management'}
                        </div>
                    `;
                }
            } catch (error) {
                console.error('Error fetching task management:', error);
                container.innerHTML = `
                    <div class="alert alert-danger" role="alert">
                        <i class="ti ti-alert-circle me-2"></i>
                        Failed to load task management
                    </div>
                `;
            }
        },

        renderTaskManagement: function(data) {
            const container = document.querySelector(CONFIG.selectors.taskManagementContainer);
            if (!container) return;

            const stats = data.statistics || {};
            const activeTasks = data.active_tasks || [];

            const html = `
                <div class="row mb-4">
                    <div class="col-md-3">
                        <div class="c-stat-card c-stat-card--primary">
                            <div class="c-stat-card__value">${stats.total_active || 0}</div>
                            <div class="c-stat-card__label">Active Tasks</div>
                            <div class="c-stat-card__icon"><i class="ti ti-activity"></i></div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="c-stat-card c-stat-card--success">
                            <div class="c-stat-card__value">${stats.by_status?.SUCCESS || 0}</div>
                            <div class="c-stat-card__label">Completed</div>
                            <div class="c-stat-card__icon"><i class="ti ti-check"></i></div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="c-stat-card c-stat-card--danger">
                            <div class="c-stat-card__value">${stats.by_status?.FAILURE || 0}</div>
                            <div class="c-stat-card__label">Failed</div>
                            <div class="c-stat-card__icon"><i class="ti ti-x"></i></div>
                        </div>
                    </div>
                    <div class="col-md-3">
                        <div class="c-stat-card c-stat-card--warning">
                            <div class="c-stat-card__value">${stats.by_status?.PENDING || 0}</div>
                            <div class="c-stat-card__label">Pending</div>
                            <div class="c-stat-card__icon"><i class="ti ti-clock"></i></div>
                        </div>
                    </div>
                </div>

                <div class="c-table-wrapper">
                    <table class="c-table c-table--hover c-table--striped">
                        <thead class="c-table__head">
                            <tr>
                                <th class="c-table__header">Task ID</th>
                                <th class="c-table__header">Type</th>
                                <th class="c-table__header">User</th>
                                <th class="c-table__header">Status</th>
                                <th class="c-table__header">Progress</th>
                                <th class="c-table__header">Created</th>
                                <th class="c-table__header">Actions</th>
                            </tr>
                        </thead>
                        <tbody class="c-table__body">
                            ${activeTasks.length > 0 ?
                                activeTasks.map(task => this.renderTaskRow(task)).join('') :
                                '<tr><td colspan="7" class="text-center c-text-muted py-4">No active tasks</td></tr>'
                            }
                        </tbody>
                    </table>
                </div>
            `;

            container.innerHTML = html;
        },

        renderTaskRow: function(task) {
            const statusColor = this.getStatusColor(task.celery_state || task.status);

            return `
                <tr class="c-table__row ${task.celery_state === 'REVOKED' ? 'is-muted' : ''}">
                    <td class="c-table__cell" data-label="Task ID">
                        <code class="c-code">${task.task_id.substring(0, 8)}...</code>
                        ${task.celery_state === 'REVOKED' ? '<small class="c-text-muted">CANCELLED</small>' : ''}
                    </td>
                    <td class="c-table__cell" data-label="Type">
                        <span class="c-badge c-badge--secondary">${task.task_type || 'unknown'}</span>
                    </td>
                    <td class="c-table__cell" data-label="User">${task.user_id || 'N/A'}</td>
                    <td class="c-table__cell" data-label="Status">
                        <span class="c-badge c-badge--${statusColor}">
                            ${task.celery_state || task.status || 'UNKNOWN'}
                        </span>
                    </td>
                    <td class="c-table__cell" data-label="Progress">
                        <div class="c-progress">
                            <div class="c-progress__bar c-progress__bar--${statusColor}"
                                 role="progressbar"
                                 aria-valuenow="${task.progress || 0}"
                                 aria-valuemin="0" aria-valuemax="100"
                                 style="width: ${task.progress || 0}%">
                                ${task.progress || 0}%
                            </div>
                        </div>
                        ${task.stage ? `<small class="c-text-muted">${task.stage}</small>` : ''}
                    </td>
                    <td class="c-table__cell" data-label="Created">
                        <small>${task.created_at ? new Date(task.created_at).toLocaleString() : 'N/A'}</small>
                    </td>
                    <td class="c-table__cell" data-label="Actions">
                        <div class="c-button-group c-button-group--sm">
                            ${['PENDING', 'PROGRESS', 'STARTED'].includes(task.celery_state) ?
                                `<button class="btn btn-outline-danger btn-sm" data-action="revoke-task" data-task-id="${task.task_id}" title="DESTROY Task (Nuclear Option)">
                                    <i class="ti ti-bomb"></i>
                                </button>` : ''
                            }
                            ${['REVOKED', 'FAILURE', 'SUCCESS'].includes(task.celery_state) ?
                                `<button class="btn btn-outline-secondary btn-sm" data-action="remove-task" data-task-id="${task.task_id}" title="Remove from List">
                                    <i class="ti ti-trash"></i> <span>Clear</span>
                                </button>` : ''
                            }
                            <button class="btn btn-outline-primary btn-sm" data-action="view-task-details" data-task-id="${task.task_id}" title="View Details">
                                <i class="ti ti-eye"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        },

        getStatusColor: function(status) {
            const colors = {
                'SUCCESS': 'success',
                'FAILURE': 'danger',
                'PENDING': 'warning',
                'STARTED': 'primary',
                'PROGRESS': 'primary',
                'REVOKED': 'dark'
            };
            return colors[status] || 'light';
        },

        revokeTask: async function(taskId) {
            const result = await window.Swal.fire({
                title: 'DESTROY Task?',
                html: `
                    <div class="text-start">
                        <p class="text-warning"><strong>⚠️ WARNING: Nuclear Option</strong></p>
                        <p>This will completely <strong>DESTROY</strong> the task:</p>
                        <ul class="text-start">
                            <li>Terminate the running process</li>
                            <li>Remove all Redis data</li>
                            <li>Purge from all tracking systems</li>
                            <li>Cannot be undone</li>
                        </ul>
                        <p class="text-danger"><strong>Are you absolutely sure?</strong></p>
                    </div>
                `,
                icon: 'warning',
                showCancelButton: true,
                confirmButtonColor: this.getThemeColor('danger', '#dc3545'),
                cancelButtonColor: this.getThemeColor('secondary', '#6c757d'),
                confirmButtonText: '💥 DESTROY IT',
                cancelButtonText: 'No, keep it',
                width: '500px'
            });

            if (!result.isConfirmed) return;

            try {
                const response = await fetch(`${CONFIG.endpoints.revokeTask}${taskId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    }
                });

                const data = await response.json();

                if (data.success) {
                    window.Swal.fire({
                        title: 'DESTROYED! 💥',
                        text: 'The task has been completely obliterated.',
                        icon: 'success',
                        timer: 3000,
                        showConfirmButton: false
                    });
                    setTimeout(() => this.refreshTaskList(), 1000);
                } else {
                    window.Swal.fire({ title: 'Error!', text: data.error || 'Failed to destroy task', icon: 'error' });
                }
            } catch (error) {
                console.error('Error destroying task:', error);
                window.Swal.fire({ title: 'Error!', text: 'Failed to destroy task', icon: 'error' });
            }
        },

        viewTaskDetails: async function(taskId) {
            try {
                const response = await fetch(`${CONFIG.endpoints.taskDetails}${taskId}`);
                const data = await response.json();

                if (data.success) {
                    const task = data.task;
                    const detailsHtml = `
                        <div class="text-start">
                            <p><strong>Task ID:</strong> <code>${task.task_id}</code></p>
                            <p><strong>Type:</strong> <span class="c-badge c-badge--secondary">${task.task_type || 'N/A'}</span></p>
                            <p><strong>Status:</strong> <span class="c-badge c-badge--${this.getStatusColor(task.celery_state || task.status)}">${task.celery_state || task.status || 'N/A'}</span></p>
                            <p><strong>Progress:</strong> ${task.progress || 0}%</p>
                            <p><strong>Stage:</strong> ${task.stage || 'N/A'}</p>
                            <p><strong>Created:</strong> ${task.created_at ? new Date(task.created_at).toLocaleString() : 'N/A'}</p>
                            ${task.message ? `<p><strong>Message:</strong> ${task.message}</p>` : ''}
                        </div>
                    `;

                    window.Swal.fire({
                        title: 'Task Details',
                        html: detailsHtml,
                        icon: 'info',
                        width: '600px',
                        confirmButtonText: 'Close'
                    });
                } else {
                    window.Swal.fire({ title: 'Error!', text: data.error || 'Failed to load task details', icon: 'error' });
                }
            } catch (error) {
                console.error('Error fetching task details:', error);
                window.Swal.fire({ title: 'Error!', text: 'Failed to load task details', icon: 'error' });
            }
        },

        removeTask: async function(taskId) {
            const result = await window.Swal.fire({
                title: 'Remove Task?',
                text: 'This will remove the task from the list. Are you sure?',
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: this.getThemeColor('secondary', '#6c757d'),
                cancelButtonColor: this.getThemeColor('danger', '#dc3545'),
                confirmButtonText: 'Yes, remove it',
                cancelButtonText: 'Cancel'
            });

            if (!result.isConfirmed) return;

            try {
                const response = await fetch(`${CONFIG.endpoints.removeTask}${taskId}`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    }
                });

                const data = await response.json();

                if (data.success) {
                    window.Swal.fire({
                        title: 'Removed!',
                        text: 'The task has been removed from the list.',
                        icon: 'success',
                        timer: 2000,
                        showConfirmButton: false
                    });
                    setTimeout(() => this.refreshTaskList(), 500);
                } else {
                    window.Swal.fire({ title: 'Error!', text: data.error || 'Failed to remove task', icon: 'error' });
                }
            } catch (error) {
                console.error('Error removing task:', error);
                window.Swal.fire({ title: 'Error!', text: 'Failed to remove task', icon: 'error' });
            }
        },

        cleanupOldTasks: async function() {
            const result = await window.Swal.fire({
                title: 'Cleanup Old Tasks?',
                html: `
                    <div class="text-start">
                        <p>This will remove:</p>
                        <ul class="text-start">
                            <li>TaskManager entries older than 24 hours</li>
                            <li>Celery metadata older than 7 days</li>
                            <li>Improves Redis performance</li>
                        </ul>
                        <p class="text-muted"><small>Recent tasks will be preserved</small></p>
                    </div>
                `,
                icon: 'question',
                showCancelButton: true,
                confirmButtonColor: this.getThemeColor('warning', '#ffc107'),
                cancelButtonColor: this.getThemeColor('secondary', '#6c757d'),
                confirmButtonText: '🧹 Clean Up',
                cancelButtonText: 'Cancel'
            });

            if (!result.isConfirmed) return;

            try {
                const response = await fetch(CONFIG.endpoints.cleanupTasks, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': this.getCsrfToken()
                    }
                });

                const data = await response.json();

                if (data.success) {
                    window.Swal.fire({
                        title: 'Cleanup Complete! 🧹',
                        html: `
                            <div class="text-start">
                                <p><strong>Cleaned up:</strong></p>
                                <ul>
                                    <li>Registry: ${data.registry_cleaned} tasks</li>
                                    <li>Metadata: ${data.metadata_cleaned} keys</li>
                                    <li><strong>Total: ${data.total_cleaned} items</strong></li>
                                </ul>
                            </div>
                        `,
                        icon: 'success',
                        timer: 4000,
                        showConfirmButton: false
                    });
                    setTimeout(() => this.refreshTaskList(), 1000);
                } else {
                    window.Swal.fire({ title: 'Error!', text: data.error || 'Failed to cleanup tasks', icon: 'error' });
                }
            } catch (error) {
                console.error('Error cleaning up tasks:', error);
                window.Swal.fire({ title: 'Error!', text: 'Failed to cleanup tasks', icon: 'error' });
            }
        },

        refreshTaskList: function() {
            this.fetchTaskList();
        },

        /* ====================================================================
           UTILITY FUNCTIONS
           ==================================================================== */

        getCsrfToken: function() {
            return document.querySelector('input[name="csrf_token"]')?.value ||
                   document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || '';
        },

        getThemeColor: function(colorName, fallback) {
            return (typeof window.ECSTheme !== 'undefined' && window.ECSTheme.getColor) ?
                   window.ECSTheme.getColor(colorName) : fallback;
        },

        showComponentToast: function(type, title, message) {
            if (window.ModernComponents?.Toast) {
                window.ModernComponents.Toast.show({ type, title, message, duration: 5000 });
            }
        },

        showToast: function(title, message, type) {
            const container = document.querySelector(CONFIG.selectors.toastContainer);
            if (!container) return;

            const toastId = 'toast-' + Date.now();
            const toastHTML = `
                <div id="${toastId}" class="toast align-items-center border-0 bg-${type} text-white" role="alert" aria-live="assertive" aria-atomic="true">
                    <div class="d-flex">
                        <div class="toast-body">
                            <strong>${title}:</strong> ${message}
                        </div>
                        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
                    </div>
                </div>
            `;
            container.insertAdjacentHTML('beforeend', toastHTML);

            const toastElement = document.getElementById(toastId);
            if (toastElement && typeof window.bootstrap !== 'undefined') {
                const toast = new window.bootstrap.Toast(toastElement, { autohide: true, delay: 5000 });
                toast.show();

                toastElement.addEventListener('hidden.bs.toast', function() {
                    toastElement.remove();
                });
            }
        }
    };

    /* ========================================================================
       REGISTER WITH INITSYSTEM OR FALLBACK TO DOMCONTENTLOADED
       ======================================================================== */

    // Expose for external access (MUST be before any callbacks or registrations)
    window.AdminDashboard = AdminDashboard;

    if (true) {
        InitSystem.register('AdminDashboard', function(context) {
            window.AdminDashboard.init(context);
        }, {
            priority: 50
        });
    } else {
        document.addEventListener('DOMContentLoaded', function() {
            window.AdminDashboard.init(document);
        });
    }

// Backward compatibility
window.CONFIG = CONFIG;
