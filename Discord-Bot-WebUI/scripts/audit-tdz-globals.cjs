#!/usr/bin/env node
/**
 * TDZ Global Audit Script - Fixed Version
 *
 * Finds potential TDZ errors by checking for bare global usage
 * that should use window.X pattern.
 *
 * Run: node scripts/audit-tdz-globals.cjs
 */

const fs = require('fs');
const { glob } = require('glob');

// High-priority globals that are commonly used across files
// These are the ones most likely to cause TDZ errors
// NOTE: 'config' is excluded because it's commonly used as a local variable name
const HIGH_PRIORITY_GLOBALS = [
  // Vendor libraries (from vendor-globals.js) - CRITICAL
  'bootstrap', 'Swal', 'flatpickr', 'Cropper', 'feather',
  'Hammer', 'PerfectScrollbar', 'Sortable', 'Shepherd', 'Waves', 'io',
  'Toastify', 'Chart', 'Menu', 'Helpers',
  // Config variables (from config.js) - CRITICAL
  'templateName', 'assetsPath', 'TemplateCustomizer', 'rtlSupport',
];

// Files that DEFINE globals (should be skipped)
const DEFINITION_FILES = [
  'vendor-globals.js',
  'config.js',
  'helpers-minimal.js',
  'init-system.js'
];

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function findAllJsFiles() {
  const files = await glob('app/static/{js,custom_js,assets/js}/**/*.js', {
    ignore: ['**/vendor/**', '**/vite-dist/**', '**/dist/**', '**/gen/**', '**/node_modules/**']
  });
  return files;
}

function checkFileForBareGlobals(filePath, globalsToCheck) {
  // Skip files that define globals
  const fileName = filePath.split('/').pop();
  if (DEFINITION_FILES.includes(fileName)) {
    return [];
  }

  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  const violations = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const lineNum = i + 1;
    const trimmed = line.trim();

    // Skip comments
    if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) {
      continue;
    }

    // Skip import statements
    if (trimmed.startsWith('import ')) {
      continue;
    }

    // Skip export statements
    if (trimmed.startsWith('export ')) {
      continue;
    }

    for (const globalName of globalsToCheck) {
      // Skip if line already uses window.globalName (correct usage)
      if (line.includes(`window.${globalName}`)) {
        continue;
      }

      // Skip typeof checks - they're safe
      if (line.includes(`typeof ${globalName}`)) {
        continue;
      }

      // Skip if it's defining the global (window.X = ...)
      if (new RegExp(`window\\.${escapeRegex(globalName)}\\s*=`).test(line)) {
        continue;
      }

      // Skip declarations (var/let/const globalName)
      if (new RegExp(`(?:var|let|const)\\s+${escapeRegex(globalName)}\\b`).test(line)) {
        continue;
      }

      // Skip function parameters
      if (new RegExp(`function\\s*\\([^)]*\\b${escapeRegex(globalName)}\\b`).test(line)) {
        continue;
      }

      // Remove string literals to avoid false positives
      const lineNoStrings = line
        .replace(/'[^']*'/g, '""')
        .replace(/"[^"]*"/g, '""')
        .replace(/`[^`]*`/g, '""');

      // Look for bare usage patterns:
      // globalName( - function call
      // globalName. - property access
      // globalName, - in list
      // = globalName - assignment
      // && globalName or || globalName - conditionals

      const patterns = [
        new RegExp(`(?<![.\\w])${escapeRegex(globalName)}\\s*\\(`), // Function call: Swal(
        new RegExp(`(?<![.\\w])${escapeRegex(globalName)}\\s*\\.`), // Property access: Swal.fire
        new RegExp(`[=!<>]\\s*${escapeRegex(globalName)}(?![\\w])`), // Comparison: === Swal
        new RegExp(`\\|\\|\\s*${escapeRegex(globalName)}(?![\\w])`), // || Swal
        new RegExp(`&&\\s*${escapeRegex(globalName)}(?![\\w])`), // && Swal
        new RegExp(`\\(\\s*${escapeRegex(globalName)}\\s*\\)`), // (Swal)
        new RegExp(`:\\s*${escapeRegex(globalName)}(?![\\w])`), // : Swal in objects
        new RegExp(`\\?\\s*${escapeRegex(globalName)}(?![\\w])`), // ternary ? Swal
      ];

      let found = false;
      for (const pattern of patterns) {
        if (pattern.test(lineNoStrings)) {
          // Double-check it's not preceded by window.
          const match = lineNoStrings.match(pattern);
          if (match) {
            const idx = lineNoStrings.indexOf(match[0]);
            const before = lineNoStrings.substring(Math.max(0, idx - 7), idx);
            if (!before.includes('window.')) {
              violations.push({
                file: filePath,
                line: lineNum,
                globalName,
                context: trimmed.substring(0, 100)
              });
              found = true;
              break;
            }
          }
        }
      }

      if (found) break; // One violation per line is enough
    }
  }

  return violations;
}

async function main() {
  console.log('🔍 TDZ Global Audit - Checking high-priority globals\n');
  console.log('Globals checked:', HIGH_PRIORITY_GLOBALS.join(', '));
  console.log('\n' + '='.repeat(70) + '\n');

  const jsFiles = await findAllJsFiles();
  console.log(`📁 Scanning ${jsFiles.length} JavaScript files...\n`);

  const allViolations = [];

  for (const filePath of jsFiles) {
    try {
      const violations = checkFileForBareGlobals(filePath, HIGH_PRIORITY_GLOBALS);
      allViolations.push(...violations);
    } catch (err) {
      console.error(`Error reading ${filePath}:`, err.message);
    }
  }

  // Group by file
  const byFile = new Map();
  for (const v of allViolations) {
    if (!byFile.has(v.file)) byFile.set(v.file, []);
    byFile.get(v.file).push(v);
  }

  if (allViolations.length === 0) {
    console.log('✅ No TDZ-prone bare global usage found!\n');
    console.log('All high-priority globals are properly accessed via window.X\n');
    process.exit(0);
  }

  console.log(`❌ Found ${allViolations.length} potential TDZ violations:\n`);

  for (const [file, violations] of byFile) {
    console.log(`\n📄 ${file}`);
    for (const v of violations) {
      console.log(`   Line ${v.line}: bare "${v.globalName}" → use "window.${v.globalName}"`);
      console.log(`   → ${v.context}`);
    }
  }

  // Summary by global
  console.log('\n' + '='.repeat(70));
  console.log('\n📊 Summary by global:\n');

  const countByGlobal = {};
  for (const v of allViolations) {
    countByGlobal[v.globalName] = (countByGlobal[v.globalName] || 0) + 1;
  }

  Object.entries(countByGlobal)
    .sort((a, b) => b[1] - a[1])
    .forEach(([name, count]) => {
      console.log(`   ${name}: ${count} violation(s)`);
    });

  console.log('\n🔧 Fix: Replace bare globals with window.X pattern\n');
  process.exit(1);
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
