/**
 * Mobile Table Enhancer
 * 
 * Adds data-title attributes to table cells for mobile view
 * Specifically targets complex tables like user management tables
 */
document.addEventListener('DOMContentLoaded', function() {
  // Find all tables that need mobile enhancement but aren't already card tables
  const tables = document.querySelectorAll('.table:not(.mobile-card-table)');
  
  tables.forEach(function(table) {
    // Get header text for each column
    const headers = [];
    const headerCells = table.querySelectorAll('thead th');
    
    headerCells.forEach(function(th) {
      headers.push(th.textContent.trim());
    });
    
    // Apply data-title to each cell in the table body
    const rows = table.querySelectorAll('tbody tr');
    
    rows.forEach(function(row) {
      const cells = row.querySelectorAll('td');
      
      cells.forEach(function(cell, index) {
        if (index < headers.length && !cell.hasAttribute('data-title')) {
          cell.setAttribute('data-title', headers[index]);
        }
      });
    });
  });

  // Fix dropdown opening behavior on mobile
  const dropdownToggles = document.querySelectorAll('.dropdown-toggle');
  
  dropdownToggles.forEach(function(toggle) {
    toggle.addEventListener('click', function(e) {
      // On mobile, ensure the dropdown stays in view
      if (window.innerWidth < 992) {
        const dropdown = this.nextElementSibling;
        if (dropdown && dropdown.classList.contains('dropdown-menu')) {
          // Briefly show the dropdown to calculate its height
          dropdown.style.display = 'block';
          dropdown.style.visibility = 'hidden';
          
          setTimeout(() => {
            const dropdownHeight = dropdown.offsetHeight;
            const windowHeight = window.innerHeight;
            const toggleRect = this.getBoundingClientRect();
            const toggleMiddle = toggleRect.top + (toggleRect.height / 2);
            
            // Position the dropdown based on available space
            if (toggleMiddle < windowHeight / 2) {
              // More space below, show dropdown below
              dropdown.style.top = 'auto';
              dropdown.style.bottom = 'auto';
              dropdown.style.maxHeight = 'calc(100vh - ' + (toggleRect.bottom + 10) + 'px)';
            } else {
              // More space above, show dropdown above
              dropdown.style.bottom = 'auto';
              dropdown.style.top = 'auto';
              dropdown.style.maxHeight = 'calc(100vh - 100px)';
            }
            
            dropdown.style.display = '';
            dropdown.style.visibility = '';
          }, 10);
        }
      }
    });
  });

  // Handle dropdown menu overflowing screen edges
  function adjustDropdownPosition() {
    const openDropdowns = document.querySelectorAll('.dropdown-menu.show');
    
    openDropdowns.forEach(function(dropdown) {
      const rect = dropdown.getBoundingClientRect();
      
      // If dropdown extends beyond right edge, adjust position
      if (rect.right > window.innerWidth) {
        dropdown.style.left = 'auto';
        dropdown.style.right = '0';
      }
      
      // If dropdown extends beyond bottom edge, adjust position
      if (rect.bottom > window.innerHeight) {
        dropdown.style.top = 'auto';
        dropdown.style.bottom = '100%';
      }
    });
  }

  // Monitor dropdowns opening
  const observer = new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
      if (mutation.type === 'attributes' && 
          mutation.attributeName === 'class' && 
          mutation.target.classList.contains('dropdown-menu') && 
          mutation.target.classList.contains('show')) {
        adjustDropdownPosition();
      }
    });
  });

  // Observe all dropdown menus for class changes
  document.querySelectorAll('.dropdown-menu').forEach(function(dropdown) {
    observer.observe(dropdown, { attributes: true });
  });

  // Fix pagination on mobile
  const paginationContainers = document.querySelectorAll('.pagination');
  
  if (window.innerWidth < 768 && paginationContainers.length > 0) {
    paginationContainers.forEach(function(pagination) {
      // If there are many pages, create a condensed view
      const pageItems = pagination.querySelectorAll('.page-item:not(.disabled):not(.active)');
      
      if (pageItems.length > 7) {
        let visiblePages = [];
        const activePage = pagination.querySelector('.page-item.active');
        
        if (activePage) {
          const activePageNum = parseInt(activePage.textContent.trim(), 10) || 1;
          
          // Show first, last, and pages around active
          const allPageItems = Array.from(pagination.querySelectorAll('.page-item'));
          const firstItem = allPageItems.find(item => !item.classList.contains('disabled') && item.textContent.trim() !== '«');
          const lastItem = [...allPageItems].reverse().find(item => !item.classList.contains('disabled') && item.textContent.trim() !== '»');
          
          // Hide all pages first
          pageItems.forEach(item => {
            if (item !== firstItem && item !== lastItem) {
              item.style.display = 'none';
            }
          });
          
          // Show pages around active
          allPageItems.forEach(item => {
            const pageNum = parseInt(item.textContent.trim(), 10) || 0;
            if (!isNaN(pageNum) && (
                pageNum === activePageNum || 
                pageNum === activePageNum - 1 || 
                pageNum === activePageNum + 1 ||
                pageNum === 1 ||
                pageNum === parseInt(lastItem.textContent.trim(), 10)
              )) {
              item.style.display = '';
            }
          });
          
          // Add ellipsis if needed
          if (activePageNum > 3) {
            const ellipsisBefore = document.createElement('li');
            ellipsisBefore.className = 'page-item disabled';
            ellipsisBefore.innerHTML = '<span class="page-link">…</span>';
            firstItem.after(ellipsisBefore);
          }
          
          if (activePageNum < parseInt(lastItem.textContent.trim(), 10) - 2) {
            const ellipsisAfter = document.createElement('li');
            ellipsisAfter.className = 'page-item disabled';
            ellipsisAfter.innerHTML = '<span class="page-link">…</span>';
            
            const activeIndex = allPageItems.findIndex(item => item === activePage);
            if (activeIndex !== -1 && activeIndex < allPageItems.length - 1) {
              allPageItems[activeIndex + 1].after(ellipsisAfter);
            }
          }
        }
      }
    });
  }
});