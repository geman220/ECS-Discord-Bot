/**
 * Profile Merge Management
 * Handles the UI and interaction for merging duplicate player profiles
 */

document.addEventListener('DOMContentLoaded', function() {
    initializeMergeProfileUI();
});

function initializeMergeProfileUI() {
    // Handle field selection visual feedback
    document.querySelectorAll('.value-option').forEach(option => {
        option.addEventListener('click', function() {
            const field = this.dataset.field;
            const value = this.dataset.value;

            // Remove selected class from other options for this field
            document.querySelectorAll(`[data-field="${field}"]`).forEach(opt => {
                opt.classList.remove('selected');
            });

            // Add selected class to clicked option
            this.classList.add('selected');

            // Check the radio button
            this.querySelector('input[type="radio"]').checked = true;

            // Update preview
            updateMergePreview();
        });
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
