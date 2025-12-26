/**
 * ============================================================================
 * MESSAGES INBOX
 * ============================================================================
 *
 * Full-page messaging interface with conversation list and chat view.
 *
 * Features:
 * - Load and display conversations
 * - Real-time message delivery via WebSocket
 * - Send messages with Enter key support
 * - Typing indicators
 * - User search for new conversations
 * - Mobile-responsive view switching
 *
 * ============================================================================
 */

(function() {
  'use strict';

  // Configuration from server
  const config = window.MessagesInboxConfig || {};
  const API_BASE = config.apiBase || '/api/messages';
  const CURRENT_USER_ID = config.currentUserId;
  const SETTINGS = config.settings || {};

  // State
  let conversations = [];
  let activeUserId = null;
  let activeConversation = null;
  let isLoadingMessages = false;
  let socket = null;
  let typingTimeout = null;
  let searchTimeout = null;

  // DOM Elements
  const inbox = document.querySelector('[data-component="messages-inbox"]');
  if (!inbox) {
    console.warn('[MessagesInbox] No messages-inbox component found. Skipping initialization.');
    return;
  }
  console.log('[MessagesInbox] Initializing...');

  const elements = {
    inbox,
    conversationList: inbox.querySelector('[data-list="conversations"]'),
    loadingState: inbox.querySelector('[data-state="loading"]'),
    emptyState: inbox.querySelector('[data-state="empty"]'),
    sidebarFooter: inbox.querySelector('[data-footer="sidebar"]'),
    welcomeState: inbox.querySelector('[data-state="welcome"]'),
    chatView: inbox.querySelector('[data-view="chat"]'),
    chatAvatar: inbox.querySelector('[data-chat-avatar]'),
    chatStatus: inbox.querySelector('[data-chat-status]'),
    chatName: inbox.querySelector('[data-chat-name]'),
    chatOnlineText: inbox.querySelector('[data-chat-online-text]'),
    chatProfileLink: inbox.querySelector('[data-chat-profile-link]'),
    messagesContainer: inbox.querySelector('[data-messages]'),
    messagesLoading: inbox.querySelector('[data-state="messages-loading"]'),
    typingIndicator: inbox.querySelector('[data-typing-indicator]'),
    typingName: inbox.querySelector('[data-typing-name]'),
    messageInput: inbox.querySelector('[data-input="message"]'),
    charCount: inbox.querySelector('[data-char-count]'),
    sendButton: inbox.querySelector('[data-action="send-message"]'),
    searchInput: inbox.querySelector('[data-input="search-conversations"]'),
  };

  // Modal elements
  const modal = document.getElementById('newConversationModal');
  const userSearchInput = document.getElementById('userSearchInput');
  const userResultsList = document.querySelector('[data-list="user-results"]');

  /**
   * Initialize the inbox
   */
  function init() {
    loadConversations();
    setupEventListeners();
    setupWebSocket();

    // Open initial user if specified
    if (config.initialUser) {
      openConversation(config.initialUser);
    }
  }

  /**
   * Set up event listeners
   */
  function setupEventListeners() {
    // New conversation buttons
    const newConversationBtns = document.querySelectorAll('[data-action="new-conversation"]');
    newConversationBtns.forEach((btn) => {
      btn.addEventListener('click', function(e) {
        openNewConversationModal(e);
      });
    });

    // Mark all read button
    const markAllReadBtn = inbox.querySelector('[data-action="mark-all-read"]');
    if (markAllReadBtn) {
      markAllReadBtn.addEventListener('click', markAllAsRead);
    }

    // Back to list (mobile)
    const backBtn = inbox.querySelector('[data-action="back-to-list"]');
    if (backBtn) {
      backBtn.addEventListener('click', closeChat);
    }

    // Message input
    if (elements.messageInput) {
      elements.messageInput.addEventListener('input', handleInputChange);
      elements.messageInput.addEventListener('keydown', handleKeyDown);
    }

    // Send button
    if (elements.sendButton) {
      elements.sendButton.addEventListener('click', sendMessage);
    }

    // Conversation search
    if (elements.searchInput) {
      elements.searchInput.addEventListener('input', handleConversationSearch);
    }

    // User search in modal
    if (userSearchInput) {
      userSearchInput.addEventListener('input', handleUserSearch);
    }

    // Modal reset on hide
    if (modal) {
      modal.addEventListener('hidden.bs.modal', () => {
        if (userSearchInput) userSearchInput.value = '';
        if (userResultsList) {
          userResultsList.innerHTML = `
            <div class="c-user-search-results__hint">
              <i class="ti ti-info-circle me-1" aria-hidden="true"></i>
              Type at least 2 characters to search
            </div>
          `;
        }
      });
    }
  }

  /**
   * Set up WebSocket connection
   */
  function setupWebSocket() {
    if (typeof io === 'undefined') return;

    // Reuse existing global socket if available (from navbar presence)
    // Check if socket EXISTS (not just connected) - it may still be connecting
    if (window.socket) {
      console.log('[MessagesInbox] Reusing existing socket (connected:', window.socket.connected, ')');
      socket = window.socket;
      setupSocketListeners();
      return;
    }

    // Create new socket if none exists
    console.log('[MessagesInbox] Creating new socket connection');
    socket = io({
      // Use polling first to establish sticky session cookie with multiple workers
      transports: ['polling', 'websocket'],
      upgrade: true,
      withCredentials: true
    });

    // Store globally for other components to reuse
    window.socket = socket;

    setupSocketListeners();
  }

  /**
   * Set up socket event listeners
   */
  function setupSocketListeners() {
    if (!socket) return;

    socket.on('connect', () => {
      console.log('[MessagesInbox] WebSocket connected');
    });

    socket.on('new_message', handleNewMessage);
    socket.on('typing_start', handleTypingStart);
    socket.on('typing_stop', handleTypingStop);
    socket.on('message_read', handleMessageRead);
  }

  /**
   * Load conversations from API
   */
  async function loadConversations() {
    try {
      showLoading(true);

      const response = await fetch(`${API_BASE}?limit=50`);
      const data = await response.json();

      if (data.success) {
        conversations = data.conversations || [];
        renderConversations();
      }
    } catch (error) {
      console.error('[MessagesInbox] Error loading conversations:', error);
    } finally {
      showLoading(false);
    }
  }

  /**
   * Show/hide loading state
   */
  function showLoading(show) {
    if (elements.loadingState) {
      elements.loadingState.classList.toggle('u-hidden', !show);
    }
  }

  /**
   * Render conversations list
   */
  function renderConversations(filteredList = null) {
    const list = filteredList || conversations;

    // Show/hide empty state
    if (elements.emptyState) {
      elements.emptyState.classList.toggle('u-hidden', list.length > 0);
    }

    // Show/hide footer
    if (elements.sidebarFooter) {
      elements.sidebarFooter.classList.toggle('u-hidden', list.length === 0);
    }

    // Clear existing items (keep loading and empty states)
    const existingItems = elements.conversationList.querySelectorAll('.c-messages-conversation');
    existingItems.forEach(el => el.remove());

    // Render conversations
    list.forEach(conv => {
      const element = createConversationElement(conv);
      elements.conversationList.appendChild(element);
    });
  }

  /**
   * Create a conversation list item element
   */
  function createConversationElement(conv) {
    const div = document.createElement('div');
    div.className = 'c-messages-conversation';
    div.dataset.userId = conv.user.id;

    if (conv.user.id === activeUserId) {
      div.classList.add('is-active');
    }

    const avatarUrl = conv.user.avatar_url || '/static/img/default-avatar.png';
    const statusClass = conv.user.is_online ? 'is-online' : 'is-offline';
    const previewClass = conv.last_message.sent_by_me ? 'is-sent' : '';

    div.innerHTML = `
      <div class="c-messages-conversation__avatar-wrapper">
        <img src="${avatarUrl}" alt="${conv.user.name}" class="c-messages-conversation__avatar">
        <span class="c-online-status c-online-status--sm ${statusClass}"></span>
      </div>
      <div class="c-messages-conversation__info">
        <p class="c-messages-conversation__name">${escapeHtml(conv.user.name)}</p>
        <p class="c-messages-conversation__preview ${previewClass}">${escapeHtml(conv.last_message.content)}</p>
      </div>
      <div class="c-messages-conversation__meta">
        <span class="c-messages-conversation__time">${conv.last_message.time_ago}</span>
        ${conv.unread_count > 0 ? `<span class="c-messages-conversation__unread">${conv.unread_count}</span>` : ''}
      </div>
    `;

    div.addEventListener('click', () => openConversation(conv.user));

    return div;
  }

  /**
   * Open a conversation with a user
   */
  async function openConversation(user) {
    activeUserId = user.id;
    activeConversation = user;

    // Update sidebar selection
    document.querySelectorAll('.c-messages-conversation').forEach(el => {
      el.classList.toggle('is-active', parseInt(el.dataset.userId) === user.id);
    });

    // Update chat header
    updateChatHeader(user);

    // Show chat view
    showChatView(true);

    // Load messages
    await loadMessages(user.id);

    // Close modal if open - use ModalManager if available, fallback to Bootstrap
    if (modal) {
      if (typeof ModalManager !== 'undefined') {
        ModalManager.hide('newConversationModal');
      } else {
        const bsModal = bootstrap.Modal.getInstance(modal);
        if (bsModal) bsModal.hide();
      }
    }

    // Focus input
    if (elements.messageInput) {
      elements.messageInput.focus();
    }
  }

  /**
   * Update chat header with user info
   */
  function updateChatHeader(user) {
    const avatarUrl = user.avatar_url || '/static/img/default-avatar.png';

    if (elements.chatAvatar) {
      elements.chatAvatar.src = avatarUrl;
      elements.chatAvatar.alt = user.name;
    }

    if (elements.chatStatus) {
      elements.chatStatus.className = `c-online-status c-online-status--sm ${user.is_online ? 'is-online' : 'is-offline'}`;
    }

    if (elements.chatName) {
      elements.chatName.textContent = user.name;
      elements.chatName.href = user.profile_url || '#';
    }

    if (elements.chatOnlineText) {
      elements.chatOnlineText.textContent = user.is_online ? 'Online' : 'Offline';
      elements.chatOnlineText.className = `c-messages-chat__user-status ${user.is_online ? 'is-online' : ''}`;
    }

    if (elements.chatProfileLink) {
      elements.chatProfileLink.href = user.profile_url || '#';
      elements.chatProfileLink.style.display = user.profile_url ? '' : 'none';
    }
  }

  /**
   * Show/hide chat view
   */
  function showChatView(show) {
    if (elements.welcomeState) {
      elements.welcomeState.classList.toggle('u-hidden', show);
    }
    if (elements.chatView) {
      elements.chatView.classList.toggle('u-hidden', !show);
    }
    // Mobile: toggle class on inbox
    inbox.classList.toggle('is-chatting', show);
  }

  /**
   * Close chat (mobile)
   */
  function closeChat() {
    activeUserId = null;
    activeConversation = null;
    showChatView(false);

    document.querySelectorAll('.c-messages-conversation').forEach(el => {
      el.classList.remove('is-active');
    });
  }

  /**
   * Load messages for a conversation
   */
  async function loadMessages(userId) {
    if (isLoadingMessages) return;
    isLoadingMessages = true;

    try {
      if (elements.messagesLoading) {
        elements.messagesLoading.classList.remove('u-hidden');
      }
      if (elements.messagesContainer) {
        // Clear existing messages
        const existingMessages = elements.messagesContainer.querySelectorAll('.c-messages-message, .c-messages-date-separator');
        existingMessages.forEach(el => el.remove());
      }

      const response = await fetch(`${API_BASE}/${userId}?limit=100`);
      const data = await response.json();

      if (data.success) {
        renderMessages(data.messages || []);

        // Update user status
        if (data.user && activeConversation) {
          activeConversation.is_online = data.user.is_online;
          updateChatHeader(activeConversation);
        }

        // Update unread count in sidebar
        updateConversationUnread(userId, 0);
      }
    } catch (error) {
      console.error('[MessagesInbox] Error loading messages:', error);
    } finally {
      isLoadingMessages = false;
      if (elements.messagesLoading) {
        elements.messagesLoading.classList.add('u-hidden');
      }
    }
  }

  /**
   * Render messages in the chat view
   */
  function renderMessages(messages) {
    let lastDate = null;

    messages.forEach(msg => {
      // Date separator
      const msgDate = new Date(msg.created_at).toDateString();
      if (msgDate !== lastDate) {
        const separator = createDateSeparator(msg.created_at);
        elements.messagesContainer.appendChild(separator);
        lastDate = msgDate;
      }

      const element = createMessageElement(msg);
      elements.messagesContainer.appendChild(element);
    });

    // Scroll to bottom
    scrollToBottom();
  }

  /**
   * Create date separator element
   */
  function createDateSeparator(dateStr) {
    const div = document.createElement('div');
    div.className = 'c-messages-date-separator';

    const date = new Date(dateStr);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    let label;
    if (date.toDateString() === today.toDateString()) {
      label = 'Today';
    } else if (date.toDateString() === yesterday.toDateString()) {
      label = 'Yesterday';
    } else {
      label = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }

    div.innerHTML = `<span class="c-messages-date-separator__text">${label}</span>`;
    return div;
  }

  /**
   * Create message element
   */
  function createMessageElement(msg) {
    const div = document.createElement('div');
    const isSent = msg.sender_id === CURRENT_USER_ID;
    div.className = `c-messages-message ${isSent ? 'c-messages-message--sent' : 'c-messages-message--received'}`;
    div.dataset.messageId = msg.id;

    const time = formatTime(msg.created_at);
    const readIcon = isSent && msg.is_read && SETTINGS.read_receipts ?
      '<i class="ti ti-checks c-messages-message__read" aria-label="Read"></i>' : '';

    div.innerHTML = `
      <div class="c-messages-message__bubble">${escapeHtml(msg.content)}</div>
      <div class="c-messages-message__time">${time}${readIcon}</div>
    `;

    return div;
  }

  /**
   * Handle input change
   */
  function handleInputChange() {
    const value = elements.messageInput.value;
    const length = value.length;
    const maxLength = SETTINGS.max_message_length || 2000;

    // Update character count
    if (elements.charCount) {
      elements.charCount.textContent = `${length}/${maxLength}`;
      elements.charCount.classList.toggle('is-warning', length > maxLength * 0.8);
      elements.charCount.classList.toggle('is-limit', length >= maxLength);
    }

    // Enable/disable send button
    if (elements.sendButton) {
      elements.sendButton.disabled = length === 0 || length > maxLength;
    }

    // Auto-resize textarea
    elements.messageInput.style.height = 'auto';
    elements.messageInput.style.height = Math.min(elements.messageInput.scrollHeight, 120) + 'px';

    // Send typing indicator
    if (SETTINGS.typing_indicators && activeUserId && socket) {
      clearTimeout(typingTimeout);
      socket.emit('typing_start', { recipient_id: activeUserId });

      typingTimeout = setTimeout(() => {
        socket.emit('typing_stop', { recipient_id: activeUserId });
      }, 2000);
    }
  }

  /**
   * Handle keydown in message input
   */
  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  /**
   * Send a message
   */
  async function sendMessage() {
    const content = elements.messageInput.value.trim();
    if (!content || !activeUserId) return;

    const maxLength = SETTINGS.max_message_length || 2000;
    if (content.length > maxLength) return;

    // Disable send button
    if (elements.sendButton) {
      elements.sendButton.disabled = true;
    }

    try {
      const response = await fetch(`${API_BASE}/${activeUserId}`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({ content })
      });

      const data = await response.json();

      if (data.success && data.message) {
        // Clear input
        elements.messageInput.value = '';
        elements.messageInput.style.height = 'auto';
        if (elements.charCount) {
          elements.charCount.textContent = `0/${maxLength}`;
          elements.charCount.classList.remove('is-warning', 'is-limit');
        }

        // Add message to view
        const element = createMessageElement(data.message);
        elements.messagesContainer.appendChild(element);
        scrollToBottom();

        // Update conversation in sidebar
        updateConversationPreview(activeUserId, content, true);

        // Stop typing indicator
        if (socket) {
          socket.emit('typing_stop', { recipient_id: activeUserId });
        }
      } else {
        showError(data.error || 'Failed to send message');
      }
    } catch (error) {
      console.error('[MessagesInbox] Error sending message:', error);
      showError('Failed to send message');
    }

    // Re-enable based on input
    handleInputChange();
  }

  /**
   * Handle incoming WebSocket message
   */
  function handleNewMessage(msg) {
    // Only process if from someone we're chatting with
    if (msg.sender_id === activeUserId) {
      const element = createMessageElement(msg);
      elements.messagesContainer.appendChild(element);
      scrollToBottom();

      // Mark as read
      markMessageAsRead(msg.id);
    }

    // Update sidebar
    if (msg.sender_id !== CURRENT_USER_ID) {
      updateConversationPreview(msg.sender_id, msg.content, false);

      // Increment unread if not active
      if (msg.sender_id !== activeUserId) {
        incrementConversationUnread(msg.sender_id);
      }
    }

    // Reload conversations to update order
    loadConversations();
  }

  /**
   * Handle typing start event
   */
  function handleTypingStart(data) {
    if (data.user_id === activeUserId && elements.typingIndicator) {
      elements.typingIndicator.classList.remove('u-hidden');
      if (elements.typingName) {
        elements.typingName.textContent = activeConversation?.name + ' is typing';
      }
      scrollToBottom();
    }
  }

  /**
   * Handle typing stop event
   */
  function handleTypingStop(data) {
    if (data.user_id === activeUserId && elements.typingIndicator) {
      elements.typingIndicator.classList.add('u-hidden');
    }
  }

  /**
   * Handle message read event
   */
  function handleMessageRead(data) {
    if (data.reader_id === activeUserId) {
      // Update read status on messages
      document.querySelectorAll('.c-messages-message--sent').forEach(el => {
        const timeEl = el.querySelector('.c-messages-message__time');
        if (timeEl && !timeEl.querySelector('.c-messages-message__read')) {
          timeEl.innerHTML += '<i class="ti ti-checks c-messages-message__read" aria-label="Read"></i>';
        }
      });
    }
  }

  /**
   * Mark a message as read
   */
  async function markMessageAsRead(messageId) {
    try {
      await fetch(`${API_BASE}/${messageId}/read`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCsrfToken()
        }
      });
    } catch (error) {
      console.error('[MessagesInbox] Error marking message read:', error);
    }
  }

  /**
   * Mark all messages as read
   */
  async function markAllAsRead() {
    try {
      const response = await fetch(`${API_BASE}/mark-all-read`, {
        method: 'POST',
        headers: {
          'X-CSRFToken': getCsrfToken()
        }
      });

      const data = await response.json();
      if (data.success) {
        // Update all conversation unread counts
        document.querySelectorAll('.c-messages-conversation__unread').forEach(el => el.remove());

        // Update global badge
        updateGlobalBadge(0);
      }
    } catch (error) {
      console.error('[MessagesInbox] Error marking all read:', error);
    }
  }

  /**
   * Update conversation preview in sidebar
   */
  function updateConversationPreview(userId, content, sentByMe) {
    const conv = document.querySelector(`.c-messages-conversation[data-user-id="${userId}"]`);
    if (conv) {
      const preview = conv.querySelector('.c-messages-conversation__preview');
      if (preview) {
        preview.textContent = content.length > 50 ? content.substring(0, 50) + '...' : content;
        preview.classList.toggle('is-sent', sentByMe);
      }

      const time = conv.querySelector('.c-messages-conversation__time');
      if (time) {
        time.textContent = 'Just now';
      }
    }
  }

  /**
   * Update conversation unread count
   */
  function updateConversationUnread(userId, count) {
    const conv = document.querySelector(`.c-messages-conversation[data-user-id="${userId}"]`);
    if (conv) {
      let badge = conv.querySelector('.c-messages-conversation__unread');
      if (count > 0) {
        if (!badge) {
          badge = document.createElement('span');
          badge.className = 'c-messages-conversation__unread';
          conv.querySelector('.c-messages-conversation__meta').appendChild(badge);
        }
        badge.textContent = count;
      } else if (badge) {
        badge.remove();
      }
    }
  }

  /**
   * Increment conversation unread count
   */
  function incrementConversationUnread(userId) {
    const conv = document.querySelector(`.c-messages-conversation[data-user-id="${userId}"]`);
    if (conv) {
      let badge = conv.querySelector('.c-messages-conversation__unread');
      if (badge) {
        badge.textContent = parseInt(badge.textContent) + 1;
      } else {
        badge = document.createElement('span');
        badge.className = 'c-messages-conversation__unread';
        badge.textContent = '1';
        conv.querySelector('.c-messages-conversation__meta').appendChild(badge);
      }
    }
  }

  /**
   * Handle conversation search
   */
  function handleConversationSearch() {
    const query = elements.searchInput.value.toLowerCase().trim();

    if (!query) {
      renderConversations();
      return;
    }

    const filtered = conversations.filter(conv =>
      conv.user.name.toLowerCase().includes(query) ||
      conv.last_message.content.toLowerCase().includes(query)
    );

    renderConversations(filtered);
  }

  /**
   * Open new conversation modal
   */
  function openNewConversationModal() {
    if (modal) {
      // Use ModalManager if available, fallback to Bootstrap
      if (typeof ModalManager !== 'undefined') {
        ModalManager.show('newConversationModal');
      } else if (typeof bootstrap !== 'undefined' && bootstrap.Modal) {
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
      } else {
        console.error('[MessagesInbox] Neither ModalManager nor Bootstrap available');
      }
    } else {
      console.error('[MessagesInbox] Modal element not found');
    }
  }

  /**
   * Handle user search in modal
   */
  function handleUserSearch() {
    const query = userSearchInput.value.trim();

    clearTimeout(searchTimeout);

    if (query.length < 2) {
      userResultsList.innerHTML = `
        <div class="c-user-search-results__hint">
          <i class="ti ti-info-circle me-1" aria-hidden="true"></i>
          Type at least 2 characters to search
        </div>
      `;
      return;
    }

    userResultsList.innerHTML = `
      <div class="c-user-search-results__loading">
        <div class="c-messages-list__spinner"></div>
      </div>
    `;

    searchTimeout = setTimeout(async () => {
      try {
        const response = await fetch(`${API_BASE}/users/search?q=${encodeURIComponent(query)}&limit=10`);
        const data = await response.json();

        if (data.success && data.users.length > 0) {
          userResultsList.innerHTML = '';
          data.users.forEach(user => {
            const div = document.createElement('div');
            div.className = 'c-user-search-results__item';
            div.innerHTML = `
              <img src="${user.avatar_url || '/static/img/default-avatar.png'}" alt="${user.name}" class="c-user-search-results__avatar">
              <span class="c-user-search-results__name">${escapeHtml(user.name)}</span>
            `;
            div.addEventListener('click', () => openConversation(user));
            userResultsList.appendChild(div);
          });
        } else {
          userResultsList.innerHTML = `
            <div class="c-user-search-results__empty">
              <i class="ti ti-user-off" style="font-size: 2rem; margin-bottom: 0.5rem; opacity: 0.5;" aria-hidden="true"></i>
              <p>No users found</p>
            </div>
          `;
        }
      } catch (error) {
        console.error('[MessagesInbox] Error searching users:', error);
        userResultsList.innerHTML = `
          <div class="c-user-search-results__empty">
            <p>Search failed. Please try again.</p>
          </div>
        `;
      }
    }, 300);
  }

  /**
   * Scroll messages to bottom
   */
  function scrollToBottom() {
    if (elements.messagesContainer) {
      elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
    }
  }

  /**
   * Format time for display
   */
  function formatTime(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      hour12: true
    });
  }

  /**
   * Escape HTML to prevent XSS
   */
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  /**
   * Get CSRF token
   */
  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute('content') : '';
  }

  /**
   * Update global unread badge (in navbar)
   */
  function updateGlobalBadge(count) {
    const badge = document.querySelector('[data-badge="messages-count"]');
    if (badge) {
      badge.textContent = count;
      badge.classList.toggle('u-hidden', count === 0);
    }
  }

  /**
   * Show error toast
   */
  function showError(message) {
    // Use your existing toast system
    if (typeof window.showToast === 'function') {
      window.showToast(message, 'error');
    } else {
      console.error('[MessagesInbox]', message);
    }
  }

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();
