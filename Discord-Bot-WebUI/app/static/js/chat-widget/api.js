/**
 * Chat Widget - API Functions
 * Server communication for conversations and messages
 *
 * @module chat-widget/api
 */

import { CONFIG } from './config.js';
import { getState, getElements, updateSettings, addMessage, updateMessage, removeMessage } from './state.js';

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
 * Load messages for a user
 * @param {number} userId - User ID
 * @param {Function} renderCallback - Callback to render messages
 * @param {Function} scrollCallback - Callback to scroll to bottom
 */
export async function loadMessages(userId, renderCallback, scrollCallback) {
  const state = getState();
  try {
    const data = await fetchJSON(CONFIG.api.messages(userId));
    if (data.success) {
      state.messages = data.messages || [];
      updateSettings(data.settings || {});
      if (renderCallback) renderCallback();
      if (scrollCallback) scrollCallback();

      // Return for chaining
      return data;
    }
  } catch (error) {
    console.error('[ChatWidget] Failed to load messages', error);
  }
  return null;
}

/**
 * Send a message
 * @param {number} userId - Recipient user ID
 * @param {string} content - Message content
 * @param {Function} renderCallback - Callback to render messages
 * @param {Function} scrollCallback - Callback to scroll to bottom
 * @returns {Promise<Object>} Response data
 */
export async function sendMessage(userId, content, renderCallback, scrollCallback) {
  const state = getState();
  const elements = getElements();

  try {
    const data = await fetchJSON(CONFIG.api.send(userId), {
      method: 'POST',
      body: JSON.stringify({ content })
    });

    if (data.success) {
      // Add message to local state
      addMessage(data.message);
      if (renderCallback) renderCallback();
      if (scrollCallback) scrollCallback();

      // Clear input
      if (elements.composerInput) {
        elements.composerInput.value = '';
        elements.composerInput.style.height = 'auto';
      }

      return data;
    }

    return data;
  } catch (error) {
    console.error('[ChatWidget] Failed to send message', error);
    window.showToast('Failed to send message', 'error');
    throw error;
  }
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
  sendMessage,
  loadUnreadCount,
  searchUsers,
  deleteMessage
};
