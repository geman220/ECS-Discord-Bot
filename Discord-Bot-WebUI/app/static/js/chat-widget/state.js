/**
 * Chat Widget - State Management
 * Centralized state and DOM element caching
 *
 * @module chat-widget/state
 */

// Initialization flag
let _initialized = false;

// Widget state
const state = {
  isOpen: false,
  currentView: 'list', // 'list' | 'chat'
  activeConversation: null,
  conversations: [],
  messages: [],
  unreadCount: 0,
  onlineUsers: [],
  isTyping: false,
  typingTimeout: null,
  searchQuery: '',
  searchResults: [],
  settings: {
    typingIndicators: true,
    readReceipts: true,
    maxMessageLength: 2000
  }
};

// Cached DOM elements
let elements = {};

/**
 * Cache DOM elements for quick access
 */
export function cacheElements() {
  elements = {
    widget: document.querySelector('.c-chat-widget'),
    trigger: document.querySelector('.c-chat-widget__trigger'),
    badge: document.querySelector('.c-chat-widget__badge'),
    panel: document.querySelector('.c-chat-widget__panel'),

    // List view
    listView: document.querySelector('.c-chat-widget__list-view'),
    searchInput: document.querySelector('.c-chat-widget__search-input'),
    searchResults: document.querySelector('.c-chat-widget__search-results'),
    onlineList: document.querySelector('.c-chat-widget__online-list'),
    conversationList: document.querySelector('.c-chat-widget__conversations'),
    emptyState: document.querySelector('.c-chat-widget__empty'),

    // Chat view
    chatView: document.querySelector('.c-chat-widget__chat'),
    backBtn: document.querySelector('.c-chat-widget__back-btn'),
    chatAvatar: document.querySelector('.c-chat-widget__chat-avatar img'),
    chatAvatarContainer: document.querySelector('.c-chat-widget__chat-avatar'),
    chatName: document.querySelector('.c-chat-widget__chat-name'),
    chatStatus: document.querySelector('.c-chat-widget__chat-status'),
    messagesContainer: document.querySelector('.c-chat-widget__messages'),
    typingIndicator: document.querySelector('.c-chat-widget__typing'),
    composerInput: document.querySelector('.c-chat-widget__composer-input'),
    sendBtn: document.querySelector('.c-chat-widget__send-btn'),

    // Header buttons
    newChatBtn: document.querySelector('[data-action="new-chat"]'),
    openInboxBtn: document.querySelector('[data-action="open-inbox"]'),
    closeBtns: document.querySelectorAll('[data-action="close-widget"]')
  };
}

/**
 * Get cached DOM elements
 * @returns {Object} Elements object
 */
export function getElements() {
  return elements;
}

/**
 * Get current state
 * @returns {Object} State object
 */
export function getState() {
  return state;
}

/**
 * Check if initialized
 * @returns {boolean}
 */
export function isInitialized() {
  return _initialized;
}

/**
 * Set initialized flag
 */
export function setInitialized() {
  _initialized = true;
}

/**
 * Update state property
 * @param {string} key - State key
 * @param {*} value - New value
 */
export function setState(key, value) {
  if (key in state) {
    state[key] = value;
  }
}

/**
 * Update settings
 * @param {Object} newSettings - Settings to merge
 */
export function updateSettings(newSettings) {
  state.settings = { ...state.settings, ...newSettings };
}

/**
 * Set active conversation
 * @param {Object|null} conversation - Conversation data
 */
export function setActiveConversation(conversation) {
  state.activeConversation = conversation;
}

/**
 * Get active conversation
 * @returns {Object|null}
 */
export function getActiveConversation() {
  return state.activeConversation;
}

/**
 * Add message to state
 * @param {Object} message - Message object
 */
export function addMessage(message) {
  state.messages.push(message);
}

/**
 * Update message in state
 * @param {number} messageId - Message ID
 * @param {Object} updates - Properties to update
 */
export function updateMessage(messageId, updates) {
  const msgIndex = state.messages.findIndex(m => m.id === messageId);
  if (msgIndex !== -1) {
    state.messages[msgIndex] = { ...state.messages[msgIndex], ...updates };
  }
}

/**
 * Remove message from state
 * @param {number} messageId - Message ID
 */
export function removeMessage(messageId) {
  state.messages = state.messages.filter(m => m.id !== messageId);
}

/**
 * Clear search state
 */
export function clearSearchState() {
  state.searchQuery = '';
  state.searchResults = [];
}

/**
 * Reset conversation state
 */
export function resetConversationState() {
  state.currentView = 'list';
  state.activeConversation = null;
  state.messages = [];
}

export default {
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
};
