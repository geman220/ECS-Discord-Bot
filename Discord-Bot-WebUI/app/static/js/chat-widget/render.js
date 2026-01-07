/**
 * Chat Widget - Render Functions
 * DOM rendering for conversations, messages, and UI elements
 *
 * @module chat-widget/render
 */

import { CONFIG, EMOJI_MAP } from './config.js';
import { getState, getElements } from './state.js';

/**
 * Generate role badge HTML for a user
 * @param {Object} user - User object with role flags
 * @returns {string} HTML string with badge icons
 */
export function renderRoleBadges(user) {
  if (!user) return '';

  const badges = [];

  // Global Admin - Crown icon (highest priority)
  if (user.is_global_admin) {
    badges.push('<span class="c-chat-widget__role-badge c-chat-widget__role-badge--admin" title="Global Admin"><i class="ti ti-crown"></i></span>');
  }
  // Pub League Admin - Shield icon
  else if (user.is_admin) {
    badges.push('<span class="c-chat-widget__role-badge c-chat-widget__role-badge--admin" title="Admin"><i class="ti ti-shield-check"></i></span>');
  }

  // Coach - Whistle icon
  if (user.is_coach) {
    badges.push('<span class="c-chat-widget__role-badge c-chat-widget__role-badge--coach" title="Coach"><i class="ti ti-speakerphone"></i></span>');
  }

  // Referee - Cards icon
  if (user.is_ref) {
    badges.push('<span class="c-chat-widget__role-badge c-chat-widget__role-badge--ref" title="Referee"><i class="ti ti-cards"></i></span>');
  }

  return badges.length > 0 ? `<span class="c-chat-widget__role-badges">${badges.join('')}</span>` : '';
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

    return `
      <div class="c-chat-widget__conversation ${isActive ? 'c-chat-widget__conversation--active' : ''} ${isUnread ? 'c-chat-widget__conversation--unread' : ''}"
           data-user-id="${conv.user.id}"
           data-user-name="${escapeHtml(conv.user.name)}"
           data-avatar="${avatarUrl}"
           data-online="${isOnline}"
           data-is-coach="${conv.user.is_coach || false}"
           data-is-admin="${conv.user.is_admin || false}"
           data-is-global-admin="${conv.user.is_global_admin || false}"
           data-is-ref="${conv.user.is_ref || false}"
           role="button"
           tabindex="0">
        <div class="c-chat-widget__conv-avatar ${isOnline ? 'c-chat-widget__conv-avatar--online' : ''}">
          <img src="${avatarUrl}" alt="${escapeHtml(conv.user.name)}" onerror="this.src='${defaultAvatar}'">
        </div>
        <div class="c-chat-widget__conv-content">
          <div class="c-chat-widget__conv-header">
            <span class="c-chat-widget__conv-name">${escapeHtml(conv.user.name)}${roleBadges}</span>
            <span class="c-chat-widget__conv-time">${conv.last_message.time_ago}</span>
          </div>
          <div class="c-chat-widget__conv-preview">
            ${conv.last_message.sent_by_me ? 'You: ' : ''}${escapeHtml(conv.last_message.content)}
          </div>
        </div>
        ${isUnread ? `<div class="c-chat-widget__conv-badge">${conv.unread_count}</div>` : ''}
      </div>
    `;
  }).join('');

  elements.conversationList.innerHTML = html;
}

/**
 * Render messages in active conversation
 */
export function renderMessages() {
  const elements = getElements();
  const state = getState();

  if (!elements.messagesContainer) return;

  if (state.messages.length === 0) {
    elements.messagesContainer.innerHTML = `
      <div class="c-chat-widget__empty p-4">
        <i class="c-chat-widget__empty-icon ti ti-message-2"></i>
        <div class="c-chat-widget__empty-text">No messages yet. Say hello!</div>
      </div>
    `;
    return;
  }

  const currentUserId = getCurrentUserId();

  const html = state.messages.map(msg => {
    const isSent = msg.sender_id === currentUserId;
    const isDeleted = msg.is_deleted;

    // Deleted message placeholder
    if (isDeleted) {
      return `
        <div class="c-chat-widget__message c-chat-widget__message--${isSent ? 'sent' : 'received'} c-chat-widget__message--deleted"
             data-message-id="${msg.id}">
          <div class="c-chat-widget__message-bubble c-chat-widget__message-bubble--deleted">
            <i class="ti ti-message-off me-2 opacity-75"></i>
            ${isSent ? 'You unsent a message' : 'This message was unsent'}
          </div>
          <span class="c-chat-widget__message-time">
            ${formatMessageTime(msg.created_at)}
          </span>
        </div>
      `;
    }

    // Convert emoji shortcodes
    const contentWithEmojis = convertEmojiShortcodes(escapeHtml(msg.content));

    return `
      <div class="c-chat-widget__message c-chat-widget__message--${isSent ? 'sent' : 'received'}"
           data-message-id="${msg.id}"
           data-sender-id="${msg.sender_id}">
        <div class="c-chat-widget__message-actions">
          <button class="c-chat-widget__message-action-btn" data-action="delete-menu" title="Delete message">
            <i class="ti ti-trash"></i>
          </button>
        </div>
        <div class="c-chat-widget__message-bubble">
          ${contentWithEmojis}
        </div>
        <span class="c-chat-widget__message-time">
          ${formatMessageTime(msg.created_at)}
          ${isSent && msg.is_read ? '<i class="ti ti-checks chat-read-indicator"></i>' : ''}
        </span>
      </div>
    `;
  }).join('');

  elements.messagesContainer.innerHTML = html;
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
      <div class="c-chat-widget__search-result"
           data-user-id="${user.id}"
           data-user-name="${escapeHtml(user.name)}"
           data-avatar="${avatarUrl}"
           data-online="${user.is_online || false}"
           data-is-coach="${user.is_coach || false}"
           data-is-admin="${user.is_admin || false}"
           data-is-global-admin="${user.is_global_admin || false}"
           data-is-ref="${user.is_ref || false}"
           role="button"
           tabindex="0">
        <div class="c-chat-widget__search-result-avatar">
          <img src="${avatarUrl}" alt="${escapeHtml(user.name)}" onerror="this.src='${defaultAvatar}'">
        </div>
        <span class="c-chat-widget__search-result-name">${escapeHtml(user.name)}${roleBadges}</span>
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
      <div class="c-chat-widget__online-user"
           data-user-id="${user.id}"
           data-user-name="${escapeHtml(user.name)}"
           data-avatar="${avatarUrl}"
           data-online="true"
           role="button"
           tabindex="0">
        <div class="c-chat-widget__online-avatar">
          <img src="${avatarUrl}" alt="${escapeHtml(user.name)}" onerror="this.src='${defaultAvatar}'">
        </div>
        <span class="c-chat-widget__online-name">${escapeHtml(user.name.split(' ')[0])}</span>
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
 * Update send button enabled state
 */
export function updateSendButton() {
  const elements = getElements();

  if (!elements.sendBtn || !elements.composerInput) return;

  const hasContent = elements.composerInput.value.trim().length > 0;
  elements.sendBtn.disabled = !hasContent;
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
      <div class="d-flex justify-content-center p-5">
        <div class="c-chat-widget__typing-dots">
          <span class="c-chat-widget__typing-dot"></span>
          <span class="c-chat-widget__typing-dot"></span>
          <span class="c-chat-widget__typing-dot"></span>
        </div>
      </div>
    `;
  }
}

export default {
  renderRoleBadges,
  convertEmojiShortcodes,
  renderConversations,
  renderMessages,
  renderSearchResults,
  renderOnlineUsers,
  updateBadge,
  updateSendButton,
  formatMessageTime,
  getCurrentUserId,
  showMessagesLoading
};
