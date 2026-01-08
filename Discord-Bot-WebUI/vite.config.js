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
        // CSS entry - Using CSS Cascade Layers architecture
        styles: resolve(__dirname, 'app/static/css/main-entry.css'),
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
