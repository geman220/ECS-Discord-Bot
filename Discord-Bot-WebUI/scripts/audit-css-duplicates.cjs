/**
 * CSS Duplicate Selector Audit
 *
 * Finds duplicate CSS selectors across files and reports:
 * 1. Which selectors are defined multiple times
 * 2. Which files contain each duplicate
 * 3. Priority issues (same selector in multiple component files)
 */

const fs = require('fs');
const path = require('path');
const glob = require('glob');

const CSS_DIR = path.join(__dirname, '../app/static/css');

// Extract selectors from CSS content
function extractSelectors(content, filePath) {
  const selectors = [];

  // Remove comments
  content = content.replace(/\/\*[\s\S]*?\*\//g, '');

  // Match selectors (simplified - handles most common cases)
  const regex = /^([.#][\w\-\[\]="':\s,>+~*]+)\s*\{/gm;
  let match;

  while ((match = regex.exec(content)) !== null) {
    // Split compound selectors
    const selectorGroup = match[1].trim();
    const individualSelectors = selectorGroup.split(',').map(s => s.trim());

    individualSelectors.forEach(sel => {
      if (sel) {
        selectors.push({
          selector: sel,
          file: filePath
        });
      }
    });
  }

  return selectors;
}

// Main audit function
function auditDuplicates() {
  const cssFiles = glob.sync('**/*.css', { cwd: CSS_DIR, absolute: true });

  console.log(`\n${'='.repeat(80)}`);
  console.log('CSS DUPLICATE SELECTOR AUDIT');
  console.log(`${'='.repeat(80)}\n`);
  console.log(`Scanning ${cssFiles.length} CSS files...\n`);

  const selectorMap = new Map(); // selector -> array of files

  // Process each file
  cssFiles.forEach(file => {
    const relativePath = path.relative(CSS_DIR, file);
    const content = fs.readFileSync(file, 'utf8');
    const selectors = extractSelectors(content, relativePath);

    selectors.forEach(({ selector }) => {
      if (!selectorMap.has(selector)) {
        selectorMap.set(selector, new Set());
      }
      selectorMap.get(selector).add(relativePath);
    });
  });

  // Find duplicates (selectors in 2+ files)
  const duplicates = [];
  selectorMap.forEach((files, selector) => {
    if (files.size > 1) {
      duplicates.push({
        selector,
        files: Array.from(files),
        count: files.size
      });
    }
  });

  // Sort by count descending
  duplicates.sort((a, b) => b.count - a.count);

  // Categorize duplicates
  const bemDuplicates = duplicates.filter(d => d.selector.startsWith('.c-'));
  const bootstrapOverrides = duplicates.filter(d =>
    /^\.(btn|modal|dropdown|alert|badge|card|form|nav|table|toast|accordion)/i.test(d.selector)
  );
  const otherDuplicates = duplicates.filter(d =>
    !d.selector.startsWith('.c-') &&
    !/^\.(btn|modal|dropdown|alert|badge|card|form|nav|table|toast|accordion)/i.test(d.selector)
  );

  // Report BEM duplicates (these are the problematic ones)
  console.log(`${'─'.repeat(80)}`);
  console.log('🚨 BEM COMPONENT DUPLICATES (SHOULD BE FIXED)');
  console.log(`${'─'.repeat(80)}\n`);

  if (bemDuplicates.length === 0) {
    console.log('✅ No BEM component duplicates found!\n');
  } else {
    console.log(`Found ${bemDuplicates.length} BEM selectors defined in multiple files:\n`);

    bemDuplicates.slice(0, 30).forEach(({ selector, files, count }) => {
      console.log(`\n${selector} (${count} files):`);
      files.forEach(f => console.log(`  - ${f}`));
    });

    if (bemDuplicates.length > 30) {
      console.log(`\n... and ${bemDuplicates.length - 30} more`);
    }
  }

  // Report Bootstrap overrides (these are usually intentional)
  console.log(`\n${'─'.repeat(80)}`);
  console.log('ℹ️  BOOTSTRAP OVERRIDES (Usually intentional)');
  console.log(`${'─'.repeat(80)}\n`);
  console.log(`Found ${bootstrapOverrides.length} Bootstrap selectors with overrides`);
  console.log('(These are often intentional for theming/customization)\n');

  // Summary
  console.log(`\n${'='.repeat(80)}`);
  console.log('SUMMARY');
  console.log(`${'='.repeat(80)}\n`);
  console.log(`Total duplicate selectors: ${duplicates.length}`);
  console.log(`  - BEM components (.c-*): ${bemDuplicates.length} ⚠️  REVIEW THESE`);
  console.log(`  - Bootstrap overrides: ${bootstrapOverrides.length}`);
  console.log(`  - Other: ${otherDuplicates.length}`);

  // Write detailed report
  const reportPath = path.join(__dirname, '../css-duplicates-report.json');
  const report = {
    timestamp: new Date().toISOString(),
    summary: {
      total: duplicates.length,
      bem: bemDuplicates.length,
      bootstrap: bootstrapOverrides.length,
      other: otherDuplicates.length
    },
    bemDuplicates: bemDuplicates,
    bootstrapOverrides: bootstrapOverrides.slice(0, 20),
    otherDuplicates: otherDuplicates.slice(0, 20)
  };

  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(`\nDetailed report saved to: css-duplicates-report.json`);

  return bemDuplicates.length;
}

// Run audit
const bemDuplicateCount = auditDuplicates();
process.exit(bemDuplicateCount > 0 ? 1 : 0);
