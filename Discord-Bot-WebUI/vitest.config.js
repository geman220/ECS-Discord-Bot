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
    alias: {
      '@js': resolve(__dirname, 'app/static/js'),
      '@custom': resolve(__dirname, 'app/static/custom_js'),
      '@utils': resolve(__dirname, 'app/static/js/utils'),
      '@services': resolve(__dirname, 'app/static/js/services')
    }
  }
});
