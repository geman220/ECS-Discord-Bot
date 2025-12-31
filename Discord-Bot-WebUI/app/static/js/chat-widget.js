/**
 * ==========================================================================
 * CHAT WIDGET - Floating Messenger Component
 * ==========================================================================
 *
 * Facebook Messenger-inspired floating chat widget with:
 * - Conversation list view
 * - Active chat view
 * - Real-time WebSocket updates
 * - Mobile-first responsive design
 * - Smart positioning
 *
 * CSS: /static/css/components/c-chat-widget.css
 * Uses BEM naming: .c-chat-widget__*
 *
 * @requires Socket.IO (for real-time messaging)
 * @requires /api/messages endpoints
 */
// ES Module
'use strict';

// ============================================================================
  // CONFIGURATION
  // ============================================================================

  export const CONFIG = {
    api: {
      conversations: '/api/messages',
      messages: (userId) => `/api/messages/${userId}`,
      send: (userId) => `/api/messages/${userId}`,
      unreadCount: '/api/messages/unread-count',
      searchUsers: '/api/messages/users/search',
      markRead: (msgId) => `/api/messages/${msgId}/read`
    },
    polling: {
      enabled: true,
      interval: 30000
    },
    ui: {
      animationDuration: 250,
      typingDebounce: 2000,
      searchDebounce: 300,
      maxMessageLength: 2000
    }
  };

  // ============================================================================
  // STATE
  // ============================================================================

  let _initialized = false;

  const state = {
    isOpen: false,
    currentView: 'list', // 'list' | 'chat'
    activeConversation: null,
    conversations: [],
    messages: [],
    unreadCount: 0,
    onlineUsers: [],
    isTyping: false,
    typingTimeout: null,
    searchQuery: '',
    searchResults: [],
    settings: {
      typingIndicators: true,
      readReceipts: true,
      maxMessageLength: 2000
    }
  };

  // ============================================================================
  // DOM ELEMENTS
  // ============================================================================

  let elements = {};

  export function cacheElements() {
    elements = {
      widget: document.querySelector('.c-chat-widget'),
      trigger: document.querySelector('.c-chat-widget__trigger'),
      badge: document.querySelector('.c-chat-widget__badge'),
      panel: document.querySelector('.c-chat-widget__panel'),

      // List view
      listView: document.querySelector('.c-chat-widget__list-view'),
      searchInput: document.querySelector('.c-chat-widget__search-input'),
      searchResults: document.querySelector('.c-chat-widget__search-results'),
      onlineList: document.querySelector('.c-chat-widget__online-list'),
      conversationList: document.querySelector('.c-chat-widget__conversations'),
      emptyState: document.querySelector('.c-chat-widget__empty'),

      // Chat view
      chatView: document.querySelector('.c-chat-widget__chat'),
      backBtn: document.querySelector('.c-chat-widget__back-btn'),
      chatAvatar: document.querySelector('.c-chat-widget__chat-avatar img'),
      chatAvatarContainer: document.querySelector('.c-chat-widget__chat-avatar'),
      chatName: document.querySelector('.c-chat-widget__chat-name'),
      chatStatus: document.querySelector('.c-chat-widget__chat-status'),
      messagesContainer: document.querySelector('.c-chat-widget__messages'),
      typingIndicator: document.querySelector('.c-chat-widget__typing'),
      composerInput: document.querySelector('.c-chat-widget__composer-input'),
      sendBtn: document.querySelector('.c-chat-widget__send-btn'),

      // Header buttons
      newChatBtn: document.querySelector('[data-action="new-chat"]'),
      openInboxBtn: document.querySelector('[data-action="open-inbox"]'),
      closeBtns: document.querySelectorAll('[data-action="close-widget"]')
    };
  }

  // ============================================================================
  // API FUNCTIONS
  // ============================================================================

  export function getCSRFToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  async function fetchJSON(url, options = {}) {
    try {
      const headers = {
        'Content-Type': 'application/json',
        ...options.headers
      };

      // Add CSRF token for non-GET requests
      if (options.method && options.method !== 'GET') {
        headers['X-CSRFToken'] = getCSRFToken();
      }

      const response = await fetch(url, { ...options, headers });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      return await response.json();
    } catch (error) {
      console.error(`[window.ChatWidget] API Error: ${url}`, error);
      throw error;
    }
  }

  async function loadConversations() {
    try {
      const data = await fetchJSON(CONFIG.api.conversations);
      if (data.success) {
        state.conversations = data.conversations || [];
        renderConversations();
      }
    } catch (error) {
      console.error('[ChatWidget] Failed to load conversations', error);
    }
  }

  async function loadMessages(userId) {
    try {
      const data = await fetchJSON(CONFIG.api.messages(userId));
      if (data.success) {
        state.messages = data.messages || [];
        state.settings = { ...state.settings, ...data.settings };
        renderMessages();
        scrollToBottom();

        // Update unread count after reading messages
        loadUnreadCount();
      }
    } catch (error) {
      console.error('[ChatWidget] Failed to load messages', error);
    }
  }

  async function sendMessage(userId, content) {
    try {
      const data = await fetchJSON(CONFIG.api.send(userId), {
        method: 'POST',
        body: JSON.stringify({ content })
      });

      if (data.success) {
        // Add message to local state
        state.messages.push(data.message);
        renderMessages();
        scrollToBottom();

        // Clear input
        if (elements.composerInput) {
          elements.composerInput.value = '';
          elements.composerInput.style.height = 'auto';
          updateSendButton();
        }

        // Update conversation list
        loadConversations();
      }

      return data;
    } catch (error) {
      console.error('[ChatWidget] Failed to send message', error);
      window.showToast('Failed to send message', 'error');
      throw error;
    }
  }

  async function loadUnreadCount() {
    try {
      const data = await fetchJSON(CONFIG.api.unreadCount);
      if (data.success) {
        state.unreadCount = data.count;
        updateBadge();
      }
    } catch (error) {
      console.error('[ChatWidget] Failed to load unread count', error);
    }
  }

  async function searchUsers(query) {
    if (query.length < 2) {
      state.searchResults = [];
      renderSearchResults();
      return;
    }

    console.log('[ChatWidget] Searching users for:', query);

    try {
      const data = await fetchJSON(`${CONFIG.api.searchUsers}?q=${encodeURIComponent(query)}`);
      console.log('[ChatWidget] Search response:', data);

      if (data.success) {
        state.searchResults = data.users || [];
        renderSearchResults();
        console.log('[ChatWidget] Found', state.searchResults.length, 'users');
      } else {
        console.warn('[ChatWidget] Search returned success=false:', data.error);
        state.searchResults = [];
        renderSearchResults();
      }
    } catch (error) {
      console.error('[ChatWidget] Failed to search users', error);
      state.searchResults = [];
      renderSearchResults();
    }
  }

  // ============================================================================
  // RENDER FUNCTIONS
  // ============================================================================

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

  export function renderConversations() {
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

    const defaultAvatar = '/static/img/default_player.png';

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
            <img src="${avatarUrl}" alt="${window.escapeHtml(conv.user.name)}" onerror="this.src='${defaultAvatar}'">
          </div>
          <div class="c-chat-widget__conv-content">
            <div class="c-chat-widget__conv-header">
              <span class="c-chat-widget__conv-name">${escapeHtml(conv.user.name)}${roleBadges}</span>
              <span class="c-chat-widget__conv-time">${conv.last_message.time_ago}</span>
            </div>
            <div class="c-chat-widget__conv-preview">
              ${conv.last_message.sent_by_me ? 'You: ' : ''}${window.escapeHtml(conv.last_message.content)}
            </div>
          </div>
          ${isUnread ? `<div class="c-chat-widget__conv-badge">${conv.unread_count}</div>` : ''}
        </div>
      `;
    }).join('');

    elements.conversationList.innerHTML = html;
  }

  export function renderMessages() {
    if (!elements.messagesContainer) return;

    if (state.messages.length === 0) {
      elements.messagesContainer.innerHTML = `
        <div class="c-chat-widget__empty" style="padding: 24px;">
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
              <i class="ti ti-message-off" style="margin-right: 6px; opacity: 0.7;"></i>
              ${isSent ? 'You unsent a message' : 'This message was unsent'}
            </div>
            <span class="c-chat-widget__message-time">
              ${formatMessageTime(msg.created_at)}
            </span>
          </div>
        `;
      }

      // Convert emoji shortcodes
      const contentWithEmojis = convertEmojiShortcodes(window.escapeHtml(msg.content));

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
            ${isSent && msg.is_read ? '<i class="ti ti-checks" style="margin-left: 4px; color: var(--cw-accent);"></i>' : ''}
          </span>
        </div>
      `;
    }).join('');

    elements.messagesContainer.innerHTML = html;
  }

  export function handleDeleteMenuClick(element, e) {
    e.stopPropagation();

    const messageEl = element.closest('.c-chat-widget__message');
    if (!messageEl) return;

    const messageId = parseInt(messageEl.dataset.messageId);
    const senderId = parseInt(messageEl.dataset.senderId);
    const currentUserId = getCurrentUserId();
    const isSent = senderId === currentUserId;

    showDeleteConfirmation(messageId, isSent);
  }

  export function showDeleteConfirmation(messageId, isSent) {
    // Use SweetAlert2 if available
    if (typeof window.Swal !== 'undefined') {
      const options = {
        title: 'Delete message?',
        icon: 'question',
        showCancelButton: true,
        confirmButtonColor: 'var(--cw-danger, #ef4444)',
        cancelButtonColor: 'var(--cw-text-secondary, #6b7280)',
        confirmButtonText: 'Delete for me',
        cancelButtonText: 'Cancel',
        customClass: {
          popup: 'c-chat-widget-swal'
        }
      };

      // Add "Unsend for everyone" option if user sent the message
      if (isSent) {
        options.showDenyButton = true;
        options.denyButtonText = 'Unsend for everyone';
        options.denyButtonColor = 'var(--cw-accent, #7c3aed)';
      }

      window.Swal.fire(options).then((result) => {
        if (result.isConfirmed) {
          // Delete for me only
          deleteMessage(messageId, 'me');
        } else if (result.isDenied) {
          // Unsend for everyone
          deleteMessage(messageId, 'everyone');
        }
      });
    } else {
      // Fallback to simple confirm
      if (confirm('Delete this message for yourself?')) {
        deleteMessage(messageId, 'me');
      }
    }
  }

  async function deleteMessage(messageId, deleteFor) {
    try {
      let url, method;

      if (deleteFor === 'everyone') {
        url = `/api/messages/message/${messageId}`;
        method = 'DELETE';
      } else {
        url = `/api/messages/message/${messageId}/hide`;
        method = 'POST';
      }

      const response = await fetchJSON(url, { method });

      if (response.success) {
        if (deleteFor === 'everyone') {
          // Update message in local state to show as deleted
          const msgIndex = state.messages.findIndex(m => m.id === messageId);
          if (msgIndex !== -1) {
            state.messages[msgIndex].is_deleted = true;
            state.messages[msgIndex].content = null;
          }
        } else {
          // Remove from local state (hidden for me)
          state.messages = state.messages.filter(m => m.id !== messageId);
        }

        renderMessages();
        scrollToBottom();
        window.showToast(deleteFor === 'everyone' ? 'Message unsent' : 'Message deleted', 'success');
      } else {
        window.showToast(response.error || 'Failed to delete message', 'error');
      }
    } catch (error) {
      console.error('[ChatWidget] Delete message error:', error);
      window.showToast('Failed to delete message', 'error');
    }
  }

  // Emoji shortcode conversion
  export const EMOJI_MAP = {
    ':)': '😊', ':-)': '😊', '=)': '😊',
    ':(': '😞', ':-(': '😞', '=(': '😞',
    ':D': '😃', ':-D': '😃', '=D': '😃',
    ';)': '😉', ';-)': '😉',
    ':P': '😛', ':-P': '😛', ':p': '😛',
    ':O': '😮', ':-O': '😮', ':o': '😮',
    '<3': '❤️', '</3': '💔',
    ':*': '😘', ':-*': '😘',
    ":'(": '😢', ":')": '😂',
    ':fire:': '🔥', ':heart:': '❤️', ':thumbsup:': '👍', ':thumbsdown:': '👎',
    ':clap:': '👏', ':wave:': '👋', ':ok:': '👌', ':100:': '💯',
    ':star:': '⭐', ':sun:': '☀️', ':moon:': '🌙', ':soccer:': '⚽',
    ':trophy:': '🏆', ':medal:': '🏅', ':crown:': '👑',
    ':check:': '✅', ':x:': '❌', ':warning:': '⚠️',
    ':party:': '🎉', ':confetti:': '🎊',
    'xD': '😆', 'XD': '😆',
    'B)': '😎', 'B-)': '😎',
    '-_-': '😑', ':|': '😐',
    ':angry:': '😠', '>:(': '😠',
    ':thinking:': '🤔', ':shrug:': '🤷',
    ':pray:': '🙏', ':muscle:': '💪',
    ':eyes:': '👀', ':sweat:': '😅',
    ':cool:': '😎', ':lol:': '😂', ':rofl:': '🤣'
  };

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

  export function renderSearchResults() {
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
    const defaultAvatar = '/static/img/default_player.png';

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
            <img src="${avatarUrl}" alt="${window.escapeHtml(user.name)}" onerror="this.src='${defaultAvatar}'">
          </div>
          <span class="c-chat-widget__search-result-name">${escapeHtml(user.name)}${roleBadges}</span>
        </div>
      `;
    }).join('');

    elements.searchResults.innerHTML = html;
    elements.searchResults.classList.add('is-visible');
    console.log('[ChatWidget] Search results dropdown visible');
  }

  export function renderOnlineUsers(users) {
    if (!elements.onlineList) return;

    const onlineSection = elements.onlineList.closest('.c-chat-widget__online');

    if (!users || users.length === 0) {
      if (onlineSection) onlineSection.classList.add('u-hidden');
      return;
    }

    if (onlineSection) onlineSection.classList.remove('u-hidden');

    const defaultAvatar = '/static/img/default_player.png';

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
            <img src="${avatarUrl}" alt="${window.escapeHtml(user.name)}" onerror="this.src='${defaultAvatar}'">
          </div>
          <span class="c-chat-widget__online-name">${escapeHtml(user.name.split(' ')[0])}</span>
        </div>
      `;
    }).join('');

    elements.onlineList.innerHTML = html;
  }

  export function updateBadge() {
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

  export function updateSendButton() {
    if (!elements.sendBtn || !elements.composerInput) return;

    const hasContent = elements.composerInput.value.trim().length > 0;
    elements.sendBtn.disabled = !hasContent;
  }

  // ============================================================================
  // VIEW MANAGEMENT
  // ============================================================================

  export function openWidget() {
    if (!elements.widget) return;

    state.isOpen = true;
    elements.widget.dataset.state = 'open';

    // Lock body scroll on mobile - cross-browser compatible approach
    if (window.innerWidth <= 767) {
      // Save scroll position
      const scrollY = window.scrollY || window.pageYOffset || document.documentElement.scrollTop;
      document.body.dataset.chatScrollY = scrollY;

      // Add class for CSS-based scroll lock
      document.documentElement.classList.add('chat-widget-open');
      document.body.classList.add('chat-widget-open');

      // iOS Safari fix: set body top to preserve visual scroll position
      document.body.style.top = `-${scrollY}px`;
    }

    // Load initial data
    loadConversations();
    loadUnreadCount();

    // Join messaging room
    joinMessagingRoom();

    // Focus search on desktop
    if (window.innerWidth > 575 && elements.searchInput) {
      setTimeout(() => elements.searchInput.focus(), CONFIG.ui.animationDuration);
    }
  }

  export function closeWidget() {
    if (!elements.widget) return;

    state.isOpen = false;
    state.currentView = 'list';
    state.activeConversation = null;
    state.messages = [];
    elements.widget.dataset.state = 'closed';
    elements.widget.dataset.view = 'list';

    // Unlock body scroll on mobile - cross-browser compatible
    document.documentElement.classList.remove('chat-widget-open');
    document.body.classList.remove('chat-widget-open');
    document.body.style.top = '';

    if (document.body.dataset.chatScrollY !== undefined) {
      const scrollY = parseInt(document.body.dataset.chatScrollY || '0', 10);
      delete document.body.dataset.chatScrollY;
      // Restore scroll position after removing fixed positioning
      window.scrollTo(0, scrollY);
    }

    // Clear search state
    clearSearch();
  }

  export function toggleWidget() {
    if (state.isOpen) {
      closeWidget();
    } else {
      openWidget();
    }
  }

  export function openConversation(userId, userName, avatarUrl, isOnline, roleInfo) {
    state.currentView = 'chat';
    state.activeConversation = {
      id: parseInt(userId),
      name: userName,
      avatar: avatarUrl,
      isOnline: isOnline === 'true' || isOnline === true,
      roles: roleInfo || {}
    };

    if (elements.widget) {
      elements.widget.dataset.view = 'chat';
    }

    // Update chat header
    const defaultAvatar = '/static/img/default_player.png';

    if (elements.chatAvatar) {
      elements.chatAvatar.src = avatarUrl || defaultAvatar;
      elements.chatAvatar.onerror = function() { this.src = defaultAvatar; };
    }
    if (elements.chatName) {
      // Display name with role badges
      const roleBadges = renderRoleBadges(roleInfo);
      elements.chatName.innerHTML = window.escapeHtml(userName) + roleBadges;
    }
    if (elements.chatStatus) {
      elements.chatStatus.textContent = state.activeConversation.isOnline ? 'Online' : 'Offline';
      elements.chatStatus.classList.toggle('c-chat-widget__chat-status--offline', !state.activeConversation.isOnline);
    }

    // Update avatar online status
    if (elements.chatAvatarContainer) {
      elements.chatAvatarContainer.classList.toggle('c-chat-widget__chat-avatar--online', state.activeConversation.isOnline);
    }

    // Clear messages and show loading
    if (elements.messagesContainer) {
      elements.messagesContainer.innerHTML = `
        <div style="display: flex; justify-content: center; padding: 40px;">
          <div class="c-chat-widget__typing-dots">
            <span class="c-chat-widget__typing-dot"></span>
            <span class="c-chat-widget__typing-dot"></span>
            <span class="c-chat-widget__typing-dot"></span>
          </div>
        </div>
      `;
    }

    // Load messages
    loadMessages(userId);

    // Focus composer
    if (elements.composerInput) {
      setTimeout(() => elements.composerInput.focus(), CONFIG.ui.animationDuration);
    }
  }

  export function closeConversation() {
    state.currentView = 'list';
    state.activeConversation = null;
    state.messages = [];

    if (elements.widget) {
      elements.widget.dataset.view = 'list';
    }

    // Clear search state when going back
    clearSearch();

    // Refresh conversations
    loadConversations();
  }

  export function scrollToBottom() {
    if (elements.messagesContainer) {
      requestAnimationFrame(() => {
        elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
      });
    }
  }

  // ============================================================================
  // EVENT HANDLERS
  // ============================================================================

  export function handleTriggerClick(e) {
    e.preventDefault();
    e.stopPropagation();
    toggleWidget();
  }

  export function handleConversationClick(e) {
    const conversation = e.target.closest('.c-chat-widget__conversation, .c-chat-widget__online-user, .c-chat-widget__search-result');
    if (!conversation) return;

    const userId = conversation.dataset.userId;
    const userName = conversation.dataset.userName;
    const avatarUrl = conversation.dataset.avatar;
    const isOnline = conversation.dataset.online;

    // Get role info from data attributes (or from state for conversations)
    const roleInfo = {
      is_coach: conversation.dataset.isCoach === 'true',
      is_admin: conversation.dataset.isAdmin === 'true',
      is_global_admin: conversation.dataset.isGlobalAdmin === 'true',
      is_ref: conversation.dataset.isRef === 'true'
    };

    openConversation(userId, userName, avatarUrl, isOnline, roleInfo);

    // Clear search state completely
    clearSearch();
  }

  export function clearSearch() {
    state.searchQuery = '';
    state.searchResults = [];
    if (elements.searchInput) {
      elements.searchInput.value = '';
    }
    if (elements.searchResults) {
      elements.searchResults.classList.remove('is-visible');
      elements.searchResults.innerHTML = '';
    }
  }

  export function handleBackClick(e) {
    e.preventDefault();
    closeConversation();
  }

  export function handleSendClick(e) {
    e.preventDefault();
    if (!state.activeConversation || !elements.composerInput) return;

    const content = elements.composerInput.value.trim();
    if (!content) return;

    sendMessage(state.activeConversation.id, content);
  }

  export function handleComposerKeydown(e) {
    // Send on Enter (without Shift)
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendClick(e);
      return;
    }

    // Emit typing indicator
    emitTypingStart();
  }

  export function handleComposerInput() {
    updateSendButton();
    autoResizeTextarea(elements.composerInput);
  }

  let searchDebounceTimer = null;
  export function handleSearchInput(e) {
    const query = e.target.value.trim();
    state.searchQuery = query;
    console.log('[ChatWidget] Search input:', query);

    clearTimeout(searchDebounceTimer);
    searchDebounceTimer = setTimeout(() => {
      searchUsers(query);
    }, CONFIG.ui.searchDebounce);
  }

  export function handleSearchFocus() {
    if (state.searchResults.length > 0 && elements.searchResults) {
      elements.searchResults.classList.add('is-visible');
    }
  }

  export function handleSearchBlur() {
    // Delay hiding to allow click on results
    setTimeout(() => {
      if (elements.searchResults) {
        elements.searchResults.classList.remove('is-visible');
      }
    }, 200);
  }

  export function handleKeydown(e) {
    // Close on Escape
    if (e.key === 'Escape') {
      if (state.currentView === 'chat') {
        closeConversation();
      } else if (state.isOpen) {
        closeWidget();
      }
    }
  }

  export function handleClickOutside(e) {
    if (!elements.widget || !state.isOpen) return;

    // Don't close if clicking inside widget
    if (elements.widget.contains(e.target)) return;

    // Don't close on mobile (full screen)
    if (window.innerWidth <= 575) return;

    closeWidget();
  }

  // ============================================================================
  // WEBSOCKET INTEGRATION
  // ============================================================================

  let socket = null;

  export function initWebSocket() {
    // Use SocketManager if available (preferred method)
    if (typeof window.SocketManager !== 'undefined') {
      console.log('[ChatWidget] Using SocketManager');

      // Get socket reference
      socket = window.SocketManager.getSocket();

      // Register connect callback - fires immediately if already connected
      window.SocketManager.onConnect('ChatWidget', function(connectedSocket) {
        socket = connectedSocket;
        console.log('[ChatWidget] Socket connected via SocketManager');
        // Join messaging room when connected
        if (state.isOpen) {
          joinMessagingRoom();
        }
      });

      // Register disconnect callback
      window.SocketManager.onDisconnect('ChatWidget', function(reason) {
        console.log('[ChatWidget] Socket disconnected:', reason);
      });

      // Attach event listeners via SocketManager
      attachSocketListeners();
      return;
    }

    // Fallback: Check if Socket.IO is available
    if (typeof window.io === 'undefined') {
      console.warn('[ChatWidget] Socket.IO not available, using polling');
      if (CONFIG.polling.enabled) {
        setInterval(loadUnreadCount, CONFIG.polling.interval);
      }
      return;
    }

    // Fallback: Use existing socket or create new one
    const checkSocket = () => {
      if (window.socket && window.socket.connected) {
        socket = window.socket;
        attachSocketListenersDirect();
      } else if (window.socket) {
        // Socket exists but not connected - wait for connect event
        socket = window.socket;
        window.socket.once('connect', () => {
          attachSocketListenersDirect();
        });
      } else {
        // Try again in a second
        setTimeout(checkSocket, 1000);
      }
    };

    checkSocket();
  }

  export function attachSocketListeners() {
    // Use SocketManager for event registration (handles reconnects properly)
    if (typeof window.SocketManager !== 'undefined') {
      // Message events
      window.SocketManager.on('ChatWidget', 'new_message', handleNewMessage);
      window.SocketManager.on('ChatWidget', 'dm_sent', handleMessageSent);
      window.SocketManager.on('ChatWidget', 'dm_error', handleMessageError);
      window.SocketManager.on('ChatWidget', 'dm_unread_update', handleUnreadUpdate);
      window.SocketManager.on('ChatWidget', 'message_deleted', handleMessageDeleted);

      // Typing events
      window.SocketManager.on('ChatWidget', 'user_typing', handleUserTyping);

      // Read receipts
      window.SocketManager.on('ChatWidget', 'messages_read', handleMessagesRead);

      // Presence events
      window.SocketManager.on('ChatWidget', 'user_online', handleUserOnline);
      window.SocketManager.on('ChatWidget', 'user_offline', handleUserOffline);
      window.SocketManager.on('ChatWidget', 'online_users', handleOnlineUsers);

      console.log('[ChatWidget] Socket listeners attached via SocketManager');
      return;
    }

    // Fallback to direct attachment
    attachSocketListenersDirect();
  }

  export function attachSocketListenersDirect() {
    if (!window.socket) return;

    // Message events
    window.socket.on('new_message', handleNewMessage);
    window.socket.on('dm_sent', handleMessageSent);
    window.socket.on('dm_error', handleMessageError);
    window.socket.on('dm_unread_update', handleUnreadUpdate);
    window.socket.on('message_deleted', handleMessageDeleted);

    // Typing events
    window.socket.on('user_typing', handleUserTyping);

    // Read receipts
    window.socket.on('messages_read', handleMessagesRead);

    // Presence events
    window.socket.on('user_online', handleUserOnline);
    window.socket.on('user_offline', handleUserOffline);
    window.socket.on('online_users', handleOnlineUsers);

    console.log('[ChatWidget] Socket listeners attached (direct)');
  }

  export function handleMessageDeleted(data) {
    const messageId = data.message_id;
    const deletedFor = data.deleted_for;

    // Find message in local state
    const msgIndex = state.messages.findIndex(m => m.id === messageId);

    if (msgIndex !== -1) {
      if (deletedFor === 'everyone') {
        // Mark as unsent (show placeholder)
        state.messages[msgIndex].is_deleted = true;
        state.messages[msgIndex].content = null;
        renderMessages();
      }
      // Note: 'delete for me' by the other user doesn't affect our view
    }
  }

  export function joinMessagingRoom() {
    // Use SocketManager if available
    if (typeof window.SocketManager !== 'undefined') {
      if (window.SocketManager.isConnected()) {
        window.SocketManager.emit('join_messaging');
      }
      return;
    }

    // Fallback
    if (socket && window.socket.connected) {
      window.socket.emit('join_messaging');
    }
  }

  export function handleNewMessage(message) {
    // Update unread count
    state.unreadCount++;
    updateBadge();

    // If in active conversation with sender, add message
    if (state.activeConversation && message.sender_id === state.activeConversation.id) {
      state.messages.push(message);
      renderMessages();
      scrollToBottom();

      // Mark as read
      if (typeof window.SocketManager !== 'undefined') {
        window.SocketManager.emit('mark_dm_read', { sender_id: message.sender_id });
      } else if (socket) {
        window.socket.emit('mark_dm_read', { sender_id: message.sender_id });
      }
    }

    // Refresh conversation list
    loadConversations();

    // Show notification if widget is closed
    if (!state.isOpen) {
      showNotification(message.sender_name, message.content);
    }
  }

  export function handleMessageSent(data) {
    // Message already added locally, just confirm
    console.log('[ChatWidget] Message sent:', data.message?.id);
  }

  export function handleMessageError(data) {
    window.showToast(data.error || 'Failed to send message', 'error');
  }

  export function handleUnreadUpdate(data) {
    state.unreadCount = data.count;
    updateBadge();
  }

  export function handleUserTyping(data) {
    if (!state.activeConversation || data.user_id !== state.activeConversation.id) return;

    if (data.typing) {
      showTypingIndicator();
    } else {
      hideTypingIndicator();
    }
  }

  export function handleMessagesRead(data) {
    // Update read receipts in UI
    if (state.activeConversation && data.reader_id === state.activeConversation.id) {
      state.messages.forEach(msg => {
        if (msg.sender_id !== data.reader_id) {
          msg.is_read = true;
        }
      });
      renderMessages();
    }
  }

  export function handleUserOnline(data) {
    // Update online status in conversation list
    updateUserOnlineStatus(data.user_id, true);

    // Update active conversation
    if (state.activeConversation?.id === data.user_id) {
      state.activeConversation.isOnline = true;
      if (elements.chatStatus) {
        elements.chatStatus.textContent = 'Online';
        elements.chatStatus.classList.remove('c-chat-widget__chat-status--offline');
      }
      if (elements.chatAvatarContainer) {
        elements.chatAvatarContainer.classList.add('c-chat-widget__chat-avatar--online');
      }
    }
  }

  export function handleUserOffline(data) {
    updateUserOnlineStatus(data.user_id, false);

    if (state.activeConversation?.id === data.user_id) {
      state.activeConversation.isOnline = false;
      if (elements.chatStatus) {
        elements.chatStatus.textContent = 'Offline';
        elements.chatStatus.classList.add('c-chat-widget__chat-status--offline');
      }
      if (elements.chatAvatarContainer) {
        elements.chatAvatarContainer.classList.remove('c-chat-widget__chat-avatar--online');
      }
    }
  }

  export function handleOnlineUsers(data) {
    state.onlineUsers = data.users || [];
    renderOnlineUsers(state.onlineUsers);
  }

  export function updateUserOnlineStatus(userId, isOnline) {
    const convElements = document.querySelectorAll(`[data-user-id="${userId}"]`);
    convElements.forEach(el => {
      el.dataset.online = isOnline;
      const avatar = el.querySelector('.c-chat-widget__conv-avatar, .c-chat-widget__online-avatar');
      if (avatar) {
        avatar.classList.toggle('c-chat-widget__conv-avatar--online', isOnline);
      }
    });
  }

  // ============================================================================
  // TYPING INDICATOR
  // ============================================================================

  export function emitTypingStart() {
    if (!state.activeConversation || !state.settings.typingIndicators) return;

    // Check if we can emit
    const canEmit = (typeof window.SocketManager !== 'undefined' && window.SocketManager.isConnected()) ||
                    (socket && window.socket.connected);
    if (!canEmit) return;

    if (!state.isTyping) {
      state.isTyping = true;
      if (typeof window.SocketManager !== 'undefined') {
        window.SocketManager.emit('typing_start', { recipient_id: state.activeConversation.id });
      } else if (socket) {
        window.socket.emit('typing_start', { recipient_id: state.activeConversation.id });
      }
    }

    // Reset timeout
    clearTimeout(state.typingTimeout);
    state.typingTimeout = setTimeout(() => {
      state.isTyping = false;
      if (typeof window.SocketManager !== 'undefined') {
        window.SocketManager.emit('typing_stop', { recipient_id: state.activeConversation.id });
      } else if (socket) {
        window.socket.emit('typing_stop', { recipient_id: state.activeConversation.id });
      }
    }, CONFIG.ui.typingDebounce);
  }

  export function showTypingIndicator() {
    if (elements.typingIndicator) {
      elements.typingIndicator.style.display = 'flex';
      scrollToBottom();
    }
  }

  export function hideTypingIndicator() {
    if (elements.typingIndicator) {
      elements.typingIndicator.style.display = 'none';
    }
  }

  // ============================================================================
  // UTILITIES
  // ============================================================================

  export function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

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

  export function autoResizeTextarea(textarea) {
    if (!textarea) return;

    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
  }

  export function showToast(message, type = 'info') {
    // Use SweetAlert2 if available, otherwise console
    if (typeof window.Swal !== 'undefined') {
      window.Swal.fire({
        toast: true,
        position: 'top-end',
        icon: type,
        title: message,
        showConfirmButton: false,
        timer: 3000,
        timerProgressBar: true
      });
    } else {
      console.log(`[window.ChatWidget] ${type}: ${message}`);
    }
  }

  export function showNotification(title, body) {
    // Browser notification if permitted
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, {
        body: body.length > 50 ? body.substring(0, 50) + '...' : body,
        icon: '/static/images/logo-icon.png',
        tag: 'chat-message'
      });
    }
  }

  // ============================================================================
  // SMART POSITIONING
  // ============================================================================

  export function updatePosition() {
    if (!elements.widget) return;

    // Check for mobile bottom nav
    const mobileNav = document.querySelector('.mobile-bottom-nav, .c-mobile-nav, [data-mobile-nav]');
    if (mobileNav) {
      const navHeight = mobileNav.offsetHeight;
      document.documentElement.style.setProperty('--mobile-nav-height', `${navHeight}px`);
    }
  }

  // ============================================================================
  // EVENT DELEGATION REGISTRATION
  // ============================================================================

  export function registerEventHandlers() {
    // EventDelegation handler is registered at module scope below
    // This function is kept for consistency but no longer registers handlers
  }

  // ============================================================================
  // INITIALIZATION
  // ============================================================================

  export function bindEvents() {
    // Trigger button
    if (elements.trigger) {
      elements.trigger.addEventListener('click', handleTriggerClick);
    }

    // Close buttons (both list view and chat view)
    if (elements.closeBtns) {
      elements.closeBtns.forEach(btn => {
        btn.addEventListener('click', closeWidget);
      });
    }

    // Conversation clicks (event delegation)
    if (elements.conversationList) {
      elements.conversationList.addEventListener('click', handleConversationClick);
    }
    if (elements.onlineList) {
      elements.onlineList.addEventListener('click', handleConversationClick);
    }
    if (elements.searchResults) {
      elements.searchResults.addEventListener('click', handleConversationClick);
    }

    // Back button
    if (elements.backBtn) {
      elements.backBtn.addEventListener('click', handleBackClick);
    }

    // Send button
    if (elements.sendBtn) {
      elements.sendBtn.addEventListener('click', handleSendClick);
    }

    // Composer
    if (elements.composerInput) {
      elements.composerInput.addEventListener('keydown', handleComposerKeydown);
      elements.composerInput.addEventListener('input', handleComposerInput);

      // iOS Safari fix: ensure textarea is focusable on tap
      elements.composerInput.addEventListener('touchstart', function(e) {
        // Don't prevent default - allow normal touch behavior
        // Just ensure element can receive focus
        this.style.pointerEvents = 'auto';
      }, { passive: true });

      // Ensure focus works on click (fallback for all browsers)
      elements.composerInput.addEventListener('click', function(e) {
        e.stopPropagation();
        this.focus();
      });
    }

    // Search
    if (elements.searchInput) {
      console.log('[ChatWidget] Search input found, binding events');
      elements.searchInput.addEventListener('input', handleSearchInput);
      elements.searchInput.addEventListener('focus', handleSearchFocus);
      elements.searchInput.addEventListener('blur', handleSearchBlur);
    } else {
      console.warn('[ChatWidget] Search input not found!');
    }

    // Global events
    document.addEventListener('keydown', handleKeydown);
    document.addEventListener('click', handleClickOutside);

    // Window resize
    window.addEventListener('resize', updatePosition);

    // Open inbox button
    if (elements.openInboxBtn) {
      elements.openInboxBtn.addEventListener('click', () => {
        window.location.href = '/messages';
      });
    }

    // New chat button (focus search)
    if (elements.newChatBtn) {
      elements.newChatBtn.addEventListener('click', () => {
        if (state.currentView === 'chat') {
          closeConversation();
        }
        if (elements.searchInput) {
          elements.searchInput.focus();
        }
      });
    }
  }

  function init() {
    // Guard against duplicate initialization
    if (_initialized) return;

    // Page guard - only initialize if chat widget exists on page
    // This must be checked after DOMContentLoaded when the element exists
    if (!document.querySelector('.c-chat-widget')) {
      console.log('[ChatWidget] No widget element found, skipping initialization');
      return;
    }

    _initialized = true;

    cacheElements();
    registerEventHandlers();
    bindEvents();
    initWebSocket();
    updatePosition();

    // Load initial unread count
    loadUnreadCount();

    // Polling fallback
    if (CONFIG.polling.enabled) {
      setInterval(loadUnreadCount, CONFIG.polling.interval);
    }

    console.log('[ChatWidget] Initialized');
  }

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('chat-widget', init, {
      priority: 35,
      reinitializable: true,
      description: 'Floating chat widget'
    });
  }

  // Fallback: Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose to global for external access
  window.ChatWidget = {
    open: openWidget,
    close: closeWidget,
    toggle: toggleWidget,
    openConversation: openConversation,
    refresh: loadConversations,
    getUnreadCount: () => state.unreadCount
  };

  // ============================================================================
  // EVENT DELEGATION - Registered at module scope
  // ============================================================================
  // MUST use window.EventDelegation to avoid TDZ errors in bundled code

  window.EventDelegation.register('delete-menu', handleDeleteMenuClick, { preventDefault: true });

// Backward compatibility
window.CONFIG = CONFIG;

// Backward compatibility
window.EMOJI_MAP = EMOJI_MAP;

// Backward compatibility
window.cacheElements = cacheElements;

// Backward compatibility
window.getCSRFToken = getCSRFToken;

// Backward compatibility
window.renderRoleBadges = renderRoleBadges;

// Backward compatibility
window.renderConversations = renderConversations;

// Backward compatibility
window.renderMessages = renderMessages;

// Backward compatibility
window.handleDeleteMenuClick = handleDeleteMenuClick;

// Backward compatibility
window.showDeleteConfirmation = showDeleteConfirmation;

// Backward compatibility
window.convertEmojiShortcodes = convertEmojiShortcodes;

// Backward compatibility
window.renderSearchResults = renderSearchResults;

// Backward compatibility
window.renderOnlineUsers = renderOnlineUsers;

// Backward compatibility
window.updateBadge = updateBadge;

// Backward compatibility
window.updateSendButton = updateSendButton;

// Backward compatibility
window.openWidget = openWidget;

// Backward compatibility
window.closeWidget = closeWidget;

// Backward compatibility
window.toggleWidget = toggleWidget;

// Backward compatibility
window.openConversation = openConversation;

// Backward compatibility
window.closeConversation = closeConversation;

// Backward compatibility
window.scrollToBottom = scrollToBottom;

// Backward compatibility
window.handleTriggerClick = handleTriggerClick;

// Backward compatibility
window.handleConversationClick = handleConversationClick;

// Backward compatibility
window.clearSearch = clearSearch;

// Backward compatibility
window.handleBackClick = handleBackClick;

// Backward compatibility
window.handleSendClick = handleSendClick;

// Backward compatibility
window.handleComposerKeydown = handleComposerKeydown;

// Backward compatibility
window.handleComposerInput = handleComposerInput;

// Backward compatibility
window.handleSearchInput = handleSearchInput;

// Backward compatibility
window.handleSearchFocus = handleSearchFocus;

// Backward compatibility
window.handleSearchBlur = handleSearchBlur;

// Backward compatibility
window.handleKeydown = handleKeydown;

// Backward compatibility
window.handleClickOutside = handleClickOutside;

// Backward compatibility
window.initWebSocket = initWebSocket;

// Backward compatibility
window.attachSocketListeners = attachSocketListeners;

// Backward compatibility
window.attachSocketListenersDirect = attachSocketListenersDirect;

// Backward compatibility
window.handleMessageDeleted = handleMessageDeleted;

// Backward compatibility
window.joinMessagingRoom = joinMessagingRoom;

// Backward compatibility
window.handleNewMessage = handleNewMessage;

// Backward compatibility
window.handleMessageSent = handleMessageSent;

// Backward compatibility
window.handleMessageError = handleMessageError;

// Backward compatibility
window.handleUnreadUpdate = handleUnreadUpdate;

// Backward compatibility
window.handleUserTyping = handleUserTyping;

// Backward compatibility
window.handleMessagesRead = handleMessagesRead;

// Backward compatibility
window.handleUserOnline = handleUserOnline;

// Backward compatibility
window.handleUserOffline = handleUserOffline;

// Backward compatibility
window.handleOnlineUsers = handleOnlineUsers;

// Backward compatibility
window.updateUserOnlineStatus = updateUserOnlineStatus;

// Backward compatibility
window.emitTypingStart = emitTypingStart;

// Backward compatibility
window.showTypingIndicator = showTypingIndicator;

// Backward compatibility
window.hideTypingIndicator = hideTypingIndicator;

// Backward compatibility
window.escapeHtml = escapeHtml;

// Backward compatibility
window.formatMessageTime = formatMessageTime;

// Backward compatibility
window.getCurrentUserId = getCurrentUserId;

// Backward compatibility
window.autoResizeTextarea = autoResizeTextarea;

// Backward compatibility
window.showToast = showToast;

// Backward compatibility
window.showNotification = showNotification;

// Backward compatibility
window.updatePosition = updatePosition;

// Backward compatibility
window.registerEventHandlers = registerEventHandlers;

// Backward compatibility
window.bindEvents = bindEvents;

// Backward compatibility
window.init = init;
