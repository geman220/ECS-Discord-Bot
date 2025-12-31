/**
 * ============================================================================
 * MESSENGER WIDGET - Unified Sidebar Messaging Component
 * ============================================================================
 *
 * Facebook Messenger-style sidebar widget combining:
 * - Online users display
 * - Conversation list
 * - Real-time chat interface
 * - User search
 * - Message management (read, send, delete)
 *
 * Dependencies:
 * - Socket.IO (for real-time features)
 * - Bootstrap 5 (optional, for modals)
 *
 * ============================================================================
 */

/**
 * ES Module Export
 */
export class MessengerWidget {
    constructor() {
      this.widget = null;
      this.currentUserId = null;
      this.currentUserName = '';
      this.conversations = [];
      this.messages = [];
      this.onlineUsers = [];
      this.unreadCount = 0;
      this.typingTimeout = null;
      this.socket = null;
      this.refreshIntervals = {};
    }

    /**
     * Initialize the messenger widget
     */
    init() {
      this.widget = document.querySelector('[data-component="messenger-widget"]');
      if (!this.widget) return;

      this.bindEvents();
      this.setupWebSocket();
      this.loadOnlineUsers();
      this.loadConversations();
      this.loadUnreadCount();

      // Set up periodic refreshes
      this.refreshIntervals.online = setInterval(() => this.loadOnlineUsers(), 30000);
      this.refreshIntervals.unread = setInterval(() => this.loadUnreadCount(), 60000);

      console.log('[Messenger] Initialized');
    }

    /**
     * Get CSRF token
     */
    getCSRFToken() {
      const meta = document.querySelector('meta[name="csrf-token"]');
      return meta ? meta.getAttribute('content') : '';
    }

    /**
     * Bind DOM events using event delegation
     */
    bindEvents() {
      // Event delegation for all actions
      this.widget.addEventListener('click', (e) => {
        const action = e.target.closest('[data-action]');
        if (action) {
          e.preventDefault();
          this.handleAction(action.dataset.action, action);
        }

        // Conversation click
        const conv = e.target.closest('[data-conversation-id]');
        if (conv && !action) {
          e.preventDefault();
          const userId = parseInt(conv.dataset.conversationId, 10);
          this.openConversation(userId);
        }

        // Online user click
        const onlineUser = e.target.closest('[data-online-user-id]');
        if (onlineUser && !action) {
          e.preventDefault();
          const userId = parseInt(onlineUser.dataset.onlineUserId, 10);
          this.openConversation(userId);
        }
      });

      // Search input
      const searchInput = this.widget.querySelector('[data-input="search"]');
      if (searchInput) {
        searchInput.addEventListener('input', (e) => this.handleSearch(e.target.value));
      }

      // Message input
      const msgInput = this.widget.querySelector('[data-input="message"]');
      if (msgInput) {
        msgInput.addEventListener('keydown', (e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            this.sendMessage();
          }
        });
        msgInput.addEventListener('input', () => this.handleTyping());

        // Auto-resize textarea
        msgInput.addEventListener('input', () => {
          msgInput.style.height = 'auto';
          msgInput.style.height = Math.min(msgInput.scrollHeight, 100) + 'px';
        });
      }

      // Close on escape when chatting
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && this.widget.classList.contains('is-chatting')) {
          this.showList();
        }
      });
    }

    /**
     * Handle action buttons
     */
    handleAction(action, element) {
      switch (action) {
        case 'back':
          this.showList();
          break;
        case 'new-chat':
          this.focusSearch();
          break;
        case 'send-message':
          this.sendMessage();
          break;
        case 'delete-message':
          const msgId = element.closest('[data-message-id]')?.dataset.messageId;
          if (msgId) this.deleteMessage(parseInt(msgId, 10));
          break;
        case 'open-messages':
          window.location.href = '/messages';
          break;
      }
    }

    /**
     * Setup WebSocket connection
     */
    setupWebSocket() {
      if (typeof window.io === 'undefined') return;

      const checkSocket = () => {
        if (window.socket && window.socket.connected) {
          this.socket = window.socket;
          this.attachSocketListeners();
        } else {
          setTimeout(checkSocket, 1000);
        }
      };
      checkSocket();
    }

    /**
     * Attach WebSocket event listeners
     */
    attachSocketListeners() {
      if (!this.socket) return;

      this.socket.on('new_message', (data) => this.handleNewMessage(data));
      this.socket.on('user_typing', (data) => this.handleTypingIndicator(data));
      this.socket.on('messages_read', (data) => this.handleMessagesRead(data));
      this.socket.on('dm_sent', (data) => {
        if (data.message) this.appendMessage(data.message);
      });
      this.socket.on('dm_error', (data) => {
        this.showToast(data.error || 'Failed to send message', 'error');
      });
      this.socket.on('user_online', () => this.loadOnlineUsers());
      this.socket.on('user_offline', () => this.loadOnlineUsers());
      this.socket.on('message_deleted', (data) => this.handleMessageDeleted(data));
    }

    // ========================================================================
    // ONLINE USERS
    // ========================================================================

    /**
     * Load online users
     */
    async loadOnlineUsers() {
      try {
        const response = await fetch('/api/notifications/presence/online-users?details=true&limit=8');
        const data = await response.json();

        if (data.success) {
          this.onlineUsers = data.online_users || [];
          this.renderOnlineUsers();
          this.updateOnlineCount(data.count || this.onlineUsers.length);
        }
      } catch (error) {
        console.warn('[Messenger] Failed to load online users:', error);
      }
    }

    /**
     * Render online users
     */
    renderOnlineUsers() {
      const list = this.widget.querySelector('[data-online-list]');
      if (!list) return;

      list.innerHTML = '';

      if (this.onlineUsers.length === 0) {
        list.innerHTML = '<span class="c-messenger__online-empty">No one online</span>';
        return;
      }

      this.onlineUsers.forEach(user => {
        const el = document.createElement('div');
        el.className = 'c-messenger__online-user';
        el.dataset.onlineUserId = user.id;
        el.title = `Chat with ${user.name}`;

        const avatarUrl = user.avatar_url || '/static/img/default_player.png';

        el.innerHTML = `
          <div class="c-messenger__online-avatar">
            <img src="${avatarUrl}" alt="${user.name}" class="c-messenger__online-avatar-img"
                 onerror="this.src='/static/img/default_player.png'">
            <span class="c-online-status c-online-status--sm is-online"></span>
          </div>
          <span class="c-messenger__online-name">${user.name.split(' ')[0]}</span>
        `;

        list.appendChild(el);
      });
    }

    /**
     * Update online count display
     */
    updateOnlineCount(count) {
      const countEl = this.widget.querySelector('[data-online-count]');
      if (countEl) {
        countEl.textContent = count;
      }
    }

    // ========================================================================
    // CONVERSATIONS
    // ========================================================================

    /**
     * Load conversations list
     */
    async loadConversations() {
      const list = this.widget.querySelector('[data-conversation-list]');
      const loading = this.widget.querySelector('[data-state="loading"]');
      const empty = this.widget.querySelector('[data-state="empty"]');

      if (loading) loading.classList.remove('u-hidden');
      if (empty) empty.classList.add('u-hidden');

      try {
        const response = await fetch('/api/messages');
        const data = await response.json();

        if (loading) loading.classList.add('u-hidden');

        if (data.success) {
          this.conversations = data.conversations || [];
          this.renderConversations();
        }
      } catch (error) {
        console.error('[Messenger] Failed to load conversations:', error);
        if (loading) loading.classList.add('u-hidden');
      }
    }

    /**
     * Render conversations list
     */
    renderConversations() {
      const list = this.widget.querySelector('[data-conversation-list]');
      const empty = this.widget.querySelector('[data-state="empty"]');
      if (!list) return;

      // Clear existing
      const items = list.querySelectorAll('.c-messenger__conversation');
      items.forEach(item => item.remove());

      if (this.conversations.length === 0) {
        if (empty) empty.classList.remove('u-hidden');
        return;
      }

      if (empty) empty.classList.add('u-hidden');

      this.conversations.forEach(conv => {
        const item = document.createElement('div');
        item.className = 'c-messenger__conversation';
        if (conv.unread_count > 0) item.classList.add('is-unread');
        item.dataset.conversationId = conv.user.id;

        const avatarUrl = conv.user.avatar_url || '/static/img/default_player.png';
        const onlineClass = conv.user.is_online ? 'is-online' : 'is-offline';
        const preview = conv.last_message
          ? `${conv.last_message.sent_by_me ? 'You: ' : ''}${conv.last_message.content}`
          : 'No messages yet';

        item.innerHTML = `
          <div class="c-messenger__conversation-avatar">
            <img src="${avatarUrl}" alt="${conv.user.name}"
                 class="c-messenger__conversation-avatar-img"
                 onerror="this.src='/static/img/default_player.png'">
            <span class="c-online-status c-online-status--sm ${onlineClass}"
                  data-online-status="${conv.user.id}"></span>
          </div>
          <div class="c-messenger__conversation-body">
            <p class="c-messenger__conversation-name">${conv.user.name}</p>
            <p class="c-messenger__conversation-preview">${this.escapeHtml(preview)}</p>
          </div>
          <div class="c-messenger__conversation-meta">
            ${conv.last_message ? `<span class="c-messenger__conversation-time">${conv.last_message.time_ago}</span>` : ''}
            ${conv.unread_count > 0 ? `<span class="c-messenger__conversation-unread">${conv.unread_count}</span>` : ''}
          </div>
        `;

        list.appendChild(item);
      });
    }

    /**
     * Open a conversation
     */
    async openConversation(userId) {
      this.currentUserId = userId;
      this.widget.classList.add('is-chatting');

      // Update header
      const user = this.onlineUsers.find(u => u.id === userId)
        || this.conversations.find(c => c.user.id === userId)?.user;

      if (user) {
        this.currentUserName = user.name;
        const headerTitle = this.widget.querySelector('[data-header-title] span');
        if (headerTitle) headerTitle.textContent = user.name;
      }

      // Load messages
      await this.loadMessages(userId);

      // Focus input
      const input = this.widget.querySelector('[data-input="message"]');
      if (input) input.focus();
    }

    // ========================================================================
    // MESSAGES
    // ========================================================================

    /**
     * Load messages for a conversation
     */
    async loadMessages(userId) {
      const container = this.widget.querySelector('[data-messages]');
      if (!container) return;

      container.innerHTML = '<div class="c-messenger__loading"><div class="c-messenger__loading-spinner"></div></div>';

      try {
        const response = await fetch(`/api/messages/${userId}`);
        const data = await response.json();

        if (data.success) {
          this.messages = data.messages || [];
          this.renderMessages(container);
          this.scrollToBottom(container);
          this.loadUnreadCount();
        }
      } catch (error) {
        console.error('[Messenger] Failed to load messages:', error);
        container.innerHTML = '<p class="c-messenger__empty">Failed to load messages</p>';
      }
    }

    /**
     * Render messages
     */
    renderMessages(container) {
      if (!container) return;
      container.innerHTML = '';

      if (this.messages.length === 0) {
        container.innerHTML = `
          <div class="c-messenger__empty">
            <i class="ti ti-message-2 c-messenger__empty-icon"></i>
            <p class="c-messenger__empty-text">No messages yet. Say hello!</p>
          </div>
        `;
        return;
      }

      this.messages.forEach(msg => this.appendMessage(msg, false));
    }

    /**
     * Append a message to the chat
     */
    appendMessage(msg, scroll = true) {
      const container = this.widget.querySelector('[data-messages]');
      if (!container) return;

      // Remove empty state
      const empty = container.querySelector('.c-messenger__empty');
      if (empty) empty.remove();

      const isSent = msg.sender_id !== this.currentUserId;
      const bubble = document.createElement('div');
      bubble.className = `c-messenger__message c-messenger__message--${isSent ? 'sent' : 'received'}`;
      bubble.dataset.messageId = msg.id;

      const timeStr = msg.created_at
        ? new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        : '';

      bubble.innerHTML = `
        <div class="c-messenger__message-content">${this.escapeHtml(msg.content)}</div>
        <div class="c-messenger__message-time">${timeStr}</div>
        ${isSent ? `
          <div class="c-messenger__message-actions">
            <button class="c-messenger__message-action" data-action="delete-message" title="Delete">
              <i class="ti ti-trash"></i>
            </button>
          </div>
        ` : ''}
      `;

      container.appendChild(bubble);

      if (scroll) this.scrollToBottom(container);
    }

    /**
     * Send a message
     */
    async sendMessage() {
      const input = this.widget.querySelector('[data-input="message"]');
      if (!input || !this.currentUserId) return;

      const content = input.value.trim();
      if (!content) return;

      input.value = '';
      input.style.height = 'auto';
      input.focus();

      if (this.socket && this.socket.connected) {
        this.socket.emit('send_dm', {
          recipient_id: this.currentUserId,
          content: content
        });
      } else {
        // HTTP fallback
        try {
          const response = await fetch(`/api/messages/${this.currentUserId}`, {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': this.getCSRFToken()
            },
            body: JSON.stringify({ content })
          });
          const data = await response.json();
          if (data.success && data.message) {
            this.appendMessage(data.message);
          } else {
            this.showToast(data.error || 'Failed to send', 'error');
          }
        } catch (error) {
          this.showToast('Failed to send message', 'error');
        }
      }
    }

    /**
     * Delete a message
     */
    async deleteMessage(messageId) {
      if (!confirm('Delete this message?')) return;

      try {
        const response = await fetch(`/api/messages/message/${messageId}`, {
          method: 'DELETE',
          headers: {
            'X-CSRFToken': this.getCSRFToken()
          }
        });
        const data = await response.json();

        if (data.success) {
          const msgEl = this.widget.querySelector(`[data-message-id="${messageId}"]`);
          if (msgEl) {
            msgEl.classList.add('is-deleting');
            setTimeout(() => msgEl.remove(), 200);
          }
        } else {
          this.showToast(data.error || 'Failed to delete', 'error');
        }
      } catch (error) {
        this.showToast('Failed to delete message', 'error');
      }
    }

    /**
     * Handle incoming message
     */
    handleNewMessage(data) {
      this.loadUnreadCount();

      if (this.widget.classList.contains('is-chatting') && this.currentUserId === data.sender_id) {
        this.appendMessage(data);
        this.markAsRead(data.id);
      } else {
        this.showToast(`${data.sender_name}: ${data.content.substring(0, 50)}`, 'info');
      }

      if (!this.widget.classList.contains('is-chatting')) {
        this.loadConversations();
      }
    }

    /**
     * Handle message deleted event
     */
    handleMessageDeleted(data) {
      const msgEl = this.widget.querySelector(`[data-message-id="${data.message_id}"]`);
      if (msgEl) msgEl.remove();
    }

    /**
     * Handle typing indicator
     */
    handleTypingIndicator(data) {
      if (this.currentUserId !== data.user_id) return;

      const container = this.widget.querySelector('[data-messages]');
      let typingEl = container?.querySelector('.c-messenger__typing');

      if (data.typing) {
        if (!typingEl) {
          typingEl = document.createElement('div');
          typingEl.className = 'c-messenger__typing';
          typingEl.innerHTML = `
            <span class="c-messenger__typing-dots">
              <span class="c-messenger__typing-dot"></span>
              <span class="c-messenger__typing-dot"></span>
              <span class="c-messenger__typing-dot"></span>
            </span>
            <span>typing...</span>
          `;
          container.appendChild(typingEl);
          this.scrollToBottom(container);
        }
      } else {
        if (typingEl) typingEl.remove();
      }
    }

    /**
     * Handle typing (send indicator)
     */
    handleTyping() {
      if (!this.socket || !this.currentUserId) return;

      if (this.typingTimeout) clearTimeout(this.typingTimeout);

      this.socket.emit('typing_start', { recipient_id: this.currentUserId });

      this.typingTimeout = setTimeout(() => {
        this.socket.emit('typing_stop', { recipient_id: this.currentUserId });
      }, 2000);
    }

    /**
     * Handle messages read notification
     */
    handleMessagesRead(data) {
      // Could add read receipts visual
    }

    /**
     * Mark message as read
     */
    markAsRead(messageId) {
      if (this.socket && this.socket.connected) {
        this.socket.emit('mark_dm_read', { message_id: messageId });
      }
    }

    // ========================================================================
    // SEARCH
    // ========================================================================

    /**
     * Handle search input
     */
    async handleSearch(query) {
      if (query.length < 2) {
        this.renderConversations();
        return;
      }

      try {
        const response = await fetch(`/api/messages/users/search?q=${encodeURIComponent(query)}`);
        const data = await response.json();

        if (data.success && data.users) {
          this.renderSearchResults(data.users);
        }
      } catch (error) {
        console.error('[Messenger] Search failed:', error);
      }
    }

    /**
     * Render search results
     */
    renderSearchResults(users) {
      const list = this.widget.querySelector('[data-conversation-list]');
      if (!list) return;

      const items = list.querySelectorAll('.c-messenger__conversation');
      items.forEach(item => item.remove());

      users.forEach(user => {
        const item = document.createElement('div');
        item.className = 'c-messenger__conversation';
        item.dataset.conversationId = user.id;

        const avatarUrl = user.avatar_url || '/static/img/default_player.png';

        item.innerHTML = `
          <div class="c-messenger__conversation-avatar">
            <img src="${avatarUrl}" alt="${user.name}"
                 class="c-messenger__conversation-avatar-img"
                 onerror="this.src='/static/img/default_player.png'">
          </div>
          <div class="c-messenger__conversation-body">
            <p class="c-messenger__conversation-name">${user.name}</p>
            <p class="c-messenger__conversation-preview">Click to start chatting</p>
          </div>
        `;

        list.appendChild(item);
      });
    }

    /**
     * Focus search input
     */
    focusSearch() {
      const input = this.widget.querySelector('[data-input="search"]');
      if (input) {
        input.focus();
        input.value = '';
      }
    }

    // ========================================================================
    // UI HELPERS
    // ========================================================================

    /**
     * Show conversation list (exit chat view)
     */
    showList() {
      this.widget.classList.remove('is-chatting');
      this.currentUserId = null;
      this.currentUserName = '';
      this.loadConversations();

      // Reset header
      const headerTitle = this.widget.querySelector('[data-header-title] span');
      if (headerTitle) headerTitle.textContent = 'Messages';
    }

    /**
     * Load unread count
     */
    async loadUnreadCount() {
      try {
        const response = await fetch('/api/messages/unread-count');
        const data = await response.json();
        if (data.success) {
          this.updateBadge(data.count);
        }
      } catch (error) {
        console.warn('[Messenger] Failed to load unread count:', error);
      }
    }

    /**
     * Update badge count
     */
    updateBadge(count) {
      this.unreadCount = count;

      const badge = this.widget.querySelector('[data-badge="unread"]');
      if (badge) {
        badge.textContent = count > 99 ? '99+' : count;
        badge.classList.toggle('u-hidden', count === 0);
      }

      // Update navbar badge too
      const navBadge = document.querySelector('[data-badge="messages-count"]');
      if (navBadge) {
        navBadge.textContent = count > 99 ? '99+' : count;
        navBadge.classList.toggle('u-hidden', count === 0);
      }
    }

    /**
     * Scroll to bottom of container
     */
    scrollToBottom(container) {
      if (container) {
        container.scrollTop = container.scrollHeight;
      }
    }

    /**
     * Escape HTML
     */
    escapeHtml(text) {
      const div = document.createElement('div');
      div.textContent = text;
      return div.innerHTML;
    }

    /**
     * Show toast notification
     */
    showToast(message, type = 'info') {
      if (typeof window.Swal !== 'undefined') {
        window.Swal.fire({
          toast: true,
          position: 'top-end',
          icon: type,
          title: message,
          showConfirmButton: false,
          timer: 3000
        });
      } else {
        console.log(`[${type}]`, message);
      }
    }

    /**
     * Cleanup on destroy
     */
    destroy() {
      Object.values(this.refreshIntervals).forEach(interval => {
        if (interval) clearInterval(interval);
      });
    }
  }

  // Initialize
  window.MessengerWidget = new MessengerWidget();

  // Register with InitSystem (primary)
  if (typeof window.InitSystem !== 'undefined' && window.InitSystem.register) {
    window.InitSystem.register('messenger-widget', () => window.MessengerWidget.init(), {
      priority: 35,
      reinitializable: true,
      description: 'Messenger sidebar widget'
    });
  }

  // Fallback: Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      window.MessengerWidget.init();
    });
  } else {
    window.MessengerWidget.init();
  }

  // Cleanup on page unload
  window.addEventListener('beforeunload', () => {
    window.MessengerWidget.destroy();
  });

// Backward compat
window.MessengerWidget = MessengerWidget;
