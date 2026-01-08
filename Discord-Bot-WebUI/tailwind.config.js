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
    resolve(__dirname, 'node_modules/flowbite/**/*.js'),
  ],
  theme: {
    extend: {
      colors: {
        // ECS Brand Colors
        'ecs-green': {
          DEFAULT: '#1a472a',
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
        },
        'ecs-gold': {
          DEFAULT: '#c9a227',
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
        // Dark theme backgrounds (matching Flowbite dark mode)
        'dark': {
          'bg': '#111827',
          'card': '#1f2937',
          'border': '#374151',
          'hover': '#374151',
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
