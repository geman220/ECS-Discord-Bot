/**
 * Chat Widget - Socket Handler
 * WebSocket integration for real-time messaging
 *
 * @module chat-widget/socket-handler
 */

import { CONFIG } from './config.js';
import { getState, getElements, addMessage, updateMessage, setConnectionStatus, flushOfflineQueue } from './state.js';
import { loadConversations, loadUnreadCount, sendMessage } from './api.js';
import { renderConversations, renderMessages, renderOnlineUsers, updateBadge, renderConnectionStatus } from './render.js';
import { scrollToBottom } from './view-manager.js';

// Audio element for notification sound
let notificationSound = null;

// Socket reference
let socket = null;

/**
 * Initialize notification sound
 */
function initNotificationSound() {
  if (notificationSound) return;

  try {
    notificationSound = new Audio(CONFIG.sounds.newMessage);
    notificationSound.volume = 0.5;
    // Preload
    notificationSound.load();
  } catch (e) {
    console.warn('[ChatWidget] Could not initialize notification sound:', e);
  }
}

/**
 * Play notification sound
 */
export function playNotificationSound() {
  const state = getState();

  if (!CONFIG.sounds.enabled || !state.settings.soundEnabled) return;

  if (!notificationSound) {
    initNotificationSound();
  }

  if (notificationSound) {
    notificationSound.currentTime = 0;
    notificationSound.play().catch(() => {
      // Ignore - often blocked by browser until user interaction
    });
  }
}

/**
 * Process offline queue after reconnection
 */
async function processOfflineQueue() {
  const queue = flushOfflineQueue();

  if (queue.length === 0) return;

  console.log('[ChatWidget] Processing', queue.length, 'queued messages');
  window.showToast(`Sending ${queue.length} queued message(s)...`, 'info');

  for (const item of queue) {
    try {
      await sendMessage(item.userId, item.content, item.renderCallback, item.scrollCallback);
    } catch (error) {
      console.error('[ChatWidget] Failed to send queued message:', error);
    }
  }
}

/**
 * Initialize WebSocket connection
 */
export function initWebSocket() {
  // Initialize notification sound
  initNotificationSound();

  // Use SocketManager if available (preferred method)
  if (typeof window.SocketManager !== 'undefined') {
    console.log('[ChatWidget] Using SocketManager');

    // Get socket reference
    socket = window.SocketManager.getSocket();

    // Register connect callback - fires immediately if already connected
    window.SocketManager.onConnect('ChatWidget', function(connectedSocket) {
      socket = connectedSocket;
      console.log('[ChatWidget] Socket connected via SocketManager');

      // Update connection status
      setConnectionStatus(true, false);
      renderConnectionStatus();

      // Join messaging room when connected
      const state = getState();
      if (state.isOpen) {
        joinMessagingRoom();
      }

      // Process any queued messages
      processOfflineQueue();
    });

    // Register disconnect callback
    window.SocketManager.onDisconnect('ChatWidget', function(reason) {
      console.log('[ChatWidget] Socket disconnected:', reason);
      setConnectionStatus(false, true);
      renderConnectionStatus();
    });

    // Attach event listeners via SocketManager
    attachSocketListeners();

    // Set initial connection status
    setConnectionStatus(window.SocketManager.isConnected(), false);
    renderConnectionStatus();
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

  // Show notification if widget is closed or not focused on this conversation
  const shouldNotify = !state.isOpen ||
                       !state.activeConversation ||
                       state.activeConversation.id !== message.sender_id;

  if (shouldNotify) {
    // Play sound notification
    playNotificationSound();

    // Show browser notification
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
    elements.typingIndicator.classList.add('is-visible');
    elements.typingIndicator.classList.remove('d-none');
    scrollToBottom();
  }
}

/**
 * Hide typing indicator
 */
export function hideTypingIndicator() {
  const elements = getElements();

  if (elements.typingIndicator) {
    elements.typingIndicator.classList.remove('is-visible');
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
  playNotificationSound,
  showTypingIndicator,
  hideTypingIndicator
};
