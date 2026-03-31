// ai-assistant/render.js
import { escapeHtml } from '../utils/safe-html.js';

const messagesEl = () => document.getElementById('ai-assistant-messages');

function linkify(text) {
    // Convert markdown links [text](url) to clickable HTML links
    return text.replace(
        /\[([^\]]+)\]\(([^)]+)\)/g,
        '<a href="$2" class="text-ecs-green hover:underline font-medium">$1</a>'
    );
}

function simpleMarkdown(text) {
    let html = escapeHtml(text);
    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-xs">$1</code>');
    // Line breaks
    html = html.replace(/\n/g, '<br>');
    // Links (after escaping, restore markdown links)
    html = linkify(html);
    return html;
}

export function renderUserMessage(text) {
    const container = messagesEl();
    if (!container) return;

    const div = document.createElement('div');
    div.className = 'flex justify-end';
    div.innerHTML = `
        <div class="max-w-[80%] bg-ecs-green text-white rounded-2xl rounded-br-md px-4 py-2.5 text-sm">
            ${escapeHtml(text)}
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

export function renderAssistantMessage(text, logId) {
    const container = messagesEl();
    if (!container) return;

    // Remove typing indicator if present
    const typing = container.querySelector('#ai-typing-indicator');
    if (typing) typing.remove();

    const div = document.createElement('div');
    div.className = 'flex justify-start';
    div.innerHTML = `
        <div class="max-w-[85%]">
            <div class="bg-gray-100 dark:bg-gray-700 rounded-2xl rounded-bl-md px-4 py-2.5 text-sm text-gray-900 dark:text-gray-100 leading-relaxed">
                ${simpleMarkdown(text)}
            </div>
            ${logId ? `
            <div class="flex items-center gap-2 mt-1 ml-2">
                <button data-action="ai-assistant-rate" data-log-id="${logId}" data-rating="5"
                        class="text-gray-400 hover:text-green-500 transition-colors p-0.5" title="Helpful">
                    <i class="ti ti-thumb-up text-xs"></i>
                </button>
                <button data-action="ai-assistant-rate" data-log-id="${logId}" data-rating="1"
                        class="text-gray-400 hover:text-red-500 transition-colors p-0.5" title="Not helpful">
                    <i class="ti ti-thumb-down text-xs"></i>
                </button>
            </div>` : ''}
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

export function renderTypingIndicator() {
    const container = messagesEl();
    if (!container) return;

    const div = document.createElement('div');
    div.id = 'ai-typing-indicator';
    div.className = 'flex justify-start';
    div.innerHTML = `
        <div class="bg-gray-100 dark:bg-gray-700 rounded-2xl rounded-bl-md px-4 py-3 text-sm">
            <div class="flex gap-1">
                <span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0ms"></span>
                <span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 150ms"></span>
                <span class="w-2 h-2 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 300ms"></span>
            </div>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

export function renderError(message) {
    const container = messagesEl();
    if (!container) return;

    const typing = container.querySelector('#ai-typing-indicator');
    if (typing) typing.remove();

    const div = document.createElement('div');
    div.className = 'flex justify-start';
    div.innerHTML = `
        <div class="max-w-[85%] bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-2xl rounded-bl-md px-4 py-2.5 text-sm text-red-700 dark:text-red-300">
            <i class="ti ti-alert-circle mr-1"></i>${escapeHtml(message)}
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
}

export function renderSuggestionChips(suggestions) {
    const container = document.getElementById('ai-assistant-chips');
    if (!container) return;

    container.innerHTML = suggestions.map(text => `
        <button type="button" data-action="ai-assistant-chip" data-message="${escapeHtml(text)}"
                class="px-3 py-1.5 text-xs font-medium rounded-full border border-gray-200 dark:border-gray-600
                       text-gray-700 dark:text-gray-300 bg-white dark:bg-gray-700
                       hover:bg-ecs-green/10 hover:border-ecs-green hover:text-ecs-green transition-colors">
            ${escapeHtml(text)}
        </button>
    `).join('');
}

export function clearMessages() {
    const container = messagesEl();
    if (!container) return;

    container.innerHTML = `
        <div class="text-center text-sm text-gray-400 dark:text-gray-500 py-8">
            <i class="ti ti-sparkles text-3xl mb-2 block"></i>
            <p>Ask me anything about the portal</p>
        </div>
    `;
}

export function updateUsageBadge(daily, dailyLimit) {
    const badge = document.getElementById('ai-assistant-usage-badge');
    if (badge) {
        const remaining = dailyLimit - daily;
        badge.textContent = `${remaining} left today`;
    }
}
