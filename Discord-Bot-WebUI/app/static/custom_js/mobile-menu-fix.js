/**
 * Mobile Menu Fix - Ensures the sidebar menu works properly on mobile devices
 * Particularly for iOS Safari where touchability issues occur
 */

document.addEventListener('DOMContentLoaded', function() {
  // References to key elements
  const layoutMenu = document.getElementById('layout-menu');
  const menuToggleIcon = document.getElementById('menu-toggle-icon');
  const closeIcon = document.getElementById('close-icon');
  const layoutOverlay = document.querySelector('.layout-overlay');
  
  // Create layout overlay if it doesn't exist
  if (!layoutOverlay) {
    const overlayDiv = document.createElement('div');
    overlayDiv.className = 'layout-overlay';
    document.body.appendChild(overlayDiv);
  }

  // Function to open menu
  function openMenu() {
    document.documentElement.classList.add('layout-menu-expanded');
    document.body.classList.add('layout-menu-expanded');
    if (layoutMenu) {
      layoutMenu.style.transform = 'translateX(0)';
    }
    if (closeIcon) {
      closeIcon.classList.remove('d-none');
    }
  }

  // Function to close menu
  function closeMenu() {
    document.documentElement.classList.remove('layout-menu-expanded');
    document.body.classList.remove('layout-menu-expanded');
    if (layoutMenu) {
      layoutMenu.style.transform = 'translateX(-100%)';
    }
    if (closeIcon) {
      closeIcon.classList.add('d-none');
    }
  }

  // Toggle menu function
  function toggleMenu() {
    if (document.documentElement.classList.contains('layout-menu-expanded')) {
      closeMenu();
    } else {
      openMenu();
    }
  }

  // Event listeners for menu toggle
  const menuToggles = document.querySelectorAll('.layout-menu-toggle');
  menuToggles.forEach(toggle => {
    toggle.addEventListener('click', function(e) {
      e.preventDefault();
      toggleMenu();
    });
  });

  // Close when clicking the X icon
  if (closeIcon) {
    closeIcon.addEventListener('click', function(e) {
      e.preventDefault();
      closeMenu();
    });
  }

  // Close when clicking the overlay
  document.addEventListener('click', function(e) {
    if (e.target.classList.contains('layout-overlay') && 
        document.documentElement.classList.contains('layout-menu-expanded')) {
      closeMenu();
    }
  });

  // Fix for any inert attributes on menu items
  const menuItems = document.querySelectorAll('.menu-item a');
  menuItems.forEach(item => {
    item.removeAttribute('inert');
    item.style.pointerEvents = 'auto';
  });

  // Remove problematic attributes from the menu
  if (layoutMenu) {
    layoutMenu.removeAttribute('inert');
    layoutMenu.style.pointerEvents = 'auto';
    layoutMenu.style.userSelect = 'auto';
    layoutMenu.style.touchAction = 'auto';
  }

  // iOS specific fixes
  const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || 
               (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  
  if (isIOS) {
    // Extra iOS fixes
    document.documentElement.classList.add('ios-device');
    
    // Fix scrolling in menu for iOS
    if (layoutMenu) {
      layoutMenu.style.webkitOverflowScrolling = 'touch';
    }
    
    // Additional handling for iOS gesture conflicts
    const menuLinks = document.querySelectorAll('.menu-link, .menu-toggle');
    menuLinks.forEach(link => {
      link.addEventListener('touchstart', function(e) {
        // Ensure links are touchable
        e.stopPropagation();
      }, { passive: true });
    });
  }
});