#!/usr/bin/env node
/**
 * !important Declaration Audit Script
 * Categorizes !important usage as justified or unjustified
 */

const fs = require('fs');
const path = require('path');

const CSS_DIR = path.join(__dirname, '../app/static/css');

// Justified contexts for !important
const justifiedPatterns = [
  // Accessibility
  /@media\s*\(\s*prefers-reduced-motion/i,
  /@media\s*\(\s*prefers-contrast/i,

  // Print styles
  /@media\s*print/i,

  // Utility classes (by convention)
  /\.u-[a-z]/i,
  /\.mobile-/i,
  /\.desktop-/i,
  /\.touch-/i,
  /\.ios-/i,

  // State overrides
  /\.is-hidden/i,
  /\.is-visible/i,
  /\.hidden/i,
  /\.d-none/i,
  /\.visually-hidden/i,

  // Z-index management
  /z-index.*!important/i,

  // Dark mode overrides (data-style selector)
  /\[data-style="dark"\]/i,
  /\[data-bs-theme="dark"\]/i,
];

// Files that are expected to use !important (library overrides)
const justifiedFiles = [
  'sweetalert-modern.css',  // SweetAlert2 library overrides
  'bootstrap-theming.css',   // Bootstrap overrides
  'bootstrap-color-overrides.css',
  'component-aliases.css',   // Migration layer
  'waves-effects.css',       // Third-party library
];

// Results tracking
const results = {
  justified: [],
  unjustified: [],
  byFile: {}
};

function analyzeFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const relativePath = path.relative(CSS_DIR, filePath);
  const fileName = path.basename(filePath);

  // Check if file is in justified list
  const isJustifiedFile = justifiedFiles.some(f => fileName === f);

  const lines = content.split('\n');
  let currentContext = 'base';
  let braceDepth = 0;
  const fileResults = { justified: 0, unjustified: 0, details: [] };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineNum = i + 1;

    // Track @media context
    if (line.includes('@media')) {
      currentContext = line;
    }

    // Track brace depth for context
    braceDepth += (line.match(/{/g) || []).length;
    braceDepth -= (line.match(/}/g) || []).length;
    if (braceDepth === 0) {
      currentContext = 'base';
    }

    // Check for !important
    if (line.includes('!important')) {
      // Check if it's a comment
      if (line.trim().startsWith('/*') || line.trim().startsWith('*') || line.trim().startsWith('//')) {
        continue;
      }

      // Check if justified
      let isJustified = isJustifiedFile;

      if (!isJustified) {
        // Check context patterns
        isJustified = justifiedPatterns.some(pattern =>
          pattern.test(currentContext) || pattern.test(line)
        );
      }

      // Check for explicit JUSTIFIED comment nearby
      if (!isJustified) {
        const nearbyLines = lines.slice(Math.max(0, i - 10), i + 1).join('\n');
        if (/JUSTIFIED.*!important/i.test(nearbyLines)) {
          isJustified = true;
        }
      }

      if (isJustified) {
        fileResults.justified++;
        results.justified.push({ file: relativePath, line: lineNum, content: line.trim() });
      } else {
        fileResults.unjustified++;
        results.unjustified.push({ file: relativePath, line: lineNum, content: line.trim() });
      }
    }
  }

  if (fileResults.justified + fileResults.unjustified > 0) {
    results.byFile[relativePath] = fileResults;
  }
}

function walkDir(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);

    if (stat.isDirectory()) {
      // Skip utilities directory (expected to use !important)
      if (file === 'utilities' || file === 'tokens') continue;
      walkDir(fullPath);
    } else if (file.endsWith('.css') && file !== 'bootstrap-minimal.css') {
      analyzeFile(fullPath);
    }
  }
}

console.log('================================================================================');
console.log('!IMPORTANT DECLARATION AUDIT');
console.log('================================================================================\n');

walkDir(CSS_DIR);

console.log('SUMMARY');
console.log('────────────────────────────────────────────────────────────────────────────────');
console.log(`Justified !important declarations: ${results.justified.length}`);
console.log(`Unjustified !important declarations: ${results.unjustified.length}`);
console.log('');

if (results.unjustified.length > 0) {
  console.log('UNJUSTIFIED !IMPORTANT (should be removed/refactored)');
  console.log('────────────────────────────────────────────────────────────────────────────────');

  // Group by file
  const byFile = {};
  results.unjustified.forEach(item => {
    if (!byFile[item.file]) byFile[item.file] = [];
    byFile[item.file].push(item);
  });

  // Sort by count
  const sorted = Object.entries(byFile).sort((a, b) => b[1].length - a[1].length);

  sorted.slice(0, 15).forEach(([file, items]) => {
    console.log(`\n${file} (${items.length} unjustified):`);
    items.slice(0, 5).forEach(item => {
      console.log(`  Line ${item.line}: ${item.content.substring(0, 70)}...`);
    });
    if (items.length > 5) {
      console.log(`  ... and ${items.length - 5} more`);
    }
  });
}

console.log('\n================================================================================');
console.log('Audit complete.');
console.log('================================================================================');

// Save detailed report
const reportPath = path.join(__dirname, 'important-audit-report.json');
fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
console.log(`\nDetailed report saved to: ${reportPath}`);
