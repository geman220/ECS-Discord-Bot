/**
 * Pass Studio Subgroups Manager
 *
 * Handles ECS supporter subgroup management
 */

import { InitSystem } from './init-system.js';
import { escapeHtml } from './utils/sanitize.js';

const SubgroupsManager = {
    passTypeCode: '',

    init(passTypeCode) {
        this.passTypeCode = passTypeCode || 'ecs_membership';
        console.log('SubgroupsManager initialized');
    },

    getCsrfToken() {
        return document.querySelector('[name=csrf_token]')?.value ||
               document.querySelector('meta[name="csrf-token"]')?.content || '';
    },

    showToast(message, type = 'info') {
        if (typeof PassStudio !== 'undefined' && PassStudio.showToast) {
            PassStudio.showToast(message, type);
        } else if (typeof Swal !== 'undefined') {
            Swal.fire({ toast: true, position: 'top-end', icon: type, title: message, showConfirmButton: false, timer: 3000 });
        }
    },

    addSubgroup() {
        Swal.fire({
            title: 'Add Subgroup',
            html: `
                <div class="text-left">
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name <span class="text-red-500">*</span></label>
                        <input type="text" id="sg-name" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" placeholder="e.g., Gorilla FC">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Code</label>
                        <input type="text" id="sg-code" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" placeholder="e.g., gorilla_fc (auto-generated if blank)">
                        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">Lowercase identifier, no spaces</p>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                        <textarea id="sg-desc" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" rows="2" placeholder="Optional description"></textarea>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Add Subgroup',
            customClass: { popup: 'dark:bg-gray-800', title: 'dark:text-white', htmlContainer: 'dark:text-gray-300' },
            preConfirm: () => {
                const name = document.getElementById('sg-name').value.trim();
                if (!name) { Swal.showValidationMessage('Name is required'); return false; }
                return {
                    name,
                    code: document.getElementById('sg-code').value.trim() || name.toLowerCase().replace(/\s+/g, '_'),
                    description: document.getElementById('sg-desc').value.trim()
                };
            }
        }).then(async (result) => {
            if (result.isConfirmed) await this.saveSubgroup(result.value);
        });
    },

    editSubgroup(id, name, code, description) {
        Swal.fire({
            title: 'Edit Subgroup',
            html: `
                <div class="text-left">
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name <span class="text-red-500">*</span></label>
                        <input type="text" id="edit-sg-name" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(name)}">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Code</label>
                        <input type="text" id="edit-sg-code" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white opacity-50 cursor-not-allowed" value="${escapeHtml(code)}" disabled>
                        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">Code cannot be changed after creation</p>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                        <textarea id="edit-sg-desc" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" rows="2">${escapeHtml(description || '')}</textarea>
                    </div>
                </div>
            `,
            showCancelButton: true,
            confirmButtonText: 'Save Changes',
            customClass: { popup: 'dark:bg-gray-800', title: 'dark:text-white', htmlContainer: 'dark:text-gray-300' },
            preConfirm: () => {
                const name = document.getElementById('edit-sg-name').value.trim();
                if (!name) { Swal.showValidationMessage('Name is required'); return false; }
                return { name, description: document.getElementById('edit-sg-desc').value.trim() };
            }
        }).then(async (result) => {
            if (result.isConfirmed) await this.updateSubgroup(id, result.value);
        });
    },

    async deleteSubgroup(id, name) {
        const result = await Swal.fire({
            title: 'Delete Subgroup?',
            text: `Are you sure you want to delete "${name}"? This won't affect existing passes.`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#d33',
            confirmButtonText: 'Yes, delete',
            customClass: { popup: 'dark:bg-gray-800', title: 'dark:text-white', htmlContainer: 'dark:text-gray-300' }
        });
        if (result.isConfirmed) {
            try {
                const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/subgroups/${id}`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.getCsrfToken() }
                });
                const data = await response.json();
                if (data.success) { this.showToast('Subgroup deleted', 'success'); location.reload(); }
                else { this.showToast(data.error || 'Error deleting subgroup', 'error'); }
            } catch (error) { this.showToast('Error deleting subgroup', 'error'); }
        }
    },

    async saveSubgroup(subgroupData) {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/subgroups`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCsrfToken() },
                body: JSON.stringify(subgroupData)
            });
            const data = await response.json();
            if (data.success) { this.showToast('Subgroup added', 'success'); location.reload(); }
            else { this.showToast(data.error || 'Error adding subgroup', 'error'); }
        } catch (error) { this.showToast('Error adding subgroup', 'error'); }
    },

    async updateSubgroup(id, subgroupData) {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/subgroups/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCsrfToken() },
                body: JSON.stringify(subgroupData)
            });
            const data = await response.json();
            if (data.success) { this.showToast('Subgroup updated', 'success'); location.reload(); }
            else { this.showToast(data.error || 'Error updating subgroup', 'error'); }
        } catch (error) { this.showToast('Error updating subgroup', 'error'); }
    }
};

window.SubgroupsManager = SubgroupsManager;
window.addSubgroup = () => SubgroupsManager.addSubgroup();
window.editSubgroup = (id, name, code, desc) => SubgroupsManager.editSubgroup(id, name, code, desc);
window.deleteSubgroup = (id, name) => SubgroupsManager.deleteSubgroup(id, name);

let _subgroupsManagerInitialized = false;
function initSubgroupsManager() {
    if (_subgroupsManagerInitialized) return;
    const initScript = document.getElementById('subgroups-manager-init-data');
    if (!initScript) return;
    _subgroupsManagerInitialized = true;
    try {
        const initData = JSON.parse(initScript.textContent);
        window.SubgroupsManager.init(initData.passTypeCode || 'ecs_membership');
    } catch (e) { console.error('Failed to parse SubgroupsManager init data:', e); }
}

InitSystem.register('pass-studio-subgroups', initSubgroupsManager, {
    priority: 38,
    reinitializable: false,
    description: 'Pass studio subgroups management'
});
