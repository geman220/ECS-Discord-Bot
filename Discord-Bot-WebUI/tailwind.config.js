import { fileURLToPath } from 'url';
import { dirname, resolve } from 'path';
import flowbitePlugin from 'flowbite/plugin';
import formsPlugin from '@tailwindcss/forms';

// Get directory path for ESM
const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: [
    // Use absolute paths to ensure content is found regardless of where Tailwind runs
    resolve(__dirname, 'app/templates/**/*.html'),
    resolve(__dirname, 'app/static/js/**/*.js'),
    // custom_js was NOT scanned, but those modules build DOM with Tailwind classes
    // (modal-builder.js constructs the whole report-match modal client-side). Any
    // class used ONLY there was silently purged out of the stylesheet — no error,
    // just an unstyled element.
    resolve(__dirname, 'app/static/custom_js/**/*.js'),
    resolve(__dirname, 'node_modules/flowbite/**/*.js'),
  ],
  theme: {
    extend: {
      colors: {
        // ECS Brand Colors
        'ecs-green': {
          // Themed to the ECS Pub League LOGO green (#40b050), slightly deepened
          // for readable white text. Overridable via Appearance (--color-primary-rgb).
          DEFAULT: 'rgb(var(--color-primary-rgb, 46 157 68) / <alpha-value>)',
          dark: 'rgb(var(--color-primary-dark-rgb, 28 122 52) / <alpha-value>)',
          50: '#f0fdf4',
          100: '#dcfce7',
          200: '#bbf7d0',
          300: '#86efac',
          400: '#4ade80',
          500: '#22c55e',
          600: '#16a34a',
          700: '#15803d',
          800: '#1a472a',
          900: '#14532d',
          950: '#052e16',
        },
        'ecs-gold': {
          DEFAULT: 'rgb(var(--color-accent-rgb, 201 162 39) / <alpha-value>)',
          50: '#fefce8',
          100: '#fef9c3',
          200: '#fef08a',
          300: '#fde047',
          400: '#facc15',
          500: '#c9a227',
          600: '#ca8a04',
          700: '#a16207',
          800: '#854d0e',
          900: '#713f12',
        },
        // ECS Pub League LOGO blue (#203090) — the brand accent (green + blue).
        'ecs-blue': {
          DEFAULT: '#203090',
          50: '#eef1fb',
          100: '#d8def5',
          200: '#b3bdec',
          300: '#8593de',
          400: '#5e6fd0',
          500: '#3a49a8',
          600: '#203090',
          700: '#1a2775',
          800: '#161f5e',
          900: '#121847',
        },
        // Dark theme backgrounds (matching Flowbite dark mode)
        'dark': {
          'bg': '#111827',
          'card': '#1f2937',
          'border': '#374151',
          'hover': '#374151',
        },
        // Theme-customizable colors (via Admin Panel > Appearance)
        // These reference CSS variables that can be overridden per-site
        // Default values match ECS Brand + Flowbite/Tailwind palette
        'theme': {
          'primary': 'var(--color-primary, #1a472a)',           // ECS Green
          'primary-light': 'var(--color-primary-light, #15803d)',
          'primary-dark': 'var(--color-primary-dark, #14532d)',
          'secondary': 'var(--color-secondary, #6b7280)',       // Gray-500
          'accent': 'var(--color-accent, #c9a227)',             // ECS Gold
          'success': 'var(--color-success, #16a34a)',           // Green-600
          'warning': 'var(--color-warning, #d97706)',           // Amber-600
          'danger': 'var(--color-danger, #dc2626)',             // Red-600
          'info': 'var(--color-info, #2563eb)',                 // Blue-600
        },
        'theme-text': {
          'heading': 'var(--color-text-heading, #111827)',      // Gray-900
          'body': 'var(--color-text-body, #374151)',            // Gray-700
          'muted': 'var(--color-text-muted, #6b7280)',          // Gray-500
          'link': 'var(--color-text-link, #1a472a)',            // ECS Green
        },
        'theme-bg': {
          'body': 'var(--color-bg-body, #f9fafb)',              // Gray-50
          'card': 'var(--color-bg-card, #ffffff)',
          'input': 'var(--color-bg-input, #ffffff)',
          'sidebar': 'var(--color-bg-sidebar, #111827)',        // Gray-900
        },
        'theme-border': {
          'DEFAULT': 'var(--color-border, #e5e7eb)',            // Gray-200
          'input': 'var(--color-border-input, #d1d5db)',        // Gray-300
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [
    flowbitePlugin,
    formsPlugin,
  ],
};
