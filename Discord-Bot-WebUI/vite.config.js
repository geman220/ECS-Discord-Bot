import { defineConfig } from 'vite';
import { resolve } from 'path';
import inject from '@rollup/plugin-inject';

// BUILD_MODE controls dev vs prod behavior
// Set BUILD_MODE=dev in .env for debugging (source maps, no minification)
// Set BUILD_MODE=prod in .env for production (no source maps, minified)
const isDev = process.env.BUILD_MODE === 'dev';

export default defineConfig({
  // esbuild options
  esbuild: {
    // In prod, drop console and debugger statements; in dev, keep them for debugging
    drop: isDev ? [] : ['console', 'debugger'],
    // Keep function names in dev for better stack traces
    keepNames: isDev,
  },

  // Root directory for source files
  root: resolve(__dirname, 'app/static'),

  // Base public path - Flask will serve from /static/
  base: '/static/',

  // Plugins
  plugins: [
    // Inject makes jQuery available in all modules without explicit imports
    // This is the industry standard approach (equivalent to Webpack's ProvidePlugin)
    inject({
      $: 'jquery',
      jQuery: 'jquery',
      // Only process JS files, not CSS
      include: ['**/*.js'],
      exclude: ['**/*.css'],
    }),
  ],

  // Pre-bundle jQuery for faster dev server startup
  optimizeDeps: {
    include: ['jquery'],
  },

  build: {
    // Output directory (relative to root) - using 'vite-dist' to avoid conflicts with old dist/
    outDir: resolve(__dirname, 'app/static/vite-dist'),

    // Don't empty outDir on build (we'll handle cleanup)
    emptyOutDir: true,

    // Generate manifest for Flask integration
    manifest: true,

    // Rollup options for bundling
    rollupOptions: {
      input: {
        // Main application bundle
        main: resolve(__dirname, 'app/static/js/main-entry.js'),
        // NOTE: css/main-entry.css (the Bootstrap-era cascade-layers bundle) was
        // built here as a `styles` entry for years but NOTHING ever linked its
        // output — 1.9 MB of dead weight in every build. Removed 2026-07.
        // Note: Tailwind CSS is compiled separately via npm run build:tailwind
      },
      output: {
        // Asset naming
        entryFileNames: 'js/[name]-[hash].js',
        chunkFileNames: 'js/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          if (assetInfo.name.endsWith('.css')) {
            return 'css/[name]-[hash][extname]';
          }
          return 'assets/[name]-[hash][extname]';
        },

        // Split the big third-party libraries out of the main app bundle.
        //
        // WHY: the app bundle was one 1.8 MB file. Every deploy changes its hash, so
        // every returning user re-downloaded all 1.8 MB just because one app file
        // changed. Vendor libs change only when package.json does — giving each its
        // own immutable-cached chunk means a normal deploy re-downloads just the small
        // app chunk, and the vendor chunks stay cached for months.
        //
        // SAFETY: this does NOT change init order. ES modules evaluate strictly in
        // import-graph order and Rollup never violates it, so vendor-globals.js still
        // runs (and sets window.jQuery/$ etc.) before any app module that uses them,
        // exactly as before. Chunk boundaries only affect file grouping, not sequence.
        // vite_asset() emits modulepreload for the full transitive chunk set so there
        // is no load waterfall.
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined; // app code stays in main
          // One chunk per heavy library (each cached independently across deploys).
          if (id.includes('datatables')) return 'vendor-datatables';
          if (id.includes('sweetalert2')) return 'vendor-swal';
          if (id.includes('cropperjs')) return 'vendor-cropper';
          if (id.includes('flowbite')) return 'vendor-flowbite';
          if (id.includes('flatpickr')) return 'vendor-flatpickr';
          if (id.includes('socket.io') || id.includes('engine.io')) return 'vendor-socketio';
          if (id.includes('/jquery/') || id.includes('jquery/dist')) return 'vendor-jquery';
          // Everything smaller (hammerjs, sortablejs, …) shares one chunk.
          return 'vendor-misc';
        },
      },
    },

    // Minification: disabled in dev for readable code, enabled in prod
    minify: isDev ? false : 'esbuild',

    // Source maps: enabled in dev for debugging original files in DevTools
    // In dev, browser shows original file:line even though code is bundled
    sourcemap: isDev,
  },

  // Development server config
  server: {
    // Origin for HMR
    origin: 'http://localhost:5173',

    // CORS for Flask dev server
    cors: true,

    // Watch options
    watch: {
      usePolling: true, // For Docker/WSL compatibility
    },
  },

  // Resolve aliases
  resolve: {
    alias: {
      '@': resolve(__dirname, 'app/static'),
      '@js': resolve(__dirname, 'app/static/js'),
      '@css': resolve(__dirname, 'app/static/css'),
    },
  },
});
