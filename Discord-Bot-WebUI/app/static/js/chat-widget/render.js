/**
 * Chat Widget - Render Functions
 * DOM rendering for conversations, messages, and UI elements
 *
 * @module chat-widget/render
 */

import { CONFIG, EMOJI_MAP } from './config.js';
import { getState, getElements } from './state.js';

/**
 * Escape HTML special characters to prevent XSS.
 * Escapes quotes too so the result is safe inside attribute values,
 * which the old textContent/innerHTML trick was not.
 * @param {string} str - String to escape
 * @returns {string} Escaped string
 */
const HTML_ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export function escapeHtml(str) {
  if (str == null) return '';
  return String(str).replace(/[&<>"']/g, ch => HTML_ESCAPES[ch]);
}

/**
 * Generate role badge HTML for a user
 * @param {Object} user - User object with role flags
 * @returns {string} HTML string with badge icons
 */
export function renderRoleBadges(user) {
  if (!user) return '';

  const badgeBase = 'inline-flex h-[18px] w-[18px] items-center justify-center rounded text-[11px] leading-none';
  const badges = [];

  // Global Admin - Crown icon (highest priority)
  if (user.is_global_admin) {
    badges.push(`<span class="${badgeBase} bg-ecs-blue-600 text-ecs-gold-300" title="Global Admin"><i class="ti ti-crown"></i></span>`);
  }
  // Pub League Admin - Shield icon
  else if (user.is_admin) {
    badges.push(`<span class="${badgeBase} bg-ecs-blue-600 text-ecs-gold-300" title="Admin"><i class="ti ti-shield-check"></i></span>`);
  }

  // Coach - Whistle icon
  if (user.is_coach) {
    badges.push(`<span class="${badgeBase} bg-ecs-green text-white" title="Coach"><i class="ti ti-speakerphone"></i></span>`);
  }

  // Referee - Cards icon
  if (user.is_ref) {
    badges.push(`<span class="${badgeBase} bg-amber-400 text-gray-900" title="Referee"><i class="ti ti-cards"></i></span>`);
  }

  return badges.length > 0 ? `<span class="ml-1.5 inline-flex items-center gap-1 align-middle">${badges.join('')}</span>` : '';
}

/**
 * Convert emoji shortcodes to actual emojis
 * @param {string} text - Text with shortcodes
 * @returns {string} Text with emojis
 */
export function convertEmojiShortcodes(text) {
  if (!text) return text;

  let result = text;
  for (const [shortcode, emoji] of Object.entries(EMOJI_MAP)) {
    // Escape special regex characters in the shortcode
    const escaped = shortcode.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    result = result.replace(new RegExp(escaped, 'g'), emoji);
  }
  return result;
}

/**
 * Render conversation list
 */
export function renderConversations() {
  const elements = getElements();
  const state = getState();

  if (!elements.conversationList) return;

  if (state.conversations.length === 0) {
    elements.conversationList.innerHTML = '';
    if (elements.emptyState) {
      elements.emptyState.style.display = 'flex';
    }
    return;
  }

  if (elements.emptyState) {
    elements.emptyState.style.display = 'none';
  }

  const defaultAvatar = CONFIG.ui.defaultAvatar;

  const html = state.conversations.map(conv => {
    const isActive = state.activeConversation?.id === conv.user.id;
    const isUnread = conv.unread_count > 0;
    const isOnline = conv.user.is_online;
    const avatarUrl = conv.user.avatar_url || defaultAvatar;
    const roleBadges = renderRoleBadges(conv.user);

    const rowState = isActive
      ? 'bg-ecs-green-50 dark:bg-ecs-green-900/20'
      : isUnread
        ? 'bg-ecs-green-50/50 dark:bg-ecs-green-900/10'
        : '';

    return `
      <div class="c-chat-widget__conversation flex cursor-pointer items-center gap-3 px-4 py-3 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ecs-green dark:hover:bg-gray-700/60 ${rowState}"
           data-user-id="${conv.user.id}"
           data-user-name="${escapeHtml(conv.user.name)}"
           data-avatar="${escapeHtml(avatarUrl)}"
           data-online="${isOnline}"
           data-is-coach="${conv.user.is_coach || false}"
           data-is-admin="${conv.user.is_admin || false}"
           data-is-global-admin="${conv.user.is_global_admin || false}"
           data-is-ref="${conv.user.is_ref || false}"
           role="button"
           tabindex="0">
        <div class="c-chat-widget__conv-avatar relative h-12 w-12 shrink-0 rounded-full ${isOnline ? 'c-chat-widget__conv-avatar--online' : ''}">
          <img class="h-full w-full rounded-full object-cover" src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(conv.user.name)}" onerror="this.src='${defaultAvatar}'">
        </div>
        <div class="min-w-0 flex-1">
          <div class="mb-0.5 flex items-center justify-between gap-2">
            <span class="truncate text-[15px] ${isUnread ? 'font-bold' : 'font-semibold'} text-gray-900 dark:text-white">${escapeHtml(conv.user.name)}${roleBadges}</span>
            <span class="shrink-0 text-xs text-gray-500 dark:text-gray-400">${conv.last_message.time_ago}</span>
          </div>
          <div class="flex items-center gap-1 text-[13px] ${isUnread ? 'font-medium text-gray-900 dark:text-white' : 'text-gray-500 dark:text-gray-400'}">
            ${conv.last_message.sent_by_me ? `<span class="shrink-0 text-gray-500 dark:text-gray-400">You:</span>` : ''}
            <span class="truncate">${escapeHtml(conv.last_message.content)}</span>
            ${conv.last_message.sent_by_me && conv.last_message.is_read ? '<i class="ti ti-checks ml-auto shrink-0 text-xs text-ecs-green" title="Read"></i>' : ''}
            ${conv.last_message.sent_by_me && !conv.last_message.is_read ? '<i class="ti ti-check ml-auto shrink-0 text-xs text-gray-400 dark:text-gray-500" title="Sent"></i>' : ''}
          </div>
        </div>
        ${isUnread ? `<div class="flex h-5 min-w-[1.25rem] shrink-0 items-center justify-center rounded-full bg-ecs-green px-1.5 text-xs font-semibold text-white">${conv.unread_count}</div>` : ''}
      </div>
    `;
  }).join('');

  elements.conversationList.innerHTML = html;
}

/**
 * Render messages in active conversation
 * @param {boolean} isPrepending - Whether we're prepending older messages
 */
export function renderMessages(isPrepending = false) {
  const elements = getElements();
  const state = getState();

  if (!elements.messagesContainer) return;

  // Remember scroll position if prepending
  let scrollHeight = 0;
  if (isPrepending) {
    scrollHeight = elements.messagesContainer.scrollHeight;
  }

  if (state.messages.length === 0) {
    elements.messagesContainer.innerHTML = `
      <div class="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
        <i class="ti ti-message-2 text-4xl text-gray-300 dark:text-gray-600"></i>
        <div class="text-sm text-gray-500 dark:text-gray-400">No messages yet. Say hello!</div>
      </div>
    `;
    return;
  }

  const currentUserId = getCurrentUserId();

  // Build load more button if there are more messages
  const loadMoreBtn = state.hasMoreMessages ? `
    <div class="flex justify-center py-2">
      <button class="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-4 py-1.5 text-xs font-medium text-gray-500 transition-colors hover:border-ecs-green hover:text-gray-900 disabled:cursor-not-allowed disabled:opacity-60 dark:border-gray-600 dark:bg-gray-700 dark:text-gray-300 dark:hover:border-ecs-green dark:hover:text-white"
              data-action="load-more-messages" ${state.isLoadingMore ? 'disabled' : ''}>
        ${state.isLoadingMore ? '<i class="ti ti-loader-2 animate-spin"></i> Loading...' : '<i class="ti ti-history"></i> Load earlier messages'}
      </button>
    </div>
  ` : '';

  const dividerLine = '<span class="h-px flex-1 bg-gray-200 dark:bg-gray-700"></span>';
  let lastDayKey = null;

  const messagesHtml = state.messages.map(msg => {
    const isSent = msg.sender_id === currentUserId;
    const isDeleted = msg.is_deleted;
    const isPending = msg.is_pending;
    const isFailed = msg.is_failed;

    // Day separator between messages from different days
    let daySeparator = '';
    const msgDate = msg.created_at ? new Date(msg.created_at) : new Date();
    if (!isNaN(msgDate)) {
      const dayKey = msgDate.toDateString();
      if (dayKey !== lastDayKey) {
        lastDayKey = dayKey;
        daySeparator = `
          <div class="my-2 flex items-center gap-3 text-[11px] font-medium uppercase tracking-wide text-gray-400 dark:text-gray-500">
            ${dividerLine}<span>${formatDayLabel(msgDate)}</span>${dividerLine}
          </div>
        `;
      }
    }

    const alignment = isSent ? 'self-end' : 'self-start';
    const timeAlignment = isSent ? 'self-end' : '';

    // Deleted message placeholder
    if (isDeleted) {
      return `
        ${daySeparator}
        <div class="c-chat-widget__message flex w-fit max-w-[80%] flex-col opacity-70 ${alignment}"
             data-message-id="${msg.id}">
          <div class="flex items-center rounded-2xl bg-gray-100 px-3.5 py-2.5 text-[13px] italic text-gray-500 dark:bg-gray-700/60 dark:text-gray-400">
            <i class="ti ti-message-off me-2 opacity-75"></i>
            ${isSent ? 'You unsent a message' : 'This message was unsent'}
          </div>
          <span class="mt-1 px-1 text-[11px] text-gray-400 dark:text-gray-500 ${timeAlignment}">
            ${formatMessageTime(msg.created_at)}
          </span>
        </div>
      `;
    }

    // Convert emoji shortcodes
    const contentWithEmojis = convertEmojiShortcodes(escapeHtml(msg.content));

    // Bubble styling by direction + state
    let bubbleClasses = isSent
      ? 'rounded-2xl rounded-br-md bg-ecs-green text-white'
      : 'rounded-2xl rounded-bl-md bg-gray-100 text-gray-900 dark:bg-gray-700 dark:text-white';
    if (isPending) {
      bubbleClasses += ' opacity-70';
    } else if (isFailed) {
      bubbleClasses = 'rounded-2xl border border-dashed border-red-400 bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300';
    }

    // Status indicator for pending/failed
    let statusIndicator = '';
    if (isPending) {
      statusIndicator = '<i class="ti ti-clock ml-1 animate-pulse text-xs text-gray-400 dark:text-gray-500" title="Sending..."></i>';
    } else if (isFailed) {
      statusIndicator = '<i class="ti ti-alert-circle ml-1 text-xs text-red-500" title="Failed to send - tap to retry"></i>';
    } else if (isSent && msg.is_read) {
      statusIndicator = '<i class="ti ti-checks ml-1 text-xs text-ecs-green" title="Read"></i>';
    } else if (isSent) {
      statusIndicator = '<i class="ti ti-check ml-1 text-xs text-gray-400 dark:text-gray-500" title="Sent"></i>';
    }

    const actionPosition = isSent
      ? '-left-8 max-sm:left-auto max-sm:right-full max-sm:mr-1'
      : '-right-8 max-sm:right-auto max-sm:left-full max-sm:ml-1';

    return `
      ${daySeparator}
      <div class="c-chat-widget__message group/msg relative flex w-fit max-w-[80%] flex-col ${alignment} ${isFailed ? 'cursor-pointer' : ''}"
           data-message-id="${msg.id}"
           data-sender-id="${msg.sender_id}"
           ${isFailed ? 'data-action="retry-message"' : ''}>
        ${!isPending && !isFailed ? `
        <div class="invisible absolute top-1/2 z-[5] -translate-y-1/2 opacity-0 transition-opacity focus-within:visible focus-within:opacity-100 group-hover/msg:visible group-hover/msg:opacity-100 max-sm:visible max-sm:opacity-100 ${actionPosition}">
          <button class="flex h-7 w-7 items-center justify-center rounded-full bg-gray-100 text-gray-500 transition-colors hover:bg-red-100 hover:text-red-600 dark:bg-gray-700 dark:text-gray-400 dark:hover:bg-red-900/40 dark:hover:text-red-400"
                  data-action="delete-menu" title="Delete message">
            <i class="ti ti-trash text-sm"></i>
          </button>
        </div>
        ` : ''}
        <div class="px-3.5 py-2.5 text-sm leading-snug [word-break:break-word] ${bubbleClasses}">
          ${contentWithEmojis}
        </div>
        <span class="mt-1 px-1 text-[11px] text-gray-400 dark:text-gray-500 ${timeAlignment}">
          ${formatMessageTime(msg.created_at)}
          ${statusIndicator}
        </span>
      </div>
    `;
  }).join('');

  // Combine load more button with messages
  elements.messagesContainer.innerHTML = loadMoreBtn + messagesHtml;

  // Restore scroll position after prepending
  if (isPrepending && scrollHeight > 0) {
    const newScrollHeight = elements.messagesContainer.scrollHeight;
    elements.messagesContainer.scrollTop = newScrollHeight - scrollHeight;
  }
}

/**
 * Render search results dropdown
 */
export function renderSearchResults() {
  const elements = getElements();
  const state = getState();

  if (!elements.searchResults) {
    console.warn('[ChatWidget] Search results element not found');
    return;
  }

  if (state.searchResults.length === 0) {
    console.log('[ChatWidget] No search results, hiding dropdown');
    elements.searchResults.classList.remove('is-visible');
    elements.searchResults.innerHTML = '';
    return;
  }

  console.log('[ChatWidget] Rendering', state.searchResults.length, 'search results');
  const defaultAvatar = CONFIG.ui.defaultAvatar;

  const html = state.searchResults.map(user => {
    const avatarUrl = user.avatar_url || defaultAvatar;
    const roleBadges = renderRoleBadges(user);
    return `
      <div class="c-chat-widget__search-result flex cursor-pointer items-center gap-2.5 px-3 py-2.5 transition-colors hover:bg-gray-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ecs-green dark:hover:bg-gray-600"
           data-user-id="${user.id}"
           data-user-name="${escapeHtml(user.name)}"
           data-avatar="${escapeHtml(avatarUrl)}"
           data-online="${user.is_online || false}"
           data-is-coach="${user.is_coach || false}"
           data-is-admin="${user.is_admin || false}"
           data-is-global-admin="${user.is_global_admin || false}"
           data-is-ref="${user.is_ref || false}"
           role="button"
           tabindex="0">
        <div class="h-8 w-8 shrink-0 overflow-hidden rounded-full">
          <img class="h-full w-full object-cover" src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(user.name)}" onerror="this.src='${defaultAvatar}'">
        </div>
        <span class="truncate text-sm font-medium text-gray-900 dark:text-white">${escapeHtml(user.name)}${roleBadges}</span>
      </div>
    `;
  }).join('');

  elements.searchResults.innerHTML = html;
  elements.searchResults.classList.add('is-visible');
  console.log('[ChatWidget] Search results dropdown visible');
}

/**
 * Render online users list
 * @param {Array} users - Online users array
 */
export function renderOnlineUsers(users) {
  const elements = getElements();

  if (!elements.onlineList) return;

  const onlineSection = elements.onlineList.closest('.c-chat-widget__online');

  if (!users || users.length === 0) {
    if (onlineSection) onlineSection.classList.add('u-hidden');
    return;
  }

  if (onlineSection) onlineSection.classList.remove('u-hidden');

  const defaultAvatar = CONFIG.ui.defaultAvatar;

  const html = users.slice(0, 8).map(user => {
    const avatarUrl = user.avatar_url || defaultAvatar;
    return `
      <div class="c-chat-widget__online-user flex shrink-0 cursor-pointer flex-col items-center gap-1 focus-visible:outline-none"
           data-user-id="${user.id}"
           data-user-name="${escapeHtml(user.name)}"
           data-avatar="${escapeHtml(avatarUrl)}"
           data-online="true"
           role="button"
           tabindex="0">
        <div class="c-chat-widget__online-avatar relative h-11 w-11 rounded-full ring-2 ring-transparent transition-shadow hover:ring-ecs-green">
          <img class="h-full w-full rounded-full object-cover" src="${escapeHtml(avatarUrl)}" alt="${escapeHtml(user.name)}" onerror="this.src='${defaultAvatar}'">
        </div>
        <span class="max-w-[56px] truncate text-center text-[11px] text-gray-500 dark:text-gray-400">${escapeHtml(user.name.split(' ')[0])}</span>
      </div>
    `;
  }).join('');

  elements.onlineList.innerHTML = html;
}

/**
 * Update unread badge display
 */
export function updateBadge() {
  const elements = getElements();
  const state = getState();

  if (!elements.badge) return;

  if (state.unreadCount > 0) {
    elements.badge.textContent = state.unreadCount > 99 ? '99+' : state.unreadCount;
    elements.badge.dataset.count = state.unreadCount;
    elements.badge.style.display = '';
  } else {
    elements.badge.style.display = 'none';
    elements.badge.dataset.count = '0';
  }

  // Also update navbar badge if it exists
  const navbarBadge = document.querySelector('[data-badge="messages-count"]');
  if (navbarBadge) {
    navbarBadge.textContent = state.unreadCount > 99 ? '99+' : state.unreadCount;
    navbarBadge.classList.toggle('u-hidden', state.unreadCount === 0);
  }
}

/**
 * Update send button enabled state + character counter near the limit
 */
export function updateSendButton() {
  const elements = getElements();

  if (!elements.sendBtn || !elements.composerInput) return;

  const value = elements.composerInput.value;
  elements.sendBtn.disabled = value.trim().length === 0;

  // Show remaining-characters hint once within 200 of the limit
  if (elements.charCounter) {
    const remaining = CONFIG.ui.maxMessageLength - value.length;
    if (remaining <= 200) {
      elements.charCounter.textContent = `${remaining} left`;
      elements.charCounter.classList.toggle('text-red-500', remaining <= 50);
      elements.charCounter.style.display = '';
    } else {
      elements.charCounter.style.display = 'none';
    }
  }
}

/**
 * Format message time for display
 * @param {string} isoString - ISO timestamp
 * @returns {string} Formatted time
 */
export function formatMessageTime(isoString) {
  if (!isoString) return '';

  const date = new Date(isoString);
  const now = new Date();
  const diff = now - date;

  // Today: show time
  if (diff < 86400000 && date.getDate() === now.getDate()) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  // Yesterday
  if (diff < 172800000) {
    return 'Yesterday';
  }

  // This week: show day name
  if (diff < 604800000) {
    return date.toLocaleDateString([], { weekday: 'short' });
  }

  // Older: show date
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

/**
 * Format a date as a day-separator label (Today / Yesterday / weekday / date)
 * @param {Date} date - Message date
 * @returns {string} Label
 */
export function formatDayLabel(date) {
  const now = new Date();
  const startOfDay = d => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86400000);

  if (dayDiff === 0) return 'Today';
  if (dayDiff === 1) return 'Yesterday';
  if (dayDiff < 7) return date.toLocaleDateString([], { weekday: 'long' });
  const opts = { month: 'short', day: 'numeric' };
  if (date.getFullYear() !== now.getFullYear()) opts.year = 'numeric';
  return date.toLocaleDateString([], opts);
}

/**
 * Get current user ID from various sources
 * @returns {number|null}
 */
export function getCurrentUserId() {
  // Try to get from global or meta tag
  if (window.currentUserId) return parseInt(window.currentUserId);

  const meta = document.querySelector('meta[name="user-id"]');
  if (meta) return parseInt(meta.content);

  // Try from session data
  const sessionData = document.querySelector('[data-user-id]');
  if (sessionData) return parseInt(sessionData.dataset.userId);

  return null;
}

/**
 * Show loading state in messages container
 */
export function showMessagesLoading() {
  const elements = getElements();

  if (elements.messagesContainer) {
    elements.messagesContainer.innerHTML = `
      <div class="flex justify-center p-5">
        <div class="flex gap-1">
          <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 dark:bg-gray-500"></span>
          <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:150ms] dark:bg-gray-500"></span>
          <span class="h-1.5 w-1.5 animate-bounce rounded-full bg-gray-400 [animation-delay:300ms] dark:bg-gray-500"></span>
        </div>
      </div>
    `;
  }
}

/**
 * Render connection status indicator
 */
export function renderConnectionStatus() {
  const state = getState();
  const elements = getElements();

  // Find or create status indicator
  let statusEl = document.querySelector('.c-chat-widget__connection-status');

  if (!statusEl && elements.panel) {
    // Create status element in panel header
    statusEl = document.createElement('div');
    statusEl.className = 'c-chat-widget__connection-status';
    const header = elements.panel.querySelector('.c-chat-widget__header');
    if (header) {
      header.appendChild(statusEl);
    }
  }

  if (!statusEl) return;

  const baseClass = 'c-chat-widget__connection-status ml-auto items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium';

  if (state.isConnected) {
    statusEl.innerHTML = '';
    statusEl.className = `${baseClass} hidden`;
  } else if (state.isReconnecting) {
    statusEl.innerHTML = '<i class="ti ti-loader-2 animate-spin"></i> Reconnecting...';
    statusEl.className = `${baseClass} flex bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300`;
  } else {
    statusEl.innerHTML = '<i class="ti ti-wifi-off"></i> Offline';
    statusEl.className = `${baseClass} flex bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300`;
  }
}

/**
 * Render message search results
 */
export function renderMessageSearchResults() {
  const state = getState();
  const elements = getElements();

  // Would need a dedicated element for message search results
  // For now, just log
  console.log('[ChatWidget] Message search results:', state.messageSearchResults.length);
}

export default {
  escapeHtml,
  renderRoleBadges,
  convertEmojiShortcodes,
  renderConversations,
  renderMessages,
  renderSearchResults,
  renderOnlineUsers,
  updateBadge,
  updateSendButton,
  formatMessageTime,
  formatDayLabel,
  getCurrentUserId,
  showMessagesLoading,
  renderConnectionStatus,
  renderMessageSearchResults
};
