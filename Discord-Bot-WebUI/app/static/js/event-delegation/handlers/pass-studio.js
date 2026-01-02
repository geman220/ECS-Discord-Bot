import { EventDelegation } from '../core.js';

/**
 * Pass Studio Action Handlers
 * Handles wallet pass design and configuration
 */

// PASS STUDIO ACTIONS
// ============================================================================

/**
 * Platform Toggle Action
 * Switches between Apple and Google wallet preview
 */
window.EventDelegation.register('toggle-platform', function(element, e) {
    e.preventDefault();

    const platform = element.dataset.platform;

    if (!platform) {
        console.error('[toggle-platform] Missing platform attribute');
        return;
    }

    if (window.PassStudio && typeof window.PassStudio.setPreviewPlatform === 'function') {
        window.PassStudio.setPreviewPlatform(platform);
    } else {
        console.error('[toggle-platform] PassStudio.setPreviewPlatform not available');
    }
});

/**
 * Update Pass Style Action
 * Changes pass layout style (generic, storeCard, eventTicket)
 * Triggered by change event on radio buttons
 */
window.EventDelegation.register('update-pass-style', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updatePassStylePreview === 'function') {
        window.PassStudio.updatePassStylePreview();
    } else {
        console.error('[update-pass-style] window.PassStudio.updatePassStylePreview not available');
    }
});

/**
 * Apply Color Preset Action
 * Applies predefined color schemes to the pass
 */
window.EventDelegation.register('apply-color-preset', function(element, e) {
    e.preventDefault();

    const bg = element.dataset.bg;
    const fg = element.dataset.fg;
    const label = element.dataset.label;

    if (!bg || !fg || !label) {
        console.error('[apply-color-preset] Missing color data attributes');
        return;
    }

    // Set color inputs
    const bgColorInput = document.getElementById('background_color');
    const fgColorInput = document.getElementById('foreground_color');
    const labelColorInput = document.getElementById('label_color');

    if (bgColorInput) bgColorInput.value = bg;
    if (fgColorInput) fgColorInput.value = fg;
    if (labelColorInput) labelColorInput.value = label;

    // Set text inputs
    const bgColorText = document.getElementById('background_color_text');
    const fgColorText = document.getElementById('foreground_color_text');
    const labelColorText = document.getElementById('label_color_text');

    if (bgColorText) bgColorText.value = bg;
    if (fgColorText) fgColorText.value = fg;
    if (labelColorText) labelColorText.value = label;

    // Update preview
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }

    // Mark unsaved
    if (window.PassStudio && typeof window.PassStudio.markUnsaved === 'function') {
        window.PassStudio.markUnsaved();
    }
});

/**
 * Sync Color Input Action
 * Syncs color picker with text input and vice versa
 */
window.EventDelegation.register('sync-color-input', function(element, e) {
    const targetId = element.dataset.target;
    if (!targetId) return;

    const target = document.getElementById(targetId);
    if (!target) return;

    // Sync the values
    if (element.type === 'color') {
        // Color picker changed - update text input
        const textInput = document.getElementById(targetId + '_text');
        if (textInput) textInput.value = element.value;
    } else {
        // Text input changed - update color picker
        target.value = element.value;
    }

    // Update preview
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }
});

/**
 * Update Preview Field Action
 * Updates specific field in preview (e.g., logo text)
 */
window.EventDelegation.register('update-preview-field', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }
});

/**
 * Toggle Logo Visibility Action
 * Shows/hides logo in preview
 */
window.EventDelegation.register('toggle-logo-visibility', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.toggleLogoVisibility === 'function') {
        window.PassStudio.toggleLogoVisibility();
    }
});

/**
 * Open Asset Cropper Action
 * Opens modal to upload/crop pass assets
 */
window.EventDelegation.register('open-asset-cropper', function(element, e) {
    e.preventDefault();

    const assetType = element.dataset.assetType;

    if (!assetType) {
        console.error('[open-asset-cropper] Missing asset type');
        return;
    }

    if (window.PassStudio && typeof window.PassStudio.openAssetCropper === 'function') {
        window.PassStudio.openAssetCropper(assetType);
    } else {
        console.error('[open-asset-cropper] window.PassStudio.openAssetCropper not available');
    }
});

/**
 * Update Google Preview Action
 * Updates Google Wallet preview with URL changes
 */
window.EventDelegation.register('update-google-preview', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updateGooglePreview === 'function') {
        window.PassStudio.updateGooglePreview();
    }
});

/**
 * Update Barcode Preview Action
 * Shows/hides barcode in preview
 */
window.EventDelegation.register('update-barcode-preview', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updateBarcodePreview === 'function') {
        window.PassStudio.updateBarcodePreview();
    }
});

/**
 * Save Appearance Action
 * Saves appearance settings to server
 */
window.EventDelegation.register('save-appearance', function(element, e) {
    e.preventDefault();

    if (window.PassStudio && typeof window.PassStudio.saveAppearance === 'function') {
        window.PassStudio.saveAppearance();
    } else {
        console.error('[save-appearance] PassStudio.saveAppearance not available');
    }
});

/**
 * Initialize Defaults Action
 * Loads default field configuration for pass
 */
window.EventDelegation.register('initialize-defaults', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.initializeDefaults === 'function') {
        window.FieldsManager.initializeDefaults();
    } else {
        console.error('[initialize-defaults] FieldsManager.initializeDefaults not available');
    }
});

/**
 * Add Pass Field Action
 * Opens modal to add new pass field (Pass Studio)
 */
window.EventDelegation.register('add-pass-field', function(element, e) {
    e.preventDefault();

    const fieldType = element.dataset.fieldType;

    if (!fieldType) {
        console.error('[add-pass-field] Missing field type');
        return;
    }

    if (window.FieldsManager && typeof window.FieldsManager.openAddFieldModal === 'function') {
        window.FieldsManager.openAddFieldModal(fieldType);
    } else {
        console.error('[add-pass-field] FieldsManager.openAddFieldModal not available');
    }
});

/**
 * Create Field Action
 * Creates new field from modal data
 */
window.EventDelegation.register('create-field', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.createField === 'function') {
        window.FieldsManager.createField();
    } else {
        console.error('[create-field] FieldsManager.createField not available');
    }
});

/**
 * Save Fields Action
 * Saves all field configurations to server
 */
window.EventDelegation.register('save-fields', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.saveFields === 'function') {
        window.FieldsManager.saveFields();
    } else {
        console.error('[save-fields] FieldsManager.saveFields not available');
    }
});

/**
 * Reset Fields Action
 * Resets fields to last saved state
 */
window.EventDelegation.register('reset-fields', function(element, e) {
    e.preventDefault();

    if (window.FieldsManager && typeof window.FieldsManager.resetFields === 'function') {
        window.FieldsManager.resetFields();
    } else {
        console.error('[reset-fields] FieldsManager.resetFields not available');
    }
});

/**
 * Insert Variable Action
 * Inserts template variable at cursor position
 */
window.EventDelegation.register('insert-variable', function(element, e) {
    e.preventDefault();

    const variableName = element.dataset.variableName;

    if (!variableName) {
        console.error('[insert-variable] Missing variable name');
        return;
    }

    if (window.FieldsManager && typeof window.FieldsManager.insertVariableInAdd === 'function') {
        window.FieldsManager.insertVariableInAdd(variableName);
    } else {
        console.error('[insert-variable] FieldsManager.insertVariableInAdd not available');
    }
});

// ============================================================================
// DIAGNOSTICS PAGE ACTIONS - Handled by wallet-config-handlers.js
// ============================================================================
// Removed: print-page, toggle-detail, run-admin-command (duplicates)

// ============================================================================
// WALLET PASS MANAGEMENT ACTIONS - Handled by admin-wallet.js
// ============================================================================
// Removed: bulk-void-passes, bulk-reactivate-passes, clear-pass-selection,
// void-pass, reactivate-pass, bulk-generate-passes, confirm-bulk-void (duplicates)

// ============================================================================
// WOOCOMMERCE INTEGRATION ACTIONS - Handled by wallet-config-handlers.js
// ============================================================================
// Removed: copy-to-clipboard, save-woocommerce-url, generate-secret,
// validate-plugin-connection (duplicates)

// ============================================================================
// SPONSORS/LOCATIONS/SUBGROUPS ACTIONS
// Note: delete-sponsor and delete-subgroup are also in wallet-config-handlers.js
// These are pass-studio specific implementations for the sponsors/subgroups tabs
// ============================================================================

/**
 * Add/Edit/Toggle Sponsor - Pass Studio specific
 */
window.EventDelegation.register('add-sponsor', function(element, e) {
    e.preventDefault();
    if (typeof window.addSponsor === 'function') {
        window.addSponsor();
    } else {
        console.error('[add-sponsor] addSponsor function not found');
    }
}, { preventDefault: true });

window.EventDelegation.register('edit-sponsor', function(element, e) {
    e.preventDefault();
    const sponsorId = element.dataset.sponsorId;
    if (typeof window.editSponsor === 'function') {
        window.editSponsor(sponsorId);
    }
}, { preventDefault: true });

window.EventDelegation.register('toggle-sponsor', function(element, e) {
    e.preventDefault();
    const sponsorId = element.dataset.sponsorId;
    const active = element.dataset.active;
    if (typeof window.toggleSponsor === 'function') {
        window.toggleSponsor(sponsorId, active === 'true');
    }
}, { preventDefault: true });

// Removed: delete-sponsor (handled by wallet-config-handlers.js)

/**
 * Add/Edit/Toggle Location - Pass Studio specific
 */
window.EventDelegation.register('add-location', function(element, e) {
    e.preventDefault();
    if (typeof window.addLocation === 'function') {
        window.addLocation();
    } else {
        console.error('[add-location] addLocation function not found');
    }
}, { preventDefault: true });

window.EventDelegation.register('edit-location', function(element, e) {
    e.preventDefault();
    const locationId = element.dataset.locationId;
    if (typeof window.editLocation === 'function') {
        window.editLocation(locationId);
    }
}, { preventDefault: true });

window.EventDelegation.register('toggle-location', function(element, e) {
    e.preventDefault();
    const locationId = element.dataset.locationId;
    const active = element.dataset.active;
    if (typeof window.toggleLocation === 'function') {
        window.toggleLocation(locationId, active === 'true');
    }
}, { preventDefault: true });

window.EventDelegation.register('delete-location', function(element, e) {
    e.preventDefault();
    const locationId = element.dataset.locationId;
    const locationName = element.dataset.locationName;
    if (typeof window.deleteLocation === 'function') {
        window.deleteLocation(locationId, locationName);
    }
}, { preventDefault: true });

/**
 * Add/Edit Subgroup - Pass Studio specific
 */
window.EventDelegation.register('add-subgroup', function(element, e) {
    e.preventDefault();
    if (typeof window.addSubgroup === 'function') {
        window.addSubgroup();
    } else {
        console.error('[add-subgroup] addSubgroup function not found');
    }
}, { preventDefault: true });

window.EventDelegation.register('edit-subgroup', function(element, e) {
    e.preventDefault();
    const subgroupId = element.dataset.subgroupId;
    const subgroupName = element.dataset.subgroupName;
    const subgroupCode = element.dataset.subgroupCode;
    const subgroupDescription = element.dataset.subgroupDescription || '';
    if (typeof window.editSubgroup === 'function') {
        window.editSubgroup(subgroupId, subgroupName, subgroupCode, subgroupDescription);
    }
}, { preventDefault: true });

// Removed: delete-subgroup (handled by wallet-config-handlers.js)

// ============================================================================
// TEMPLATE SECTION ACTIONS - Handled by wallet-config-handlers.js / message-templates.js
// ============================================================================
// Removed: edit-category (handled by communication-handlers.js)
// Removed: edit-template (handled by wallet-config-handlers.js)
// Removed: preview-template (handled by message-templates.js)
// Removed: copy-template (handled by message-templates.js)

// ============================================================================
// FORM UTILITY ACTIONS - Handled by wallet-config-handlers.js / form-actions.js
// ============================================================================
// Removed: reset-form (handled by wallet-config-handlers.js)
// Removed: clear-selection (handled by form-actions.js)

// ============================================================================

// Handlers loaded
