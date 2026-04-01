// ai-assistant/storage.js - localStorage persistence for conversations
import { AI_CONFIG } from './config.js';

const EMPTY_STATE = { activeConversationId: null, conversations: {} };

function _read() {
    try {
        const raw = localStorage.getItem(AI_CONFIG.storageKey);
        if (!raw) return { ...EMPTY_STATE, conversations: {} };
        const data = JSON.parse(raw);
        if (!data || typeof data.conversations !== 'object') return { ...EMPTY_STATE, conversations: {} };
        return data;
    } catch {
        return { ...EMPTY_STATE, conversations: {} };
    }
}

function _write(data) {
    try {
        localStorage.setItem(AI_CONFIG.storageKey, JSON.stringify(data));
    } catch {
        // QuotaExceeded - prune oldest conversation and retry
        const ids = Object.keys(data.conversations);
        if (ids.length > 0) {
            ids.sort((a, b) => (data.conversations[a].updatedAt || 0) - (data.conversations[b].updatedAt || 0));
            delete data.conversations[ids[0]];
            if (data.activeConversationId === ids[0]) data.activeConversationId = null;
            try { localStorage.setItem(AI_CONFIG.storageKey, JSON.stringify(data)); } catch { /* give up */ }
        }
    }
}

export function loadConversations() {
    const data = _read();
    pruneOldConversations(data);
    return data;
}

export function getActiveConversation(data) {
    if (!data.activeConversationId) return null;
    return data.conversations[data.activeConversationId] || null;
}

export function createConversation(data) {
    const id = 'conv_' + crypto.randomUUID();
    const now = Date.now();
    data.conversations[id] = {
        id,
        title: '',
        createdAt: now,
        updatedAt: now,
        messages: [],
    };
    data.activeConversationId = id;
    _write(data);
    return id;
}

export function addMessage(data, role, content, logId) {
    const conv = data.conversations[data.activeConversationId];
    if (!conv) return;

    conv.messages.push({
        role,
        content,
        timestamp: Date.now(),
        ...(logId ? { logId } : {}),
    });
    conv.updatedAt = Date.now();

    // Auto-title from first user message
    if (!conv.title && role === 'user') {
        conv.title = content.length > 50 ? content.slice(0, 47) + '...' : content;
    }

    _write(data);
}

export function switchConversation(data, id) {
    if (data.conversations[id]) {
        data.activeConversationId = id;
        _write(data);
        return true;
    }
    return false;
}

export function deleteConversation(data, id) {
    delete data.conversations[id];
    if (data.activeConversationId === id) {
        data.activeConversationId = null;
    }
    _write(data);
}

export function getConversationList(data) {
    return Object.values(data.conversations)
        .map(conv => ({
            id: conv.id,
            title: conv.title || 'Untitled',
            updatedAt: conv.updatedAt,
            messageCount: conv.messages.length,
        }))
        .sort((a, b) => b.updatedAt - a.updatedAt);
}

function pruneOldConversations(data) {
    const maxAge = AI_CONFIG.maxConversationAgeDays * 24 * 60 * 60 * 1000;
    const cutoff = Date.now() - maxAge;
    const ids = Object.keys(data.conversations);

    // Remove expired
    for (const id of ids) {
        if (data.conversations[id].updatedAt < cutoff) {
            delete data.conversations[id];
            if (data.activeConversationId === id) data.activeConversationId = null;
        }
    }

    // Enforce max count (keep newest)
    const remaining = Object.values(data.conversations).sort((a, b) => b.updatedAt - a.updatedAt);
    if (remaining.length > AI_CONFIG.maxConversations) {
        for (const conv of remaining.slice(AI_CONFIG.maxConversations)) {
            delete data.conversations[conv.id];
            if (data.activeConversationId === conv.id) data.activeConversationId = null;
        }
    }

    _write(data);
}
