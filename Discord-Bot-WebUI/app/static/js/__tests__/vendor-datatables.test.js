/**
 * DataTables + jQuery integration smoke test
 * @module __tests__/vendor-datatables
 *
 * Why this exists: the `js-tests` CI job runs vitest but never `npm run build`, and
 * the rest of the suite only covers plain utility modules. That left jQuery and
 * DataTables — the two most upgrade-sensitive vendor libraries in the app — with
 * ZERO automated coverage, so a major bump of either could go green in CI and only
 * break in a browser. A Dependabot PR bumping datatables.net alone (leaving
 * datatables.net-dt on the previous major) passed every check.
 *
 * This mirrors app/static/js/vendor-globals.js exactly: same imports, same plugin
 * registration order. It asserts the integration points the app actually relies on,
 * including the option shapes used at real init sites.
 */

import { describe, it, expect, beforeAll, afterEach } from 'vitest';
import $ from 'jquery';

// DataTables resolves `window.jQuery` when its module initializer runs (see the
// jQuerySetup() path in datatables.net/js/dataTables.mjs). In the browser that
// ordering is satisfied for free: jQuery's dist assigns window.jQuery/$ as it loads,
// which happens before the DataTables import is evaluated. Under vitest, a top-level
// `import DataTable from 'datatables.net-dt'` is hoisted above every statement, so
// window.jQuery would still be unset and DataTables would silently skip attaching
// itself to $.fn. Import it dynamically instead, after the globals are in place —
// this reproduces the real load order rather than working around it.
let DataTable;

beforeAll(async () => {
  window.jQuery = $;
  window.$ = $;
  DataTable = (await import('datatables.net-dt')).default;
  await import('datatables.net-responsive-dt');
});

function buildTable() {
  document.body.innerHTML = `
    <table id="t">
      <thead><tr><th>Name</th><th>Team</th><th>Goals</th></tr></thead>
      <tbody>
        <tr><td>Ana</td><td>Reds</td><td>7</td></tr>
        <tr><td>Ben</td><td>Blues</td><td>3</td></tr>
        <tr><td>Cy</td><td>Reds</td><td>11</td></tr>
      </tbody>
    </table>`;
  return document.getElementById('t');
}

describe('jQuery + DataTables integration', () => {
  afterEach(() => {
    if ($.fn.DataTable && $.fn.DataTable.isDataTable('#t')) {
      $('#t').DataTable().destroy();
    }
    document.body.innerHTML = '';
  });

  it('registers DataTable as a jQuery plugin', () => {
    // The app never calls the imported `DataTable` symbol directly — every init site
    // is `$(sel).DataTable(...)`, which only works if the module patched $.fn.
    expect(typeof DataTable).toBe('function');
    expect(typeof $.fn.DataTable).toBe('function');
    expect(typeof $.fn.DataTable.isDataTable).toBe('function');
  });

  it('initializes and renders rows', () => {
    buildTable();
    const dt = $('#t').DataTable({ info: true, paging: true, pageLength: 10 });
    expect(dt.rows().count()).toBe(3);
    expect($.fn.DataTable.isDataTable('#t')).toBe(true);
  });

  it('supports the option shapes used at real init sites', () => {
    buildTable();
    // Mirrors the union of options across the app's DataTable() calls.
    const dt = $('#t').DataTable({
      info: true,
      responsive: true,
      pageLength: 25,
      lengthMenu: [[10, 25, 50, -1], [10, 25, 50, 'All']],
      order: [[2, 'desc']],
      columnDefs: [{ targets: 2, type: 'num' }],
      language: { search: 'Filter:', emptyTable: 'Nothing here' },
      destroy: true,
    });
    expect(dt.rows().count()).toBe(3);
  });

  it('loads the Responsive extension (used by 13 init sites)', () => {
    buildTable();
    $('#t').DataTable({ responsive: true });
    expect($.fn.dataTable.Responsive).toBeDefined();
  });

  it('still accepts the legacy `dom` option strings the app passes', () => {
    // DataTables 2 deprecated `dom` in favour of `layout`. Two live init sites still
    // pass `dom` (mobile-forms.js and custom_js/admin-manage-subs.js). If a future
    // major removes it, this test fails instead of the page silently losing its
    // search box and pagination controls.
    buildTable();
    expect(() => {
      $('#t').DataTable({ dom: '<"top"f>rt<"bottom"ip><"clear">', destroy: true });
    }).not.toThrow();
  });

  it('filters via the search API', () => {
    buildTable();
    const dt = $('#t').DataTable();
    dt.search('Reds').draw();
    expect(dt.rows({ search: 'applied' }).count()).toBe(2);
  });

  it('sorts numerically on the ordered column', () => {
    buildTable();
    const dt = $('#t').DataTable({ order: [[2, 'desc']] });
    const first = dt.rows({ order: 'applied' }).data()[0];
    expect(first[0]).toBe('Cy'); // 11 goals
  });

  it('destroys cleanly so re-init is safe', () => {
    buildTable();
    $('#t').DataTable({ destroy: true });
    $('#t').DataTable().destroy();
    expect($.fn.DataTable.isDataTable('#t')).toBe(false);
    expect(() => $('#t').DataTable({ destroy: true })).not.toThrow();
  });
});
