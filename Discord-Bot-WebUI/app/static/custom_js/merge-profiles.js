/**
 * Profile Merge Management
 * Handles the UI and interaction for merging duplicate player profiles
 */
import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function init() {
    if (_initialized) return;
    _initialized = true;

    initializeMergeProfileUI();
}

function initializeMergeProfileUI() {
    // Handle field selection visual feedback
    // ROOT CAUSE FIX: Uses event delegation instead of per-element listeners
    document.addEventListener('click', function(e) {
        const option = e.target.closest('.value-option');
        if (!option) return;

        const field = option.dataset.field;

        // Remove selected class from other options for this field
        document.querySelectorAll(`[data-field="${field}"]`).forEach(opt => {
            opt.classList.remove('selected');
        });

        // Add selected class to clicked option
        option.classList.add('selected');

        // Check the radio button
        const radio = option.querySelector('input[type="radio"]');
        if (radio) radio.checked = true;

        // Update preview
        updateMergePreview();
    });

    // Initialize with current selections
    updateMergePreview();
}

function updateMergePreview() {
    const updatesList = document.getElementById('updatesList');
    if (!updatesList) return;

    const updates = [];

    document.querySelectorAll('input[type="radio"]:checked').forEach(radio => {
        const field = radio.name.replace('field_', '');
        const value = radio.value;

        if (value === 'new') {
            updates.push(`<small class="d-block text-primary">Update ${field.replace('_', ' ')}</small>`);
        } else if (value === 'combine') {
            updates.push(`<small class="d-block text-warning">Combine ${field.replace('_', ' ')}</small>`);
        }
    });

    if (updates.length > 0) {
        updatesList.innerHTML = updates.join('');
    } else {
        updatesList.innerHTML = '<p class="text-muted mb-0"><em>No changes selected</em></p>';
    }
}

// Export functions for template compatibility
window.initializeMergeProfileUI = initializeMergeProfileUI;
window.updateMergePreview = updateMergePreview;

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('merge-profiles', init, {
        priority: 45,
        reinitializable: false,
        description: 'Profile merge management'
    });
}

// Fallback
// window.InitSystem handles initialization
