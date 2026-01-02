/**
 * ============================================================================
 * ANNOUNCEMENT FORM MODULE
 * ============================================================================
 *
 * Handles the announcement form page with live preview and character counter.
 *
 * Features:
 * - Live preview updates as user types
 * - Character count for content field
 * - Delete announcement handler with event delegation
 *
 * ============================================================================
 */
'use strict';

import { InitSystem } from '../init-system.js';
import { EventDelegation } from '../event-delegation/core.js';

/* ========================================================================
   ANNOUNCEMENT FORM CONTROLLER
   ======================================================================== */

const AnnouncementForm = {
    // Configuration
    config: {
        maxChars: 2000,
        selectors: {
            titleInput: '#title',
            contentInput: '#content',
            prioritySelect: '#priority',
            typeSelect: '#announcement_type',
            previewTitle: '#preview-title',
            previewBody: '#preview-body',
            previewPriority: '#preview-priority',
            previewType: '#preview-type'
        }
    },

    // DOM element references
    elements: {},

    /**
     * Initialize the announcement form
     */
    init: function(context = document) {
        // Page guard - only run on announcement form page
        const titleInput = context.querySelector(this.config.selectors.titleInput);
        const contentInput = context.querySelector(this.config.selectors.contentInput);
        if (!titleInput || !contentInput) {
            return; // Not on announcement form page
        }

        console.log('[AnnouncementForm] Initializing...');

        // Cache DOM elements
        this.elements = {
            titleInput: titleInput,
            contentInput: contentInput,
            prioritySelect: context.querySelector(this.config.selectors.prioritySelect),
            typeSelect: context.querySelector(this.config.selectors.typeSelect),
            previewTitle: context.querySelector(this.config.selectors.previewTitle),
            previewBody: context.querySelector(this.config.selectors.previewBody),
            previewPriority: context.querySelector(this.config.selectors.previewPriority),
            previewType: context.querySelector(this.config.selectors.previewType)
        };

        // Additional guard for preview elements
        if (!this.elements.previewTitle || !this.elements.previewBody) {
            return; // Preview elements not present
        }

        this.initPreviewListeners();
        this.initCharacterCounter();
        this.initDeleteHandler(context);

        console.log('[AnnouncementForm] Initialized');
    },

    /**
     * Initialize live preview listeners
     */
    initPreviewListeners: function() {
        const self = this;

        this.elements.titleInput.addEventListener('input', () => self.updatePreview());
        this.elements.contentInput.addEventListener('input', () => self.updatePreview());

        if (this.elements.prioritySelect) {
            this.elements.prioritySelect.addEventListener('change', () => self.updatePreview());
        }
        if (this.elements.typeSelect) {
            this.elements.typeSelect.addEventListener('change', () => self.updatePreview());
        }
    },

    /**
     * Update the preview section
     */
    updatePreview: function() {
        this.elements.previewTitle.textContent = this.elements.titleInput.value || 'Announcement Title';
        this.elements.previewBody.textContent = this.elements.contentInput.value || 'Announcement content will appear here...';

        if (this.elements.prioritySelect && this.elements.previewPriority) {
            this.elements.previewPriority.textContent = this.elements.prioritySelect.value.charAt(0).toUpperCase() + this.elements.prioritySelect.value.slice(1);

            // Update priority badge color
            this.elements.previewPriority.className = 'badge ';
            switch(this.elements.prioritySelect.value) {
                case 'high':
                    this.elements.previewPriority.className += 'bg-danger';
                    break;
                case 'medium':
                    this.elements.previewPriority.className += 'bg-warning';
                    break;
                case 'low':
                    this.elements.previewPriority.className += 'bg-secondary';
                    break;
                default:
                    this.elements.previewPriority.className += 'bg-info';
            }
        }

        if (this.elements.typeSelect && this.elements.previewType) {
            this.elements.previewType.textContent = this.elements.typeSelect.value.charAt(0).toUpperCase() + this.elements.typeSelect.value.slice(1);
        }
    },

    /**
     * Initialize character counter for content field
     */
    initCharacterCounter: function() {
        const self = this;
        const maxChars = this.config.maxChars;

        // Build character count display safely (no user input in HTML)
        const charCount = document.createElement('div');
        charCount.className = 'form-text';

        const small = document.createElement('small');
        small.textContent = 'Characters: ';

        const countSpan = document.createElement('span');
        countSpan.id = 'char-count';
        countSpan.textContent = this.elements.contentInput.value.length;

        small.appendChild(countSpan);
        small.appendChild(document.createTextNode(`/${maxChars}`));
        charCount.appendChild(small);
        this.elements.contentInput.parentNode.appendChild(charCount);

        this.elements.contentInput.addEventListener('input', function() {
            document.getElementById('char-count').textContent = this.value.length;
            if (this.value.length > maxChars * 0.9) {
                charCount.className = 'form-text text-warning';
            } else if (this.value.length > maxChars) {
                charCount.className = 'form-text text-danger';
            } else {
                charCount.className = 'form-text';
            }
        });
    },

    /**
     * Initialize delete announcement handler using event delegation
     */
    initDeleteHandler: function(context) {
        // Use event delegation for delete buttons
        context.addEventListener('click', function(e) {
            const btn = e.target.closest('[data-action="delete-announcement"]');
            if (!btn) return;

            const announcementId = btn.dataset.id;
            if (confirm('Are you sure you want to delete this announcement? This action cannot be undone.')) {
                const form = document.createElement('form');
                form.method = 'POST';
                form.action = btn.getAttribute('data-url') || `/admin-panel/communication/announcements/${announcementId}/delete`;

                const csrfToken = document.createElement('input');
                csrfToken.type = 'hidden';
                csrfToken.name = 'csrf_token';
                csrfToken.value = document.querySelector('input[name="csrf_token"]').value;
                form.appendChild(csrfToken);

                document.body.appendChild(form);
                form.submit();
            }
        });
    }
};

/* ========================================================================
   REGISTER WITH INITSYSTEM OR FALLBACK TO DOMCONTENTLOADED
   ======================================================================== */

// Expose for external access
window.AnnouncementForm = AnnouncementForm;

if (typeof window.InitSystem !== 'undefined') {
    window.InitSystem.register('AnnouncementForm', function(context) {
        window.AnnouncementForm.init(context);
    }, {
        priority: 50
    });
} else {
    document.addEventListener('DOMContentLoaded', function() {
        window.AnnouncementForm.init(document);
    });
}

export { AnnouncementForm };
