#!/usr/bin/env node
/**
 * CSS Color Migration Script
 * Converts hardcoded hex colors to CSS variable tokens
 */

const fs = require('fs');
const path = require('path');

// Color mappings: hex → CSS variable
const COLOR_MAP = {
  // Secondary/Slate Scale (most common)
  '#1e293b': 'var(--color-secondary-900)',
  '#334155': 'var(--color-secondary-800)',
  '#475569': 'var(--color-secondary-700)',
  '#64748b': 'var(--color-secondary-600)',
  '#94a3b8': 'var(--color-secondary-400)',
  '#cbd5e1': 'var(--color-secondary-300)',
  '#e2e8f0': 'var(--color-secondary-200)',
  '#f1f5f9': 'var(--color-secondary-100)',
  '#f8fafc': 'var(--color-secondary-50)',
  '#0f172a': 'var(--color-secondary-950)',

  // Primary Blue Scale
  '#2563eb': 'var(--color-primary-600)',
  '#3b82f6': 'var(--color-primary-500)',
  '#60a5fa': 'var(--color-primary-400)',
  '#1d4ed8': 'var(--color-primary-700)',
  '#1e40af': 'var(--color-primary-800)',
  '#1e3a8a': 'var(--color-primary-900)',
  '#dbeafe': 'var(--color-primary-100)',
  '#eff6ff': 'var(--color-primary-50)',
  '#bfdbfe': 'var(--color-primary-200)',
  '#93c5fd': 'var(--color-primary-300)',

  // Success Green Scale
  '#10b981': 'var(--color-success-500)',
  '#059669': 'var(--color-success-700)',
  '#34d399': 'var(--color-success-400)',
  '#6ee7b7': 'var(--color-success-300)',
  '#d1fae5': 'var(--color-success-100)',
  '#ecfdf5': 'var(--color-success-50)',
  '#047857': 'var(--color-success-800)',
  '#28a745': 'var(--color-success-500)', // Bootstrap success
  '#198754': 'var(--color-success-600)', // Bootstrap 5 success

  // Danger Red Scale
  '#ef4444': 'var(--color-danger-600)',
  '#dc2626': 'var(--color-danger-700)',
  '#f87171': 'var(--color-danger-400)',
  '#fca5a5': 'var(--color-danger-300)',
  '#fee2e2': 'var(--color-danger-100)',
  '#fef2f2': 'var(--color-danger-50)',
  '#b91c1c': 'var(--color-danger-800)',
  '#dc3545': 'var(--color-danger-600)', // Bootstrap danger

  // Warning/Accent Amber Scale
  '#f59e0b': 'var(--color-accent-600)',
  '#fbbf24': 'var(--color-accent-400)',
  '#fcd34d': 'var(--color-accent-300)',
  '#fde68a': 'var(--color-accent-200)',
  '#fef3c7': 'var(--color-accent-100)',
  '#d97706': 'var(--color-accent-700)',
  '#ffc107': 'var(--color-warning)', // Bootstrap warning
  '#f97316': 'var(--color-warning-500)', // Orange warning

  // Info Blue Scale
  '#0ea5e9': 'var(--color-info-500)',
  '#38bdf8': 'var(--color-info-400)',
  '#06b6d4': 'var(--color-info-600)',
  '#0891b2': 'var(--color-info-700)',
  '#17a2b8': 'var(--color-info-600)', // Bootstrap info

  // Neutral/Gray Scale
  '#ffffff': 'var(--color-white)',
  '#fff': 'var(--color-white)',
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
  '#09090b': 'var(--color-neutral-950)',

  // Bootstrap grays
  '#f8f9fa': 'var(--color-neutral-50)',
  '#e9ecef': 'var(--color-neutral-200)',
  '#dee2e6': 'var(--color-neutral-300)',
  '#ced4da': 'var(--color-neutral-300)',
  '#adb5bd': 'var(--color-neutral-400)',
  '#6c757d': 'var(--color-secondary-600)',
  '#495057': 'var(--color-secondary-700)',
  '#343a40': 'var(--color-secondary-800)',
  '#212529': 'var(--color-secondary-900)',

  // Bootstrap primary
  '#0d6efd': 'var(--color-primary)',
  '#0b5ed7': 'var(--color-primary-700)',
  '#0a58ca': 'var(--color-primary-700)',

  // Special colors
  '#697a8d': 'var(--color-secondary-600)',
  '#696cff': 'var(--color-primary)', // Purple-ish, closest to primary
  '#5865f2': 'var(--color-discord)', // Discord brand
  '#7289da': 'var(--color-discord-600)', // Discord alt

  // Common aliases
  '#000': 'var(--color-neutral-950)',
  '#000000': 'var(--color-neutral-950)',

  // Round 2 - Additional common colors
  '#ea5455': 'var(--color-danger-500)', // Sneat theme red
  '#2b2c40': 'var(--color-secondary-900)', // Sneat dark bg
  '#ff9f43': 'var(--color-accent-500)', // Sneat warning/orange
  '#28c76f': 'var(--color-success-500)', // Sneat success
  '#007bff': 'var(--color-primary)', // Old Bootstrap primary
  '#4ade80': 'var(--color-success-400)', // Tailwind green-400
  '#22c55e': 'var(--color-success-500)', // Tailwind green-500
  '#4752c4': 'var(--color-discord-hover)', // Discord hover
  '#8b5cf6': 'var(--color-primary-500)', // Purple (map to primary)
  '#566a7f': 'var(--color-secondary-600)', // Sneat text
  '#a3a4cc': 'var(--color-secondary-400)', // Light purple text

  // Short hex codes
  '#ddd': 'var(--color-neutral-300)',
  '#ccc': 'var(--color-neutral-400)',
  '#999': 'var(--color-neutral-500)',
  '#888': 'var(--color-neutral-500)',
  '#777': 'var(--color-neutral-600)',
  '#666': 'var(--color-neutral-600)',
  '#555': 'var(--color-neutral-700)',
  '#444': 'var(--color-neutral-700)',
  '#333': 'var(--color-neutral-800)',
  '#222': 'var(--color-neutral-900)',
  '#111': 'var(--color-neutral-950)',
  '#eee': 'var(--color-neutral-200)',
  '#f0f0f0': 'var(--color-neutral-100)',
  '#e0e0e0': 'var(--color-neutral-200)',
  '#d0d0d0': 'var(--color-neutral-300)',

  // More theme colors
  '#2a2a2a': 'var(--color-neutral-900)',
  '#404040': 'var(--color-neutral-700)',
  '#505050': 'var(--color-neutral-600)',
  '#606060': 'var(--color-neutral-600)',
  '#808080': 'var(--color-neutral-500)',
  '#a0a0a0': 'var(--color-neutral-400)',
  '#b0b0b0': 'var(--color-neutral-400)',
  '#c0c0c0': 'var(--color-neutral-400)',
};

// Files/directories to skip
const SKIP_PATTERNS = [
  'vite-dist',
  '/gen/',
  'node_modules',
  'tokens/colors.css', // Don't modify the source!
  'bootstrap-minimal.css', // Vendor file
];

function shouldSkip(filePath) {
  return SKIP_PATTERNS.some(pattern => filePath.includes(pattern));
}

function migrateColors(content, filePath) {
  let modified = content;
  let changeCount = 0;
  const changes = [];

  for (const [hex, cssVar] of Object.entries(COLOR_MAP)) {
    // Case-insensitive regex for hex colors
    const regex = new RegExp(hex.replace('#', '#'), 'gi');
    const matches = modified.match(regex);

    if (matches) {
      // Don't replace if already inside a var() or in a comment defining the color
      const safeContent = modified.replace(/\/\*[\s\S]*?\*\//g, match => match.replace(/#/g, '§'));
      const safeMatches = safeContent.match(regex);

      if (safeMatches) {
        const beforeCount = (modified.match(regex) || []).length;
        modified = modified.replace(regex, cssVar);
        const afterCount = beforeCount;
        changeCount += afterCount;
        changes.push(`${hex} → ${cssVar} (${afterCount}x)`);
      }
    }
  }

  return { content: modified, changeCount, changes };
}

function processFile(filePath, dryRun = false) {
  if (shouldSkip(filePath)) {
    return { skipped: true };
  }

  const content = fs.readFileSync(filePath, 'utf8');
  const result = migrateColors(content, filePath);

  if (result.changeCount > 0) {
    if (!dryRun) {
      fs.writeFileSync(filePath, result.content, 'utf8');
    }
    return {
      file: filePath,
      changes: result.changeCount,
      details: result.changes,
    };
  }

  return { noChanges: true };
}

function processDirectory(dirPath, dryRun = false) {
  const results = [];

  function walkDir(dir) {
    const files = fs.readdirSync(dir);

    for (const file of files) {
      const filePath = path.join(dir, file);
      const stat = fs.statSync(filePath);

      if (stat.isDirectory()) {
        if (!shouldSkip(filePath)) {
          walkDir(filePath);
        }
      } else if (file.endsWith('.css')) {
        const result = processFile(filePath, dryRun);
        if (result.changes) {
          results.push(result);
        }
      }
    }
  }

  walkDir(dirPath);
  return results;
}

// Main execution
const args = process.argv.slice(2);
const dryRun = args.includes('--dry-run');
const targetDir = args.find(a => !a.startsWith('--')) ||
  path.join(__dirname, '..', 'app', 'static', 'css');

console.log('='.repeat(80));
console.log('CSS COLOR MIGRATION TO TOKENS');
console.log('='.repeat(80));
console.log(`Target: ${targetDir}`);
console.log(`Mode: ${dryRun ? 'DRY RUN (no changes)' : 'LIVE (making changes)'}`);
console.log('='.repeat(80));
console.log('');

const results = processDirectory(targetDir, dryRun);

if (results.length === 0) {
  console.log('No files needed migration.');
} else {
  let totalChanges = 0;

  for (const result of results) {
    console.log(`\n📁 ${path.relative(targetDir, result.file)}`);
    console.log(`   ${result.changes} color replacements:`);
    for (const detail of result.details.slice(0, 10)) {
      console.log(`     • ${detail}`);
    }
    if (result.details.length > 10) {
      console.log(`     ... and ${result.details.length - 10} more`);
    }
    totalChanges += result.changes;
  }

  console.log('\n' + '='.repeat(80));
  console.log(`SUMMARY: ${totalChanges} replacements in ${results.length} files`);
  console.log('='.repeat(80));
}
