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

import { describe, it, expect, afterEach } from 'vitest';

// LOAD ORDER IS THE POINT OF THIS FILE — do not "fix" it with a dynamic import.
//
// These three statements mirror app/static/js/vendor-globals.js exactly: it does
// `import jQuery from 'jquery'` (line 21), `Object.assign(window, {$: jQuery, jQuery})`
// (line 22), and `import DataTable from 'datatables.net-dt'` (line 159). ES module
// imports are HOISTED, so the DataTables import is evaluated before line 22 ever runs.
//
// That matters because DataTables 3 dropped its `jquery` dependency (2.x declared
// `"jquery": ">=1.7"`, 3.0.0 declares only `datatables.net`). It now resolves jQuery at
// module-init time via `window.jQuery` (datatables.net/js/dataTables.mjs:1204) and calls
// jQuerySetup() to attach `$.fn.dataTable`. With window.jQuery still unset at that
// moment, registration silently never happens and every `$(sel).DataTable(...)` in the
// app throws "not a function".
//
// An earlier version of this file set window.jQuery in beforeAll and then dynamically
// imported DataTables. That passed all 8 assertions while every table in the app was
// dead — it tested an ordering the app does not have. Keep the static imports below.
import { readFileSync } from 'node:fs';
import $ from 'jquery';
import DataTable from 'datatables.net-dt';
import 'datatables.net-responsive-dt';

window.jQuery = $;
window.$ = $;

// Mirrors vendor-globals.js: the explicit registration that makes the above work.
// Comment this line out and every assertion below fails — which is the point.
DataTable.use($);

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

  it('vendor-globals.js still registers jQuery with DataTables', () => {
    // The assertions in this file replicate vendor-globals.js's sequence rather than
    // importing it (it also pulls in Flowbite, SweetAlert2 and socket.io, which do not
    // load under happy-dom). So this guards the real file at the source level: if the
    // DataTable.use() call is ever deleted or reordered away, every table in the app
    // breaks silently and the behavioural assertions below would NOT catch it.
    // cwd-relative, not import.meta.url — under vitest that is an http:// URL, which
    // readFileSync rejects with "The URL must be of scheme file".
    const src = readFileSync('app/static/js/vendor-globals.js', 'utf8');
    // Anchored to line start so a commented-out `// DataTable.use(jQuery);` does not
    // satisfy it — the first version of this guard matched the comment and passed.
    expect(src).toMatch(/^[ \t]*DataTable\.use\(\s*jQuery\s*\)\s*;/m);
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
