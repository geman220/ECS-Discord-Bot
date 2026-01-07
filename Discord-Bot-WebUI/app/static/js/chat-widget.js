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
 * Refactored to use modular subcomponents in ./chat-widget/:
 * - config.js: Configuration constants and emoji map
 * - state.js: State management and DOM element caching
 * - api.js: Server communication
 * - render.js: DOM rendering functions
 * - view-manager.js: Open/close widget and navigation
 * - event-handlers.js: User interaction handlers
 * - socket-handler.js: WebSocket integration
 *
 * CSS: /static/css/components/c-chat-widget.css
 * Uses BEM naming: .c-chat-widget__*
 *
 * @requires Socket.IO (for real-time messaging)
 * @requires /api/messages endpoints
 * @module chat-widget
 */
'use strict';

import { InitSystem } from './init-system.js';
import { EventDelegation } from './event-delegation/core.js';

// Import from submodules
import { CONFIG, EMOJI_MAP } from './chat-widget/config.js';

import {
  cacheElements,
  getElements,
  getState,
  isInitialized,
  setInitialized,
  setState,
  updateSettings,
  setActiveConversation,
  getActiveConversation,
  addMessage,
  updateMessage,
  removeMessage,
  clearSearchState,
  resetConversationState
} from './chat-widget/state.js';

import {
  fetchJSON,
  loadConversations,
  loadMessages,
  sendMessage,
  loadUnreadCount,
  searchUsers,
  deleteMessage
} from './chat-widget/api.js';

import {
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
} from './chat-widget/render.js';

import {
  openWidget,
  closeWidget,
  toggleWidget,
  openConversation,
  closeConversation,
  scrollToBottom,
  clearSearch,
  updatePosition
} from './chat-widget/view-manager.js';

import {
  initWebSocket,
  joinMessagingRoom,
  emitTypingStart,
  showTypingIndicator,
  hideTypingIndicator
} from './chat-widget/socket-handler.js';

import {
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
  autoResizeTextarea
} from './chat-widget/event-handlers.js';

/**
 * Bind DOM event listeners
 */
function bindEvents() {
  const elements = getElements();

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
    elements.composerInput.addEventListener('touchstart', function() {
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
      const state = getState();
      if (state.currentView === 'chat') {
        closeConversation();
      }
      if (elements.searchInput) {
        elements.searchInput.focus();
      }
    });
  }
}

/**
 * Initialize chat widget
 */
function initChatWidget() {
  // Guard against duplicate initialization
  if (isInitialized()) return;

  // Page guard - only initialize if chat widget exists on page
  if (!document.querySelector('.c-chat-widget')) {
    console.log('[ChatWidget] No widget element found, skipping initialization');
    return;
  }

  setInitialized();

  cacheElements();
  bindEvents();
  initWebSocket();
  updatePosition();

  // Load initial unread count
  loadUnreadCount(updateBadge);

  // Polling fallback
  if (CONFIG.polling.enabled) {
    setInterval(() => loadUnreadCount(updateBadge), CONFIG.polling.interval);
  }

  console.log('[ChatWidget] Initialized');
}

// Register with InitSystem
if (window.InitSystem && window.InitSystem.register) {
  window.InitSystem.register('chat-widget', initChatWidget, {
    priority: 35,
    reinitializable: true,
    description: 'Floating chat widget'
  });
}

// Event Delegation - delete-menu handler
window.EventDelegation.register('delete-menu', handleDeleteMenuClick, { preventDefault: true });

// Public API
const ChatWidget = {
  open: openWidget,
  close: closeWidget,
  toggle: toggleWidget,
  openConversation: openConversation,
  refresh: () => loadConversations(renderConversations),
  getUnreadCount: () => getState().unreadCount
};

// Backward compatibility - expose to global scope
window.ChatWidget = ChatWidget;
window.escapeHtml = escapeHtml;

// Export for ES modules
export {
  initChatWidget,
  ChatWidget,
  CONFIG,
  EMOJI_MAP,
  // State
  getState,
  getElements,
  setState,
  setActiveConversation,
  getActiveConversation,
  // API
  loadConversations,
  loadMessages,
  sendMessage,
  loadUnreadCount,
  searchUsers,
  deleteMessage,
  // Render
  renderConversations,
  renderMessages,
  renderSearchResults,
  renderOnlineUsers,
  updateBadge,
  formatMessageTime,
  getCurrentUserId,
  // View
  openWidget,
  closeWidget,
  toggleWidget,
  openConversation,
  closeConversation,
  scrollToBottom,
  clearSearch,
  // Socket
  initWebSocket,
  joinMessagingRoom,
  emitTypingStart
};

export default ChatWidget;
