/**
 * Navbar - State Management
 * Centralized state for the navbar
 *
 * @module navbar/state
 */

// Navbar element reference
let navbar = null;

// State
let activeDropdown = null;
let lastScrollTop = 0;
let presenceSocket = null;

/**
 * Initialize navbar state
 * @returns {HTMLElement|null} Navbar element
 */
export function initState() {
  navbar = document.querySelector('.c-navbar-modern');
  return navbar;
}

/**
 * Get navbar element
 * @returns {HTMLElement|null}
 */
export function getNavbar() {
  return navbar;
}

/**
 * Get active dropdown ID
 * @returns {string|null}
 */
export function getActiveDropdown() {
  return activeDropdown;
}

/**
 * Set active dropdown ID
 * @param {string|null} dropdownId
 */
export function setActiveDropdown(dropdownId) {
  activeDropdown = dropdownId;
}

/**
 * Get last scroll position
 * @returns {number}
 */
export function getLastScrollTop() {
  return lastScrollTop;
}

/**
 * Set last scroll position
 * @param {number} value
 */
export function setLastScrollTop(value) {
  lastScrollTop = value;
}

/**
 * Get presence socket
 * @returns {Object|null}
 */
export function getPresenceSocket() {
  return presenceSocket;
}

/**
 * Set presence socket
 * @param {Object|null} socket
 */
export function setPresenceSocket(socket) {
  presenceSocket = socket;
}

export default {
  initState,
  getNavbar,
  getActiveDropdown,
  setActiveDropdown,
  getLastScrollTop,
  setLastScrollTop,
  getPresenceSocket,
  setPresenceSocket
};
