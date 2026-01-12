/**
 * Chat Widget - View Management
 * Open/close widget and conversation navigation
 *
 * @module chat-widget/view-manager
 */

import { CONFIG } from './config.js';
import { getState, getElements, setState, setActiveConversation, clearSearchState, resetConversationState } from './state.js';
import { loadConversations, loadUnreadCount, loadMessages } from './api.js';
import { renderConversations, renderMessages, updateBadge, renderRoleBadges, showMessagesLoading, escapeHtml } from './render.js';
import { joinMessagingRoom } from './socket-handler.js';

/**
 * Open the chat widget
 */
export function openWidget() {
  const elements = getElements();
  const state = getState();

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
  loadConversations(renderConversations);
  loadUnreadCount(updateBadge);

  // Join messaging room
  joinMessagingRoom();

  // Focus search on desktop
  if (window.innerWidth > 575 && elements.searchInput) {
    setTimeout(() => elements.searchInput.focus(), CONFIG.ui.animationDuration);
  }
}

/**
 * Close the chat widget
 */
export function closeWidget() {
  const elements = getElements();
  const state = getState();

  if (!elements.widget) return;

  state.isOpen = false;
  resetConversationState();
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

/**
 * Toggle widget open/close
 */
export function toggleWidget() {
  const state = getState();
  if (state.isOpen) {
    closeWidget();
  } else {
    openWidget();
  }
}

/**
 * Open a conversation with a user
 * @param {number|string} userId - User ID
 * @param {string} userName - User name
 * @param {string} avatarUrl - Avatar URL
 * @param {boolean|string} isOnline - Online status
 * @param {Object} roleInfo - Role information
 */
export function openConversation(userId, userName, avatarUrl, isOnline, roleInfo) {
  const elements = getElements();
  const state = getState();

  // Track when conversation was opened to prevent immediate close from click events
  state.lastConversationOpenTime = Date.now();

  state.currentView = 'chat';
  setActiveConversation({
    id: parseInt(userId),
    name: userName,
    avatar: avatarUrl,
    isOnline: isOnline === 'true' || isOnline === true,
    roles: roleInfo || {}
  });

  if (elements.widget) {
    elements.widget.dataset.view = 'chat';
  }

  // Update chat header
  const defaultAvatar = CONFIG.ui.defaultAvatar;

  if (elements.chatAvatar) {
    elements.chatAvatar.src = avatarUrl || defaultAvatar;
    elements.chatAvatar.onerror = function() { this.src = defaultAvatar; };
  }
  if (elements.chatName) {
    // Display name with role badges
    const roleBadges = renderRoleBadges(roleInfo);
    elements.chatName.innerHTML = escapeHtml(userName) + roleBadges;
  }
  if (elements.chatStatus) {
    const activeConversation = state.activeConversation;
    elements.chatStatus.textContent = activeConversation.isOnline ? 'Online' : 'Offline';
    elements.chatStatus.classList.toggle('c-chat-widget__chat-status--offline', !activeConversation.isOnline);
  }

  // Update avatar online status
  if (elements.chatAvatarContainer) {
    elements.chatAvatarContainer.classList.toggle('c-chat-widget__chat-avatar--online', state.activeConversation.isOnline);
  }

  // Show loading state
  showMessagesLoading();

  // Load messages
  loadMessages(userId, renderMessages, scrollToBottom);

  // Focus composer
  if (elements.composerInput) {
    setTimeout(() => elements.composerInput.focus(), CONFIG.ui.animationDuration);
  }
}

/**
 * Close current conversation (back to list)
 */
export function closeConversation() {
  const elements = getElements();

  resetConversationState();

  if (elements.widget) {
    elements.widget.dataset.view = 'list';
  }

  // Clear search state when going back
  clearSearch();

  // Refresh conversations
  loadConversations(renderConversations);
}

/**
 * Scroll messages container to bottom
 */
export function scrollToBottom() {
  const elements = getElements();

  if (elements.messagesContainer) {
    requestAnimationFrame(() => {
      elements.messagesContainer.scrollTop = elements.messagesContainer.scrollHeight;
    });
  }
}

/**
 * Clear search input and results
 */
export function clearSearch() {
  const elements = getElements();

  clearSearchState();

  if (elements.searchInput) {
    elements.searchInput.value = '';
  }
  if (elements.searchResults) {
    elements.searchResults.classList.remove('is-visible');
    elements.searchResults.innerHTML = '';
  }
}

/**
 * Update widget position based on mobile nav
 */
export function updatePosition() {
  const elements = getElements();

  if (!elements.widget) return;

  // Check for mobile bottom nav
  const mobileNav = document.querySelector('.mobile-bottom-nav, .c-mobile-nav, [data-mobile-nav]');
  if (mobileNav) {
    const navHeight = mobileNav.offsetHeight;
    document.documentElement.style.setProperty('--mobile-nav-height', `${navHeight}px`);
  }
}

export default {
  openWidget,
  closeWidget,
  toggleWidget,
  openConversation,
  closeConversation,
  scrollToBottom,
  clearSearch,
  updatePosition
};
