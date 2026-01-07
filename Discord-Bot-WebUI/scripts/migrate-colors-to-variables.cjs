#!/usr/bin/env node
/**
 * Color Migration Script
 * Replaces hardcoded hex colors with CSS variables
 */

const fs = require('fs');
const path = require('path');

const CSS_DIR = path.join(__dirname, '../app/static/css');

// Mapping of hex colors to CSS variables
const colorMap = {
  // Primary colors
  '#2563EB': 'var(--color-primary-600)',
  '#2563eb': 'var(--color-primary-600)',
  '#1D4ED8': 'var(--color-primary-700)',
  '#1d4ed8': 'var(--color-primary-700)',
  '#3B82F6': 'var(--color-primary-500)',
  '#3b82f6': 'var(--color-info-600)',
  '#60A5FA': 'var(--color-primary-400)',
  '#60a5fa': 'var(--color-primary-400)',
  '#93C5FD': 'var(--color-primary-300)',
  '#93c5fd': 'var(--color-primary-300)',
  '#BFDBFE': 'var(--color-primary-200)',
  '#bfdbfe': 'var(--color-primary-200)',
  '#DBEAFE': 'var(--color-primary-100)',
  '#dbeafe': 'var(--color-primary-100)',
  '#EFF6FF': 'var(--color-primary-50)',
  '#eff6ff': 'var(--color-primary-50)',

  // Secondary/Slate colors
  '#0F172A': 'var(--color-secondary-950)',
  '#0f172a': 'var(--color-secondary-950)',
  '#1E293B': 'var(--color-secondary-900)',
  '#1e293b': 'var(--color-secondary-900)',
  '#334155': 'var(--color-secondary-800)',
  '#475569': 'var(--color-secondary-700)',
  '#64748B': 'var(--color-secondary-600)',
  '#64748b': 'var(--color-secondary-600)',
  '#94A3B8': 'var(--color-secondary-400)',
  '#94a3b8': 'var(--color-secondary-400)',
  '#CBD5E1': 'var(--color-secondary-300)',
  '#cbd5e1': 'var(--color-secondary-300)',
  '#E2E8F0': 'var(--color-secondary-200)',
  '#e2e8f0': 'var(--color-secondary-200)',
  '#F1F5F9': 'var(--color-secondary-100)',
  '#f1f5f9': 'var(--color-secondary-100)',
  '#F8FAFC': 'var(--color-secondary-50)',
  '#f8fafc': 'var(--color-secondary-50)',

  // Neutral/Zinc colors
  '#FFFFFF': 'var(--color-white)',
  '#ffffff': 'var(--color-white)',
  '#fff': 'var(--color-white)',
  '#FFF': 'var(--color-white)',
  '#FAFAFA': 'var(--color-neutral-50)',
  '#fafafa': 'var(--color-neutral-50)',
  '#F4F4F5': 'var(--color-neutral-100)',
  '#f4f4f5': 'var(--color-neutral-100)',
  '#E4E4E7': 'var(--color-neutral-200)',
  '#e4e4e7': 'var(--color-neutral-200)',
  '#D4D4D8': 'var(--color-neutral-300)',
  '#d4d4d8': 'var(--color-neutral-300)',
  '#A1A1AA': 'var(--color-neutral-400)',
  '#a1a1aa': 'var(--color-neutral-400)',
  '#71717A': 'var(--color-neutral-500)',
  '#71717a': 'var(--color-neutral-500)',
  '#52525B': 'var(--color-neutral-600)',
  '#52525b': 'var(--color-neutral-600)',
  '#3F3F46': 'var(--color-neutral-700)',
  '#3f3f46': 'var(--color-neutral-700)',
  '#27272A': 'var(--color-neutral-800)',
  '#27272a': 'var(--color-neutral-800)',
  '#18181B': 'var(--color-neutral-900)',
  '#18181b': 'var(--color-neutral-900)',
  '#09090B': 'var(--color-neutral-950)',
  '#09090b': 'var(--color-neutral-950)',
  '#000': 'var(--color-neutral-950)',
  '#000000': 'var(--color-neutral-950)',

  // Success colors
  '#10B981': 'var(--color-success-500)',
  '#10b981': 'var(--color-success-500)',
  '#34D399': 'var(--color-success-400)',
  '#34d399': 'var(--color-success-400)',
  '#6EE7B7': 'var(--color-success-300)',
  '#6ee7b7': 'var(--color-success-300)',
  '#059669': 'var(--color-success-700)',
  '#047857': 'var(--color-success-800)',
  '#D1FAE5': 'var(--color-success-100)',
  '#d1fae5': 'var(--color-success-100)',
  '#ECFDF5': 'var(--color-success-50)',
  '#ecfdf5': 'var(--color-success-50)',

  // Danger colors
  '#EF4444': 'var(--color-danger-600)',
  '#ef4444': 'var(--color-danger-600)',
  '#F87171': 'var(--color-danger-400)',
  '#f87171': 'var(--color-danger-400)',
  '#DC2626': 'var(--color-danger-700)',
  '#dc2626': 'var(--color-danger-700)',
  '#B91C1C': 'var(--color-danger-800)',
  '#b91c1c': 'var(--color-danger-800)',
  '#FCA5A5': 'var(--color-danger-300)',
  '#fca5a5': 'var(--color-danger-300)',
  '#FECACA': 'var(--color-danger-200)',
  '#fecaca': 'var(--color-danger-200)',
  '#FEE2E2': 'var(--color-danger-100)',
  '#fee2e2': 'var(--color-danger-100)',
  '#FEF2F2': 'var(--color-danger-50)',
  '#fef2f2': 'var(--color-danger-50)',

  // Warning colors
  '#F59E0B': 'var(--color-warning-600)',
  '#f59e0b': 'var(--color-warning-600)',
  '#FBBF24': 'var(--color-warning-400)',
  '#fbbf24': 'var(--color-warning-400)',
  '#F97316': 'var(--color-warning-500)',
  '#f97316': 'var(--color-warning-500)',
  '#FB923C': 'var(--color-warning-400)',
  '#fb923c': 'var(--color-warning-400)',
  '#FCD34D': 'var(--color-warning-300)',
  '#fcd34d': 'var(--color-warning-300)',
  '#FDE68A': 'var(--color-warning-200)',
  '#fde68a': 'var(--color-warning-200)',
  '#FEF3C7': 'var(--color-warning-100)',
  '#fef3c7': 'var(--color-warning-100)',
  '#D97706': 'var(--color-warning-700)',
  '#d97706': 'var(--color-warning-700)',

  // Info colors (cyan/blue)
  '#06B6D4': 'var(--color-info-500)',
  '#06b6d4': 'var(--color-info-500)',
  '#22D3EE': 'var(--color-info-400)',
  '#22d3ee': 'var(--color-info-400)',

  // Bootstrap legacy
  '#0d6efd': 'var(--color-primary-600)',
  '#0D6EFD': 'var(--color-primary-600)',
  '#198754': 'var(--color-success-700)',
  '#dc3545': 'var(--color-danger-600)',
  '#ffc107': 'var(--color-warning-400)',
  '#0dcaf0': 'var(--color-info-400)',
  '#6c757d': 'var(--color-secondary-600)',

  // Discord
  '#5865F2': 'var(--color-discord)',
  '#5865f2': 'var(--color-discord)',
  '#7289DA': 'var(--color-discord-600)',
  '#7289da': 'var(--color-discord-600)',

  // Old gray values
  '#f8f9fa': 'var(--color-secondary-50)',
  '#dee2e6': 'var(--color-secondary-200)',
  '#ced4da': 'var(--color-secondary-300)',
  '#adb5bd': 'var(--color-secondary-400)',
  '#6c757d': 'var(--color-secondary-600)',
  '#495057': 'var(--color-secondary-700)',
  '#343a40': 'var(--color-secondary-800)',
  '#212529': 'var(--color-secondary-900)',
};

// Files to exclude from processing
const excludeFiles = [
  'tokens/colors.css',
  'bootstrap-minimal.css',
];

// Track changes
let totalReplacements = 0;
const changedFiles = [];

function processFile(filePath) {
  const relativePath = path.relative(CSS_DIR, filePath);

  // Skip excluded files
  if (excludeFiles.some(ex => relativePath.includes(ex))) {
    return;
  }

  let content = fs.readFileSync(filePath, 'utf8');
  let modified = false;
  let fileReplacements = 0;

  // Process each color mapping
  for (const [hex, variable] of Object.entries(colorMap)) {
    // Create regex that matches the hex color not already in a var()
    // and not in url(), data:, or comments
    const regex = new RegExp(
      `(?<!var\\([^)]*)(${hex.replace('#', '\\#')})(?![0-9a-fA-F])`,
      'gi'
    );

    const matches = content.match(regex);
    if (matches) {
      // Don't replace if already wrapped in var() or inside url()/data:
      const lines = content.split('\n');
      const newLines = lines.map(line => {
        // Skip lines with var(), url(), data:, or comments
        if (line.includes('var(--') ||
            line.includes('url(') ||
            line.includes('data:') ||
            line.trim().startsWith('/*') ||
            line.trim().startsWith('*')) {
          return line;
        }

        // Replace hex with variable
        const newLine = line.replace(new RegExp(hex.replace('#', '\\#'), 'gi'), variable);
        if (newLine !== line) {
          fileReplacements++;
          modified = true;
        }
        return newLine;
      });
      content = newLines.join('\n');
    }
  }

  if (modified) {
    fs.writeFileSync(filePath, content);
    changedFiles.push({ file: relativePath, replacements: fileReplacements });
    totalReplacements += fileReplacements;
  }
}

function walkDir(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);

    if (stat.isDirectory()) {
      walkDir(fullPath);
    } else if (file.endsWith('.css')) {
      processFile(fullPath);
    }
  }
}

console.log('================================================================================');
console.log('COLOR MIGRATION - Replacing hardcoded hex values with CSS variables');
console.log('================================================================================\n');

walkDir(CSS_DIR);

console.log(`\nFiles modified: ${changedFiles.length}`);
console.log(`Total replacements: ${totalReplacements}\n`);

if (changedFiles.length > 0) {
  console.log('Changed files:');
  changedFiles.sort((a, b) => b.replacements - a.replacements);
  changedFiles.forEach(({ file, replacements }) => {
    console.log(`  ${file}: ${replacements} replacements`);
  });
}

console.log('\n================================================================================');
console.log('Migration complete. Run build to verify.');
console.log('================================================================================');
