/**
 * Chat Widget - API Functions
 * Server communication for conversations and messages
 *
 * @module chat-widget/api
 */

import { CONFIG } from './config.js';
import { getState, getElements, updateSettings, addMessage, updateMessage, removeMessage, prependMessages, addToOfflineQueue, removeFromOfflineQueue } from './state.js';

/**
 * Get CSRF token from meta tag or cookie
 * @returns {string} CSRF token
 */
function getCSRFToken() {
  // Try meta tag first
  const meta = document.querySelector('meta[name="csrf-token"]');
  if (meta) return meta.getAttribute('content');

  // Fallback to cookie
  const cookies = document.cookie.split(';');
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'csrf_token') return decodeURIComponent(value);
  }

  return '';
}

/**
 * Fetch JSON with error handling and CSRF support
 * @param {string} url - API URL
 * @param {Object} options - Fetch options
 * @returns {Promise<Object>} Response data
 */
export async function fetchJSON(url, options = {}) {
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
    console.error(`[ChatWidget] API Error: ${url}`, error);
    throw error;
  }
}

/**
 * Load all conversations
 * @param {Function} renderCallback - Callback to render conversations
 */
export async function loadConversations(renderCallback) {
  const state = getState();
  try {
    const data = await fetchJSON(CONFIG.api.conversations);
    if (data.success) {
      state.conversations = data.conversations || [];
      if (renderCallback) renderCallback();
    }
  } catch (error) {
    console.error('[ChatWidget] Failed to load conversations', error);
  }
}

/**
 * Load messages for a user (initial load)
 * @param {number} userId - User ID
 * @param {Function} renderCallback - Callback to render messages
 * @param {Function} scrollCallback - Callback to scroll to bottom
 */
export async function loadMessages(userId, renderCallback, scrollCallback) {
  const state = getState();
  try {
    // Reset pagination state
    state.messageOffset = 0;
    state.hasMoreMessages = true;

    const data = await fetchJSON(CONFIG.api.messages(userId, 0, CONFIG.ui.messagesPerPage));
    if (data.success) {
      state.messages = data.messages || [];
      state.hasMoreMessages = data.has_more !== false && (data.messages?.length || 0) >= CONFIG.ui.messagesPerPage;
      state.messageOffset = state.messages.length;
      updateSettings(data.settings || {});
      if (renderCallback) renderCallback();
      if (scrollCallback) scrollCallback();

      return data;
    }
  } catch (error) {
    console.error('[ChatWidget] Failed to load messages', error);
  }
  return null;
}

/**
 * Load more (older) messages
 * @param {number} userId - User ID
 * @param {Function} renderCallback - Callback to render messages
 * @returns {Promise<boolean>} Whether more messages were loaded
 */
export async function loadMoreMessages(userId, renderCallback) {
  const state = getState();

  if (state.isLoadingMore || !state.hasMoreMessages) {
    return false;
  }

  state.isLoadingMore = true;

  try {
    const data = await fetchJSON(CONFIG.api.messages(userId, state.messageOffset, CONFIG.ui.messagesPerPage));
    if (data.success) {
      const newMessages = data.messages || [];

      if (newMessages.length > 0) {
        // Prepend older messages to the beginning
        prependMessages(newMessages);
        state.messageOffset += newMessages.length;
        state.hasMoreMessages = newMessages.length >= CONFIG.ui.messagesPerPage;
        if (renderCallback) renderCallback(true); // true = prepending
      } else {
        state.hasMoreMessages = false;
      }

      return newMessages.length > 0;
    }
  } catch (error) {
    console.error('[ChatWidget] Failed to load more messages', error);
  } finally {
    state.isLoadingMore = false;
  }
  return false;
}

/**
 * Send a message (with offline queue support)
 * @param {number} userId - Recipient user ID
 * @param {string} content - Message content
 * @param {Function} renderCallback - Callback to render messages
 * @param {Function} scrollCallback - Callback to scroll to bottom
 * @returns {Promise<Object>} Response data
 */
export async function sendMessage(userId, content, renderCallback, scrollCallback) {
  const state = getState();
  const elements = getElements();

  // Generate temp ID for optimistic UI
  const tempId = `temp_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

  // Create optimistic message
  const optimisticMessage = {
    id: tempId,
    content,
    sender_id: getCurrentUserId(),
    recipient_id: userId,
    created_at: new Date().toISOString(),
    is_read: false,
    is_pending: true
  };

  // Add optimistically to local state
  addMessage(optimisticMessage);
  if (renderCallback) renderCallback();
  if (scrollCallback) scrollCallback();

  // Clear input immediately for better UX
  if (elements.composerInput) {
    elements.composerInput.value = '';
    elements.composerInput.style.height = 'auto';
  }

  // If offline, queue the message
  if (!state.isConnected) {
    addToOfflineQueue({
      tempId,
      userId,
      content,
      renderCallback,
      scrollCallback
    });
    window.showToast('Message queued - will send when online', 'info');
    return { success: true, queued: true };
  }

  try {
    const data = await fetchJSON(CONFIG.api.send(userId), {
      method: 'POST',
      body: JSON.stringify({ content })
    });

    if (data.success) {
      // Replace optimistic message with real one
      updateMessage(tempId, {
        id: data.message.id,
        is_pending: false,
        created_at: data.message.created_at
      });
      if (renderCallback) renderCallback();
      return data;
    } else {
      // Mark as failed
      updateMessage(tempId, { is_failed: true, is_pending: false });
      if (renderCallback) renderCallback();
      window.showToast(data.error || 'Failed to send message', 'error');
      return data;
    }
  } catch (error) {
    console.error('[ChatWidget] Failed to send message', error);

    // Mark as failed but keep in UI for retry
    updateMessage(tempId, { is_failed: true, is_pending: false });
    if (renderCallback) renderCallback();
    window.showToast('Failed to send message - tap to retry', 'error');

    throw error;
  }
}

/**
 * Get current user ID
 * @returns {number|null}
 */
function getCurrentUserId() {
  if (window.currentUserId) return parseInt(window.currentUserId);
  const meta = document.querySelector('meta[name="user-id"]');
  if (meta) return parseInt(meta.content);
  return null;
}

/**
 * Retry sending a failed message
 * @param {string} tempId - Temporary message ID
 * @param {Function} renderCallback - Callback to render messages
 * @param {Function} scrollCallback - Callback to scroll to bottom
 */
export async function retryMessage(tempId, renderCallback, scrollCallback) {
  const state = getState();
  const message = state.messages.find(m => m.id === tempId);

  if (!message || !message.is_failed) return;

  // Mark as pending again
  updateMessage(tempId, { is_pending: true, is_failed: false });
  if (renderCallback) renderCallback();

  try {
    const data = await fetchJSON(CONFIG.api.send(message.recipient_id), {
      method: 'POST',
      body: JSON.stringify({ content: message.content })
    });

    if (data.success) {
      updateMessage(tempId, {
        id: data.message.id,
        is_pending: false,
        created_at: data.message.created_at
      });
    } else {
      updateMessage(tempId, { is_failed: true, is_pending: false });
      window.showToast(data.error || 'Failed to send message', 'error');
    }
  } catch (error) {
    updateMessage(tempId, { is_failed: true, is_pending: false });
  }

  if (renderCallback) renderCallback();
}

/**
 * Load unread message count
 * @param {Function} updateCallback - Callback to update badge
 */
export async function loadUnreadCount(updateCallback) {
  const state = getState();
  try {
    const data = await fetchJSON(CONFIG.api.unreadCount);
    if (data.success) {
      state.unreadCount = data.count;
      if (updateCallback) updateCallback();
    }
  } catch (error) {
    console.error('[ChatWidget] Failed to load unread count', error);
  }
}

/**
 * Search for users
 * @param {string} query - Search query
 * @param {Function} renderCallback - Callback to render results
 */
export async function searchUsers(query, renderCallback) {
  const state = getState();

  if (query.length < 2) {
    state.searchResults = [];
    if (renderCallback) renderCallback();
    return;
  }

  console.log('[ChatWidget] Searching users for:', query);

  try {
    const data = await fetchJSON(`${CONFIG.api.searchUsers}?q=${encodeURIComponent(query)}`);
    console.log('[ChatWidget] Search response:', data);

    if (data.success) {
      state.searchResults = data.users || [];
      if (renderCallback) renderCallback();
      console.log('[ChatWidget] Found', state.searchResults.length, 'users');
    } else {
      console.warn('[ChatWidget] Search returned success=false:', data.error);
      state.searchResults = [];
      if (renderCallback) renderCallback();
    }
  } catch (error) {
    console.error('[ChatWidget] Failed to search users', error);
    state.searchResults = [];
    if (renderCallback) renderCallback();
  }
}

/**
 * Search messages content
 * @param {string} query - Search query
 * @param {Function} renderCallback - Callback to render results
 */
export async function searchMessages(query, renderCallback) {
  const state = getState();

  if (query.length < 2) {
    state.messageSearchResults = [];
    state.isSearchingMessages = false;
    if (renderCallback) renderCallback();
    return;
  }

  state.isSearchingMessages = true;
  state.messageSearchQuery = query;

  try {
    const data = await fetchJSON(`${CONFIG.api.searchMessages}?q=${encodeURIComponent(query)}`);

    if (data.success) {
      state.messageSearchResults = data.results || [];
      if (renderCallback) renderCallback();
    } else {
      state.messageSearchResults = [];
      if (renderCallback) renderCallback();
    }
  } catch (error) {
    console.error('[ChatWidget] Failed to search messages', error);
    state.messageSearchResults = [];
    if (renderCallback) renderCallback();
  } finally {
    state.isSearchingMessages = false;
  }
}

/**
 * Delete a message
 * @param {number} messageId - Message ID
 * @param {string} deleteFor - 'me' or 'everyone'
 * @param {Function} renderCallback - Callback to render messages
 * @param {Function} scrollCallback - Callback to scroll to bottom
 */
export async function deleteMessage(messageId, deleteFor, renderCallback, scrollCallback) {
  try {
    let url, method;

    if (deleteFor === 'everyone') {
      url = CONFIG.api.deleteMessage(messageId);
      method = 'DELETE';
    } else {
      url = CONFIG.api.hideMessage(messageId);
      method = 'POST';
    }

    const response = await fetchJSON(url, { method });

    if (response.success) {
      if (deleteFor === 'everyone') {
        // Update message in local state to show as deleted
        updateMessage(messageId, { is_deleted: true, content: null });
      } else {
        // Remove from local state (hidden for me)
        removeMessage(messageId);
      }

      if (renderCallback) renderCallback();
      if (scrollCallback) scrollCallback();
      window.showToast(deleteFor === 'everyone' ? 'Message unsent' : 'Message deleted', 'success');
      return true;
    } else {
      window.showToast(response.error || 'Failed to delete message', 'error');
      return false;
    }
  } catch (error) {
    console.error('[ChatWidget] Delete message error:', error);
    window.showToast('Failed to delete message', 'error');
    return false;
  }
}

export default {
  fetchJSON,
  loadConversations,
  loadMessages,
  loadMoreMessages,
  sendMessage,
  retryMessage,
  loadUnreadCount,
  searchUsers,
  searchMessages,
  deleteMessage
};
