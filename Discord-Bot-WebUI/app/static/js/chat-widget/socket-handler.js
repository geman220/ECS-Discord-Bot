/**
 * Chat Widget - Socket Handler
 * WebSocket integration for real-time messaging
 *
 * @module chat-widget/socket-handler
 */

import { CONFIG } from './config.js';
import { getState, getElements, addMessage, updateMessage } from './state.js';
import { loadConversations, loadUnreadCount } from './api.js';
import { renderConversations, renderMessages, renderOnlineUsers, updateBadge } from './render.js';
import { scrollToBottom } from './view-manager.js';

// Socket reference
let socket = null;

/**
 * Initialize WebSocket connection
 */
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
      const state = getState();
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
      setInterval(() => loadUnreadCount(updateBadge), CONFIG.polling.interval);
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

/**
 * Attach socket listeners via SocketManager
 */
function attachSocketListeners() {
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

/**
 * Attach socket listeners directly to window.socket
 */
function attachSocketListenersDirect() {
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

/**
 * Join messaging room
 */
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

/**
 * Handle incoming new message
 * @param {Object} message - Message data
 */
function handleNewMessage(message) {
  const state = getState();

  // Update unread count
  state.unreadCount++;
  updateBadge();

  // If in active conversation with sender, add message
  if (state.activeConversation && message.sender_id === state.activeConversation.id) {
    addMessage(message);
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
  loadConversations(renderConversations);

  // Show notification if widget is closed
  if (!state.isOpen) {
    showNotification(message.sender_name, message.content);
  }
}

/**
 * Handle message sent confirmation
 * @param {Object} data - Response data
 */
function handleMessageSent(data) {
  // Message already added locally, just confirm
  console.log('[ChatWidget] Message sent:', data.message?.id);
}

/**
 * Handle message error
 * @param {Object} data - Error data
 */
function handleMessageError(data) {
  window.showToast(data.error || 'Failed to send message', 'error');
}

/**
 * Handle unread count update
 * @param {Object} data - Unread data
 */
function handleUnreadUpdate(data) {
  const state = getState();
  state.unreadCount = data.count;
  updateBadge();
}

/**
 * Handle message deleted event
 * @param {Object} data - Delete data
 */
function handleMessageDeleted(data) {
  const messageId = data.message_id;
  const deletedFor = data.deleted_for;

  if (deletedFor === 'everyone') {
    // Mark as unsent (show placeholder)
    updateMessage(messageId, { is_deleted: true, content: null });
    renderMessages();
  }
  // Note: 'delete for me' by the other user doesn't affect our view
}

/**
 * Handle user typing event
 * @param {Object} data - Typing data
 */
function handleUserTyping(data) {
  const state = getState();

  if (!state.activeConversation || data.user_id !== state.activeConversation.id) return;

  if (data.typing) {
    showTypingIndicator();
  } else {
    hideTypingIndicator();
  }
}

/**
 * Handle messages read event
 * @param {Object} data - Read data
 */
function handleMessagesRead(data) {
  const state = getState();

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

/**
 * Handle user online event
 * @param {Object} data - Online data
 */
function handleUserOnline(data) {
  const state = getState();
  const elements = getElements();

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

/**
 * Handle user offline event
 * @param {Object} data - Offline data
 */
function handleUserOffline(data) {
  const state = getState();
  const elements = getElements();

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

/**
 * Handle online users list
 * @param {Object} data - Online users data
 */
function handleOnlineUsers(data) {
  const state = getState();
  state.onlineUsers = data.users || [];
  renderOnlineUsers(state.onlineUsers);
}

/**
 * Update user online status in DOM
 * @param {number} userId - User ID
 * @param {boolean} isOnline - Online status
 */
function updateUserOnlineStatus(userId, isOnline) {
  const convElements = document.querySelectorAll(`[data-user-id="${userId}"]`);
  convElements.forEach(el => {
    el.dataset.online = isOnline;
    const avatar = el.querySelector('.c-chat-widget__conv-avatar, .c-chat-widget__online-avatar');
    if (avatar) {
      avatar.classList.toggle('c-chat-widget__conv-avatar--online', isOnline);
    }
  });
}

/**
 * Emit typing start event
 */
export function emitTypingStart() {
  const state = getState();

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

/**
 * Show typing indicator
 */
export function showTypingIndicator() {
  const elements = getElements();

  if (elements.typingIndicator) {
    elements.typingIndicator.style.display = 'flex';
    scrollToBottom();
  }
}

/**
 * Hide typing indicator
 */
export function hideTypingIndicator() {
  const elements = getElements();

  if (elements.typingIndicator) {
    elements.typingIndicator.style.display = 'none';
  }
}

/**
 * Show browser notification
 * @param {string} title - Notification title
 * @param {string} body - Notification body
 */
function showNotification(title, body) {
  // Browser notification if permitted
  if ('Notification' in window && Notification.permission === 'granted') {
    new Notification(title, {
      body: body.length > 50 ? body.substring(0, 50) + '...' : body,
      icon: '/static/images/logo-icon.png',
      tag: 'chat-message'
    });
  }
}

export default {
  initWebSocket,
  joinMessagingRoom,
  emitTypingStart,
  showTypingIndicator,
  hideTypingIndicator
};
