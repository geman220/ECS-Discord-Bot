'use strict';

/**
 * Help Topic Editor Module
 * Handles markdown editor modal functionality for help topic creation
 *
 * @module help-topic-editor
 * @requires InitSystem
 * @requires EasyMDE (loaded externally)
 */

import { InitSystem } from '../js/init-system.js';

/**
 * Help Topic Editor functionality
 */
const HelpTopicEditor = {
    // Editor instance
    editor: null,

    /**
     * Initialize help topic editor functionality
     */
    init() {
        this.modal = document.getElementById('markdown-editor-modal');
        this.textarea = document.getElementById('markdown_editor');
        this.container = document.getElementById('modal-editor-container');
        this.openBtn = document.querySelector('[data-action="open-markdown-editor"]');
        this.closeBtn = document.querySelector('[data-action="close-markdown-editor"]');

        if (!this.modal || !this.textarea || !this.container) {
            console.log('[HelpTopicEditor] Required elements not found, skipping initialization');
            return;
        }

        this.setupImageUpload();
        this.setupEventListeners();
        this.setupFileUpload();

        console.log('[HelpTopicEditor] Initialized');
    },

    /**
     * Get CSRF token
     * @returns {string} CSRF token
     */
    getCsrfToken() {
        const metaToken = document.querySelector('meta[name="csrf-token"]');
        if (metaToken) {
            return metaToken.getAttribute('content');
        }
        const inputToken = document.querySelector('input[name="csrf_token"]');
        return inputToken ? inputToken.value : '';
    },

    /**
     * Get image upload URL
     * @returns {string} Upload URL
     */
    getImageUploadUrl() {
        // Try to get from data attribute or default
        const form = document.querySelector('[data-component="help-editor-form"]');
        return form?.dataset?.imageUploadUrl || '/help/upload-image';
    },

    /**
     * Setup hidden file input for custom image upload
     */
    setupImageUpload() {
        if (document.getElementById('easymde_custom_image_upload')) {
            return;
        }

        const imageInput = document.createElement('input');
        imageInput.type = 'file';
        imageInput.accept = 'image/*';
        imageInput.id = 'easymde_custom_image_upload';
        imageInput.style.display = 'none';
        document.body.appendChild(imageInput);

        imageInput.addEventListener('change', () => {
            const file = imageInput.files[0];
            if (file) {
                this.uploadImage(file);
            }
        });
    },

    /**
     * Upload image to server
     * @param {File} file - Image file
     */
    uploadImage(file) {
        const formData = new FormData();
        formData.append('image', file);

        fetch(this.getImageUploadUrl(), {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': this.getCsrfToken()
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.url) {
                const cm = this.editor.codemirror;
                const doc = cm.getDoc();
                const cursor = doc.getCursor();
                doc.replaceRange('![](' + data.url + ')', cursor);
            } else {
                alert(data.error || 'Image upload failed');
            }
        })
        .catch(() => alert('Image upload error'));
    },

    /**
     * Initialize EasyMDE editor
     */
    initEditor() {
        if (this.editor) return;

        // Check if EasyMDE is loaded
        if (typeof EasyMDE === 'undefined') {
            console.warn('[HelpTopicEditor] EasyMDE not loaded');
            return;
        }

        this.container.innerHTML = '';
        const clonedTextarea = this.textarea.cloneNode(true);
        clonedTextarea.id = 'modal_markdown_editor';
        this.container.appendChild(clonedTextarea);

        this.editor = new EasyMDE({
            element: clonedTextarea,
            spellChecker: false,
            autofocus: true,
            autoDownloadFontAwesome: false,
            sideBySideFullscreen: false,
            forceSync: true,
            maxHeight: 'calc(100% - 45px)',
            toolbar: [
                'bold', 'italic', 'heading', '|',
                'quote', 'unordered-list', 'ordered-list', '|',
                {
                    name: 'uploadImage',
                    action: () => {
                        document.getElementById('easymde_custom_image_upload').click();
                    },
                    className: 'fa fa-upload',
                    title: 'Upload Image'
                },
                'link', 'code', 'table', '|',
                'preview', 'side-by-side'
            ]
        });

        // Setup resize observer
        const resizeObserver = new ResizeObserver(() => {
            if (this.modal.style.display === 'block' && this.editor) {
                requestAnimationFrame(() => this.editor.codemirror.refresh());
            }
        });
        resizeObserver.observe(this.container);
    },

    /**
     * Setup event listeners
     */
    setupEventListeners() {
        if (this.openBtn) {
            this.openBtn.addEventListener('click', () => this.openModal());
        }

        if (this.closeBtn) {
            this.closeBtn.addEventListener('click', () => this.closeModal());
        }

        // Close on backdrop click
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.closeModal();
            }
        });

        // Close on escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.style.display === 'block') {
                this.closeModal();
            }
        });
    },

    /**
     * Setup file upload for markdown files
     */
    setupFileUpload() {
        const fileInput = document.getElementById('markdown_file');
        if (!fileInput) return;

        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file) {
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.textarea.value = e.target.result;
                    if (this.editor) {
                        this.editor.value(e.target.result);
                    }
                    this.openModal();
                };
                reader.readAsText(file);
            }
        });
    },

    /**
     * Open modal
     */
    openModal() {
        this.modal.style.display = 'block';
        this.initEditor();
    },

    /**
     * Close modal
     */
    closeModal() {
        this.modal.style.display = 'none';
        if (this.editor) {
            this.textarea.value = this.editor.value();
        }
    }
};

// Register with InitSystem
InitSystem.register('help-topic-editor', () => {
    // Only initialize on help topic editor page
    if (document.querySelector('[data-component="help-editor-form"]') ||
        document.getElementById('markdown-editor-modal')) {
        HelpTopicEditor.init();
    }
}, {
    priority: 40,
    description: 'Help topic markdown editor functionality',
    reinitializable: false
});

// Export for direct use
export { HelpTopicEditor };
