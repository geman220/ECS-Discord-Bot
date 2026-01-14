/**
 * Pass Studio Fields Manager
 *
 * Extracted from inline scripts in fields_tab.html
 * Handles all field operations in Pass Studio including:
 * - Field creation, editing, deletion
 * - Drag-and-drop reordering with SortableJS
 * - Location management (primary, secondary, auxiliary, header, back)
 * - Preview updates
 */

import { InitSystem } from './init-system.js';
import { ModalManager } from './modal-manager.js';
import { escapeHtml } from './utils/sanitize.js';

/**
 * Fields Manager - Handles all field operations in Pass Studio
 */
const FieldsManager = {
    // State
    frontFields: [],
    backFields: [],
    templateVariables: [],
    sampleData: {},
    sortableInstances: [],
    addFieldModal: null,
    passTypeCode: '',

    // Field limits per location - StoreCard specific
    limits: {
        primary: 1,
        secondaryAuxiliary: 4,
        header: 3,
        back: Infinity
    },

    /**
     * Initialize the fields manager
     */
    init(frontFields, backFields, templateVariables, sampleData, passTypeCode) {
        this.frontFields = frontFields || [];
        this.backFields = backFields || [];
        this.templateVariables = templateVariables || [];
        this.sampleData = sampleData || {};
        this.passTypeCode = passTypeCode || '';

        // Initialize modal
        const modalEl = document.getElementById('addFieldModal');
        if (modalEl) {
            this.addFieldModal = ModalManager.getInstance('addFieldModal');
        }

        // Render all fields
        this.renderAllFields();

        // Initialize sortable containers
        this.initSortable();

        // Update limit counters
        this.updateLimitCounters();

        // Update preview with initial field data
        this.notifyPreviewUpdate();

        // Bind event handlers
        this.bindEventHandlers();

        console.log('FieldsManager initialized', { front: this.frontFields.length, back: this.backFields.length });
    },

    /**
     * Bind event handlers to DOM elements
     */
    bindEventHandlers() {
        // Variable select change handler for static text option
        document.getElementById('add-field-variable')?.addEventListener('change', (e) => {
            const staticInput = document.getElementById('add-field-static');
            if (e.target.value === '__static__') {
                staticInput.classList.remove('hidden');
            } else {
                staticInput.classList.add('hidden');
            }
        });

        // Initialize defaults button
        document.querySelector('.js-initialize-defaults')?.addEventListener('click', () => {
            this.initializeDefaults();
        });

        // Add field buttons
        document.querySelector('.js-add-front-field')?.addEventListener('click', () => {
            this.openAddFieldModal('front');
        });

        document.querySelector('.js-add-back-field')?.addEventListener('click', () => {
            this.openAddFieldModal('back');
        });

        // Reset and save buttons
        document.querySelector('.js-reset-fields')?.addEventListener('click', () => {
            this.resetFields();
        });

        document.querySelector('.js-save-fields')?.addEventListener('click', () => {
            this.saveFields();
        });

        // Create field button in modal
        document.querySelector('.js-create-field')?.addEventListener('click', () => {
            this.createField();
        });

        // Insert variable buttons in add modal
        document.querySelectorAll('.js-insert-variable-add').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const varName = btn.dataset.variableName;
                this.insertVariableInAdd(varName);
            });
        });
    },

    /**
     * Render all fields to their containers
     */
    renderAllFields() {
        // Clear all containers
        ['primary', 'secondary', 'auxiliary', 'header'].forEach(loc => {
            const container = document.getElementById(`${loc}-fields-container`);
            if (container) container.innerHTML = '';
        });
        const backContainer = document.getElementById('back-fields-container');
        if (backContainer) backContainer.innerHTML = '';

        // Render front fields by location
        this.frontFields.forEach(field => {
            const container = document.getElementById(`${field.field_location}-fields-container`);
            if (container) {
                container.appendChild(this.createFieldCard(field, false));
            }
        });

        // Render back fields
        this.backFields.forEach(field => {
            if (backContainer) {
                backContainer.appendChild(this.createFieldCard(field, true));
            }
        });

        // Add empty state messages
        this.updateEmptyStates();
    },

    /**
     * Create a field card element
     */
    createFieldCard(field, isBackField) {
        const template = document.getElementById('field-card-template');
        const clone = template.content.cloneNode(true);
        const card = clone.querySelector('.field-card');

        const fieldKey = field.field_key;
        card.dataset.fieldKey = fieldKey;
        card.dataset.isBack = isBackField ? 'true' : 'false';

        // Set visibility state
        if (!field.is_visible) {
            card.classList.add('opacity-50');
        }

        // Set field key display
        card.querySelector('.field-key').textContent = fieldKey;

        // Set location badge
        const badge = card.querySelector('.field-location-badge');
        const location = isBackField ? 'back' : field.field_location;
        badge.textContent = location;
        badge.className = `field-location-badge text-xs font-medium px-2 py-0.5 rounded ${this.getLocationBadgeClass(location)}`;

        // Set label
        card.querySelector('.label-input').value = field.label || '';

        // Show/hide location dropdown vs field type based on front/back
        if (isBackField) {
            card.querySelector('.location-select-col').classList.add('hidden');
            card.querySelector('.data-type-col').classList.add('hidden');
            card.querySelector('.field-type-col').classList.remove('hidden');
            card.querySelector('.field-type-select').value = field.field_type || 'text';
        } else {
            card.querySelector('.location-select').value = field.field_location;
            const dataType = field.field_type || 'text';
            card.querySelector('.data-type-select').value = dataType;
            this.updateFormatOptions(card, dataType, field);
        }

        // Populate variable select
        const variableSelect = card.querySelector('.variable-select');
        this.populateVariableSelect(variableSelect);

        // Populate insert variable menu
        const insertMenu = card.querySelector('.insert-var-menu');
        this.populateInsertMenu(insertMenu, fieldKey);

        // Set current value
        const value = isBackField ? field.value : (field.value_template || '');
        const templateInput = card.querySelector('.template-input');
        templateInput.value = value;

        // Determine if simple or advanced mode
        const isSimpleVariable = this.isSimpleVariable(value);
        if (isSimpleVariable) {
            variableSelect.value = value;
        } else if (value && !isSimpleVariable) {
            card.querySelector('.simple-mode-tab').classList.remove('border-primary-600', 'text-primary-600', 'dark:text-primary-400', 'dark:border-primary-400');
            card.querySelector('.simple-mode-tab').classList.add('text-gray-500', 'dark:text-gray-400');
            card.querySelector('.advanced-mode-tab').classList.add('border-b-2', 'border-primary-600', 'text-primary-600', 'dark:text-primary-400', 'dark:border-primary-400');
            card.querySelector('.advanced-mode-tab').classList.remove('text-gray-500', 'dark:text-gray-400');
            card.querySelector('.simple-mode-content').classList.add('hidden');
            card.querySelector('.advanced-mode-content').classList.remove('hidden');
        }

        // Set preview
        this.updateCardPreview(card, value);

        // Set visibility toggle
        const visToggle = card.querySelector('.visibility-toggle');
        visToggle.checked = field.is_visible !== false;

        // Handle alignment section (front fields only)
        const alignmentSection = card.querySelector('.alignment-section');
        if (isBackField) {
            alignmentSection.classList.add('hidden');
        } else {
            const alignBtns = card.querySelectorAll('.alignment-btns input[type="radio"]');
            const alignLabels = card.querySelectorAll('.alignment-btns label');
            alignBtns.forEach((input, idx) => {
                const newId = `align-${fieldKey}-${input.value}`;
                input.id = newId;
                input.name = `align-${fieldKey}`;
                alignLabels[idx].setAttribute('for', newId);
            });

            const currentAlign = field.text_alignment || 'natural';
            const alignInput = card.querySelector(`input[name="align-${fieldKey}"][value="${currentAlign}"]`);
            if (alignInput) {
                alignInput.checked = true;
            }
        }

        // Event listeners
        this.attachCardEventListeners(card, fieldKey, isBackField);

        return card;
    },

    /**
     * Attach event listeners to a field card
     */
    attachCardEventListeners(card, fieldKey, isBackField) {
        // Label change
        card.querySelector('.label-input').addEventListener('change', (e) => {
            this.updateField(fieldKey, 'label', e.target.value, isBackField);
        });

        // Location change (front only)
        const locSelect = card.querySelector('.location-select');
        if (locSelect) {
            locSelect.addEventListener('change', (e) => {
                this.changeLocation(fieldKey, e.target.value);
            });
        }

        // Field type change (back only)
        const typeSelect = card.querySelector('.field-type-select');
        if (typeSelect) {
            typeSelect.addEventListener('change', (e) => {
                this.updateField(fieldKey, 'field_type', e.target.value, true);
            });
        }

        // Visibility toggle
        card.querySelector('.visibility-toggle').addEventListener('change', (e) => {
            this.toggleVisibility(fieldKey, e.target.checked, isBackField);
            card.classList.toggle('opacity-50', !e.target.checked);
        });

        // Delete button
        card.querySelector('.delete-btn').addEventListener('click', () => {
            this.deleteField(fieldKey, isBackField);
        });

        // Mode tabs
        card.querySelector('.simple-mode-tab').addEventListener('click', () => {
            card.querySelector('.simple-mode-tab').classList.add('border-b-2', 'border-primary-600', 'text-primary-600', 'dark:text-primary-400', 'dark:border-primary-400');
            card.querySelector('.simple-mode-tab').classList.remove('text-gray-500', 'dark:text-gray-400');
            card.querySelector('.advanced-mode-tab').classList.remove('border-b-2', 'border-primary-600', 'text-primary-600', 'dark:text-primary-400', 'dark:border-primary-400');
            card.querySelector('.advanced-mode-tab').classList.add('text-gray-500', 'dark:text-gray-400');
            card.querySelector('.simple-mode-content').classList.remove('hidden');
            card.querySelector('.advanced-mode-content').classList.add('hidden');
        });

        card.querySelector('.advanced-mode-tab').addEventListener('click', () => {
            card.querySelector('.advanced-mode-tab').classList.add('border-b-2', 'border-primary-600', 'text-primary-600', 'dark:text-primary-400', 'dark:border-primary-400');
            card.querySelector('.advanced-mode-tab').classList.remove('text-gray-500', 'dark:text-gray-400');
            card.querySelector('.simple-mode-tab').classList.remove('border-b-2', 'border-primary-600', 'text-primary-600', 'dark:text-primary-400', 'dark:border-primary-400');
            card.querySelector('.simple-mode-tab').classList.add('text-gray-500', 'dark:text-gray-400');
            card.querySelector('.advanced-mode-content').classList.remove('hidden');
            card.querySelector('.simple-mode-content').classList.add('hidden');
        });

        // Variable select change
        card.querySelector('.variable-select').addEventListener('change', (e) => {
            const newValue = e.target.value;
            this.updateFieldValue(fieldKey, newValue, isBackField);
            this.updateCardPreview(card, newValue);
            card.querySelector('.template-input').value = newValue;
        });

        // Template input change
        card.querySelector('.template-input').addEventListener('change', (e) => {
            const newValue = e.target.value;
            this.updateFieldValue(fieldKey, newValue, isBackField);
            this.updateCardPreview(card, newValue);
        });

        // Text alignment change (front fields only)
        if (!isBackField) {
            const alignInputs = card.querySelectorAll(`input[name="align-${fieldKey}"]`);
            alignInputs.forEach(input => {
                input.addEventListener('change', (e) => {
                    this.updateField(fieldKey, 'text_alignment', e.target.value, false);
                });
            });

            const dataTypeSelect = card.querySelector('.data-type-select');
            if (dataTypeSelect) {
                dataTypeSelect.addEventListener('change', (e) => {
                    const dataType = e.target.value;
                    this.updateField(fieldKey, 'field_type', dataType, false);
                    this.updateFormatOptions(card, dataType, this.frontFields.find(f => f.field_key === fieldKey));
                });
            }

            const dateStyleSelect = card.querySelector('.date-style-select');
            if (dateStyleSelect) {
                dateStyleSelect.addEventListener('change', (e) => {
                    this.updateField(fieldKey, 'date_style', e.target.value || null, false);
                });
            }

            const timeStyleSelect = card.querySelector('.time-style-select');
            if (timeStyleSelect) {
                timeStyleSelect.addEventListener('change', (e) => {
                    this.updateField(fieldKey, 'time_style', e.target.value || null, false);
                });
            }

            const numberStyleSelect = card.querySelector('.number-style-select');
            if (numberStyleSelect) {
                numberStyleSelect.addEventListener('change', (e) => {
                    this.updateField(fieldKey, 'number_style', e.target.value || null, false);
                });
            }

            const currencyCodeSelect = card.querySelector('.currency-code-select');
            if (currencyCodeSelect) {
                currencyCodeSelect.addEventListener('change', (e) => {
                    this.updateField(fieldKey, 'currency_code', e.target.value || null, false);
                });
            }
        }
    },

    /**
     * Populate variable select dropdown
     */
    populateVariableSelect(select) {
        select.innerHTML = '<option value="">-- Select variable --</option>';
        this.templateVariables.forEach(v => {
            const option = document.createElement('option');
            option.value = '{{' + v.name + '}}';
            option.textContent = v.name + ' - ' + v.description;
            select.appendChild(option);
        });
    },

    /**
     * Populate insert variable menu
     */
    populateInsertMenu(menu, fieldKey) {
        menu.innerHTML = '';
        this.templateVariables.forEach(v => {
            const a = document.createElement('a');
            a.className = 'block px-4 py-2 text-sm text-gray-700 hover:bg-gray-100 dark:text-gray-200 dark:hover:bg-gray-600 dark:hover:text-white cursor-pointer';
            a.textContent = v.name;
            a.addEventListener('click', (e) => {
                e.preventDefault();
                this.insertVariableInCard(fieldKey, v.name);
            });
            menu.appendChild(a);
        });
    },

    /**
     * Check if a value is a simple variable reference
     */
    isSimpleVariable(value) {
        if (!value) return false;
        const match = value.match(/^\{\{(\w+)\}\}$/);
        return match !== null;
    },

    /**
     * Update preview in a card
     */
    updateCardPreview(card, value) {
        const previewEl = card.querySelector('.preview-value');
        const resolved = this.resolvePreview(value);
        previewEl.textContent = resolved || '(empty)';
        previewEl.classList.toggle('text-gray-400', !resolved);
    },

    /**
     * Resolve preview value
     */
    resolvePreview(template) {
        if (!template) return '';
        let result = template;
        for (const [key, val] of Object.entries(this.sampleData)) {
            result = result.replace(new RegExp('\\{\\{' + key + '\\}\\}', 'g'), val || '');
        }
        return result;
    },

    /**
     * Get badge class for location
     */
    getLocationBadgeClass(location) {
        const classes = {
            primary: 'bg-primary-100 text-primary-800 dark:bg-primary-900 dark:text-primary-300',
            secondary: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300',
            auxiliary: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-300',
            header: 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300',
            back: 'bg-gray-800 text-white dark:bg-gray-900 dark:text-gray-200'
        };
        return classes[location] || 'bg-gray-100 text-gray-800 dark:bg-gray-700 dark:text-gray-300';
    },

    /**
     * Update format options visibility based on data type
     */
    updateFormatOptions(card, dataType, field) {
        const formatSection = card.querySelector('.format-section');
        const dateStyleGroup = card.querySelector('.date-style-group');
        const timeStyleGroup = card.querySelector('.time-style-group');
        const numberStyleGroup = card.querySelector('.number-style-group');
        const currencyCodeGroup = card.querySelector('.currency-code-group');

        dateStyleGroup.classList.add('hidden');
        timeStyleGroup.classList.add('hidden');
        numberStyleGroup.classList.add('hidden');
        currencyCodeGroup.classList.add('hidden');

        if (dataType === 'text') {
            formatSection.classList.add('hidden');
        } else {
            formatSection.classList.remove('hidden');

            if (dataType === 'date') {
                dateStyleGroup.classList.remove('hidden');
                timeStyleGroup.classList.remove('hidden');
                if (field) {
                    card.querySelector('.date-style-select').value = field.date_style || '';
                    card.querySelector('.time-style-select').value = field.time_style || '';
                }
            } else if (dataType === 'number') {
                numberStyleGroup.classList.remove('hidden');
                if (field) {
                    card.querySelector('.number-style-select').value = field.number_style || '';
                }
            } else if (dataType === 'currency') {
                currencyCodeGroup.classList.remove('hidden');
                if (field) {
                    card.querySelector('.currency-code-select').value = field.currency_code || '';
                }
            }
        }
    },

    /**
     * Initialize sortable containers
     */
    initSortable() {
        // Destroy existing instances
        this.sortableInstances.forEach(s => s.destroy());
        this.sortableInstances = [];

        // Check if Sortable is available
        if (typeof Sortable === 'undefined') {
            console.warn('SortableJS not loaded, drag-and-drop disabled');
            return;
        }

        ['primary', 'secondary', 'auxiliary', 'header', 'back'].forEach(loc => {
            const containerId = loc === 'back' ? 'back-fields-container' : `${loc}-fields-container`;
            const container = document.getElementById(containerId);
            if (container) {
                const sortable = new Sortable(container, {
                    group: loc === 'back' ? 'back-fields' : 'front-fields',
                    animation: 150,
                    handle: '.drag-handle',
                    ghostClass: 'opacity-50',
                    dragClass: 'shadow-lg',
                    onEnd: (evt) => this.handleReorder(evt)
                });
                this.sortableInstances.push(sortable);
            }
        });
    },

    /**
     * Handle field reorder after drag
     */
    handleReorder(evt) {
        const fieldKey = evt.item.dataset.fieldKey;
        const isBack = evt.item.dataset.isBack === 'true';
        const newLocation = evt.to.dataset.location;

        if (isBack) {
            const newOrder = Array.from(evt.to.children).map(el => el.dataset.fieldKey);
            this.backFields.sort((a, b) => newOrder.indexOf(a.field_key) - newOrder.indexOf(b.field_key));
            this.backFields.forEach((f, i) => f.display_order = i);
        } else {
            const field = this.frontFields.find(f => f.field_key === fieldKey);
            if (field && field.field_location !== newLocation) {
                field.field_location = newLocation;
                const badge = evt.item.querySelector('.field-location-badge');
                badge.textContent = newLocation;
                badge.className = `field-location-badge text-xs font-medium px-2 py-0.5 rounded ${this.getLocationBadgeClass(newLocation)}`;
                const locSelect = evt.item.querySelector('.location-select');
                if (locSelect) locSelect.value = newLocation;
            }

            ['primary', 'secondary', 'auxiliary', 'header'].forEach(loc => {
                const container = document.getElementById(`${loc}-fields-container`);
                if (container) {
                    const keysInOrder = Array.from(container.children).map(el => el.dataset.fieldKey);
                    this.frontFields
                        .filter(f => f.field_location === loc)
                        .forEach(f => {
                            f.display_order = keysInOrder.indexOf(f.field_key);
                        });
                }
            });
        }

        this.updateLimitCounters();
        if (typeof PassStudio !== 'undefined') PassStudio.markUnsaved();
        if (!isBack) this.notifyPreviewUpdate();
    },

    /**
     * Update empty state messages
     */
    updateEmptyStates() {
        ['primary', 'secondary', 'auxiliary', 'header'].forEach(loc => {
            const container = document.getElementById(`${loc}-fields-container`);
            if (container && container.children.length === 0) {
                container.innerHTML = `<div class="empty-state text-center py-3 text-gray-400 dark:text-gray-500 text-sm">
                    <svg class="inline w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8h16M4 16h16"/>
                    </svg>
                    Drag fields here or click Add Field
                </div>`;
            }
        });

        const backContainer = document.getElementById('back-fields-container');
        if (backContainer && backContainer.children.length === 0) {
            backContainer.innerHTML = `<div class="empty-state text-center py-3 text-gray-400 dark:text-gray-500 text-sm">
                <svg class="inline w-4 h-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/>
                </svg>
                Add fields for the back of the pass
            </div>`;
        }
    },

    /**
     * Update limit counters
     */
    updateLimitCounters() {
        const primaryCount = this.frontFields.filter(f => f.field_location === 'primary' && f.is_visible !== false).length;
        const secondaryCount = this.frontFields.filter(f => f.field_location === 'secondary' && f.is_visible !== false).length;
        const auxiliaryCount = this.frontFields.filter(f => f.field_location === 'auxiliary' && f.is_visible !== false).length;
        const headerCount = this.frontFields.filter(f => f.field_location === 'header' && f.is_visible !== false).length;
        const backCount = this.backFields.filter(f => f.is_visible !== false).length;

        const primaryEl = document.getElementById('limit-primary');
        if (primaryEl) {
            primaryEl.querySelector('.current').textContent = primaryCount;
            primaryEl.classList.toggle('border-red-500', primaryCount > this.limits.primary);
        }

        const secAuxEl = document.getElementById('limit-secondary-auxiliary');
        if (secAuxEl) {
            const combinedCount = secondaryCount + auxiliaryCount;
            secAuxEl.querySelector('.current').textContent = combinedCount;
            secAuxEl.classList.toggle('border-red-500', combinedCount > this.limits.secondaryAuxiliary);
        }

        const headerEl = document.getElementById('limit-header');
        if (headerEl) {
            headerEl.querySelector('.current').textContent = headerCount;
            headerEl.classList.toggle('border-red-500', headerCount > this.limits.header);
        }

        const backEl = document.getElementById('limit-back');
        if (backEl) {
            backEl.querySelector('.current').textContent = backCount;
        }
    },

    /**
     * Open the add field modal
     */
    openAddFieldModal(type) {
        document.getElementById('add-field-type').value = type;
        document.getElementById('add-field-label').value = '';
        document.getElementById('add-field-variable').value = '';
        document.getElementById('add-field-template').value = '';
        document.getElementById('add-field-static').value = '';
        document.getElementById('add-field-static').classList.add('hidden');

        const locGroup = document.getElementById('add-field-location-group');
        const typeGroup = document.getElementById('add-field-type-group');

        if (type === 'back') {
            locGroup.classList.add('hidden');
            typeGroup.classList.remove('hidden');
        } else {
            locGroup.classList.remove('hidden');
            typeGroup.classList.add('hidden');
        }

        document.getElementById('add-simple-tab')?.click();
        if (this.addFieldModal) {
            this.addFieldModal.show();
        }
    },

    /**
     * Insert variable at cursor in add modal
     */
    insertVariableInAdd(varName) {
        const input = document.getElementById('add-field-template');
        const cursorPos = input.selectionStart;
        const textBefore = input.value.substring(0, cursorPos);
        const textAfter = input.value.substring(input.selectionEnd);
        input.value = textBefore + '{{' + varName + '}}' + textAfter;
        input.focus();
        const newPos = cursorPos + varName.length + 4;
        input.setSelectionRange(newPos, newPos);
    },

    /**
     * Insert variable at cursor in card
     */
    insertVariableInCard(fieldKey, varName) {
        const card = document.querySelector('[data-field-key="' + fieldKey + '"]');
        if (!card) return;

        const input = card.querySelector('.template-input');
        const cursorPos = input.selectionStart;
        const textBefore = input.value.substring(0, cursorPos);
        const textAfter = input.value.substring(input.selectionEnd);
        input.value = textBefore + '{{' + varName + '}}' + textAfter;

        input.dispatchEvent(new Event('change'));
        input.focus();
    },

    /**
     * Create a new field
     */
    createField() {
        const type = document.getElementById('add-field-type').value;
        const label = document.getElementById('add-field-label').value.trim();

        if (!label) {
            this.showToast('Please enter a field label', 'error');
            return;
        }

        const fieldKey = label.toLowerCase().replace(/\s+/g, '_').replace(/[^a-z0-9_]/g, '');

        const existingField = type === 'back'
            ? this.backFields.find(f => f.field_key === fieldKey)
            : this.frontFields.find(f => f.field_key === fieldKey);

        if (existingField) {
            this.showToast('A field with this key already exists', 'error');
            return;
        }

        let value = '';
        const simpleTab = document.getElementById('add-simple-tab');
        if (simpleTab && simpleTab.classList.contains('active')) {
            const varSelect = document.getElementById('add-field-variable').value;
            if (varSelect === '__static__') {
                value = document.getElementById('add-field-static').value;
            } else {
                value = varSelect;
            }
        } else {
            value = document.getElementById('add-field-template').value;
        }

        if (type === 'back') {
            const fieldType = document.getElementById('add-field-field-type').value;
            this.backFields.push({
                field_key: fieldKey,
                label: label.toUpperCase(),
                value: value,
                field_type: fieldType,
                is_visible: true,
                display_order: this.backFields.length
            });
        } else {
            const locationInput = document.querySelector('input[name="add-field-location"]:checked');
            const location = locationInput ? locationInput.value : 'secondary';

            const currentCount = this.frontFields.filter(f => f.field_location === location && f.is_visible !== false).length;
            if (currentCount >= this.limits[location]) {
                this.showToast(`Maximum ${this.limits[location]} ${location} field(s) allowed`, 'warning');
                return;
            }

            this.frontFields.push({
                field_key: fieldKey,
                label: label.toUpperCase(),
                field_location: location,
                value_template: value,
                is_visible: true,
                display_order: this.frontFields.filter(f => f.field_location === location).length
            });
        }

        if (this.addFieldModal) {
            this.addFieldModal.hide();
        }
        this.renderAllFields();
        this.initSortable();
        this.updateLimitCounters();
        if (typeof PassStudio !== 'undefined') PassStudio.markUnsaved();
        this.notifyPreviewUpdate();
        this.showToast('Field added', 'success');
    },

    /**
     * Notify the preview to update with current field data
     */
    notifyPreviewUpdate() {
        if (typeof PassStudio !== 'undefined' && PassStudio.updatePreviewFields) {
            PassStudio.updatePreviewFields(this.frontFields, this.sampleData);
        }
    },

    /**
     * Update a field property
     */
    updateField(fieldKey, prop, value, isBack) {
        const fields = isBack ? this.backFields : this.frontFields;
        const field = fields.find(f => f.field_key === fieldKey);
        if (field) {
            field[prop] = value;
            if (typeof PassStudio !== 'undefined') PassStudio.markUnsaved();
            if (!isBack) this.notifyPreviewUpdate();
        }
    },

    /**
     * Update field value (value_template or value)
     */
    updateFieldValue(fieldKey, value, isBack) {
        const fields = isBack ? this.backFields : this.frontFields;
        const field = fields.find(f => f.field_key === fieldKey);
        if (field) {
            if (isBack) {
                field.value = value;
            } else {
                field.value_template = value;
            }
            if (typeof PassStudio !== 'undefined') PassStudio.markUnsaved();
            if (!isBack) this.notifyPreviewUpdate();
        }
    },

    /**
     * Change field location
     */
    changeLocation(fieldKey, newLocation) {
        const field = this.frontFields.find(f => f.field_key === fieldKey);
        if (!field) return;

        const currentCount = this.frontFields.filter(f => f.field_location === newLocation && f.is_visible !== false).length;
        if (currentCount >= this.limits[newLocation]) {
            this.showToast(`Maximum ${this.limits[newLocation]} ${newLocation} field(s) allowed`, 'warning');
            const card = document.querySelector(`[data-field-key="${fieldKey}"]`);
            if (card) {
                card.querySelector('.location-select').value = field.field_location;
            }
            return;
        }

        field.field_location = newLocation;

        this.renderAllFields();
        this.initSortable();
        this.updateLimitCounters();
        if (typeof PassStudio !== 'undefined') PassStudio.markUnsaved();
        this.notifyPreviewUpdate();
    },

    /**
     * Toggle field visibility
     */
    toggleVisibility(fieldKey, visible, isBack) {
        const fields = isBack ? this.backFields : this.frontFields;
        const field = fields.find(f => f.field_key === fieldKey);
        if (field) {
            field.is_visible = visible;
            this.updateLimitCounters();
            if (typeof PassStudio !== 'undefined') PassStudio.markUnsaved();
            if (!isBack) this.notifyPreviewUpdate();
        }
    },

    /**
     * Delete a field
     */
    async deleteField(fieldKey, isBack) {
        const result = await Swal.fire({
            title: 'Delete Field?',
            text: `Are you sure you want to delete "${fieldKey}"?`,
            icon: 'warning',
            showCancelButton: true,
            confirmButtonColor: (typeof ECSTheme !== 'undefined') ? ECSTheme.getColor('danger') : '#d33',
            confirmButtonText: 'Yes, delete'
        });

        if (result.isConfirmed) {
            if (isBack) {
                this.backFields = this.backFields.filter(f => f.field_key !== fieldKey);
            } else {
                this.frontFields = this.frontFields.filter(f => f.field_key !== fieldKey);
            }

            this.renderAllFields();
            this.initSortable();
            this.updateLimitCounters();
            if (typeof PassStudio !== 'undefined') PassStudio.markUnsaved();
            if (!isBack) this.notifyPreviewUpdate();
            this.showToast('Field deleted', 'success');
        }
    },

    /**
     * Reset fields to last saved state
     */
    resetFields() {
        Swal.fire({
            title: 'Reset Changes?',
            text: 'This will discard all unsaved changes.',
            icon: 'question',
            showCancelButton: true,
            confirmButtonText: 'Yes, reset'
        }).then((result) => {
            if (result.isConfirmed) {
                location.reload();
            }
        });
    },

    /**
     * Save all fields to server
     */
    async saveFields() {
        if (!this.passTypeCode) {
            this.showToast('Pass type code not set', 'error');
            return;
        }

        try {
            this.frontFields.forEach((f, i) => f.display_order = i);
            this.backFields.forEach((f, i) => f.display_order = i);

            const csrfToken = document.querySelector('[name=csrf_token]')?.value ||
                             document.querySelector('meta[name="csrf-token"]')?.content;

            const response = await fetch(`/admin/wallet/studio/${this.passTypeCode}/fields`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    front_fields: this.frontFields,
                    back_fields: this.backFields
                })
            });

            const data = await response.json();
            if (data.success) {
                this.showToast('Fields saved successfully', 'success');
                if (typeof PassStudio !== 'undefined') PassStudio.markSaved();
            } else {
                this.showToast(data.error || 'Error saving fields', 'error');
            }
        } catch (error) {
            console.error('Save error:', error);
            this.showToast('Error saving fields', 'error');
        }
    },

    /**
     * Initialize default field configurations from server
     */
    async initializeDefaults() {
        try {
            const result = await Swal.fire({
                title: 'Load Default Fields?',
                text: 'This will create standard fields (Member Name, Year, etc.) for your pass. You can customize them afterward.',
                icon: 'question',
                showCancelButton: true,
                confirmButtonText: 'Yes, load defaults',
                cancelButtonText: 'Cancel'
            });

            if (!result.isConfirmed) return;

            const csrfToken = document.querySelector('[name=csrf_token]')?.value ||
                             document.querySelector('meta[name="csrf-token"]')?.content;

            const response = await fetch('/admin/wallet/studio/init-defaults', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                }
            });

            const data = await response.json();
            if (data.success) {
                this.showToast('Default fields loaded! Refreshing page...', 'success');
                setTimeout(() => location.reload(), 1000);
            } else {
                this.showToast(data.error || 'Error loading defaults', 'error');
            }
        } catch (error) {
            console.error('Init error:', error);
            this.showToast('Error loading default fields', 'error');
        }
    },

    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
        if (typeof PassStudio !== 'undefined' && PassStudio.showToast) {
            PassStudio.showToast(message, type);
        } else if (typeof Swal !== 'undefined') {
            Swal.fire({
                toast: true,
                position: 'top-end',
                icon: type,
                title: message,
                showConfirmButton: false,
                timer: 3000
            });
        }
    }
};

// Make globally available
window.FieldsManager = FieldsManager;

// Register with InitSystem
let _fieldsManagerInitialized = false;

function initFieldsManager() {
    if (_fieldsManagerInitialized) return;

    // Look for initialization data in a script tag
    const initScript = document.getElementById('fields-manager-init-data');
    if (!initScript) return;

    _fieldsManagerInitialized = true;

    try {
        const initData = JSON.parse(initScript.textContent);
        window.FieldsManager.init(
            initData.frontFields || [],
            initData.backFields || [],
            initData.templateVariables || [],
            initData.sampleData || {},
            initData.passTypeCode || ''
        );
    } catch (e) {
        console.error('Failed to parse FieldsManager init data:', e);
    }
}

InitSystem.register('pass-studio-fields', initFieldsManager, {
    priority: 35,
    reinitializable: false,
    description: 'Pass studio fields management'
});
