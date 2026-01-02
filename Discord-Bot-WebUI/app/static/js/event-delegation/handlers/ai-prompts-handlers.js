import { EventDelegation } from '../core.js';

/**
 * AI Prompts Action Handlers
 * Handles AI prompt configuration and management
 */

// ============================================================================
// AI PROMPT MANAGEMENT
// ============================================================================

/**
 * Toggle Prompt Status
 * Toggles an AI prompt between active and inactive
 */
window.EventDelegation.register('toggle-prompt', function(element, e) {
    e.preventDefault();

    const promptId = element.dataset.promptId;

    if (!promptId) {
        console.error('[toggle-prompt] Missing prompt ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin"></i>';
    element.disabled = true;

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/ai-prompts/${promptId}/toggle`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            throw new Error(data.error || 'Failed to toggle prompt');
        }
    })
    .catch(error => {
        if (typeof window.toastr !== 'undefined') {
            window.toastr.error('Error: ' + error.message);
        } else {
            alert('Error: ' + error.message);
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

/**
 * Delete Prompt
 * Deletes an AI prompt with confirmation
 */
window.EventDelegation.register('delete-prompt', function(element, e) {
    e.preventDefault();

    const form = element.closest('form');
    if (!form) {
        console.error('[delete-prompt] No form found');
        return;
    }

    if (!confirm('Are you sure you want to delete this AI prompt? This cannot be undone.')) {
        return;
    }

    form.submit();
});

/**
 * Confirm Delete Prompt
 * Handles delete confirmation from view page
 */
window.EventDelegation.register('confirm-delete-prompt', function(element, e) {
    e.preventDefault();

    const form = element.closest('form');
    if (!form) {
        console.error('[confirm-delete-prompt] No form found');
        return;
    }

    if (confirm('Are you sure you want to delete this AI prompt? This cannot be undone.')) {
        form.submit();
    }
});

/**
 * Test Prompt
 * Tests an AI prompt with sample data
 */
window.EventDelegation.register('test-prompt', function(element, e) {
    e.preventDefault();

    const promptId = element.dataset.promptId;

    if (!promptId) {
        console.error('[test-prompt] Missing prompt ID');
        return;
    }

    const originalText = element.innerHTML;
    element.innerHTML = '<i class="ti ti-loader spin me-1"></i> Testing...';
    element.disabled = true;

    // Sample test data
    const testData = {
        match_context: "Seattle Sounders vs Portland Timbers - MLS Regular Season - 35th minute",
        events: "Yellow card shown to Portland player for rough tackle",
        score: "1-0 Seattle"
    };

    const csrfToken = document.querySelector('meta[name=csrf-token]')?.getAttribute('content') || '';

    fetch(`/ai-prompts/api/test/${promptId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken
        },
        body: JSON.stringify(testData)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const testResult = document.getElementById('test-result');
            const testOutput = document.getElementById('test-output');

            if (testResult) testResult.textContent = data.response;
            if (testOutput) testOutput.classList.remove('d-none');
        } else {
            if (typeof window.toastr !== 'undefined') {
                window.toastr.error(data.error || 'Test failed');
            }
        }
    })
    .catch(error => {
        if (typeof window.toastr !== 'undefined') {
            window.toastr.error('Network error occurred');
        }
    })
    .finally(() => {
        element.innerHTML = originalText;
        element.disabled = false;
    });
});

/**
 * Load AI Prompt Template
 * Loads an AI prompt template into the form
 * Note: Renamed from 'load-template' to avoid conflict with mobile-features-handlers.js
 */
window.EventDelegation.register('load-ai-template', function(element, e) {
    e.preventDefault();

    const templateId = element.dataset.templateId;

    if (!templateId) {
        console.error('[load-ai-template] Missing template ID');
        return;
    }

    if (!confirm('This will replace the current prompt configuration. Continue?')) {
        return;
    }

    fetch(`/ai-prompts/api/template/${templateId}`)
        .then(response => response.json())
        .then(data => {
            if (data.template_data) {
                // Populate form fields with template data
                if (data.template_data.system_prompt) {
                    const systemPrompt = document.getElementById('system_prompt');
                    if (systemPrompt) systemPrompt.value = data.template_data.system_prompt;
                }
                if (data.template_data.temperature) {
                    const temperature = document.getElementById('temperature');
                    const tempValue = document.getElementById('temp-value');
                    if (temperature) temperature.value = data.template_data.temperature;
                    if (tempValue) tempValue.textContent = data.template_data.temperature;
                }
                if (data.template_data.user_prompt_template) {
                    const userPrompt = document.getElementById('user_prompt_template');
                    if (userPrompt) userPrompt.value = data.template_data.user_prompt_template;
                }
                if (data.template_data.max_tokens) {
                    const maxTokens = document.getElementById('max_tokens');
                    if (maxTokens) maxTokens.value = data.template_data.max_tokens;
                }

                if (typeof window.toastr !== 'undefined') {
                    window.toastr.success('Template loaded successfully');
                }
            }
        })
        .catch(error => {
            if (typeof window.toastr !== 'undefined') {
                window.toastr.error('Failed to load template');
            }
        });
});

/**
 * Use AI Prompt Template
 * Redirects to create page with template ID
 * Note: Renamed from 'use-template' to avoid conflict with admin-playoff-handlers.js
 */
window.EventDelegation.register('use-ai-template', function(element, e) {
    e.preventDefault();

    const templateId = element.dataset.templateId;

    if (!templateId) {
        console.error('[use-ai-template] Missing template ID');
        return;
    }

    window.location.href = `/ai-prompts/create?template=${templateId}`;
});

/**
 * Filter Prompts
 * Filters prompts list by type and status
 */
window.EventDelegation.register('filter-prompts', function(element, e) {
    const typeFilter = document.getElementById('typeFilter');
    const activeOnly = document.getElementById('activeOnly');

    const params = new URLSearchParams();

    if (typeFilter && typeFilter.value) {
        params.append('type', typeFilter.value);
    }
    if (activeOnly) {
        params.append('active_only', activeOnly.checked);
    }

    window.location.href = window.location.pathname + '?' + params.toString();
});

/**
 * Update Personality Slider
 * Updates the display value for personality trait sliders
 */
window.EventDelegation.register('update-personality-slider', function(element, e) {
    const targetId = element.dataset.target;
    if (!targetId) return;

    const targetElement = document.getElementById(targetId);
    if (targetElement) {
        targetElement.textContent = element.value;
    }
});

/**
 * Update Temperature
 * Updates the temperature slider display value
 */
window.EventDelegation.register('update-temperature', function(element, e) {
    const tempValue = document.getElementById('temp-value');
    if (tempValue) {
        tempValue.textContent = element.value;
    }
});

/**
 * Update Rivalry Intensity
 * Updates the rivalry intensity slider display value
 */
window.EventDelegation.register('update-rivalry-intensity', function(element, e) {
    const rivalryValue = document.getElementById('rivalry-value');
    if (rivalryValue) {
        rivalryValue.textContent = element.value;
    }
});

/**
 * Validate Rivalry Teams JSON
 * Validates JSON format on blur
 */
window.EventDelegation.register('validate-rivalry-json', function(element, e) {
    const value = element.value.trim();

    if (value && value !== '') {
        try {
            JSON.parse(value);
            element.classList.remove('is-invalid');
            element.classList.add('is-valid');
        } catch (error) {
            element.classList.remove('is-valid');
            element.classList.add('is-invalid');
        }
    } else {
        element.classList.remove('is-invalid', 'is-valid');
    }
});

/**
 * Duplicate Prompt
 * Duplicates an existing prompt
 */
window.EventDelegation.register('duplicate-prompt', function(element, e) {
    e.preventDefault();

    const promptId = element.dataset.promptId;

    if (!promptId) {
        console.error('[duplicate-prompt] Missing prompt ID');
        return;
    }

    const form = element.closest('form');
    if (form) {
        form.submit();
    }
});

// ============================================================================

// Handlers loaded
