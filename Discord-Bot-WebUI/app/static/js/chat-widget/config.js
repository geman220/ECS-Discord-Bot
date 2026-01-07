/**
 * Chat Widget - Configuration
 * API endpoints and UI settings
 *
 * @module chat-widget/config
 */

export const CONFIG = {
  api: {
    conversations: '/api/messages',
    messages: (userId) => `/api/messages/${userId}`,
    send: (userId) => `/api/messages/${userId}`,
    unreadCount: '/api/messages/unread-count',
    searchUsers: '/api/messages/users/search',
    markRead: (msgId) => `/api/messages/${msgId}/read`,
    deleteMessage: (msgId) => `/api/messages/message/${msgId}`,
    hideMessage: (msgId) => `/api/messages/message/${msgId}/hide`
  },
  polling: {
    enabled: true,
    interval: 30000
  },
  ui: {
    animationDuration: 250,
    typingDebounce: 2000,
    searchDebounce: 300,
    maxMessageLength: 2000,
    defaultAvatar: '/static/img/default_player.png'
  }
};

// Emoji shortcode conversion map
export const EMOJI_MAP = {
  ':)': '😊', ':-)': '😊', '=)': '😊',
  ':(': '😞', ':-(': '😞', '=(': '😞',
  ':D': '😃', ':-D': '😃', '=D': '😃',
  ';)': '😉', ';-)': '😉',
  ':P': '😛', ':-P': '😛', ':p': '😛',
  ':O': '😮', ':-O': '😮', ':o': '😮',
  '<3': '❤️', '</3': '💔',
  ':*': '😘', ':-*': '😘',
  ":'(": '😢', ":')": '😂',
  ':fire:': '🔥', ':heart:': '❤️', ':thumbsup:': '👍', ':thumbsdown:': '👎',
  ':clap:': '👏', ':wave:': '👋', ':ok:': '👌', ':100:': '💯',
  ':star:': '⭐', ':sun:': '☀️', ':moon:': '🌙', ':soccer:': '⚽',
  ':trophy:': '🏆', ':medal:': '🏅', ':crown:': '👑',
  ':check:': '✅', ':x:': '❌', ':warning:': '⚠️',
  ':party:': '🎉', ':confetti:': '🎊',
  'xD': '😆', 'XD': '😆',
  'B)': '😎', 'B-)': '😎',
  '-_-': '😑', ':|': '😐',
  ':angry:': '😠', '>:(': '😠',
  ':thinking:': '🤔', ':shrug:': '🤷',
  ':pray:': '🙏', ':muscle:': '💪',
  ':eyes:': '👀', ':sweat:': '😅',
  ':cool:': '😎', ':lol:': '😂', ':rofl:': '🤣'
};

export default { CONFIG, EMOJI_MAP };
