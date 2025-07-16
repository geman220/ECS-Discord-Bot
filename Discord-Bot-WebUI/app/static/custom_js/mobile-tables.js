// Simple table label injection - that's it
document.addEventListener('DOMContentLoaded', function() {
  function addTableLabels() {
    const tables = document.querySelectorAll('.table-responsive table');
    
    tables.forEach(table => {
      if (table.dataset.labeled) return;
      
      const headers = Array.from(table.querySelectorAll('thead th')).map(th => th.textContent.trim());
      
      table.querySelectorAll('tbody tr').forEach(row => {
        Array.from(row.querySelectorAll('td')).forEach((cell, index) => {
          if (headers[index] && !cell.hasAttribute('data-label')) {
            cell.setAttribute('data-label', headers[index]);
          }
        });
      });
      
      table.dataset.labeled = 'true';
    });
  }
  
  // Run once on load
  addTableLabels();
  
  // Run after AJAX if jQuery exists
  if (typeof $ !== 'undefined') {
    $(document).on('ajaxComplete', addTableLabels);
  }
});