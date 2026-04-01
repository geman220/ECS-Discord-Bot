// ai-assistant/render.js
import { escapeHtml } from '../utils/safe-html.js';

const messagesEl = () => document.getElementById('ai-assistant-messages');

function linkify(text) {
    // Convert markdown links [text](url) to clickable HTML links
    return text.replace(
        /\[([^\]]+)\]\(([^)]+)\)/g,
        '<a href="$2" class="text-ecs-green dark:text-ecs-green-400 hover:underline font-medium">$1</a>'
    );
}

function simpleMarkdown(text) {
    const escaped = escapeHtml(text);
    const lines = escaped.split('\n');
    const result = [];
    let inUl = false;
    let inOl = false;

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];

        // Headers
        if (line.match(/^###\s+(.+)/)) {
            if (inUl) { result.push('</ul>'); inUl = false; }
            if (inOl) { result.push('</ol>'); inOl = false; }
            result.push(`<h4 class="font-semibold text-sm mt-3 mb-1">${line.replace(/^###\s+/, '')}</h4>`);
            continue;
        }
        if (line.match(/^##\s+(.+)/)) {
            if (inUl) { result.push('</ul>'); inUl = false; }
            if (inOl) { result.push('</ol>'); inOl = false; }
            result.push(`<h3 class="font-semibold text-base mt-3 mb-1">${line.replace(/^##\s+/, '')}</h3>`);
            continue;
        }

        // Unordered list items (- or *)
        const ulMatch = line.match(/^[-*]\s+(.+)/);
        if (ulMatch) {
            if (inOl) { result.push('</ol>'); inOl = false; }
            if (!inUl) { result.push('<ul class="list-disc list-inside ml-2 space-y-1 my-2">'); inUl = true; }
            result.push(`<li>${formatInline(ulMatch[1])}</li>`);
            continue;
        }

        // Ordered list items (1. 2. etc.)
        const olMatch = line.match(/^\d+\.\s+(.+)/);
        if (olMatch) {
            if (inUl) { result.push('</ul>'); inUl = false; }
            if (!inOl) { result.push('<ol class="list-decimal list-inside ml-2 space-y-1 my-2">'); inOl = true; }
            result.push(`<li>${formatInline(olMatch[1])}</li>`);
            continue;
        }

        // Close any open lists
        if (inUl) { result.push('</ul>'); inUl = false; }
        if (inOl) { result.push('</ol>'); inOl = false; }

        // Regular line
        if (line.trim() === '') {
            result.push('<br>');
        } else {
            result.push(formatInline(line));
            // Add <br> unless next line is a list/header/blank
            const next = lines[i + 1];
            if (next !== undefined && !next.match(/^[-*]\s/) && !next.match(/^\d+\.\s/) && !next.match(/^##/) && next.trim() !== '') {
                result.push('<br>');
            }
        }
    }

    if (inUl) result.push('</ul>');
    if (inOl) result.push('</ol>');

    return result.join('\n');
}

function formatInline(text) {
    let html = text;
    // Bold
    html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code class="px-1 py-0.5 bg-gray-100 dark:bg-gray-700 rounded text-xs">$1</code>');
    // Links
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
        <div class="max-w-[90%]">
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

export function renderRestoredMessages(messages) {
    const container = messagesEl();
    if (!container) return;

    // Clear the default placeholder
    container.innerHTML = '';

    for (const msg of messages) {
        const div = document.createElement('div');
        if (msg.role === 'user') {
            div.className = 'flex justify-end';
            div.innerHTML = `
                <div class="max-w-[80%] bg-ecs-green text-white rounded-2xl rounded-br-md px-4 py-2.5 text-sm">
                    ${escapeHtml(msg.content)}
                </div>
            `;
        } else {
            div.className = 'flex justify-start';
            div.innerHTML = `
                <div class="max-w-[90%]">
                    <div class="bg-gray-100 dark:bg-gray-700 rounded-2xl rounded-bl-md px-4 py-2.5 text-sm text-gray-900 dark:text-gray-100 leading-relaxed">
                        ${simpleMarkdown(msg.content)}
                    </div>
                    ${msg.logId ? `
                    <div class="flex items-center gap-2 mt-1 ml-2">
                        <button data-action="ai-assistant-rate" data-log-id="${msg.logId}" data-rating="5"
                                class="text-gray-400 hover:text-green-500 transition-colors p-0.5" title="Helpful">
                            <i class="ti ti-thumb-up text-xs"></i>
                        </button>
                        <button data-action="ai-assistant-rate" data-log-id="${msg.logId}" data-rating="1"
                                class="text-gray-400 hover:text-red-500 transition-colors p-0.5" title="Not helpful">
                            <i class="ti ti-thumb-down text-xs"></i>
                        </button>
                    </div>` : ''}
                </div>
            `;
        }
        container.appendChild(div);
    }

    container.scrollTop = container.scrollHeight;
}

function formatTimeAgo(timestamp) {
    const now = Date.now();
    const diff = now - timestamp;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (minutes < 1) return 'Just now';
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    if (days === 1) return 'Yesterday';
    if (days < 7) return `${days}d ago`;

    const date = new Date(timestamp);
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${months[date.getMonth()]} ${date.getDate()}`;
}

export function renderHistoryList(conversations) {
    const container = document.getElementById('ai-assistant-history-list');
    if (!container) return;

    if (conversations.length === 0) {
        container.innerHTML = `<p class="text-sm text-gray-400 dark:text-gray-500 text-center py-8">No previous conversations</p>`;
        return;
    }

    container.innerHTML = conversations.map(conv => `
        <div class="flex items-center gap-1">
            <button type="button" data-action="ai-assistant-load-conv" data-conv-id="${escapeHtml(conv.id)}"
                    class="flex-1 text-left p-3 rounded-lg hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors min-w-0">
                <p class="text-sm font-medium text-gray-900 dark:text-white truncate">${escapeHtml(conv.title)}</p>
                <p class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">${conv.messageCount} messages &middot; ${formatTimeAgo(conv.updatedAt)}</p>
            </button>
            <button type="button" data-action="ai-assistant-delete-conv" data-conv-id="${escapeHtml(conv.id)}"
                    class="flex-shrink-0 p-2 text-gray-400 hover:text-red-500 transition-colors rounded-lg" title="Delete">
                <i class="ti ti-trash text-sm"></i>
            </button>
        </div>
    `).join('');
}
