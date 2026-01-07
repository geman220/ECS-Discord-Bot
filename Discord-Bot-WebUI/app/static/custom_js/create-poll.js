/**
 * Create Poll Page
 * Handles live preview updates for poll creation
 */
// ES Module
'use strict';

import { InitSystem } from '../js/init-system.js';

let _initialized = false;

function initCreatePoll() {
    if (_initialized) return;

    // Page guard - only run if poll title element exists
    const titleInput = document.getElementById('title');
    if (!titleInput) return;

    _initialized = true;

    const questionInput = document.getElementById('question');
    const previewTitle = document.getElementById('preview-title');
    const previewQuestion = document.getElementById('preview-question');

    // Live preview functionality
    function updatePreview() {
        const title = titleInput.value || 'Poll Title';
        const question = questionInput ? (questionInput.value || 'Your poll question will appear here...') : '';

        if (previewTitle) previewTitle.textContent = title;
        if (previewQuestion) previewQuestion.textContent = question;
    }

    titleInput.addEventListener('input', updatePreview);
    if (questionInput) questionInput.addEventListener('input', updatePreview);

    // Initial update
    updatePreview();
}

// ========================================================================
// EXPORTS
// ========================================================================

export { initCreatePoll };

// Register with window.InitSystem (primary)
if (window.InitSystem && window.InitSystem.register) {
    window.InitSystem.register('create-poll', initCreatePoll, {
        priority: 35,
        reinitializable: true,
        description: 'Create poll live preview'
    });
}

// Fallback
// window.InitSystem handles initialization

// Backward compatibility
window.createPollInit = initCreatePoll;
