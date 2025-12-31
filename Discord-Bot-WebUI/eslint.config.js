/**
 * ESLint Configuration - Flat Config Format (ESLint 9+)
 *
 * This config prevents TDZ (Temporal Dead Zone) errors by catching
 * bare global references that should use window.X pattern.
 */

export default [
  {
    // Apply to all JS files in static directory
    files: ['app/static/js/**/*.js', 'app/static/custom_js/**/*.js'],

    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'module',
      globals: {
        // Browser globals
        window: 'readonly',
        document: 'readonly',
        console: 'readonly',
        fetch: 'readonly',
        setTimeout: 'readonly',
        setInterval: 'readonly',
        clearTimeout: 'readonly',
        clearInterval: 'readonly',
        requestAnimationFrame: 'readonly',
        cancelAnimationFrame: 'readonly',
        localStorage: 'readonly',
        sessionStorage: 'readonly',
        navigator: 'readonly',
        location: 'readonly',
        history: 'readonly',
        performance: 'readonly',
        MutationObserver: 'readonly',
        ResizeObserver: 'readonly',
        IntersectionObserver: 'readonly',
        CustomEvent: 'readonly',
        Event: 'readonly',
        FormData: 'readonly',
        URL: 'readonly',
        URLSearchParams: 'readonly',
        AbortController: 'readonly',
        Headers: 'readonly',
        Request: 'readonly',
        Response: 'readonly',
        Blob: 'readonly',
        File: 'readonly',
        FileReader: 'readonly',
        Image: 'readonly',
        Audio: 'readonly',
        HTMLElement: 'readonly',
        Element: 'readonly',
        Node: 'readonly',
        NodeList: 'readonly',
        DOMParser: 'readonly',
        getComputedStyle: 'readonly',
        matchMedia: 'readonly',
        alert: 'readonly',
        confirm: 'readonly',
        prompt: 'readonly',
      },
    },

    rules: {
      /**
       * CRITICAL: Prevent bare global access that causes TDZ errors
       *
       * These globals are set up in vendor-globals.js and assigned to window.
       * In bundled code, accessing them without window. prefix can cause:
       * "ReferenceError: can't access lexical declaration before initialization"
       *
       * CORRECT:   window.Swal.fire({...})
       * INCORRECT: Swal.fire({...})
       */
      'no-restricted-globals': ['error',
        // Vendor libraries - MUST use window.X
        {
          name: 'Swal',
          message: 'Use window.Swal instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'bootstrap',
          message: 'Use window.bootstrap instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'flatpickr',
          message: 'Use window.flatpickr instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Cropper',
          message: 'Use window.Cropper instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'feather',
          message: 'Use window.feather instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Hammer',
          message: 'Use window.Hammer instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'PerfectScrollbar',
          message: 'Use window.PerfectScrollbar instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Sortable',
          message: 'Use window.Sortable instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Shepherd',
          message: 'Use window.Shepherd instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Waves',
          message: 'Use window.Waves instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'io',
          message: 'Use window.io instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'DataTable',
          message: 'Use window.$.fn.DataTable instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Toastify',
          message: 'Use window.Toastify instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Chart',
          message: 'Use window.Chart instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Menu',
          message: 'Use window.Menu instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'Helpers',
          message: 'Use window.Helpers instead to avoid TDZ errors in bundled code.'
        },
        // Internal modules - MUST use window.X
        {
          name: 'EventDelegation',
          message: 'Use window.EventDelegation instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'InitSystem',
          message: 'Use window.InitSystem instead to avoid TDZ errors in bundled code.'
        },
        {
          name: 'ModalManager',
          message: 'Use window.ModalManager instead to avoid TDZ errors in bundled code.'
        },
      ],

      // Warn about console.log (but don't error - useful for debugging)
      'no-console': ['warn', { allow: ['warn', 'error', 'info'] }],
    },
  },

  // Ignore vendor files and build output
  {
    ignores: [
      'app/static/vendor/**',
      'app/static/vite-dist/**',
      'app/static/dist/**',
      'app/static/gen/**',
      'app/static/node_modules/**',
      'app/static/assets/**',
    ],
  },
];
