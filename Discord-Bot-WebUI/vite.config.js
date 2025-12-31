import { defineConfig } from 'vite';
import { resolve } from 'path';
import inject from '@rollup/plugin-inject';

export default defineConfig({
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
        // CSS entry
        styles: resolve(__dirname, 'app/static/css/main-entry.css'),
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
      },
    },

    // Minification
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: false, // Keep console.log for debugging
        drop_debugger: true,
      },
    },

    // Disable source maps in production to reduce memory usage during build
    sourcemap: false,
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
