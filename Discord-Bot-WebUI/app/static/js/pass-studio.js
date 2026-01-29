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

import { escapeHtml } from './utils/sanitize.js';

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

    _eventsRegistered: false,
    bindEvents() {
        // Only register once - ROOT CAUSE FIX: event delegation
        if (this._eventsRegistered) return;
        this._eventsRegistered = true;

        // Platform toggle handled by event delegation in event-delegation.js

        // Track changes - single delegated listener for all form elements
        document.addEventListener('change', (e) => {
            if (e.target.matches('input, select, textarea')) {
                this.markUnsaved();
            }
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
                    // Escape URLs to prevent XSS
                    const safeUrl = escapeHtml(asset.url);
                    const safeType = escapeHtml(assetType);
                    // Replace placeholder with actual image
                    preview.innerHTML = `
                        <img src="${safeUrl}" alt="${safeType}" id="asset-preview-${safeType}">
                        <span class="absolute top-1 right-1 bg-green-500 text-white rounded-full p-1">
                            <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 20 20">
                                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                            </svg>
                        </span>
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
                previewLogo.classList.remove('hidden');
                previewLogo.classList.add('flex');
                previewLogo.innerHTML = `<img src="${escapeHtml(this.assets.logo.url)}" alt="Logo">`;
            } else {
                // No logo - hide the logo area entirely for cleaner look
                previewLogo.classList.add('hidden');
                previewLogo.classList.remove('flex');
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
                googleLogo.innerHTML = `<img src="${escapeHtml(googleLogoUrl)}" alt="Logo">`;
            } else if (this.assets.logo && this.assets.logo.url) {
                // Fall back to Apple logo
                googleLogo.innerHTML = `<img src="${escapeHtml(this.assets.logo.url)}" alt="Logo">`;
            }
        }
    },

    setPreviewPlatform(platform) {
        this.currentPlatform = platform;

        // Update button states with proper Tailwind classes
        document.querySelectorAll('[data-platform]').forEach(btn => {
            const isActive = btn.dataset.platform === platform;
            // Toggle active/inactive Tailwind classes
            btn.classList.toggle('platform-toggle-active', isActive);
            btn.classList.toggle('text-primary-700', isActive);
            btn.classList.toggle('dark:text-primary-400', isActive);
            btn.classList.toggle('text-gray-700', !isActive);
            btn.classList.toggle('dark:text-gray-300', !isActive);
        });

        // Show/hide preview containers
        const applePreview = document.getElementById('apple-preview');
        const googlePreview = document.getElementById('google-preview');

        if (applePreview && googlePreview) {
            if (platform === 'apple') {
                applePreview.classList.remove('hidden');
                googlePreview.classList.add('hidden');
            } else {
                applePreview.classList.add('hidden');
                googlePreview.classList.remove('hidden');
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
        document.querySelectorAll('[id^="style-desc-"]').forEach(el => el.classList.add('hidden'));
        const descEl = document.getElementById(`style-desc-${passStyle}`);
        if (descEl) descEl.classList.remove('hidden');

        // Show/hide appropriate asset containers
        const stripWrapper = document.getElementById('asset-strip-wrapper');
        const thumbnailWrapper = document.getElementById('asset-thumbnail-wrapper');

        if (passStyle === 'generic') {
            // Generic uses thumbnail, not strip
            if (stripWrapper) stripWrapper.classList.add('hidden');
            if (thumbnailWrapper) thumbnailWrapper.classList.remove('hidden');
        } else {
            // storeCard and eventTicket use strip, not thumbnail
            if (stripWrapper) stripWrapper.classList.remove('hidden');
            if (thumbnailWrapper) thumbnailWrapper.classList.add('hidden');
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
            if (stripArea) stripArea.classList.add('hidden');
            if (thumbnail) thumbnail.classList.remove('hidden');
            if (primarySection) primarySection.classList.remove('hidden');
            if (primaryOverlay) primaryOverlay.classList.add('hidden');
            if (notch) notch.classList.add('hidden');
        } else if (passStyle === 'eventTicket') {
            // EventTicket: show strip CLEAN (no overlay), hide thumbnail, show notch
            // Fields go in secondary/auxiliary below the strip
            if (stripArea) {
                stripArea.classList.remove('hidden');
                stripArea.classList.add('flex');
            }
            if (thumbnail) thumbnail.classList.add('hidden');
            if (primarySection) primarySection.classList.add('hidden');
            if (primaryOverlay) primaryOverlay.classList.add('hidden'); // No overlay on eventTicket!
            if (notch) notch.classList.remove('hidden');
        } else {
            // storeCard: show strip WITH primary overlay, hide thumbnail, hide notch
            if (stripArea) {
                stripArea.classList.remove('hidden');
                stripArea.classList.add('flex');
            }
            if (thumbnail) thumbnail.classList.add('hidden');
            if (primarySection) primarySection.classList.add('hidden');
            if (primaryOverlay) primaryOverlay.classList.remove('hidden'); // Overlay visible for storeCard
            if (notch) notch.classList.add('hidden');
        }
    },

    openAssetCropper(assetType) {
        if (typeof window.AssetCropper !== 'undefined') {
            // Pass existing asset URL so cropper knows to show delete button
            const existingUrl = this.assets[assetType]?.url || null;
            window.AssetCropper.open(assetType, this.passTypeCode, existingUrl);
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
                    <div class="asset-placeholder flex items-center justify-center text-gray-400">
                        <svg class="w-8 h-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                        </svg>
                    </div>
                `;
            }
            // Remove the uploaded badge (Tailwind version)
            const badge = previewCard.querySelector('.bg-green-500');
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
                    <div class="google-hero-placeholder text-center text-gray-400">
                        <svg class="w-8 h-8 mx-auto mb-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>
                        </svg>
                        <span class="text-xs">Hero Image</span>
                    </div>
                `;
            }
        }

        if (logoPreview) {
            if (logoUrl) {
                logoPreview.innerHTML = `<img src="${escapeHtml(logoUrl)}" alt="Logo">`;
            } else if (this.assets.logo && this.assets.logo.url) {
                logoPreview.innerHTML = `<img src="${escapeHtml(this.assets.logo.url)}" alt="Logo">`;
            } else {
                logoPreview.innerHTML = `
                    <div class="google-logo-placeholder text-gray-400 flex items-center justify-center">
                        <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4"/>
                        </svg>
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
                          (typeof window.ECSTheme !== 'undefined' ? window.ECSTheme.getColor('neutral-50') : '#999999');

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
            headerFieldsContainer.classList.remove('hidden');
            headerFieldsContainer.classList.add('flex');
            headerFieldsContainer.innerHTML = fieldsByLocation.header.map(field => `
                <div class="pass-header-field">
                    <div class="pass-field-label pass-field-label--dynamic" data-label-color="${escapeHtml(labelColor)}">${escapeHtml(field.label || '')}</div>
                    <div class="pass-field-value">${escapeHtml(resolveValue(field))}</div>
                </div>
            `).join('');
            // Note: Dynamic label colors from configuration, kept as inline styles
            headerFieldsContainer.querySelectorAll('.pass-field-label--dynamic').forEach(el => {
                el.style.color = el.dataset.labelColor;
            });
        } else if (headerFieldsContainer) {
            headerFieldsContainer.classList.add('hidden');
            headerFieldsContainer.classList.remove('flex');
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
                    <div class="pass-field-label pass-field-label--dynamic" data-label-color="${escapeHtml(labelColor)}">${escapeHtml(field.label || '')}</div>
                    <div class="pass-field-value">${escapeHtml(resolveValue(field))}</div>
                `;
                // Note: Dynamic label colors from configuration, kept as inline styles
                const labelEl = primaryOverlay.querySelector('.pass-field-label--dynamic');
                if (labelEl) labelEl.style.color = labelEl.dataset.labelColor;
            } else if (passStyle === 'storeCard') {
                primaryOverlay.innerHTML = `
                    <div class="pass-field-label pass-field-label--dynamic pass-field-value--muted" data-label-color="${escapeHtml(labelColor)}">MEMBER</div>
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
                        <div class="pass-field-label pass-field-label--dynamic" data-label-color="${escapeHtml(labelColor)}">${escapeHtml(field.label || '')}</div>
                        <div class="pass-field-value">${escapeHtml(resolveValue(field))}</div>
                    </div>
                `).join('');
                // Note: Dynamic label colors from configuration, kept as inline styles
                primarySection.querySelectorAll('.pass-field-label--dynamic').forEach(el => {
                    el.style.color = el.dataset.labelColor;
                });
            } else if (passStyle === 'generic') {
                primarySection.innerHTML = `
                    <div class="pass-field primary-field">
                        <div class="pass-field-label pass-field-label--dynamic pass-field-value--muted" data-label-color="${escapeHtml(labelColor)}">MEMBER</div>
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
                if (stripArea && !stripArea.classList.contains('hidden')) {
                    stripArea.after(secondaryContainer);
                } else if (primarySec) {
                    primarySec.after(secondaryContainer);
                }
            }
            secondaryContainer.innerHTML = allSecondary.map(field => `
                <div class="pass-field">
                    <div class="pass-field-label pass-field-label--dynamic" data-label-color="${escapeHtml(labelColor)}">${escapeHtml(field.label || '')}</div>
                    <div class="pass-field-value">${escapeHtml(resolveValue(field))}</div>
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
            primaryValue.classList.remove('text-gray-500', 'dark:text-gray-400');
            // Using textContent here is safe (no HTML injection possible)
            primaryValue.textContent = resolveValue(field);
        } else if (primaryValue) {
            primaryValue.classList.add('text-gray-500', 'dark:text-gray-400');
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
                    <span class="google-info-label pass-field-label--dynamic" data-label-color="${escapeHtml(labelColor)}">${escapeHtml(field.label || '')}</span>
                    <span class="google-info-value">${escapeHtml(resolveValue(field))}</span>
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
            appleBarcodeArea.classList.toggle('hidden', suppressBarcode);
        }

        // Update Google preview
        const googleBarcodeArea = document.querySelector('#google-preview .google-barcode-area');
        if (googleBarcodeArea) {
            googleBarcodeArea.classList.toggle('hidden', suppressBarcode);
        }
    },

    _colorPickersRegistered: false,
    initColorPickers() {
        // Only register once - ROOT CAUSE FIX: event delegation
        if (this._colorPickersRegistered) return;
        this._colorPickersRegistered = true;

        // Single delegated listener for all color inputs
        document.addEventListener('input', (e) => {
            if (e.target.matches('.color-input')) {
                this.updatePreviewFromForm();
                this.markUnsaved();
            }
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
                previewLogo.classList.remove('hidden');
                previewLogo.classList.add('flex');
            } else {
                previewLogo.classList.add('hidden');
                previewLogo.classList.remove('flex');
            }
        }
    },

    /**
     * Set button loading state
     */
    setButtonLoading(button, loading) {
        if (!button) return;
        const saveIcon = button.querySelector('.save-icon, .publish-icon');
        const loadingIcon = button.querySelector('.loading-icon');
        const btnText = button.querySelector('.btn-text');

        if (loading) {
            button.disabled = true;
            button.classList.add('opacity-75', 'cursor-not-allowed');
            if (saveIcon) saveIcon.classList.add('hidden');
            if (loadingIcon) loadingIcon.classList.remove('hidden');
            if (btnText) btnText.textContent = 'Saving...';
        } else {
            button.disabled = false;
            button.classList.remove('opacity-75', 'cursor-not-allowed');
            if (saveIcon) saveIcon.classList.remove('hidden');
            if (loadingIcon) loadingIcon.classList.add('hidden');
        }
    },

    async saveAppearance(buttonElement) {
        const button = buttonElement || document.getElementById('save-appearance-btn');
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

        // Show loading state
        this.setButtonLoading(button, true);
        const btnText = button?.querySelector('.btn-text');

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
                this.showToast('Changes saved! Click "Publish to Passes" to push updates to devices.', 'success');
                this.markSaved();
            } else {
                this.showToast(result.error || 'Error saving appearance', 'error');
            }
        } catch (error) {
            console.error('Error saving appearance:', error);
            this.showToast('Error saving appearance', 'error');
        } finally {
            this.setButtonLoading(button, false);
            if (btnText) btnText.textContent = 'Save Changes';
        }
    },

    async publishChanges(buttonElement) {
        const button = buttonElement || document.getElementById('publish-changes-btn');

        // First, get the pass count for confirmation
        try {
            const countResponse = await fetch(`/admin/wallet/studio/${this.passTypeCode}/pass-count`);
            const countData = await countResponse.json();

            if (!countData.success) {
                this.showToast('Error getting pass count', 'error');
                return;
            }

            const passCount = countData.count;
            const passTypeName = countData.pass_type_name;

            // Show confirmation dialog
            const confirmResult = await window.Swal.fire({
                title: 'Publish Changes?',
                html: passCount > 0
                    ? `This will push updates to <strong>${passCount}</strong> active ${passTypeName} passes.<br><br>Users will see the updated design on their devices.`
                    : 'There are no active passes to update.',
                icon: passCount > 0 ? 'question' : 'info',
                showCancelButton: passCount > 0,
                confirmButtonText: passCount > 0 ? 'Publish Now' : 'OK',
                cancelButtonText: 'Cancel',
                confirmButtonColor: '#16a34a',
                reverseButtons: true
            });

            if (!confirmResult.isConfirmed || passCount === 0) {
                return;
            }

            // Show loading state
            this.setButtonLoading(button, true);
            const btnText = button?.querySelector('.btn-text');
            if (btnText) btnText.textContent = 'Publishing...';

            // Perform the publish
            const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') ||
                             document.querySelector('[name=csrf_token]')?.value || '';

            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/publish`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            });

            const result = await response.json();
            if (result.success) {
                this.showToast(result.message || 'Changes published successfully!', 'success');
            } else {
                this.showToast(result.error || 'Error publishing changes', 'error');
            }
        } catch (error) {
            console.error('Error publishing changes:', error);
            this.showToast('Error publishing changes', 'error');
        } finally {
            this.setButtonLoading(button, false);
            const btnText = button?.querySelector('.btn-text');
            if (btnText) btnText.textContent = 'Publish to Passes';
        }
    },

    showToast(message, type = 'info') {
        if (typeof window.Swal !== 'undefined') {
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

import { InitSystem } from './init-system.js';

let _passStudioInitialized = false;

function initPassStudio() {
    if (_passStudioInitialized) return;

    // Get pass type code from script tag data attribute
    const initScript = document.querySelector('script[data-pass-type-code]');
    if (!initScript) return;

    _passStudioInitialized = true;
    const passTypeCode = initScript.dataset.passTypeCode;
    window.PassStudio.init(passTypeCode);
}

window.InitSystem.register('pass-studio', initPassStudio, {
    priority: 30,
    reinitializable: false,
    description: 'Pass studio wallet management'
});

// Fallback
// window.InitSystem handles initialization
