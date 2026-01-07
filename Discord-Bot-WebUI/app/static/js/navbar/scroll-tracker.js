/**
 * Navbar - Scroll Tracker
 * Track scroll position and add shadow when scrolled
 *
 * @module navbar/scroll-tracker
 */

import { CONFIG } from './config.js';
import { getNavbar, getLastScrollTop, setLastScrollTop } from './state.js';

/**
 * Initialize scroll tracking
 */
export function initScrollTracking() {
  const navbar = getNavbar();
  if (!navbar) return;

  let ticking = false;

  window.addEventListener('scroll', () => {
    if (!ticking) {
      window.requestAnimationFrame(() => {
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

        if (scrollTop > CONFIG.scrollThreshold) {
          navbar.classList.add('is-scrolled');
        } else {
          navbar.classList.remove('is-scrolled');
        }

        setLastScrollTop(scrollTop);
        ticking = false;
      });

      ticking = true;
    }
  });
}

export default { initScrollTracking };
