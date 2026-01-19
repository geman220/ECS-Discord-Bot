/**
 * Pass Studio Sponsors Manager
 *
 * Handles sponsor management for wallet passes including:
 * - CRUD operations for sponsors
 * - Optional location creation from sponsor addresses
 */

import { InitSystem } from './init-system.js';
import { escapeHtml } from './utils/sanitize.js';

const SponsorsManager = {
    sponsorsData: [],
    passTypeCode: '',

    init(sponsorsData, passTypeCode) {
        this.sponsorsData = sponsorsData || [];
        this.passTypeCode = passTypeCode || '';
        console.log('SponsorsManager initialized', { count: this.sponsorsData.length });
    },

    getCsrfToken() {
        return document.querySelector('[name=csrf_token]')?.value ||
               document.querySelector('meta[name="csrf-token"]')?.content || '';
    },

    showToast(message, type = 'info') {
        if (typeof PassStudio !== 'undefined' && PassStudio.showToast) {
            PassStudio.showToast(message, type);
        } else if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({ toast: true, position: 'top-end', icon: type, title: message, showConfirmButton: false, timer: 3000 });
        }
    },

    addSponsor() {
        window.Swal.fire({
            title: 'Add Sponsor',
            html: `
                <div class="text-left">
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name <span class="text-red-500">*</span></label>
                        <input type="text" id="sponsor-name" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" placeholder="e.g., Hellbent Brewing">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Display Name</label>
                        <input type="text" id="sponsor-display" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" placeholder="Text shown on pass (leave blank to use name)">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                        <textarea id="sponsor-desc" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" rows="2" placeholder="Optional description for back of pass"></textarea>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Website URL</label>
                        <input type="url" id="sponsor-url" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" placeholder="https://...">
                    </div>
                    <div class="grid grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Sponsor Type</label>
                            <select id="sponsor-type" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                <option value="partner">Partner</option>
                                <option value="presenting">Presenting</option>
                                <option value="venue">Venue</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Display Location</label>
                            <select id="sponsor-location" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                <option value="back">Back of Pass</option>
                                <option value="auxiliary">Auxiliary Field</option>
                            </select>
                        </div>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Applies To</label>
                        <select id="sponsor-applies" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                            <option value="${escapeHtml(this.passTypeCode)}">This pass type only</option>
                            <option value="all">All pass types</option>
                        </select>
                    </div>
                    <hr class="my-4 border-gray-200 dark:border-gray-600">
                    <p class="text-sm text-gray-500 dark:text-gray-400 mb-2">Optional: Create a location from sponsor address</p>
                    <div class="flex items-center mb-4">
                        <input id="sponsor-create-loc" type="checkbox" class="w-4 h-4 text-primary-600 bg-gray-100 border-gray-300 rounded focus:ring-primary-500 dark:focus:ring-primary-600 dark:ring-offset-gray-800 focus:ring-2 dark:bg-gray-700 dark:border-gray-600">
                        <label for="sponsor-create-loc" class="ml-2 text-sm text-gray-900 dark:text-gray-300">Also create as a location</label>
                    </div>
                    <div id="sponsor-loc-fields" class="hidden">
                        <div class="grid grid-cols-2 gap-4 mb-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Latitude</label>
                                <input type="number" id="sponsor-lat" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" step="0.0001" placeholder="47.7240">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Longitude</label>
                                <input type="number" id="sponsor-lng" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" step="0.0001" placeholder="-122.2958">
                            </div>
                        </div>
                        <div class="mb-4">
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Address</label>
                            <input type="text" id="sponsor-address" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" placeholder="123 Main St">
                        </div>
                        <div class="grid grid-cols-2 gap-4 mb-4">
                            <div>
                                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">City</label>
                                <input type="text" id="sponsor-city" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" placeholder="Seattle">
                            </div>
                            <div>
                                <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">State</label>
                                <input type="text" id="sponsor-state" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" placeholder="WA">
                            </div>
                        </div>
                    </div>
                </div>
            `,
            width: '500px',
            showCancelButton: true,
            confirmButtonText: 'Add Sponsor',
            customClass: { popup: 'dark:bg-gray-800', title: 'dark:text-white', htmlContainer: 'dark:text-gray-300' },
            didOpen: () => {
                document.getElementById('sponsor-create-loc').addEventListener('change', function() {
                    document.getElementById('sponsor-loc-fields').classList.toggle('hidden', !this.checked);
                });
            },
            preConfirm: () => {
                const name = document.getElementById('sponsor-name').value.trim();
                if (!name) { window.Swal.showValidationMessage('Name is required'); return false; }
                const data = {
                    name,
                    display_name: document.getElementById('sponsor-display').value.trim() || name,
                    description: document.getElementById('sponsor-desc').value.trim(),
                    website_url: document.getElementById('sponsor-url').value.trim(),
                    sponsor_type: document.getElementById('sponsor-type').value,
                    display_location: document.getElementById('sponsor-location').value,
                    applies_to: document.getElementById('sponsor-applies').value
                };
                if (document.getElementById('sponsor-create-loc').checked) {
                    const lat = parseFloat(document.getElementById('sponsor-lat').value);
                    const lng = parseFloat(document.getElementById('sponsor-lng').value);
                    if (isNaN(lat) || isNaN(lng)) { window.Swal.showValidationMessage('Latitude and longitude are required'); return false; }
                    data.create_location = true;
                    data.latitude = lat;
                    data.longitude = lng;
                    data.address = document.getElementById('sponsor-address').value.trim();
                    data.city = document.getElementById('sponsor-city').value.trim();
                    data.state = document.getElementById('sponsor-state').value.trim();
                }
                return data;
            }
        }).then(async (result) => {
            if (result.isConfirmed) await this.saveSponsor(result.value);
        });
    },

    editSponsor(sponsorId) {
        const sponsor = this.sponsorsData.find(s => s.id === parseInt(sponsorId));
        if (!sponsor) { this.showToast('Sponsor not found', 'error'); return; }
        window.Swal.fire({
            title: 'Edit Sponsor',
            html: `
                <div class="text-left">
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name <span class="text-red-500">*</span></label>
                        <input type="text" id="edit-sponsor-name" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(sponsor.name)}">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Display Name</label>
                        <input type="text" id="edit-sponsor-display" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(sponsor.display_name)}">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Description</label>
                        <textarea id="edit-sponsor-desc" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" rows="2">${escapeHtml(sponsor.description || '')}</textarea>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Website URL</label>
                        <input type="url" id="edit-sponsor-url" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(sponsor.website_url || '')}">
                    </div>
                    <div class="grid grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Sponsor Type</label>
                            <select id="edit-sponsor-type" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                <option value="partner" ${sponsor.sponsor_type === 'partner' ? 'selected' : ''}>Partner</option>
                                <option value="presenting" ${sponsor.sponsor_type === 'presenting' ? 'selected' : ''}>Presenting</option>
                                <option value="venue" ${sponsor.sponsor_type === 'venue' ? 'selected' : ''}>Venue</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Display Location</label>
                            <select id="edit-sponsor-location" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                                <option value="back" ${sponsor.display_location === 'back' ? 'selected' : ''}>Back of Pass</option>
                                <option value="auxiliary" ${sponsor.display_location === 'auxiliary' ? 'selected' : ''}>Auxiliary Field</option>
                            </select>
                        </div>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Applies To</label>
                        <select id="edit-sponsor-applies" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                            <option value="ecs_membership" ${sponsor.applies_to === 'ecs_membership' ? 'selected' : ''}>ECS Only</option>
                            <option value="pub_league" ${sponsor.applies_to === 'pub_league' ? 'selected' : ''}>Pub League Only</option>
                            <option value="all" ${sponsor.applies_to === 'all' ? 'selected' : ''}>All pass types</option>
                        </select>
                    </div>
                </div>
            `,
            width: '500px',
            showCancelButton: true,
            confirmButtonText: 'Save Changes',
            customClass: { popup: 'dark:bg-gray-800', title: 'dark:text-white', htmlContainer: 'dark:text-gray-300' },
            preConfirm: () => {
                const name = document.getElementById('edit-sponsor-name').value.trim();
                if (!name) { window.Swal.showValidationMessage('Name is required'); return false; }
                return {
                    name,
                    display_name: document.getElementById('edit-sponsor-display').value.trim() || name,
                    description: document.getElementById('edit-sponsor-desc').value.trim(),
                    website_url: document.getElementById('edit-sponsor-url').value.trim(),
                    sponsor_type: document.getElementById('edit-sponsor-type').value,
                    display_location: document.getElementById('edit-sponsor-location').value,
                    applies_to: document.getElementById('edit-sponsor-applies').value
                };
            }
        }).then(async (result) => {
            if (result.isConfirmed) await this.updateSponsor(sponsorId, result.value);
        });
    },

    async toggleSponsor(sponsorId, active) {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/sponsors/${sponsorId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCsrfToken() },
                body: JSON.stringify({ is_active: active })
            });
            const data = await response.json();
            if (data.success) { this.showToast(`Sponsor ${active ? 'activated' : 'deactivated'}`, 'success'); location.reload(); }
            else { this.showToast(data.error || 'Error updating sponsor', 'error'); }
        } catch (error) { this.showToast('Error updating sponsor', 'error'); }
    },

    async deleteSponsor(sponsorId, name) {
        const result = await window.Swal.fire({
            title: 'Delete Sponsor?',
            text: `Are you sure you want to delete "${name}"?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#d33',
            confirmButtonText: 'Yes, delete',
            customClass: { popup: 'dark:bg-gray-800', title: 'dark:text-white', htmlContainer: 'dark:text-gray-300' }
        });
        if (result.isConfirmed) {
            try {
                const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/sponsors/${sponsorId}`, {
                    method: 'DELETE',
                    headers: { 'X-CSRFToken': this.getCsrfToken() }
                });
                const data = await response.json();
                if (data.success) { this.showToast('Sponsor deleted', 'success'); location.reload(); }
                else { this.showToast(data.error || 'Error deleting sponsor', 'error'); }
            } catch (error) { this.showToast('Error deleting sponsor', 'error'); }
        }
    },

    async saveSponsor(sponsorData) {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/sponsors`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCsrfToken() },
                body: JSON.stringify(sponsorData)
            });
            const data = await response.json();
            if (data.success) { this.showToast('Sponsor added', 'success'); location.reload(); }
            else { this.showToast(data.error || 'Error adding sponsor', 'error'); }
        } catch (error) { this.showToast('Error adding sponsor', 'error'); }
    },

    async updateSponsor(sponsorId, sponsorData) {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/sponsors/${sponsorId}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': this.getCsrfToken() },
                body: JSON.stringify(sponsorData)
            });
            const data = await response.json();
            if (data.success) { this.showToast('Sponsor updated', 'success'); location.reload(); }
            else { this.showToast(data.error || 'Error updating sponsor', 'error'); }
        } catch (error) { this.showToast('Error updating sponsor', 'error'); }
    }
};

window.SponsorsManager = SponsorsManager;
window.addSponsor = () => SponsorsManager.addSponsor();
window.editSponsor = (id) => SponsorsManager.editSponsor(id);
window.toggleSponsor = (id, active) => SponsorsManager.toggleSponsor(id, active);
window.deleteSponsor = (id, name) => SponsorsManager.deleteSponsor(id, name);

let _sponsorsManagerInitialized = false;
function initSponsorsManager() {
    if (_sponsorsManagerInitialized) return;
    const initScript = document.getElementById('sponsors-manager-init-data');
    if (!initScript) return;
    _sponsorsManagerInitialized = true;
    try {
        const initData = JSON.parse(initScript.textContent);
        window.SponsorsManager.init(initData.sponsors || [], initData.passTypeCode || '');
    } catch (e) { console.error('Failed to parse SponsorsManager init data:', e); }
}

InitSystem.register('pass-studio-sponsors', initSponsorsManager, {
    priority: 37,
    reinitializable: false,
    description: 'Pass studio sponsors management'
});
