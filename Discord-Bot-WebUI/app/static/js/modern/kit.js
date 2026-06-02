/*
 * Modern kit interactions — sort + filter for `_modern_kit.html` data_table().
 * (Modals/toasts/alerts reuse Flowbite's data-modal and data-dismiss-target JS,
 * already bundled — this module only owns table sort & filter.)
 *
 * Hooks (emitted by the kit macros):
 *   - section[data-modern-table]      → scope for a table + its filter
 *   - input[type="search"] (in scope) → live row filter
 *   - th[data-sort-key][data-sort-dir]→ sortable header (aria-sort kept in sync)
 *   - td[data-sort-value]             → optional explicit sort key for a cell
 *   - [data-row-card]                 → mobile card row (filtered alongside <tr>)
 *
 * Delegated at document level so it works for dynamically-injected tables too.
 */

function cellSortValue(cell) {
  if (!cell) return '';
  return (cell.getAttribute('data-sort-value') ?? cell.textContent ?? '').trim();
}

function compareValues(a, b) {
  const na = parseFloat(a.replace(/[^0-9.\-]/g, ''));
  const nb = parseFloat(b.replace(/[^0-9.\-]/g, ''));
  const bothNumeric = a !== '' && b !== '' && Number.isFinite(na) && Number.isFinite(nb)
    && /^[\s$£€%0-9.,\-]+$/.test(a) && /^[\s$£€%0-9.,\-]+$/.test(b);
  if (bothNumeric) return na - nb;
  return a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' });
}

function setHeaderState(th, dir) {
  th.setAttribute('data-sort-dir', dir);
  th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none');
  const icon = th.querySelector('i.ti');
  if (icon) {
    icon.classList.remove('ti-arrows-sort', 'ti-sort-ascending', 'ti-sort-descending', 'text-ecs-green', 'opacity-60');
    if (dir === 'asc') icon.classList.add('ti-sort-ascending', 'text-ecs-green');
    else if (dir === 'desc') icon.classList.add('ti-sort-descending', 'text-ecs-green');
    else icon.classList.add('ti-arrows-sort', 'opacity-60');
  }
}

function sortByHeader(th) {
  const table = th.closest('table');
  if (!table) return;
  const headerRow = th.parentElement;
  const colIndex = Array.prototype.indexOf.call(headerRow.children, th);
  if (colIndex < 0) return;
  const tbody = table.querySelector('tbody');
  if (!tbody) return;

  const current = th.getAttribute('data-sort-dir') || 'none';
  const dir = current === 'asc' ? 'desc' : 'asc';

  // Reset sibling headers, set this one.
  headerRow.querySelectorAll('th[data-sort-key]').forEach((other) => {
    if (other !== th) setHeaderState(other, 'none');
  });
  setHeaderState(th, dir);

  const rows = Array.prototype.slice.call(tbody.querySelectorAll(':scope > tr'));
  rows.sort((r1, r2) => {
    const v = compareValues(cellSortValue(r1.children[colIndex]), cellSortValue(r2.children[colIndex]));
    return dir === 'asc' ? v : -v;
  });
  rows.forEach((r) => tbody.appendChild(r)); // re-append in sorted order
}

function filterTable(input) {
  const scope = input.closest('[data-modern-table]');
  if (!scope) return;
  const q = input.value.trim().toLowerCase();
  scope.querySelectorAll('tbody > tr, [data-row-card], [data-row]').forEach((row) => {
    const match = !q || (row.textContent || '').toLowerCase().includes(q);
    row.classList.toggle('hidden', !match);
  });
}

// --- Delegated wiring -------------------------------------------------------
document.addEventListener('click', (e) => {
  const th = e.target.closest('th[data-sort-key]');
  if (th) sortByHeader(th);
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter' && e.key !== ' ') return;
  const th = e.target.closest('th[data-sort-key]');
  if (th) { e.preventDefault(); sortByHeader(th); }
});

document.addEventListener('input', (e) => {
  const input = e.target;
  if (input.matches('[data-modern-table] input[type="search"]')) filterTable(input);
});

// --- Chart.js token theming (best-effort) --------------------------------------
// Sets Chart.js global defaults from the CSS theme tokens so charts render with
// brand/dark-aware text + grid colors. Charts rendered after this pick it up;
// call window.applyChartTheme() + chart.update() to recolor a live chart on toggle.
function themeCharts() {
  if (!window.Chart) return;
  const cs = getComputedStyle(document.documentElement);
  const text = (cs.getPropertyValue('--color-text-muted') || '').trim() || '#71717a';
  const grid = (cs.getPropertyValue('--color-border') || '').trim() || '#e4e4e7';
  try {
    window.Chart.defaults.color = text;
    window.Chart.defaults.borderColor = grid;
    window.Chart.defaults.font = window.Chart.defaults.font || {};
    window.Chart.defaults.font.family = "'Inter', ui-sans-serif, system-ui, sans-serif";
  } catch (e) { /* Chart not ready / older API */ }
}
window.applyChartTheme = themeCharts;
if (document.readyState !== 'loading') themeCharts();
else document.addEventListener('DOMContentLoaded', themeCharts);

// --- Progress/volume bars ------------------------------------------------------
// Sets the width of [data-bar-fill] elements from their data-pct value (0-100).
// Lets templates render dynamic-percentage bars without inline style= (the JIT
// Tailwind build can't see runtime w-[X%] values, so width is applied here).
function fillBars(scope) {
  (scope || document).querySelectorAll('[data-bar-fill]').forEach((el) => {
    const pct = Math.max(0, Math.min(100, parseFloat(el.getAttribute('data-pct')) || 0));
    el.style.width = pct + '%';
  });
}
window.fillBars = fillBars;
if (document.readyState !== 'loading') fillBars();
else document.addEventListener('DOMContentLoaded', () => fillBars());
