/**
 * RSVP Page Fixes
 * 
 * A unified script to fix all issues with the RSVP page, including:
 * - Design system errors
 * - Modal positioning
 * - Dropdown positioning
 * - Other JS errors
 */

// Safely run when the DOM is loaded
(function() {
  // Wait for the DOM to be fully loaded
  document.addEventListener('DOMContentLoaded', function() {
    console.log('RSVP page fixes applied');
    
    // Fix dropdown positioning
    function fixDropdownPositioning() {
      // Using vanilla JS for performance
      document.querySelectorAll('.table-responsive, .card-body, .tab-content, .tab-pane, div.dataTables_wrapper').forEach(function(el) {
        el.style.overflow = 'visible';
        el.style.position = 'relative';
      });
      
      document.querySelectorAll('.dropdown-menu').forEach(function(menu) {
        menu.style.zIndex = '9999';
        menu.style.position = 'absolute';
      });
    }
    
    // Apply the fix after a delay
    setTimeout(fixDropdownPositioning, 500);
    
    // Add event listeners for tab switching
    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(function(tab) {
      tab.addEventListener('shown.bs.tab', function() {
        setTimeout(fixDropdownPositioning, 100);
      });
    });

    // Character counters for messages
    function initCharacterCounters() {
      const smsMessage = document.getElementById('smsMessage');
      const discordMessage = document.getElementById('discordMessage');
      const smsCharCount = document.getElementById('smsCharCount');
      const discordCharCount = document.getElementById('discordCharCount');
      
      if (smsMessage && smsCharCount) {
        smsMessage.addEventListener('input', function() {
          const count = this.value.length;
          smsCharCount.textContent = count;
          
          if (count > 160) {
            smsCharCount.classList.add('text-danger', 'fw-bold');
          } else {
            smsCharCount.classList.remove('text-danger', 'fw-bold');
          }
        });
      }
      
      if (discordMessage && discordCharCount) {
        discordMessage.addEventListener('input', function() {
          const count = this.value.length;
          discordCharCount.textContent = count;
          
          if (count > 2000) {
            discordCharCount.classList.add('text-danger', 'fw-bold');
          } else {
            discordCharCount.classList.remove('text-danger', 'fw-bold');
          }
        });
      }
    }
    
    // Initialize character counters
    initCharacterCounters();
    
    // Periodically reinitialize in case modal elements were added later
    setInterval(initCharacterCounters, 2000);
  });
})();