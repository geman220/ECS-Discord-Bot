#!/usr/bin/env node
/**
 * TDZ Global Fix Script - Exhaustive Edition
 *
 * 1. Dynamically finds ALL window.X = assignments across the codebase
 * 2. Scans ALL files for bare X usage
 * 3. Auto-fixes by replacing bare X with window.X
 *
 * Run: node scripts/fix-tdz-globals.cjs --dry-run   (preview changes)
 * Run: node scripts/fix-tdz-globals.cjs --fix       (apply changes)
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

// Built-in browser globals - safe to use bare
const BROWSER_GLOBALS = new Set([
  'window', 'document', 'console', 'fetch', 'setTimeout', 'setInterval',
  'clearTimeout', 'clearInterval', 'requestAnimationFrame', 'cancelAnimationFrame',
  'localStorage', 'sessionStorage', 'navigator', 'location', 'history',
  'performance', 'MutationObserver', 'ResizeObserver', 'IntersectionObserver',
  'CustomEvent', 'Event', 'FormData', 'URL', 'URLSearchParams', 'AbortController',
  'Headers', 'Request', 'Response', 'Blob', 'File', 'FileReader', 'Image', 'Audio',
  'HTMLElement', 'Element', 'Node', 'NodeList', 'DOMParser', 'getComputedStyle',
  'matchMedia', 'alert', 'confirm', 'prompt', 'Map', 'Set', 'WeakMap', 'WeakSet',
  'Promise', 'Symbol', 'Proxy', 'Reflect', 'JSON', 'Math', 'Date', 'RegExp',
  'Array', 'Object', 'String', 'Number', 'Boolean', 'Function', 'Error',
  'TypeError', 'ReferenceError', 'SyntaxError', 'RangeError', 'URIError',
  'parseInt', 'parseFloat', 'isNaN', 'isFinite', 'encodeURI', 'decodeURI',
  'encodeURIComponent', 'decodeURIComponent', 'undefined', 'NaN', 'Infinity',
  'globalThis', 'self', 'top', 'parent', 'frames', 'crypto', 'atob', 'btoa',
  'TextEncoder', 'TextDecoder', 'Intl', 'queueMicrotask', 'structuredClone',
  'WebSocket', 'Worker', 'Notification', 'indexedDB', 'caches',
  // i18n libraries loaded via script tag
  'i18next', 'i18NextHttpBackend',
  // Common local variable names that happen to match global patterns
  'config', 'options', 'settings', 'data', 'result', 'response', 'error',
  'callback', 'handler', 'listener', 'observer', 'instance', 'context',
]);

// Globals that are too common as local variables - skip these
const SKIP_GLOBALS = new Set([
  'config', 'options', 'data', 'result', 'error', 'callback', 'handler',
  'instance', 'context', 'state', 'props', 'value', 'item', 'element',
  'node', 'target', 'source', 'key', 'id', 'name', 'type', 'status',
]);

function escapeRegex(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function findAllJsFiles() {
  return await glob('app/static/{js,custom_js,assets/js}/**/*.js', {
    ignore: ['**/vendor/**', '**/vite-dist/**', '**/dist/**', '**/gen/**', '**/node_modules/**']
  });
}

// Step 1: Find ALL window.X = assignments
function findAllWindowGlobals(files) {
  const globals = new Map(); // name -> [{ file, line }]

  for (const filePath of files) {
    const content = fs.readFileSync(filePath, 'utf8');
    const lines = content.split('\n');

    lines.forEach((line, idx) => {
      // Match: window.X = (but not window.X.Y =)
      const matches = line.matchAll(/window\.([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=/g);
      for (const match of matches) {
        const name = match[1];
        // Skip if it's a nested property (window.X.Y =)
        const afterMatch = line.substring(match.index + match[0].length);
        if (afterMatch.trim().startsWith('.')) continue;

        if (!BROWSER_GLOBALS.has(name) && !SKIP_GLOBALS.has(name)) {
          if (!globals.has(name)) globals.set(name, []);
          globals.get(name).push({ file: filePath, line: idx + 1 });
        }
      }
    });
  }

  return globals;
}

// Step 2: Find bare usage and optionally fix
function findAndFixBareUsage(filePath, globals, doFix) {
  const content = fs.readFileSync(filePath, 'utf8');
  const lines = content.split('\n');
  const violations = [];
  let modified = false;

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i];
    const trimmed = line.trim();

    // Skip comments
    if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) continue;

    // Skip import/export statements
    if (trimmed.startsWith('import ') || trimmed.startsWith('export ')) continue;

    for (const globalName of globals.keys()) {
      // Skip if line already has window.globalName
      if (line.includes(`window.${globalName}`)) continue;

      // Skip typeof checks
      if (line.includes(`typeof ${globalName}`)) continue;

      // Build pattern to find bare usage
      // Match: globalName followed by ( or . or , or ) or space or end
      // But NOT preceded by . or word char (to avoid obj.globalName)
      const escaped = escapeRegex(globalName);
      const pattern = new RegExp(
        `(?<![.\\w])\\b${escaped}\\b(?=\\s*[.({,;:\\])])`,
        'g'
      );

      let match;
      let lineModified = false;
      const originalLine = line;

      while ((match = pattern.exec(originalLine)) !== null) {
        const idx = match.index;
        const before = originalLine.substring(Math.max(0, idx - 20), idx);

        // Skip if it's in a string (basic check)
        const beforeQuotes = (before.match(/['"]/g) || []).length;
        if (beforeQuotes % 2 !== 0) continue;

        // Skip if preceded by window.
        if (before.endsWith('window.')) continue;

        // Skip declarations (var/let/const/function/class)
        if (/(?:var|let|const|function|class)\s*$/.test(before)) continue;

        // Skip static/async method declarations
        if (/(?:static|async)\s*$/.test(before)) continue;

        const afterText = originalLine.substring(idx + globalName.length).trim();

        // Skip if it's a property key in object literal (globalName: value)
        // This handles both { globalName: val } and multi-line objects
        if (afterText.startsWith(':') && !afterText.startsWith('::')) continue;

        // Skip object shorthand properties { globalName, } or { globalName }
        if (/[{,]\s*$/.test(before) && /^[,}]/.test(afterText)) continue;

        // Skip shorthand at start of line (multi-line object) followed by , or }
        if (/^\s*$/.test(before) && /^[,}]/.test(afterText)) continue;

        // Skip method declarations in classes/objects: globalName() { or globalName(params) {
        if (/^\s*\([^)]*\)\s*\{/.test(afterText)) continue;

        // Skip function parameters
        if (/\(\s*$/.test(before) || /,\s*$/.test(before)) {
          if (afterText.startsWith(',') || afterText.startsWith(')')) continue;
        }

        violations.push({
          file: filePath,
          line: i + 1,
          globalName,
          context: trimmed.substring(0, 100)
        });

        if (doFix) {
          // Replace this occurrence
          line = line.substring(0, idx) + `window.${globalName}` + line.substring(idx + globalName.length);
          lineModified = true;
        }

        break; // One fix per global per line
      }

      if (lineModified) {
        lines[i] = line;
        modified = true;
      }
    }
  }

  if (doFix && modified) {
    fs.writeFileSync(filePath, lines.join('\n'), 'utf8');
  }

  return { violations, modified };
}

async function main() {
  const args = process.argv.slice(2);
  const dryRun = args.includes('--dry-run');
  const doFix = args.includes('--fix');

  if (!dryRun && !doFix) {
    console.log('Usage:');
    console.log('  node scripts/fix-tdz-globals.cjs --dry-run   Preview changes');
    console.log('  node scripts/fix-tdz-globals.cjs --fix       Apply changes');
    process.exit(1);
  }

  console.log(`\n🔍 TDZ Global Scanner - ${doFix ? 'FIX MODE' : 'DRY RUN'}\n`);
  console.log('='.repeat(70) + '\n');

  // Find all JS files
  const jsFiles = await findAllJsFiles();
  console.log(`📁 Scanning ${jsFiles.length} JavaScript files...\n`);

  // Step 1: Find all window.X = assignments
  console.log('Step 1: Finding all window.X = assignments...\n');
  const globals = findAllWindowGlobals(jsFiles);

  console.log(`Found ${globals.size} custom window globals:\n`);
  const sortedNames = Array.from(globals.keys()).sort();
  for (const name of sortedNames) {
    const locations = globals.get(name);
    console.log(`   window.${name} (${locations.length} definition${locations.length > 1 ? 's' : ''})`);
  }

  console.log('\n' + '='.repeat(70) + '\n');
  console.log('Step 2: Finding bare usage of these globals...\n');

  // Step 2: Find and fix bare usage
  const allViolations = [];
  const modifiedFiles = [];

  for (const filePath of jsFiles) {
    const { violations, modified } = findAndFixBareUsage(filePath, globals, doFix);
    allViolations.push(...violations);
    if (modified) modifiedFiles.push(filePath);
  }

  // Report
  if (allViolations.length === 0) {
    console.log('✅ No bare global usage found! All globals use window.X pattern.\n');
    process.exit(0);
  }

  // Group by file
  const byFile = new Map();
  for (const v of allViolations) {
    if (!byFile.has(v.file)) byFile.set(v.file, []);
    byFile.get(v.file).push(v);
  }

  console.log(`${doFix ? '🔧 Fixed' : '❌ Found'} ${allViolations.length} bare global usages:\n`);

  for (const [file, violations] of byFile) {
    console.log(`\n📄 ${file}`);
    for (const v of violations) {
      console.log(`   Line ${v.line}: ${v.globalName} → window.${v.globalName}`);
    }
  }

  // Summary
  console.log('\n' + '='.repeat(70));
  console.log('\n📊 Summary by global:\n');

  const countByGlobal = {};
  for (const v of allViolations) {
    countByGlobal[v.globalName] = (countByGlobal[v.globalName] || 0) + 1;
  }

  Object.entries(countByGlobal)
    .sort((a, b) => b[1] - a[1])
    .forEach(([name, count]) => {
      console.log(`   ${name}: ${count} occurrence(s)`);
    });

  if (doFix) {
    console.log(`\n✅ Fixed ${modifiedFiles.length} files.\n`);
    console.log('Modified files:');
    modifiedFiles.forEach(f => console.log(`   ${f}`));
    console.log('\nRun `npm run build` to verify.\n');
  } else {
    console.log(`\n💡 Run with --fix to automatically fix these issues.\n`);
  }

  process.exit(doFix ? 0 : 1);
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
