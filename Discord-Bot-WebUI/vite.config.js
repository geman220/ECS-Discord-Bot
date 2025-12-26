import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
  // Root directory for source files
  root: resolve(__dirname, 'app/static'),

  // Base public path - Flask will serve from /static/
  base: '/static/',

  build: {
    // Output directory (relative to root)
    outDir: resolve(__dirname, 'app/static/dist'),

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

    // Generate source maps for debugging
    sourcemap: true,
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
