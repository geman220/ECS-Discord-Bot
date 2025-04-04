/**
 * Page Loader Script
 * 
 * Shows a loading indicator while the page is loading and hides it when done
 */

document.addEventListener('DOMContentLoaded', function() {
  // Hide loader after short delay
  setTimeout(function() {
    const loader = document.getElementById('page-loader');
    if (loader) {
      loader.classList.add('hidden');
      setTimeout(function() {
        if (loader.parentNode) {
          loader.parentNode.removeChild(loader);
        }
      }, 500);
    }
  }, 800);
});