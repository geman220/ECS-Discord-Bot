/**
 * Migrate hardcoded hex colors to CSS variables
 */
const fs = require('fs');
const path = require('path');
const glob = require('glob');

// Color mappings: hex -> CSS variable
const colorMap = {
  // Primary scale
  '#eff6ff': 'var(--color-primary-50)',
  '#dbeafe': 'var(--color-primary-100)',
  '#bfdbfe': 'var(--color-primary-200)',
  '#93c5fd': 'var(--color-primary-300)',
  '#60a5fa': 'var(--color-primary-400)',
  '#3b82f6': 'var(--color-primary-500)',
  '#2563eb': 'var(--color-primary-600)',
  '#1d4ed8': 'var(--color-primary-700)',
  '#1e40af': 'var(--color-primary-800)',
  '#1e3a8a': 'var(--color-primary-900)',

  // Secondary/Slate scale
  '#f8fafc': 'var(--color-secondary-50)',
  '#f1f5f9': 'var(--color-secondary-100)',
  '#e2e8f0': 'var(--color-secondary-200)',
  '#cbd5e1': 'var(--color-secondary-300)',
  '#94a3b8': 'var(--color-secondary-400)',
  '#64748b': 'var(--color-secondary-600)',
  '#475569': 'var(--color-secondary-700)',
  '#334155': 'var(--color-secondary-800)',
  '#1e293b': 'var(--color-secondary-900)',
  '#0f172a': 'var(--color-secondary-950)',

  // Success/Green scale
  '#ecfdf5': 'var(--color-success-50)',
  '#d1fae5': 'var(--color-success-100)',
  '#a7f3d0': 'var(--color-success-200)',
  '#6ee7b7': 'var(--color-success-300)',
  '#34d399': 'var(--color-success-400)',
  '#10b981': 'var(--color-success-500)',
  '#059669': 'var(--color-success-700)',
  '#047857': 'var(--color-success-800)',
  '#22c55e': 'var(--color-success-500)',

  // Danger/Red scale
  '#fef2f2': 'var(--color-danger-50)',
  '#fee2e2': 'var(--color-danger-100)',
  '#fecaca': 'var(--color-danger-200)',
  '#fca5a5': 'var(--color-danger-300)',
  '#f87171': 'var(--color-danger-400)',
  '#ef4444': 'var(--color-danger-500)',
  '#dc2626': 'var(--color-danger-600)',
  '#b91c1c': 'var(--color-danger-700)',

  // Warning/Amber scale
  '#fffbeb': 'var(--color-warning-50)',
  '#fef3c7': 'var(--color-warning-100)',
  '#fde68a': 'var(--color-warning-200)',
  '#fcd34d': 'var(--color-warning-300)',
  '#fbbf24': 'var(--color-warning-400)',
  '#f59e0b': 'var(--color-warning-500)',
  '#d97706': 'var(--color-warning-600)',
  '#b45309': 'var(--color-warning-700)',

  // Info/Cyan scale
  '#ecfeff': 'var(--color-info-50)',
  '#cffafe': 'var(--color-info-100)',
  '#a5f3fc': 'var(--color-info-200)',
  '#67e8f9': 'var(--color-info-300)',
  '#22d3ee': 'var(--color-info-400)',
  '#06b6d4': 'var(--color-info-500)',
  '#0891b2': 'var(--color-info-600)',
  '#0ea5e9': 'var(--color-info)',
  '#0284c7': 'var(--color-info-600)',

  // Neutral/Zinc scale (for dark mode)
  '#fafafa': 'var(--color-neutral-50)',
  '#f4f4f5': 'var(--color-neutral-100)',
  '#e4e4e7': 'var(--color-neutral-200)',
  '#d4d4d8': 'var(--color-neutral-300)',
  '#a1a1aa': 'var(--color-neutral-400)',
  '#71717a': 'var(--color-neutral-500)',
  '#52525b': 'var(--color-neutral-600)',
  '#3f3f46': 'var(--color-neutral-700)',
  '#27272a': 'var(--color-neutral-800)',
  '#18181b': 'var(--color-neutral-900)',

  // Common colors
  '#fff': 'var(--color-white)',
  '#ffffff': 'var(--color-white)',
  '#000': 'var(--color-black)',
  '#000000': 'var(--color-black)',
};

// Files to process
const cssFiles = glob.sync('app/static/css/components/*.css');

let totalReplacements = 0;
let filesModified = 0;

cssFiles.forEach(file => {
  let content = fs.readFileSync(file, 'utf8');
  let originalContent = content;
  let fileReplacements = 0;

  // Replace each color
  Object.entries(colorMap).forEach(([hex, variable]) => {
    // Case-insensitive replacement
    const regex = new RegExp(hex.replace('#', '\\#'), 'gi');
    const matches = content.match(regex);
    if (matches) {
      fileReplacements += matches.length;
      content = content.replace(regex, variable);
    }
  });

  if (content !== originalContent) {
    fs.writeFileSync(file, content);
    console.log(`${path.basename(file)}: ${fileReplacements} replacements`);
    totalReplacements += fileReplacements;
    filesModified++;
  }
});

console.log(`\nTotal: ${totalReplacements} replacements in ${filesModified} files`);
