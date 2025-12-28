/**
 * ============================================================================
 * Pass Studio - Main JavaScript
 * ============================================================================
 *
 * Extracted from inline <script> tags in admin/pass_studio/studio.html
 * Manages pass configuration, live preview, and asset management
 *
 * EVENT DELEGATION CONVERSION (Phase 2.2 Sprint 3):
 * - All template actions now use centralized event delegation via event-delegation.js
 * - Registered actions: toggle-platform, update-pass-style, apply-color-preset,
 *   sync-color-input, update-preview-field, toggle-logo-visibility,
 *   open-asset-cropper, update-google-preview, update-barcode-preview,
 *   save-appearance, initialize-defaults, add-field, create-field,
 *   save-fields, reset-fields, insert-variable
 * - Template strings in FieldsManager use individual addEventListener calls
 *   (acceptable as they're dynamically created and not in initial HTML)
 * - CSRF token retrieval updated to vanilla JS (meta tag fallback pattern)
 *
 * ============================================================================
 */

// Pass Studio JavaScript
const PassStudio = {
    passTypeCode: '',
    hasUnsavedChanges: false,
    previewData: null,
    currentPlatform: 'apple',
    assets: {},

    init(passTypeCode) {
        this.passTypeCode = passTypeCode;
        this.loadPreviewData();
        this.loadAssets();
        this.bindEvents();
        this.initColorPickers();
    },

    bindEvents() {
        // Platform toggle handled by event delegation in event-delegation.js

        // Track changes
        document.querySelectorAll('input, select, textarea').forEach(el => {
            el.addEventListener('change', () => this.markUnsaved());
        });

        // Warn on page leave
        window.addEventListener('beforeunload', (e) => {
            if (this.hasUnsavedChanges) {
                e.preventDefault();
                e.returnValue = '';
            }
        });
    },

    markUnsaved() {
        this.hasUnsavedChanges = true;
        document.body.classList.add('has-unsaved-changes');
    },

    markSaved() {
        this.hasUnsavedChanges = false;
        document.body.classList.remove('has-unsaved-changes');
    },

    async loadPreviewData() {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/preview`);
            const data = await response.json();
            if (data.success) {
                this.previewData = data;
                this.updatePreview();
            }
        } catch (error) {
            console.error('Error loading preview data:', error);
        }
    },

    async loadAssets() {
        try {
            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/assets`);
            const data = await response.json();
            if (data.success) {
                this.assets = data.assets || {};
                this.updateAssetPreviews();
            }
        } catch (error) {
            console.error('Error loading assets:', error);
        }
    },

    updateAssetPreviews() {
        // Update asset preview cards in Appearance tab
        Object.entries(this.assets).forEach(([assetType, asset]) => {
            const card = document.querySelector(`.asset-upload-card[data-asset-type="${assetType}"]`);
            if (card && asset && asset.url) {
                const preview = card.querySelector('.asset-preview');
                if (preview) {
                    // Replace placeholder with actual image
                    preview.innerHTML = `
                        <img src="${asset.url}" alt="${assetType}" id="asset-preview-${assetType}">
                        <span class="badge bg-success position-absolute top-0 end-0 m-1"><i class="ti ti-check"></i></span>
                    `;
                }
            }
        });

        // Update live preview card assets
        this.updateLivePreviewAssets();
    },

    updateLivePreviewAssets() {
        // Update Apple preview assets
        // Logo is optional - hide if not uploaded, show if uploaded
        const previewLogo = document.getElementById('preview-logo');
        const previewStrip = document.getElementById('preview-strip');

        if (previewLogo) {
            if (this.assets.logo && this.assets.logo.url) {
                previewLogo.classList.remove('d-none');
                previewLogo.classList.add('d-flex');
                previewLogo.innerHTML = `<img src="${this.assets.logo.url}" alt="Logo">`;
            } else {
                // No logo - hide the logo area entirely for cleaner look
                previewLogo.classList.add('d-none');
                previewLogo.classList.remove('d-flex');
                previewLogo.innerHTML = '';
            }
        }

        // Strip image is now positioned absolutely behind the primary field overlay
        if (previewStrip) {
            // Find or create the strip image element
            let stripImg = previewStrip.querySelector('.pass-strip-image');
            const primaryOverlay = previewStrip.querySelector('.pass-primary-field-overlay');

            if (this.assets.strip && this.assets.strip.url) {
                if (!stripImg) {
                    stripImg = document.createElement('img');
                    stripImg.className = 'pass-strip-image';
                    stripImg.alt = 'Strip';
                    // Insert before the overlay
                    if (primaryOverlay) {
                        previewStrip.insertBefore(stripImg, primaryOverlay);
                    } else {
                        previewStrip.appendChild(stripImg);
                    }
                }
                stripImg.src = this.assets.strip.url;
            } else if (stripImg) {
                stripImg.remove();
            }
        }

        // Update Google preview logo
        const googleLogo = document.getElementById('preview-google-logo');
        if (googleLogo) {
            const googleLogoUrl = document.getElementById('google_logo_url')?.value;
            if (googleLogoUrl) {
                googleLogo.innerHTML = `<img src="${googleLogoUrl}" alt="Logo">`;
            } else if (this.assets.logo && this.assets.logo.url) {
                // Fall back to Apple logo
                googleLogo.innerHTML = `<img src="${this.assets.logo.url}" alt="Logo">`;
            }
        }
    },

    setPreviewPlatform(platform) {
        this.currentPlatform = platform;

        // Update button states
        document.querySelectorAll('[data-platform]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.platform === platform);
        });

        // Show/hide preview containers
        const applePreview = document.getElementById('apple-preview');
        const googlePreview = document.getElementById('google-preview');

        if (applePreview && googlePreview) {
            if (platform === 'apple') {
                applePreview.classList.remove('d-none');
                googlePreview.classList.add('d-none');
            } else {
                applePreview.classList.add('d-none');
                googlePreview.classList.remove('d-none');
            }
        }
    },

    /**
     * Update UI when pass style is changed
     * Shows/hides appropriate assets and updates preview layout
     */
    updatePassStylePreview() {
        const passStyle = document.querySelector('input[name="apple_pass_style"]:checked')?.value || 'generic';

        // Update style descriptions
        document.querySelectorAll('[id^="style-desc-"]').forEach(el => el.classList.add('d-none'));
        const descEl = document.getElementById(`style-desc-${passStyle}`);
        if (descEl) descEl.classList.remove('d-none');

        // Show/hide appropriate asset containers
        const stripWrapper = document.getElementById('asset-strip-wrapper');
        const thumbnailWrapper = document.getElementById('asset-thumbnail-wrapper');

        if (passStyle === 'generic') {
            // Generic uses thumbnail, not strip
            if (stripWrapper) stripWrapper.classList.add('d-none');
            if (thumbnailWrapper) thumbnailWrapper.classList.remove('d-none');
        } else {
            // storeCard and eventTicket use strip, not thumbnail
            if (stripWrapper) stripWrapper.classList.remove('d-none');
            if (thumbnailWrapper) thumbnailWrapper.classList.add('d-none');
        }

        // Update the preview card layout
        this.updatePreviewForPassStyle(passStyle);
    },

    /**
     * Update the preview card to reflect the selected pass style
     *
     * Layout differences:
     * - generic: Thumbnail in header, primary fields in separate section, no strip
     * - storeCard: Strip with primary field OVERLAID on it
     * - eventTicket: Strip displayed CLEAN (no overlay), fields below, notch at top
     */
    updatePreviewForPassStyle(passStyle) {
        const appleCard = document.getElementById('pass-preview');
        if (!appleCard) return;

        // Remove old style classes and add new one
        appleCard.classList.remove('pass-style-generic', 'pass-style-storeCard', 'pass-style-eventTicket');
        appleCard.classList.add(`pass-style-${passStyle}`);
        appleCard.setAttribute('data-pass-style', passStyle);

        // Get all the dynamic elements
        const stripArea = appleCard.querySelector('.pass-strip-area');
        const thumbnail = appleCard.querySelector('.pass-thumbnail');
        const primarySection = appleCard.querySelector('.pass-primary-fields-section');
        const primaryOverlay = appleCard.querySelector('.pass-primary-field-overlay');
        const notch = appleCard.querySelector('.pass-notch');

        if (passStyle === 'generic') {
            // Generic: hide strip, show thumbnail in header, show primary section below
            if (stripArea) stripArea.classList.add('d-none');
            if (thumbnail) thumbnail.classList.remove('d-none');
            if (primarySection) primarySection.classList.remove('d-none');
            if (primaryOverlay) primaryOverlay.classList.add('d-none');
            if (notch) notch.classList.add('d-none');
        } else if (passStyle === 'eventTicket') {
            // EventTicket: show strip CLEAN (no overlay), hide thumbnail, show notch
            // Fields go in secondary/auxiliary below the strip
            if (stripArea) {
                stripArea.classList.remove('d-none');
                stripArea.classList.add('d-flex');
            }
            if (thumbnail) thumbnail.classList.add('d-none');
            if (primarySection) primarySection.classList.add('d-none');
            if (primaryOverlay) primaryOverlay.classList.add('d-none'); // No overlay on eventTicket!
            if (notch) notch.classList.remove('d-none');
        } else {
            // storeCard: show strip WITH primary overlay, hide thumbnail, hide notch
            if (stripArea) {
                stripArea.classList.remove('d-none');
                stripArea.classList.add('d-flex');
            }
            if (thumbnail) thumbnail.classList.add('d-none');
            if (primarySection) primarySection.classList.add('d-none');
            if (primaryOverlay) primaryOverlay.classList.remove('d-none'); // Overlay visible for storeCard
            if (notch) notch.classList.add('d-none');
        }
    },

    openAssetCropper(assetType) {
        if (typeof AssetCropper !== 'undefined') {
            // Pass existing asset URL so cropper knows to show delete button
            const existingUrl = this.assets[assetType]?.url || null;
            AssetCropper.open(assetType, this.passTypeCode, existingUrl);
        } else {
            console.error('AssetCropper not loaded');
            this.showToast('Asset cropper not available', 'error');
        }
    },

    onAssetUploaded(assetType, assetData) {
        // Update local assets cache
        this.assets[assetType] = assetData;

        // Update the preview cards
        this.updateAssetPreviews();

        // Refresh live preview
        this.updateLivePreviewAssets();
    },

    onAssetDeleted(assetType) {
        // Remove from local assets cache
        delete this.assets[assetType];

        // Update the preview cards to show placeholder
        const previewCard = document.querySelector(`[data-asset-type="${assetType}"]`);
        if (previewCard) {
            const previewArea = previewCard.querySelector('.asset-preview');
            if (previewArea) {
                previewArea.innerHTML = `
                    <div class="asset-placeholder">
                        <i class="ti ti-photo fs-1"></i>
                    </div>
                `;
            }
            // Remove the uploaded badge
            const badge = previewCard.querySelector('.badge.bg-success');
            if (badge) badge.remove();
        }

        // Refresh live preview
        this.updateLivePreviewAssets();
    },

    updateGooglePreview() {
        const heroUrl = document.getElementById('google_hero_image_url')?.value;
        const logoUrl = document.getElementById('google_logo_url')?.value;

        const heroPreview = document.getElementById('preview-google-hero');
        const logoPreview = document.getElementById('preview-google-logo');

        if (heroPreview) {
            if (heroUrl) {
                // Note: Dynamic background image URL, kept as inline style
                heroPreview.style.backgroundImage = `url('${heroUrl}')`;
                heroPreview.innerHTML = '';
            } else {
                heroPreview.style.backgroundImage = '';
                heroPreview.innerHTML = `
                    <div class="google-hero-placeholder">
                        <i class="ti ti-photo-plus"></i>
                        <span>Hero Image</span>
                    </div>
                `;
            }
        }

        if (logoPreview) {
            if (logoUrl) {
                logoPreview.innerHTML = `<img src="${logoUrl}" alt="Logo">`;
            } else if (this.assets.logo && this.assets.logo.url) {
                logoPreview.innerHTML = `<img src="${this.assets.logo.url}" alt="Logo">`;
            } else {
                logoPreview.innerHTML = `
                    <div class="google-logo-placeholder">
                        <i class="ti ti-building"></i>
                    </div>
                `;
            }
        }
    },

    updatePreview() {
        // Update Apple preview card
        const appleCard = document.getElementById('pass-preview');
        if (appleCard && this.previewData) {
            const pt = this.previewData.pass_type;

            // Note: Dynamic theme colors from database, kept as inline styles
            appleCard.style.backgroundColor = pt.background_color;
            appleCard.style.color = pt.foreground_color;

            // Update label colors
            appleCard.querySelectorAll('.pass-field-label').forEach(el => {
                el.style.color = pt.label_color;
            });

            // Update logo text
            const logoText = document.getElementById('preview-logo-text');
            if (logoText) logoText.textContent = pt.logo_text;
        }

        // Update Google preview card
        const googleContent = document.querySelector('.google-pass-content');
        if (googleContent && this.previewData) {
            const pt = this.previewData.pass_type;
            // Note: Dynamic theme colors from database, kept as inline styles
            googleContent.style.backgroundColor = pt.background_color;
            googleContent.style.color = pt.foreground_color;

            googleContent.querySelectorAll('.google-info-label, .google-card-subtitle').forEach(el => {
                el.style.color = pt.label_color;
            });
        }

        // Update assets in live preview
        this.updateLivePreviewAssets();
    },

    /**
     * Update preview fields from FieldsManager data
     * Called when fields are added, removed, or modified
     */
    updatePreviewFields(frontFields, sampleData) {
        if (!frontFields || !sampleData) return;

        // Group fields by location
        const fieldsByLocation = {
            header: frontFields.filter(f => f.field_location === 'header' && f.is_visible !== false),
            primary: frontFields.filter(f => f.field_location === 'primary' && f.is_visible !== false),
            secondary: frontFields.filter(f => f.field_location === 'secondary' && f.is_visible !== false),
            auxiliary: frontFields.filter(f => f.field_location === 'auxiliary' && f.is_visible !== false)
        };

        // Get current label color
        const labelColor = document.getElementById('label_color')?.value ||
                          this.previewData?.pass_type?.label_color ||
                          (typeof ECSTheme !== 'undefined' ? ECSTheme.getColor('neutral-50') : '#999999');

        // Helper to resolve template value
        const resolveValue = (field) => {
            if (!field.value_template) return field.default_value || '';
            let value = field.value_template;
            for (const [key, val] of Object.entries(sampleData)) {
                value = value.replace(new RegExp('\\{\\{' + key + '\\}\\}', 'g'), val || '');
            }
            return value;
        };

        // Update Apple Preview
        this.updateApplePreviewFields(fieldsByLocation, labelColor, resolveValue);

        // Update Google Preview
        this.updateGooglePreviewFields(fieldsByLocation, labelColor, resolveValue);
    },

    updateApplePreviewFields(fieldsByLocation, labelColor, resolveValue) {
        const appleCard = document.getElementById('pass-preview');
        if (!appleCard) return;

        // Update Header Fields (right side of header row)
        const headerRow = appleCard.querySelector('.pass-header');
        let headerFieldsContainer = appleCard.querySelector('.pass-header-fields');

        if (fieldsByLocation.header.length > 0) {
            if (!headerFieldsContainer) {
                // Create header fields container if it doesn't exist
                headerFieldsContainer = document.createElement('div');
                headerFieldsContainer.className = 'pass-header-fields';
                headerFieldsContainer.id = 'preview-header-fields';
                // Insert before thumbnail (if exists) or at end of header
                const thumbnail = headerRow.querySelector('.pass-thumbnail');
                if (thumbnail) {
                    headerRow.insertBefore(headerFieldsContainer, thumbnail);
                } else {
                    headerRow.appendChild(headerFieldsContainer);
                }
            }
            headerFieldsContainer.classList.remove('d-none');
            headerFieldsContainer.classList.add('d-flex');
            headerFieldsContainer.innerHTML = fieldsByLocation.header.map(field => `
                <div class="pass-header-field">
                    <div class="pass-field-label pass-field-label--dynamic" data-label-color="${labelColor}">${field.label || ''}</div>
                    <div class="pass-field-value">${resolveValue(field)}</div>
                </div>
            `).join('');
            // Note: Dynamic label colors from configuration, kept as inline styles
            headerFieldsContainer.querySelectorAll('.pass-field-label--dynamic').forEach(el => {
                el.style.color = el.dataset.labelColor;
            });
        } else if (headerFieldsContainer) {
            headerFieldsContainer.classList.add('d-none');
            headerFieldsContainer.classList.remove('d-flex');
            headerFieldsContainer.innerHTML = '';
        }

        // Update Primary Field (overlaid on strip area for storeCard, or in primary section for generic)
        const passStyle = appleCard.getAttribute('data-pass-style') || 'generic';
        let primaryOverlay = appleCard.querySelector('.pass-primary-field-overlay');
        let primarySection = appleCard.querySelector('.pass-primary-fields-section');

        if (primaryOverlay) {
            // For storeCard, show primary in overlay (eventTicket doesn't use primary overlay)
            if (passStyle === 'storeCard' && fieldsByLocation.primary.length > 0) {
                const field = fieldsByLocation.primary[0];
                primaryOverlay.innerHTML = `
                    <div class="pass-field-label pass-field-label--dynamic" data-label-color="${labelColor}">${field.label || ''}</div>
                    <div class="pass-field-value">${resolveValue(field)}</div>
                `;
                // Note: Dynamic label colors from configuration, kept as inline styles
                const labelEl = primaryOverlay.querySelector('.pass-field-label--dynamic');
                if (labelEl) labelEl.style.color = labelEl.dataset.labelColor;
            } else if (passStyle === 'storeCard') {
                primaryOverlay.innerHTML = `
                    <div class="pass-field-label pass-field-label--dynamic pass-field-value--muted" data-label-color="${labelColor}">MEMBER</div>
                    <div class="pass-field-value pass-field-value--muted">No primary field</div>
                `;
                // Note: Dynamic label colors from configuration, kept as inline styles
                const labelEl = primaryOverlay.querySelector('.pass-field-label--dynamic');
                if (labelEl) labelEl.style.color = labelEl.dataset.labelColor;
            }
        }

        if (primarySection) {
            // For generic, show primary in separate section
            if (passStyle === 'generic' && fieldsByLocation.primary.length > 0) {
                primarySection.innerHTML = fieldsByLocation.primary.map(field => `
                    <div class="pass-field primary-field">
                        <div class="pass-field-label pass-field-label--dynamic" data-label-color="${labelColor}">${field.label || ''}</div>
                        <div class="pass-field-value">${resolveValue(field)}</div>
                    </div>
                `).join('');
                // Note: Dynamic label colors from configuration, kept as inline styles
                primarySection.querySelectorAll('.pass-field-label--dynamic').forEach(el => {
                    el.style.color = el.dataset.labelColor;
                });
            } else if (passStyle === 'generic') {
                primarySection.innerHTML = `
                    <div class="pass-field primary-field">
                        <div class="pass-field-label pass-field-label--dynamic pass-field-value--muted" data-label-color="${labelColor}">MEMBER</div>
                        <div class="pass-field-value pass-field-value--muted">No primary field</div>
                    </div>
                `;
                // Note: Dynamic label colors from configuration, kept as inline styles
                const labelEl = primarySection.querySelector('.pass-field-label--dynamic');
                if (labelEl) labelEl.style.color = labelEl.dataset.labelColor;
            }
        }

        // Update Secondary/Auxiliary Fields (below strip)
        // For eventTicket, also include primary fields here since they don't go on strip
        let secondaryContainer = appleCard.querySelector('.pass-secondary-fields');
        let allSecondary = [...fieldsByLocation.secondary, ...fieldsByLocation.auxiliary];

        // For eventTicket, primary fields move to secondary
        if (passStyle === 'eventTicket') {
            allSecondary = [...fieldsByLocation.primary, ...allSecondary];
        }

        if (allSecondary.length > 0) {
            if (!secondaryContainer) {
                secondaryContainer = document.createElement('div');
                secondaryContainer.className = 'pass-secondary-fields';
                const stripArea = appleCard.querySelector('.pass-strip-area');
                const primarySec = appleCard.querySelector('.pass-primary-fields-section');
                if (stripArea && !stripArea.classList.contains('d-none')) {
                    stripArea.after(secondaryContainer);
                } else if (primarySec) {
                    primarySec.after(secondaryContainer);
                }
            }
            secondaryContainer.innerHTML = allSecondary.map(field => `
                <div class="pass-field">
                    <div class="pass-field-label pass-field-label--dynamic" data-label-color="${labelColor}">${field.label || ''}</div>
                    <div class="pass-field-value">${resolveValue(field)}</div>
                </div>
            `).join('');
            // Note: Dynamic label colors from configuration, kept as inline styles
            secondaryContainer.querySelectorAll('.pass-field-label--dynamic').forEach(el => {
                el.style.color = el.dataset.labelColor;
            });
        } else if (secondaryContainer) {
            secondaryContainer.remove();
        }
    },

    updateGooglePreviewFields(fieldsByLocation, labelColor, resolveValue) {
        const googleContent = document.querySelector('.google-pass-content');
        if (!googleContent) return;

        // Update Primary Value
        let primaryValue = googleContent.querySelector('.google-primary-value');
        if (fieldsByLocation.primary.length > 0) {
            const field = fieldsByLocation.primary[0];
            if (!primaryValue) {
                primaryValue = document.createElement('div');
                primaryValue.className = 'google-primary-value';
                const header = googleContent.querySelector('.google-header');
                if (header) header.after(primaryValue);
            }
            primaryValue.classList.remove('text-muted');
            primaryValue.textContent = resolveValue(field);
        } else if (primaryValue) {
            primaryValue.classList.add('text-muted');
            primaryValue.textContent = 'No primary field configured';
        }

        // Update Info Rows
        let infoRows = googleContent.querySelector('.google-info-rows');
        const allSecondary = [...fieldsByLocation.secondary, ...fieldsByLocation.auxiliary];

        if (allSecondary.length > 0) {
            if (!infoRows) {
                infoRows = document.createElement('div');
                infoRows.className = 'google-info-rows';
                const primaryEl = googleContent.querySelector('.google-primary-value');
                if (primaryEl) primaryEl.after(infoRows);
            }
            infoRows.innerHTML = allSecondary.map(field => `
                <div class="google-info-row">
                    <span class="google-info-label pass-field-label--dynamic" data-label-color="${labelColor}">${field.label || ''}</span>
                    <span class="google-info-value">${resolveValue(field)}</span>
                </div>
            `).join('');
            // Note: Dynamic label colors from configuration, kept as inline styles
            infoRows.querySelectorAll('.pass-field-label--dynamic').forEach(el => {
                el.style.color = el.dataset.labelColor;
            });
        } else if (infoRows) {
            infoRows.remove();
        }
    },

    updatePreviewFromForm() {
        // Get form values
        const bgColor = document.getElementById('background_color')?.value;
        const fgColor = document.getElementById('foreground_color')?.value;
        const lblColor = document.getElementById('label_color')?.value;
        const logoText = document.getElementById('logo_text')?.value;

        // Update Apple preview
        const appleCard = document.getElementById('pass-preview');
        if (appleCard) {
            // Note: Dynamic theme colors from form inputs, kept as inline styles
            if (bgColor) appleCard.style.backgroundColor = bgColor;
            if (fgColor) appleCard.style.color = fgColor;
            if (lblColor) {
                appleCard.querySelectorAll('.pass-field-label').forEach(el => {
                    el.style.color = lblColor;
                });
            }
            if (logoText !== undefined) {
                const logoEl = document.getElementById('preview-logo-text');
                if (logoEl) logoEl.textContent = logoText;
            }
        }

        // Update Google preview
        const googleContent = document.querySelector('.google-pass-content');
        if (googleContent) {
            // Note: Dynamic theme colors from form inputs, kept as inline styles
            if (bgColor) googleContent.style.backgroundColor = bgColor;
            if (fgColor) googleContent.style.color = fgColor;
            if (lblColor) {
                googleContent.querySelectorAll('.google-info-label, .google-card-subtitle').forEach(el => {
                    el.style.color = lblColor;
                });
            }
        }
    },

    updateBarcodePreview() {
        const suppressBarcode = document.getElementById('suppress_barcode')?.checked;

        // Update Apple preview
        const appleBarcodeArea = document.querySelector('#apple-preview .pass-barcode-area');
        if (appleBarcodeArea) {
            appleBarcodeArea.classList.toggle('d-none', suppressBarcode);
        }

        // Update Google preview
        const googleBarcodeArea = document.querySelector('#google-preview .google-barcode-area');
        if (googleBarcodeArea) {
            googleBarcodeArea.classList.toggle('d-none', suppressBarcode);
        }
    },

    initColorPickers() {
        // Initialize color picker inputs
        document.querySelectorAll('.color-input').forEach(input => {
            input.addEventListener('input', () => {
                this.updatePreviewFromForm();
                this.markUnsaved();
            });
        });
    },

    /**
     * Toggle logo visibility in the preview
     */
    toggleLogoVisibility() {
        const showLogo = document.getElementById('show_logo')?.checked ?? true;
        const previewLogo = document.getElementById('preview-logo');

        if (previewLogo) {
            if (showLogo && this.assets.logo && this.assets.logo.url) {
                previewLogo.classList.remove('d-none');
                previewLogo.classList.add('d-flex');
            } else {
                previewLogo.classList.add('d-none');
                previewLogo.classList.remove('d-flex');
            }
        }
    },

    async saveAppearance() {
        const form = document.getElementById('appearance-form');
        const formData = new FormData(form);
        const data = Object.fromEntries(formData);

        // Include Google Wallet URLs
        data.google_hero_image_url = document.getElementById('google_hero_image_url')?.value || '';
        data.google_logo_url = document.getElementById('google_logo_url')?.value || '';

        // Explicitly include checkbox values (checkboxes don't send value when unchecked)
        data.suppress_barcode = document.getElementById('suppress_barcode')?.checked || false;
        data.show_logo = document.getElementById('show_logo')?.checked ?? true;

        // Include pass style
        const passStyleRadio = document.querySelector('input[name="apple_pass_style"]:checked');
        data.apple_pass_style = passStyleRadio?.value || 'generic';

        try {
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') ||
                             document.querySelector('[name=csrf_token]')?.value || '';

            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/appearance`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify(data)
            });

            const result = await response.json();
            if (result.success) {
                this.showToast('Appearance saved successfully', 'success');
                this.markSaved();
            } else {
                this.showToast(result.error || 'Error saving appearance', 'error');
            }
        } catch (error) {
            console.error('Error saving appearance:', error);
            this.showToast('Error saving appearance', 'error');
        }
    },

    showToast(message, type = 'info') {
        if (typeof Swal !== 'undefined') {
            Swal.fire({
                toast: true,
                position: 'top-end',
                icon: type,
                title: message,
                showConfirmButton: false,
                timer: 3000
            });
        } else {
            alert(message);
        }
    },

    insertVariable(fieldId, variable) {
        const input = document.getElementById(fieldId);
        if (input) {
            const start = input.selectionStart;
            const end = input.selectionEnd;
            const text = input.value;
            const variableText = '{{' + variable + '}}';
            input.value = text.substring(0, start) + variableText + text.substring(end);
            input.focus();
            input.selectionStart = input.selectionEnd = start + variableText.length;
            this.markUnsaved();
        }
    }
};

// Export to window for ES module compatibility
window.PassStudio = PassStudio;

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    // Get pass type code from script tag data attribute
    const initScript = document.querySelector('script[data-pass-type-code]');
    if (initScript) {
        const passTypeCode = initScript.dataset.passTypeCode;
        PassStudio.init(passTypeCode);
    }
});
