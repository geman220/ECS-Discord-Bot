/**
 * Chat Widget - Event Handlers
 * User interaction handlers for the chat widget
 *
 * @module chat-widget/event-handlers
 */

import { CONFIG } from './config.js';
import { getState, getElements } from './state.js';
import { sendMessage, searchUsers, deleteMessage, loadMoreMessages, retryMessage } from './api.js';
import { renderMessages, renderSearchResults, updateSendButton, getCurrentUserId } from './render.js';
import { toggleWidget, closeWidget, openConversation, closeConversation, scrollToBottom, clearSearch } from './view-manager.js';
import { emitTypingStart } from './socket-handler.js';

/**
 * Handle trigger button click
 * @param {Event} e - Click event
 */
export function handleTriggerClick(e) {
  e.preventDefault();
  e.stopPropagation();
  toggleWidget();
}

/**
 * Handle conversation/user click
 * @param {Event} e - Click event
 */
export function handleConversationClick(e) {
  const conversation = e.target.closest('.c-chat-widget__conversation, .c-chat-widget__online-user, .c-chat-widget__search-result');
  if (!conversation) return;

  const userId = conversation.dataset.userId;
  const userName = conversation.dataset.userName;
  const avatarUrl = conversation.dataset.avatar;
  const isOnline = conversation.dataset.online;

  // Get role info from data attributes
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

/**
 * Handle back button click
 * @param {Event} e - Click event
 */
export function handleBackClick(e) {
  e.preventDefault();
  closeConversation();
}

/**
 * Handle send button click
 * @param {Event} e - Click event
 */
export function handleSendClick(e) {
  e.preventDefault();
  const state = getState();
  const elements = getElements();

  if (!state.activeConversation || !elements.composerInput) return;

  const content = elements.composerInput.value.trim();
  if (!content) return;

  sendMessage(state.activeConversation.id, content, renderMessages, scrollToBottom);
}

/**
 * Handle composer keydown
 * @param {Event} e - Keydown event
 */
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

/**
 * Handle composer input
 */
export function handleComposerInput() {
  const elements = getElements();
  updateSendButton();
  autoResizeTextarea(elements.composerInput);
}

// Search debounce timer
let searchDebounceTimer = null;

/**
 * Handle search input
 * @param {Event} e - Input event
 */
export function handleSearchInput(e) {
  const state = getState();
  const query = e.target.value.trim();
  state.searchQuery = query;
  console.log('[ChatWidget] Search input:', query);

  clearTimeout(searchDebounceTimer);
  searchDebounceTimer = setTimeout(() => {
    searchUsers(query, renderSearchResults);
  }, CONFIG.ui.searchDebounce);
}

/**
 * Handle search input focus
 */
export function handleSearchFocus() {
  const state = getState();
  const elements = getElements();

  if (state.searchResults.length > 0 && elements.searchResults) {
    elements.searchResults.classList.add('is-visible');
  }
}

/**
 * Handle search input blur
 */
export function handleSearchBlur() {
  const elements = getElements();

  // Delay hiding to allow click on results
  setTimeout(() => {
    if (elements.searchResults) {
      elements.searchResults.classList.remove('is-visible');
    }
  }, 200);
}

/**
 * Handle global keydown
 * @param {Event} e - Keydown event
 */
export function handleKeydown(e) {
  const state = getState();

  // Close on Escape
  if (e.key === 'Escape') {
    if (state.currentView === 'chat') {
      closeConversation();
    } else if (state.isOpen) {
      closeWidget();
    }
  }
}

/**
 * Handle click outside widget
 * @param {Event} e - Click event
 */
export function handleClickOutside(e) {
  const elements = getElements();
  const state = getState();

  if (!elements.widget || !state.isOpen) return;

  // Don't close if clicking inside widget or its descendants
  if (elements.widget.contains(e.target)) return;

  // Don't close if target is no longer in DOM (e.g., search result that was cleared)
  // This happens when clicking search results - the element is removed before click fires
  if (!document.contains(e.target)) return;

  // Don't close if we just opened a conversation (within last 500ms)
  // This prevents race conditions with search result clicks
  if (state.lastConversationOpenTime && (Date.now() - state.lastConversationOpenTime) < 500) {
    return;
  }

  // Don't close on mobile (full screen)
  if (window.innerWidth <= 575) return;

  closeWidget();
}

/**
 * Handle delete menu button click
 * @param {Element} element - Clicked element
 * @param {Event} e - Click event
 */
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

/**
 * Show delete confirmation dialog
 * @param {number} messageId - Message ID
 * @param {boolean} isSent - Whether message was sent by current user
 */
function showDeleteConfirmation(messageId, isSent) {
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
        deleteMessage(messageId, 'me', renderMessages, scrollToBottom);
      } else if (result.isDenied) {
        // Unsend for everyone
        deleteMessage(messageId, 'everyone', renderMessages, scrollToBottom);
      }
    });
  } else {
    console.error('SweetAlert2 is required for confirmation dialogs.');
  }
}

/**
 * Auto-resize textarea based on content
 * @param {HTMLTextAreaElement} textarea - Textarea element
 */
export function autoResizeTextarea(textarea) {
  if (!textarea) return;

  textarea.style.height = 'auto';
  textarea.style.height = Math.min(textarea.scrollHeight, 120) + 'px';
}

/**
 * Handle load more messages click
 * @param {Element} element - Clicked element
 * @param {Event} e - Click event
 */
export function handleLoadMoreClick(element, e) {
  e.preventDefault();
  e.stopPropagation();

  const state = getState();
  if (!state.activeConversation || state.isLoadingMore) return;

  loadMoreMessages(state.activeConversation.id, renderMessages);
}

/**
 * Handle retry failed message click
 * @param {Element} element - Clicked element
 * @param {Event} e - Click event
 */
export function handleRetryMessageClick(element, e) {
  e.preventDefault();
  e.stopPropagation();

  const messageEl = element.closest('.c-chat-widget__message');
  if (!messageEl) return;

  const messageId = messageEl.dataset.messageId;
  if (!messageId) return;

  retryMessage(messageId, renderMessages, scrollToBottom);
}

export default {
  handleTriggerClick,
  handleConversationClick,
  handleBackClick,
  handleSendClick,
  handleComposerKeydown,
  handleComposerInput,
  handleSearchInput,
  handleSearchFocus,
  handleSearchBlur,
  handleKeydown,
  handleClickOutside,
  handleDeleteMenuClick,
  handleLoadMoreClick,
  handleRetryMessageClick,
  autoResizeTextarea
};
