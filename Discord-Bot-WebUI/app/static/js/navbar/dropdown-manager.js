/**
 * Navbar - Dropdown Manager
 * Handles dropdown open/close, animations, and keyboard navigation
 *
 * @module navbar/dropdown-manager
 */

import { getActiveDropdown, setActiveDropdown } from './state.js';

/**
 * Toggle dropdown open/closed
 * @param {string} dropdownId - Dropdown identifier
 */
export function toggleDropdown(dropdownId) {
  const dropdown = document.querySelector(`[data-dropdown-id="${dropdownId}"]`);
  if (!dropdown) {
    console.warn('[Navbar] No dropdown element found for:', dropdownId);
    return;
  }

  const activeDropdown = getActiveDropdown();

  // Close other dropdowns first
  if (activeDropdown && activeDropdown !== dropdownId) {
    closeDropdown(activeDropdown);
  }

  const isOpen = dropdown.classList.contains('is-open');

  if (isOpen) {
    closeDropdown(dropdownId);
  } else {
    openDropdown(dropdownId);
  }
}

/**
 * Open a dropdown with animation
 * @param {string} dropdownId - Dropdown identifier
 */
export function openDropdown(dropdownId) {
  const dropdown = document.querySelector(`[data-dropdown-id="${dropdownId}"]`);
  const toggle = document.querySelector(`[data-dropdown="${dropdownId}"]`);

  if (!dropdown) {
    console.warn('[Navbar] No dropdown found for:', dropdownId);
    return;
  }

  // Add open class for CSS animation
  dropdown.classList.add('is-open');
  dropdown.setAttribute('aria-hidden', 'false');

  if (toggle) {
    toggle.classList.add('is-active');
    toggle.setAttribute('aria-expanded', 'true');
  }

  setActiveDropdown(dropdownId);

  // Stagger animation for dropdown items
  staggerDropdownItems(dropdown);
}

/**
 * Close a dropdown
 * @param {string} dropdownId - Dropdown identifier
 */
export function closeDropdown(dropdownId) {
  const dropdown = document.querySelector(`[data-dropdown-id="${dropdownId}"]`);
  const toggle = document.querySelector(`[data-dropdown="${dropdownId}"]`);

  if (!dropdown) return;

  dropdown.classList.remove('is-open');
  dropdown.setAttribute('aria-hidden', 'true');

  if (toggle) {
    toggle.classList.remove('is-active');
    toggle.setAttribute('aria-expanded', 'false');
  }

  const activeDropdown = getActiveDropdown();
  if (activeDropdown === dropdownId) {
    setActiveDropdown(null);
  }
}

/**
 * Stagger animation for dropdown items (smooth reveal)
 * @param {HTMLElement} dropdown - Dropdown element
 */
function staggerDropdownItems(dropdown) {
  const items = dropdown.querySelectorAll('.c-navbar-modern__dropdown-item');

  items.forEach((item, index) => {
    item.style.opacity = '0';
    item.style.transform = 'translateX(-8px)';

    setTimeout(() => {
      item.style.transition = 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)';
      item.style.opacity = '1';
      item.style.transform = 'translateX(0)';
    }, index * 30);
  });
}

/**
 * Navigate dropdown items with arrow keys
 * @param {string} direction - 'ArrowDown' or 'ArrowUp'
 */
export function navigateDropdown(direction) {
  const activeDropdown = getActiveDropdown();
  const dropdown = document.querySelector(`[data-dropdown-id="${activeDropdown}"]`);
  if (!dropdown) return;

  const items = Array.from(dropdown.querySelectorAll('.c-navbar-modern__dropdown-item:not([disabled])'));
  const currentIndex = items.findIndex(item => item === document.activeElement);

  let nextIndex;
  if (direction === 'ArrowDown') {
    nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
  } else {
    nextIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
  }

  items[nextIndex]?.focus();
}

/**
 * Handle keyboard navigation
 * @param {KeyboardEvent} e - Keyboard event
 */
export function handleKeyboard(e) {
  const activeDropdown = getActiveDropdown();

  // Escape key - close all dropdowns
  if (e.key === 'Escape' && activeDropdown) {
    closeDropdown(activeDropdown);
    return;
  }

  // Arrow keys for dropdown navigation
  if (activeDropdown && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
    e.preventDefault();
    navigateDropdown(e.key);
    return;
  }
}

/**
 * Close dropdown when clicking outside
 * @param {MouseEvent} e - Click event
 */
export function handleOutsideClick(e) {
  const activeDropdown = getActiveDropdown();
  if (!activeDropdown) return;

  const dropdown = document.querySelector(`[data-dropdown-id="${activeDropdown}"]`);
  const toggle = document.querySelector(`[data-dropdown="${activeDropdown}"]`);

  const isOutside = dropdown && !dropdown.contains(e.target) && toggle && !toggle.contains(e.target);

  if (isOutside) {
    closeDropdown(activeDropdown);
  }
}

/**
 * Toggle mobile menu
 */
export function toggleMobileMenu() {
  const toggle = document.querySelector('[data-action="toggle-menu"]');
  const menu = document.querySelector('[data-mobile-menu]');

  if (!toggle || !menu) return;

  const isOpen = toggle.classList.contains('is-open');

  if (isOpen) {
    toggle.classList.remove('is-open');
    menu.classList.remove('is-open');
    document.body.style.overflow = '';
  } else {
    toggle.classList.add('is-open');
    menu.classList.add('is-open');
    document.body.style.overflow = 'hidden';
  }
}

export default {
  toggleDropdown,
  openDropdown,
  closeDropdown,
  navigateDropdown,
  handleKeyboard,
  handleOutsideClick,
  toggleMobileMenu
};
