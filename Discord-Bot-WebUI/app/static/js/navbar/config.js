/**
 * Navbar - Configuration
 * Constants and configuration for the navbar
 *
 * @module navbar/config
 */

import { showToast as toastServiceShowToast } from '../services/toast-service.js';

export const CONFIG = {
  scrollThreshold: 50,
  notificationRefreshInterval: 60000,   // 60 seconds
  presenceRefreshInterval: 120000,       // 2 minutes
  searchDebounce: 300
};

/**
 * Get CSRF token from meta tag, input field, or cookie
 * @returns {string} CSRF token
 */
export function getCSRFToken() {
  // Try meta tag first
  const csrfMeta = document.querySelector('meta[name="csrf-token"]');
  if (csrfMeta) {
    return csrfMeta.getAttribute('content');
  }

  // Try hidden input field
  const csrfInput = document.querySelector('input[name="csrf_token"]');
  if (csrfInput) {
    return csrfInput.value;
  }

  // Try cookie
  const cookies = document.cookie.split(';');
  for (const cookie of cookies) {
    const [name, value] = cookie.trim().split('=');
    if (name === 'csrf_token') {
      return decodeURIComponent(value);
    }
  }

  return '';
}

/**
 * Escape HTML to prevent XSS
 * @param {string} text - Text to escape
 * @returns {string} Escaped text
 */
export function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// showToast imported from services/toast-service.js
export const showToast = toastServiceShowToast;

export default { CONFIG, getCSRFToken, escapeHtml, showToast };
