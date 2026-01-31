/**
 * Flowbite Drawer Backdrop Cleanup
 *
 * Flowbite drawers can leave orphaned backdrop elements when closed,
 * which block touch events on the page. This module watches for
 * sidebar close events and removes any orphaned backdrops.
 *
 * @module navbar/drawer-cleanup
 */

/**
 * Initialize drawer cleanup functionality
 */
export function initDrawerCleanup() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;

  // Watch for sidebar attribute changes (aria-hidden, class changes)
  const observer = new MutationObserver((mutations) => {
    for (const mutation of mutations) {
      if (mutation.type === 'attributes') {
        const isHidden = sidebar.getAttribute('aria-hidden') === 'true' ||
                        sidebar.classList.contains('hidden') ||
                        !sidebar.classList.contains('transform-none');

        if (isHidden) {
          // Slight delay to let Flowbite finish its cleanup
          setTimeout(cleanupBackdrops, 100);
        }
      }
    }
  });

  observer.observe(sidebar, {
    attributes: true,
    attributeFilter: ['aria-hidden', 'class']
  });

  // Also clean up on page visibility change (user switching tabs/apps)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      cleanupBackdrops();
    }
  });

  // Clean up on window resize (drawer state often changes)
  let resizeTimer;
  window.addEventListener('resize', () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(cleanupBackdrops, 200);
  });

  console.debug('[DrawerCleanup] Initialized');
}

/**
 * Remove orphaned backdrop elements from the DOM
 * These can block touch events if not properly cleaned up
 */
export function cleanupBackdrops() {
  // Flowbite drawer backdrops have the drawer-backdrop attribute
  const drawerBackdrops = document.querySelectorAll('body > div[drawer-backdrop]');
  drawerBackdrops.forEach(el => {
    el.remove();
    console.debug('[DrawerCleanup] Removed drawer-backdrop element');
  });

  // Also check for generic fixed overlay divs that might be orphaned backdrops
  // These are typically full-screen, transparent overlays with high z-index
  const potentialBackdrops = document.querySelectorAll('body > div.fixed.inset-0');
  potentialBackdrops.forEach(el => {
    // Only remove if it's empty (just a backdrop, no content)
    // and has a z-index suggesting it's an overlay
    if (el.children.length === 0) {
      const zIndex = parseInt(window.getComputedStyle(el).zIndex, 10);
      // Flowbite uses z-30 for drawer backdrops
      if (zIndex >= 30 && zIndex < 50) {
        el.remove();
        console.debug('[DrawerCleanup] Removed orphaned fixed overlay');
      }
    }
  });
}

export default { initDrawerCleanup, cleanupBackdrops };
