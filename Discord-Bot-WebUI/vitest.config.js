import { defineConfig } from 'vitest/config';
import { resolve } from 'path';

export default defineConfig({
  test: {
    // Use happy-dom for faster DOM testing
    environment: 'happy-dom',

    // Test file patterns
    include: [
      'app/static/js/**/*.test.js',
      'app/static/js/**/*.spec.js',
      'app/static/custom_js/**/*.test.js',
      'app/static/custom_js/**/*.spec.js'
    ],

    // Exclude patterns
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/vite-dist/**'
    ],

    // Global test setup
    setupFiles: ['./vitest.setup.js'],

    // See the datatables aliases in `resolve` below.
    server: {
      deps: {
        inline: [/datatables\.net/],
      },
    },

    // Enable globals (describe, it, expect, etc.)
    globals: true,

    // Coverage configuration
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      include: [
        'app/static/js/**/*.js',
        'app/static/custom_js/**/*.js'
      ],
      exclude: [
        '**/node_modules/**',
        '**/*.test.js',
        '**/*.spec.js',
        '**/vendor/**',
        '**/dist/**'
      ]
    },

    // Reporter
    reporters: ['verbose'],

    // Timeout
    testTimeout: 10000
  },

  resolve: {
    // Array form (not object) so the datatables entries can be anchored regexes —
    // a plain string alias for 'datatables.net' would also prefix-match
    // 'datatables.net-dt' and silently resolve the wrong package.
    alias: [
      { find: '@js', replacement: resolve(__dirname, 'app/static/js') },
      { find: '@custom', replacement: resolve(__dirname, 'app/static/custom_js') },
      { find: '@utils', replacement: resolve(__dirname, 'app/static/js/utils') },
      { find: '@services', replacement: resolve(__dirname, 'app/static/js/services') },

      // DataTables ships a CJS build (`main`) and an ESM build (`module`). Vite's
      // production build resolves `module`, so the browser bundle is ESM — verified:
      // the emitted vendor-datatables chunk contains no `cjsRequires` and no UMD
      // branch. Vitest resolves `main` instead, and the CJS wrapper's
      // `require('datatables.net')(window)` path throws on import under DataTables 3.
      // That is a harness artifact, not a shipped bug, but it made the vendor test
      // unable to run. Pin these to the exact ESM entry the bundle uses so the test
      // exercises the code that actually ships.
      { find: /^datatables\.net$/, replacement: resolve(__dirname, 'node_modules/datatables.net/js/dataTables.mjs') },
      { find: /^datatables\.net-dt$/, replacement: resolve(__dirname, 'node_modules/datatables.net-dt/js/dataTables.dataTables.mjs') },
      { find: /^datatables\.net-responsive$/, replacement: resolve(__dirname, 'node_modules/datatables.net-responsive/js/dataTables.responsive.mjs') },
      { find: /^datatables\.net-responsive-dt$/, replacement: resolve(__dirname, 'node_modules/datatables.net-responsive-dt/js/responsive.dataTables.mjs') },
    ]
  }
});
