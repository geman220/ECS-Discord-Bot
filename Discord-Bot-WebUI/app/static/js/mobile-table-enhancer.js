/**
 * Mobile Table Enhancer
 *
 * Adds data-title attributes to table cells for mobile view
 * Specifically targets complex tables like user management tables
 *
 * REFACTORED: All inline style manipulations replaced with CSS classes
 * - Uses utility classes from /app/static/css/layout/mobile-tables.css
 * - Uses utility classes from /app/static/css/utilities/display-utils.css
 * - Eliminates all .style.* inline manipulations for maintainability
 */
document.addEventListener('DOMContentLoaded', function() {
  // Find all tables that need mobile enhancement but aren't already card tables
  const tables = document.querySelectorAll('[data-table]:not([data-mobile-view])');

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
  const dropdownToggles = document.querySelectorAll('[data-dropdown-toggle]');

  dropdownToggles.forEach(function(toggle) {
    toggle.addEventListener('click', function(e) {
      // On mobile, ensure the dropdown stays in view
      if (window.innerWidth < 992) {
        const dropdown = this.nextElementSibling;
        if (dropdown && dropdown.hasAttribute('data-dropdown-menu')) {
          // Briefly show the dropdown to calculate its height
          // REPLACED: dropdown.style.display = 'block' + dropdown.style.visibility = 'hidden'
          // WITH: .dropdown-measuring class
          dropdown.classList.add('dropdown-measuring');

          setTimeout(() => {
            const dropdownHeight = dropdown.offsetHeight;
            const windowHeight = window.innerHeight;
            const toggleRect = this.getBoundingClientRect();
            const toggleMiddle = toggleRect.top + (toggleRect.height / 2);

            // Position the dropdown based on available space
            if (toggleMiddle < windowHeight / 2) {
              // More space below, show dropdown below
              // REPLACED: dropdown.style.top/bottom/maxHeight
              // WITH: .dropdown-position-below and .dropdown-constrained-below classes
              dropdown.classList.add('dropdown-position-below', 'dropdown-constrained-below');
              dropdown.classList.remove('dropdown-position-above', 'dropdown-constrained-above');

              // Set CSS custom property for dynamic max-height calculation
              const availableSpace = windowHeight - toggleRect.bottom - 10;
              dropdown.style.setProperty('--dropdown-top-offset', `${windowHeight - availableSpace}px`);
            } else {
              // More space above, show dropdown above
              // REPLACED: dropdown.style.top/bottom/maxHeight
              // WITH: .dropdown-position-above and .dropdown-constrained-above classes
              dropdown.classList.add('dropdown-position-above', 'dropdown-constrained-above');
              dropdown.classList.remove('dropdown-position-below', 'dropdown-constrained-below');
            }

            // REPLACED: dropdown.style.display = '' + dropdown.style.visibility = ''
            // WITH: Remove .dropdown-measuring class to restore normal display
            dropdown.classList.remove('dropdown-measuring');
          }, 10);
        }
      }
    });
  });

  // Handle dropdown menu overflowing screen edges
  function adjustDropdownPosition() {
    const openDropdowns = document.querySelectorAll('[data-dropdown-menu].show');

    openDropdowns.forEach(function(dropdown) {
      const rect = dropdown.getBoundingClientRect();

      // If dropdown extends beyond right edge, adjust position
      if (rect.right > window.innerWidth) {
        // REPLACED: dropdown.style.left = 'auto' + dropdown.style.right = '0'
        // WITH: .dropdown-align-right class
        dropdown.classList.add('dropdown-align-right');
        dropdown.classList.remove('dropdown-align-left');
      }

      // If dropdown extends beyond bottom edge, adjust position
      if (rect.bottom > window.innerHeight) {
        // REPLACED: dropdown.style.top = 'auto' + dropdown.style.bottom = '100%'
        // WITH: .dropdown-position-above class
        dropdown.classList.add('dropdown-position-above');
        dropdown.classList.remove('dropdown-position-below');
      }
    });
  }

  // Monitor dropdowns opening
  const observer = new MutationObserver(function(mutations) {
    mutations.forEach(function(mutation) {
      if (mutation.type === 'attributes' &&
          mutation.attributeName === 'class' &&
          mutation.target.hasAttribute('data-dropdown-menu') &&
          mutation.target.classList.contains('show')) {
        adjustDropdownPosition();
      }
    });
  });

  // Observe all dropdown menus for class changes
  document.querySelectorAll('[data-dropdown-menu]').forEach(function(dropdown) {
    observer.observe(dropdown, { attributes: true });
  });

  // Fix pagination on mobile
  const paginationContainers = document.querySelectorAll('[data-pagination]');

  if (window.innerWidth < 768 && paginationContainers.length > 0) {
    paginationContainers.forEach(function(pagination) {
      // If there are many pages, create a condensed view
      const pageItems = pagination.querySelectorAll('[data-page-item]:not([data-page-disabled]):not([data-page-active])');

      if (pageItems.length > 7) {
        let visiblePages = [];
        const activePage = pagination.querySelector('[data-page-item][data-page-active]');

        if (activePage) {
          const activePageNum = parseInt(activePage.textContent.trim(), 10) || 1;

          // Show first, last, and pages around active
          const allPageItems = Array.from(pagination.querySelectorAll('[data-page-item]'));
          const firstItem = allPageItems.find(item => !item.hasAttribute('data-page-disabled') && item.textContent.trim() !== '«');
          const lastItem = [...allPageItems].reverse().find(item => !item.hasAttribute('data-page-disabled') && item.textContent.trim() !== '»');

          // Hide all pages first
          pageItems.forEach(item => {
            if (item !== firstItem && item !== lastItem) {
              // REPLACED: item.style.display = 'none'
              // WITH: .d-none class
              item.classList.add('d-none');
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
              // REPLACED: item.style.display = ''
              // WITH: Remove .d-none class to restore display
              item.classList.remove('d-none');
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
