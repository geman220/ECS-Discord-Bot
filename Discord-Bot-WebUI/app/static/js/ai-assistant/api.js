// ai-assistant/api.js
import { AI_CONFIG } from './config.js';

export async function askQuestion(message, conversationHistory, currentPageUrl) {
    const response = await fetch(AI_CONFIG.askUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            message,
            conversation_history: conversationHistory.slice(-AI_CONFIG.maxHistoryTurns * 2),
            current_page_url: currentPageUrl,
        }),
    });

    return response.json();
}

export async function getSuggestions() {
    const response = await fetch(`${AI_CONFIG.suggestionsUrl}?page=${encodeURIComponent(window.location.pathname)}`);
    return response.json();
}

export async function getUsage() {
    const response = await fetch(AI_CONFIG.usageUrl);
    return response.json();
}

export async function rateResponse(logId, rating) {
    const response = await fetch(AI_CONFIG.rateUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ log_id: logId, rating }),
    });
    return response.json();
}
