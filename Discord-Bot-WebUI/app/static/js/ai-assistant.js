// ai-assistant.js - AI Assistant main module
import { askQuestion, getSuggestions, getUsage, rateResponse } from './ai-assistant/api.js';
import { renderUserMessage, renderAssistantMessage, renderTypingIndicator, renderError, renderSuggestionChips, clearMessages, updateUsageBadge, renderRestoredMessages, renderHistoryList } from './ai-assistant/render.js';
import { AI_CONFIG } from './ai-assistant/config.js';
import { loadConversations, getActiveConversation, createConversation, addMessage, switchConversation, deleteConversation, getConversationList } from './ai-assistant/storage.js';

const state = {
    isOpen: false,
    isLoading: false,
    conversationHistory: [],
    activeConversationId: null,
    storageData: null,
    historyVisible: false,
};

function getElements() {
    return {
        widget: document.getElementById('ai-assistant-widget'),
        input: document.getElementById('ai-assistant-input'),
        sendBtn: document.getElementById('ai-assistant-send-btn'),
        charCount: document.getElementById('ai-assistant-char-count'),
        messagesArea: document.getElementById('ai-assistant-messages'),
        historyPanel: document.getElementById('ai-assistant-history'),
        suggestionsArea: document.getElementById('ai-assistant-suggestions'),
    };
}

function initStorage() {
    state.storageData = loadConversations();
    const active = getActiveConversation(state.storageData);

    if (active && active.messages.length > 0) {
        // Restore active conversation
        state.activeConversationId = state.storageData.activeConversationId;
        state.conversationHistory = active.messages.map(m => ({ role: m.role, content: m.content }));
        renderRestoredMessages(active.messages);
    } else {
        // Start a fresh conversation
        state.activeConversationId = createConversation(state.storageData);
    }
}

function togglePanel() {
    const { widget } = getElements();
    if (!widget) return;

    state.isOpen = !state.isOpen;
    widget.classList.toggle('hidden', !state.isOpen);

    // Prevent body scroll when modal is open
    document.body.style.overflow = state.isOpen ? 'hidden' : '';

    if (state.isOpen) {
        // Hide history if it was open
        if (state.historyVisible) toggleHistory();
        loadSuggestions();
        loadUsage();
        const { input } = getElements();
        if (input) setTimeout(() => input.focus(), 100);
    }
}

function toggleHistory() {
    const { messagesArea, historyPanel, suggestionsArea } = getElements();
    if (!messagesArea || !historyPanel) return;

    state.historyVisible = !state.historyVisible;

    if (state.historyVisible) {
        messagesArea.classList.add('hidden');
        if (suggestionsArea) suggestionsArea.classList.add('hidden');
        historyPanel.classList.remove('hidden');
        // Populate history list
        const convList = getConversationList(state.storageData);
        renderHistoryList(convList);
    } else {
        historyPanel.classList.add('hidden');
        messagesArea.classList.remove('hidden');
        if (suggestionsArea) suggestionsArea.classList.remove('hidden');
    }
}

function startNewChat() {
    state.conversationHistory = [];
    state.activeConversationId = createConversation(state.storageData);
    clearMessages();
    loadSuggestions();

    // If history panel is visible, switch back to messages
    if (state.historyVisible) toggleHistory();

    const { input } = getElements();
    if (input) {
        input.value = '';
        updateCharCount();
        input.focus();
    }
}

function loadConversationById(id) {
    if (!switchConversation(state.storageData, id)) return;

    state.activeConversationId = id;
    const conv = getActiveConversation(state.storageData);
    if (!conv) return;

    state.conversationHistory = conv.messages.map(m => ({ role: m.role, content: m.content }));
    renderRestoredMessages(conv.messages);

    // Switch back to messages view
    if (state.historyVisible) toggleHistory();
}

function deleteConversationById(id) {
    const wasActive = id === state.activeConversationId;
    deleteConversation(state.storageData, id);

    if (wasActive) {
        // Start a fresh conversation
        state.conversationHistory = [];
        state.activeConversationId = createConversation(state.storageData);
        clearMessages();
    }

    // Refresh history list
    const convList = getConversationList(state.storageData);
    renderHistoryList(convList);
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
    addMessage(state.storageData, 'user', message);

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
            addMessage(state.storageData, 'assistant', data.response, data.log_id);
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

    window.EventDelegation.register('ai-assistant-new-chat', () => {
        startNewChat();
    });

    window.EventDelegation.register('ai-assistant-history-toggle', () => {
        toggleHistory();
    });

    window.EventDelegation.register('ai-assistant-load-conv', (element) => {
        const convId = element.dataset.convId;
        if (convId) loadConversationById(convId);
    });

    window.EventDelegation.register('ai-assistant-delete-conv', (element) => {
        const convId = element.dataset.convId;
        if (convId) deleteConversationById(convId);
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
        initStorage();

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

        // Escape key closes modal
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && state.isOpen) {
                togglePanel();
            }
        });

        console.log('[AI Assistant] Initialized');
    }, {
        priority: 36,
        description: 'AI Assistant modal widget',
        reinitializable: true
    });
}
