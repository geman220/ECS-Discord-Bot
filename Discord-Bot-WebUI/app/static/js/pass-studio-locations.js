/**
 * Pass Studio Locations Manager
 *
 * Handles location management for wallet passes including:
 * - CRUD operations for partner locations
 * - Location-based notification configuration
 * - Geolocation support
 */

import { InitSystem } from './init-system.js';
import { escapeHtml } from './utils/sanitize.js';

/**
 * Locations Manager - Handles location operations in Pass Studio
 */
const LocationsManager = {
    // State
    locationsData: [],
    passTypeCode: '',
    maxLocations: 10,

    /**
     * Initialize the locations manager
     */
    init(locationsData, passTypeCode, maxLocations) {
        this.locationsData = locationsData || [];
        this.passTypeCode = passTypeCode || '';
        this.maxLocations = maxLocations || 10;

        console.log('LocationsManager initialized', { count: this.locationsData.length, passTypeCode: this.passTypeCode });
    },

    /**
     * Get CSRF token
     */
    getCsrfToken() {
        return document.querySelector('[name=csrf_token]')?.value ||
               document.querySelector('meta[name="csrf-token"]')?.content || '';
    },

    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
        if (typeof PassStudio !== 'undefined' && PassStudio.showToast) {
            PassStudio.showToast(message, type);
        } else if (typeof window.Swal !== 'undefined') {
            window.Swal.fire({
                toast: true,
                position: 'top-end',
                icon: type,
                title: message,
                showConfirmButton: false,
                timer: 3000
            });
        }
    },

    /**
     * Open add location modal
     */
    addLocation() {
        window.Swal.fire({
            title: 'Add Location',
            html: `
                <div class="text-left">
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name <span class="text-red-500">*</span></label>
                        <input type="text" id="loc-name" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="e.g., Hellbent Brewing">
                    </div>
                    <div class="grid grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Latitude <span class="text-red-500">*</span></label>
                            <input type="number" id="loc-lat" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" step="0.0001" placeholder="47.7240">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Longitude <span class="text-red-500">*</span></label>
                            <input type="number" id="loc-lng" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" step="0.0001" placeholder="-122.2958">
                        </div>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Notification Text</label>
                        <input type="text" id="loc-text" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="Text shown when user is nearby">
                        <p class="mt-1 text-xs text-gray-500 dark:text-gray-400">Leave blank to use the location name</p>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Address (optional)</label>
                        <input type="text" id="loc-address" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="123 Main St">
                    </div>
                    <div class="grid grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">City</label>
                            <input type="text" id="loc-city" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="Seattle">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">State</label>
                            <input type="text" id="loc-state" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:placeholder-gray-400 dark:text-white" placeholder="WA">
                        </div>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Applies To</label>
                        <select id="loc-applies" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                            <option value="${escapeHtml(this.passTypeCode)}">This pass type only</option>
                            <option value="all">All pass types</option>
                        </select>
                    </div>
                </div>
            `,
            width: '500px',
            showCancelButton: true,
            confirmButtonText: 'Add Location',
            customClass: {
                popup: 'dark:bg-gray-800',
                title: 'dark:text-white',
                htmlContainer: 'dark:text-gray-300'
            },
            preConfirm: () => {
                const name = document.getElementById('loc-name').value.trim();
                const lat = parseFloat(document.getElementById('loc-lat').value);
                const lng = parseFloat(document.getElementById('loc-lng').value);

                if (!name || isNaN(lat) || isNaN(lng)) {
                    window.Swal.showValidationMessage('Name, latitude, and longitude are required');
                    return false;
                }

                return {
                    name,
                    latitude: lat,
                    longitude: lng,
                    relevant_text: document.getElementById('loc-text').value.trim() || name,
                    address: document.getElementById('loc-address').value.trim(),
                    city: document.getElementById('loc-city').value.trim(),
                    state: document.getElementById('loc-state').value.trim(),
                    applies_to: document.getElementById('loc-applies').value
                };
            }
        }).then(async (result) => {
            if (result.isConfirmed) {
                await this.saveLocation(result.value);
            }
        });
    },

    /**
     * Open edit location modal
     */
    editLocation(locationId) {
        const loc = this.locationsData.find(l => l.id === parseInt(locationId));
        if (!loc) {
            this.showToast('Location not found', 'error');
            return;
        }

        window.Swal.fire({
            title: 'Edit Location',
            html: `
                <div class="text-left">
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Name <span class="text-red-500">*</span></label>
                        <input type="text" id="edit-loc-name" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(loc.name)}">
                    </div>
                    <div class="grid grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Latitude <span class="text-red-500">*</span></label>
                            <input type="number" id="edit-loc-lat" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" step="0.0001" value="${loc.latitude}">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Longitude <span class="text-red-500">*</span></label>
                            <input type="number" id="edit-loc-lng" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" step="0.0001" value="${loc.longitude}">
                        </div>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Notification Text</label>
                        <input type="text" id="edit-loc-text" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(loc.relevant_text)}">
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Address</label>
                        <input type="text" id="edit-loc-address" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(loc.address || '')}">
                    </div>
                    <div class="grid grid-cols-2 gap-4 mb-4">
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">City</label>
                            <input type="text" id="edit-loc-city" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(loc.city || '')}">
                        </div>
                        <div>
                            <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">State</label>
                            <input type="text" id="edit-loc-state" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white" value="${escapeHtml(loc.state || '')}">
                        </div>
                    </div>
                    <div class="mb-4">
                        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Applies To</label>
                        <select id="edit-loc-applies" class="bg-gray-50 border border-gray-300 text-gray-900 text-sm rounded-lg focus:ring-primary-500 focus:border-primary-500 block w-full p-2.5 dark:bg-gray-700 dark:border-gray-600 dark:text-white">
                            <option value="ecs_membership" ${loc.applies_to === 'ecs_membership' ? 'selected' : ''}>ECS Only</option>
                            <option value="pub_league" ${loc.applies_to === 'pub_league' ? 'selected' : ''}>Pub League Only</option>
                            <option value="all" ${loc.applies_to === 'all' ? 'selected' : ''}>All pass types</option>
                        </select>
                    </div>
                </div>
            `,
            width: '500px',
            showCancelButton: true,
            confirmButtonText: 'Save Changes',
            customClass: {
                popup: 'dark:bg-gray-800',
                title: 'dark:text-white',
                htmlContainer: 'dark:text-gray-300'
            },
            preConfirm: () => {
                const name = document.getElementById('edit-loc-name').value.trim();
                const lat = parseFloat(document.getElementById('edit-loc-lat').value);
                const lng = parseFloat(document.getElementById('edit-loc-lng').value);

                if (!name || isNaN(lat) || isNaN(lng)) {
                    window.Swal.showValidationMessage('Name, latitude, and longitude are required');
                    return false;
                }

                return {
                    name,
                    latitude: lat,
                    longitude: lng,
                    relevant_text: document.getElementById('edit-loc-text').value.trim() || name,
                    address: document.getElementById('edit-loc-address').value.trim(),
                    city: document.getElementById('edit-loc-city').value.trim(),
                    state: document.getElementById('edit-loc-state').value.trim(),
                    applies_to: document.getElementById('edit-loc-applies').value
                };
            }
        }).then(async (result) => {
            if (result.isConfirmed) {
                await this.updateLocation(locationId, result.value);
            }
        });
    },

    /**
     * Toggle location active status
     */
    async toggleLocation(locationId, active) {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/locations/${locationId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify({ is_active: active })
            });

            const data = await response.json();
            if (data.success) {
                this.showToast(`Location ${active ? 'activated' : 'deactivated'}`, 'success');
                location.reload();
            } else {
                this.showToast(data.error || 'Error updating location', 'error');
            }
        } catch (error) {
            console.error('Toggle location error:', error);
            this.showToast('Error updating location', 'error');
        }
    },

    /**
     * Delete a location
     */
    async deleteLocation(locationId, name) {
        const result = await window.Swal.fire({
            title: 'Delete Location?',
            text: `Are you sure you want to delete "${name}"?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#d33',
            confirmButtonText: 'Yes, delete',
            customClass: {
                popup: 'dark:bg-gray-800',
                title: 'dark:text-white',
                htmlContainer: 'dark:text-gray-300'
            }
        });

        if (result.isConfirmed) {
            try {
                const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/locations/${locationId}`, {
                    method: 'DELETE',
                    headers: {
                        'X-CSRFToken': this.getCsrfToken()
                    }
                });

                const data = await response.json();
                if (data.success) {
                    this.showToast('Location deleted', 'success');
                    location.reload();
                } else {
                    this.showToast(data.error || 'Error deleting location', 'error');
                }
            } catch (error) {
                console.error('Delete location error:', error);
                this.showToast('Error deleting location', 'error');
            }
        }
    },

    /**
     * Save a new location
     */
    async saveLocation(locationData) {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/locations`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify(locationData)
            });

            const data = await response.json();
            if (data.success) {
                this.showToast('Location added', 'success');
                location.reload();
            } else {
                this.showToast(data.error || 'Error adding location', 'error');
            }
        } catch (error) {
            console.error('Save location error:', error);
            this.showToast('Error adding location', 'error');
        }
    },

    /**
     * Update an existing location
     */
    async updateLocation(locationId, locationData) {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/locations/${locationId}`, {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': this.getCsrfToken()
                },
                body: JSON.stringify(locationData)
            });

            const data = await response.json();
            if (data.success) {
                this.showToast('Location updated', 'success');
                location.reload();
            } else {
                this.showToast(data.error || 'Error updating location', 'error');
            }
        } catch (error) {
            console.error('Update location error:', error);
            this.showToast('Error updating location', 'error');
        }
    }
};

// Make globally available
window.LocationsManager = LocationsManager;

// Legacy function wrappers for event delegation
window.addLocation = () => LocationsManager.addLocation();
window.editLocation = (id) => LocationsManager.editLocation(id);
window.toggleLocation = (id, active) => LocationsManager.toggleLocation(id, active);
window.deleteLocation = (id, name) => LocationsManager.deleteLocation(id, name);

// Register with InitSystem
let _locationsManagerInitialized = false;

function initLocationsManager() {
    if (_locationsManagerInitialized) return;

    // Look for initialization data
    const initScript = document.getElementById('locations-manager-init-data');
    if (!initScript) return;

    _locationsManagerInitialized = true;

    try {
        const initData = JSON.parse(initScript.textContent);
        window.LocationsManager.init(
            initData.locations || [],
            initData.passTypeCode || '',
            initData.maxLocations || 10
        );
    } catch (e) {
        console.error('Failed to parse LocationsManager init data:', e);
    }
}

InitSystem.register('pass-studio-locations', initLocationsManager, {
    priority: 36,
    reinitializable: false,
    description: 'Pass studio locations management'
});
