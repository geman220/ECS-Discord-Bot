// ai-assistant.js - AI Assistant main module
import { askQuestion, getSuggestions, getUsage, rateResponse } from './ai-assistant/api.js';
import { renderUserMessage, renderAssistantMessage, renderTypingIndicator, renderError, renderSuggestionChips, clearMessages, updateUsageBadge } from './ai-assistant/render.js';
import { AI_CONFIG } from './ai-assistant/config.js';

const state = {
    isOpen: false,
    isLoading: false,
    conversationHistory: [],
};

function getElements() {
    return {
        panel: document.getElementById('ai-assistant-panel'),
        trigger: document.getElementById('ai-assistant-trigger'),
        input: document.getElementById('ai-assistant-input'),
        sendBtn: document.getElementById('ai-assistant-send-btn'),
        charCount: document.getElementById('ai-assistant-char-count'),
    };
}

function togglePanel() {
    const { panel, trigger } = getElements();
    if (!panel) return;

    state.isOpen = !state.isOpen;
    panel.classList.toggle('hidden', !state.isOpen);

    if (state.isOpen) {
        // On mobile, make panel full-screen
        if (window.innerWidth < 640) {
            panel.style.cssText = 'position:fixed;top:0;left:0;right:0;bottom:0;max-height:100vh;height:100vh;border-radius:0;width:100vw;max-width:100vw;';
        }
        loadSuggestions();
        loadUsage();
        const { input } = getElements();
        if (input) setTimeout(() => input.focus(), 100);
    } else {
        // Reset mobile styles
        panel.style.cssText = '';
    }
}

async function loadSuggestions() {
    try {
        const data = await getSuggestions();
        if (data.success) {
            renderSuggestionChips(data.suggestions);
        }
    } catch (e) {
        console.warn('[AI Assistant] Failed to load suggestions:', e);
    }
}

async function loadUsage() {
    try {
        const data = await getUsage();
        if (data.success !== false) {
            updateUsageBadge(data.daily, data.daily_limit);
        }
    } catch (e) {
        console.warn('[AI Assistant] Failed to load usage:', e);
    }
}

async function sendMessage() {
    const { input, sendBtn } = getElements();
    if (!input || state.isLoading) return;

    const message = input.value.trim();
    if (!message) return;

    // Render user message and clear input
    renderUserMessage(message);
    state.conversationHistory.push({ role: 'user', content: message });
    input.value = '';
    input.style.height = 'auto';
    updateCharCount();
    if (sendBtn) sendBtn.disabled = true;

    // Show typing indicator
    state.isLoading = true;
    renderTypingIndicator();

    try {
        const data = await askQuestion(message, state.conversationHistory, window.location.pathname);

        if (data.success) {
            renderAssistantMessage(data.response, data.log_id);
            state.conversationHistory.push({ role: 'assistant', content: data.response });
        } else {
            renderError(data.message || 'An error occurred.');
        }
    } catch (e) {
        console.error('[AI Assistant] Error:', e);
        renderError('Unable to reach the AI assistant. Please try again.');
    } finally {
        state.isLoading = false;
        loadUsage();
    }
}

function updateCharCount() {
    const { input, charCount, sendBtn } = getElements();
    if (!input) return;
    const len = input.value.length;
    if (charCount) {
        charCount.textContent = len > 0 ? `${len}/${AI_CONFIG.maxMessageLength}` : '';
    }
    if (sendBtn) {
        sendBtn.disabled = len === 0 || state.isLoading;
    }
}

function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 100) + 'px';
}

// Register with EventDelegation
function registerHandlers() {
    if (!window.EventDelegation) return;

    window.EventDelegation.register('ai-assistant-toggle', () => {
        togglePanel();
    });

    window.EventDelegation.register('ai-assistant-send', () => {
        sendMessage();
    });

    window.EventDelegation.register('ai-assistant-chip', (element) => {
        const msg = element.dataset.message;
        const { input } = getElements();
        if (input && msg) {
            input.value = msg;
            updateCharCount();
            sendMessage();
        }
    });

    window.EventDelegation.register('ai-assistant-clear', () => {
        state.conversationHistory = [];
        clearMessages();
    });

    window.EventDelegation.register('ai-assistant-rate', async (element) => {
        const logId = parseInt(element.dataset.logId);
        const rating = parseInt(element.dataset.rating);
        if (!logId || !rating) return;

        try {
            await rateResponse(logId, rating);
            // Visual feedback
            const parent = element.closest('.flex');
            if (parent) {
                parent.innerHTML = `<span class="text-[10px] text-gray-400">${rating === 5 ? 'Thanks!' : 'Noted'}</span>`;
            }
        } catch (e) {
            console.warn('[AI Assistant] Rating failed:', e);
        }
    });
}

// Register with InitSystem
if (window.InitSystem) {
    window.InitSystem.register('ai-assistant', () => {
        const widget = document.getElementById('ai-assistant-widget');
        if (!widget) return;

        registerHandlers();

        // Input event listeners
        const input = document.getElementById('ai-assistant-input');
        if (input) {
            input.addEventListener('input', () => {
                updateCharCount();
                autoResize(input);
            });
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendMessage();
                }
            });
        }

        console.log('[AI Assistant] Initialized');
    }, {
        priority: 36,
        description: 'AI Assistant floating widget',
        reinitializable: true
    });
}
