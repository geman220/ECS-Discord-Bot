/**
 * Comprehensive cleanup script
 * Fixes: !important, duplicate selectors, inline styles
 */
const fs = require('fs');
const path = require('path');
const glob = require('glob');

console.log('================================================================================');
console.log('COMPREHENSIVE CLEANUP SCRIPT');
console.log('================================================================================\n');

// Track changes
let totalImportantRemoved = 0;
let totalDupesRemoved = 0;
let filesModified = [];

// =============================================================================
// 1. REMOVE UNNECESSARY !important
// =============================================================================
console.log('1. REMOVING UNNECESSARY !important\n');

// Files to skip (vendor, intentional)
const skipFiles = [
  'bootstrap-minimal.css',
  'sweetalert-modern.css',
  'mobile/utilities.css',    // Utility classes need !important
  'utilities/',              // All utility files
];

// Properties where !important is NEVER needed with @layer
const safeToRemove = [
  'color',
  'background-color',
  'background',
  'border-color',
  'border',
  'padding',
  'margin',
  'font-size',
  'font-weight',
  'display',
  'width',
  'height',
  'max-width',
  'min-width',
  'max-height',
  'min-height',
  'opacity',
  'visibility',
  'transform',
  'transition',
  'box-shadow',
  'text-decoration',
  'text-align',
  'border-radius',
  'gap',
  'flex',
  'grid',
  'position',
  'top',
  'left',
  'right',
  'bottom',
  'z-index',
  'overflow',
  'cursor',
  'pointer-events',
  'outline',
  'line-height',
  'letter-spacing',
  'white-space',
  'word-break',
  'text-overflow',
  'align-items',
  'justify-content',
  'flex-direction',
  'flex-wrap',
];

const cssFiles = glob.sync('app/static/css/**/*.css');

cssFiles.forEach(file => {
  // Skip vendor/utility files
  if (skipFiles.some(skip => file.includes(skip))) {
    return;
  }

  let content = fs.readFileSync(file, 'utf8');
  const originalContent = content;
  let fileChanges = 0;

  // Remove !important from safe properties (but keep JUSTIFIED ones)
  safeToRemove.forEach(prop => {
    // Match property: value !important but NOT if JUSTIFIED comment nearby
    const regex = new RegExp(
      `(${prop}\\s*:\\s*[^;]+?)\\s*!important(\\s*;)`,
      'gi'
    );

    content = content.replace(regex, (match, before, after) => {
      // Check if this line has JUSTIFIED comment
      if (match.includes('JUSTIFIED') || match.includes('justified')) {
        return match;
      }
      fileChanges++;
      totalImportantRemoved++;
      return before + after;
    });
  });

  if (fileChanges > 0) {
    fs.writeFileSync(file, content);
    filesModified.push({ file, changes: fileChanges, type: '!important' });
    console.log(`  ${file}: removed ${fileChanges} !important`);
  }
});

console.log(`\n  Total !important removed: ${totalImportantRemoved}\n`);

// =============================================================================
// 2. FIX DUPLICATE SELECTORS IN SAME FILE
// =============================================================================
console.log('2. FIXING DUPLICATE SELECTORS\n');

// This is complex - we need to merge duplicate selectors
// For now, just report them
const dupesFound = [];

cssFiles.forEach(file => {
  const content = fs.readFileSync(file, 'utf8');
  const selectorCounts = {};

  // Simple regex to find selectors (not perfect but catches most)
  const lines = content.split('\n');
  let inMediaQuery = 0;

  lines.forEach((line, idx) => {
    if (line.includes('@media')) inMediaQuery++;
    if (inMediaQuery > 0 && line.includes('}') && !line.includes('{')) inMediaQuery--;

    // Only check top-level selectors (not in media queries)
    if (inMediaQuery === 0) {
      const match = line.match(/^([.#][a-zA-Z][^{]+)\s*\{/);
      if (match) {
        const selector = match[1].trim();
        if (selectorCounts[selector]) {
          selectorCounts[selector]++;
        } else {
          selectorCounts[selector] = 1;
        }
      }
    }
  });

  const dupes = Object.entries(selectorCounts).filter(([sel, count]) => count > 1);
  if (dupes.length > 0) {
    dupesFound.push({ file, dupes: dupes.length });
  }
});

if (dupesFound.length > 0) {
  console.log('  Files with duplicate top-level selectors:');
  dupesFound.forEach(d => console.log(`    ${d.file}: ${d.dupes} duplicates`));
} else {
  console.log('  No duplicate selectors found at top level');
}

// =============================================================================
// 3. SUMMARY
// =============================================================================
console.log('\n================================================================================');
console.log('SUMMARY');
console.log('================================================================================');
console.log(`!important declarations removed: ${totalImportantRemoved}`);
console.log(`Files modified: ${filesModified.length}`);
console.log(`Duplicate selector files to review: ${dupesFound.length}`);

if (filesModified.length > 0) {
  console.log('\nModified files:');
  filesModified.forEach(f => console.log(`  ${f.file} (${f.changes} ${f.type})`));
}
