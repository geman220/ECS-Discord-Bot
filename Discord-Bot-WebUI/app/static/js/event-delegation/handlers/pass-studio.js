/**
 * Pass Studio Action Handlers
 * Handles wallet pass design and configuration
 */
// Uses global window.EventDelegation from core.js

// PASS STUDIO ACTIONS
// ============================================================================

/**
 * Platform Toggle Action
 * Switches between Apple and Google wallet preview
 */
EventDelegation.register('toggle-platform', function(element, e) {
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
EventDelegation.register('update-pass-style', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updatePassStylePreview === 'function') {
        window.PassStudio.updatePassStylePreview();
    } else {
        console.error('[update-pass-style] PassStudio.updatePassStylePreview not available');
    }
});

/**
 * Apply Color Preset Action
 * Applies predefined color schemes to the pass
 */
EventDelegation.register('apply-color-preset', function(element, e) {
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
EventDelegation.register('sync-color-input', function(element, e) {
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
EventDelegation.register('update-preview-field', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updatePreviewFromForm === 'function') {
        window.PassStudio.updatePreviewFromForm();
    }
});

/**
 * Toggle Logo Visibility Action
 * Shows/hides logo in preview
 */
EventDelegation.register('toggle-logo-visibility', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.toggleLogoVisibility === 'function') {
        window.PassStudio.toggleLogoVisibility();
    }
});

/**
 * Open Asset Cropper Action
 * Opens modal to upload/crop pass assets
 */
EventDelegation.register('open-asset-cropper', function(element, e) {
    e.preventDefault();

    const assetType = element.dataset.assetType;

    if (!assetType) {
        console.error('[open-asset-cropper] Missing asset type');
        return;
    }

    if (window.PassStudio && typeof window.PassStudio.openAssetCropper === 'function') {
        window.PassStudio.openAssetCropper(assetType);
    } else {
        console.error('[open-asset-cropper] PassStudio.openAssetCropper not available');
    }
});

/**
 * Update Google Preview Action
 * Updates Google Wallet preview with URL changes
 */
EventDelegation.register('update-google-preview', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updateGooglePreview === 'function') {
        window.PassStudio.updateGooglePreview();
    }
});

/**
 * Update Barcode Preview Action
 * Shows/hides barcode in preview
 */
EventDelegation.register('update-barcode-preview', function(element, e) {
    if (window.PassStudio && typeof window.PassStudio.updateBarcodePreview === 'function') {
        window.PassStudio.updateBarcodePreview();
    }
});

/**
 * Save Appearance Action
 * Saves appearance settings to server
 */
EventDelegation.register('save-appearance', function(element, e) {
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
EventDelegation.register('initialize-defaults', function(element, e) {
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
EventDelegation.register('add-pass-field', function(element, e) {
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
EventDelegation.register('create-field', function(element, e) {
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
EventDelegation.register('save-fields', function(element, e) {
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
EventDelegation.register('reset-fields', function(element, e) {
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
EventDelegation.register('insert-variable', function(element, e) {
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

console.log('[EventDelegation] Pass studio handlers loaded');
