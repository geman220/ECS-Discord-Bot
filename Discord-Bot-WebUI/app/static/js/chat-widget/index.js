/**
 * Chat Widget - Main Entry Point
 * Facebook Messenger-inspired floating chat widget
 *
 * @module chat-widget
 */

import { CONFIG } from './config.js';
import { cacheElements, getElements, isInitialized, setInitialized, getState } from './state.js';
import { loadUnreadCount } from './api.js';
import { updateBadge } from './render.js';
import { openWidget, closeWidget, toggleWidget, openConversation, updatePosition } from './view-manager.js';
import { initWebSocket } from './socket-handler.js';
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
  handleDeleteMenuClick
} from './event-handlers.js';
import { loadConversations } from './api.js';
import { renderConversations } from './render.js';

// Re-export everything for external access
export * from './config.js';
export * from './state.js';
export * from './api.js';
export * from './render.js';
export * from './view-manager.js';
export * from './socket-handler.js';
export * from './event-handlers.js';

/**
 * Bind DOM event listeners using event delegation
 */
function bindEvents() {
  // Global events (document-level delegation)
  document.addEventListener('keydown', handleKeydown);
  document.addEventListener('click', handleClickOutside);

  // Window resize
  window.addEventListener('resize', updatePosition);

  // Delegated click handler for all chat widget interactions
  document.addEventListener('click', (e) => {
    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;

    const widget = e.target.closest('.c-chat-widget');
    if (!widget) return;

    const elements = getElements();

    // Trigger button
    if (e.target.closest('[data-chat-trigger]') || e.target.closest('.c-chat-widget__trigger')) {
      handleTriggerClick(e);
      return;
    }

    // Close buttons
    if (e.target.closest('[data-chat-close]') || e.target.closest('.c-chat-widget__close')) {
      closeWidget();
      return;
    }

    // Back button
    if (e.target.closest('[data-chat-back]') || e.target.closest('.c-chat-widget__back-btn')) {
      handleBackClick(e);
      return;
    }

    // Send button
    if (e.target.closest('[data-chat-send]') || e.target.closest('.c-chat-widget__send-btn')) {
      handleSendClick(e);
      return;
    }

    // Open inbox button
    if (e.target.closest('[data-chat-open-inbox]')) {
      window.location.href = '/messages';
      return;
    }

    // New chat button
    if (e.target.closest('[data-chat-new]')) {
      const state = getState();
      if (state.currentView === 'chat') {
        import('./view-manager.js').then(m => m.closeConversation());
      }
      if (elements.searchInput) {
        elements.searchInput.focus();
      }
      return;
    }

    // Conversation clicks (in list, online users, or search results)
    const conversationItem = e.target.closest('.c-chat-widget__conversation-item, .c-chat-widget__online-item, .c-chat-widget__search-item');
    if (conversationItem) {
      handleConversationClick(e);
      return;
    }
  });

  // Delegated input/keydown for composer and search
  document.addEventListener('input', (e) => {
    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;

    if (!e.target.closest('.c-chat-widget')) return;

    if (e.target.matches('.c-chat-widget__composer-input, [data-chat-composer]')) {
      handleComposerInput(e);
    } else if (e.target.matches('.c-chat-widget__search-input, [data-chat-search]')) {
      handleSearchInput(e);
    }
  });

  document.addEventListener('keydown', (e) => {
    // Guard: ensure e.target is an Element with closest method
    if (!e.target || typeof e.target.closest !== 'function') return;

    if (!e.target.closest('.c-chat-widget')) return;

    if (e.target.matches('.c-chat-widget__composer-input, [data-chat-composer]')) {
      handleComposerKeydown(e);
    }
  });

  document.addEventListener('focusin', (e) => {
    if (e.target.matches('.c-chat-widget__search-input, [data-chat-search]')) {
      handleSearchFocus(e);
    }
  });

  document.addEventListener('focusout', (e) => {
    if (e.target.matches('.c-chat-widget__search-input, [data-chat-search]')) {
      handleSearchBlur(e);
    }
  });

  // iOS Safari fix: delegated touchstart for composer
  document.addEventListener('touchstart', (e) => {
    if (e.target.matches('.c-chat-widget__composer-input, [data-chat-composer]')) {
      e.target.style.pointerEvents = 'auto';
    }
  }, { passive: true });
}

/**
 * Initialize chat widget
 */
export function initChatWidget() {
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

// Register event delegation handler
if (window.EventDelegation) {
  window.EventDelegation.register('delete-menu', handleDeleteMenuClick, { preventDefault: true });
}

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

export default ChatWidget;
