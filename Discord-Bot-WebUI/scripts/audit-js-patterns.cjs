#!/usr/bin/env node
/**
 * ============================================================================
 * JAVASCRIPT PATTERN AUDITOR
 * ============================================================================
 *
 * Automatically detects common performance and architectural issues:
 * 1. Multiple MutationObservers watching same target
 * 2. Event listeners without delegation (querySelectorAll + addEventListener)
 * 3. Missing initialization guards (_initialized, _registered flags)
 * 4. MutationObserver callbacks that modify DOM (potential cascade)
 * 5. Duplicate global registrations
 *
 * Usage: node scripts/audit-js-patterns.js
 *
 * ============================================================================
 */

const fs = require('fs');
const path = require('path');
const glob = require('glob');

// Configuration
const JS_DIRS = [
  'app/static/js',
  'app/static/custom_js'
];

const ISSUES = {
  MUTATION_OBSERVER_BODY: [],
  MUTATION_OBSERVER_NO_GUARD: [],
  MUTATION_OBSERVER_MODIFIES_DOM: [],
  EVENT_LISTENER_NO_DELEGATION: [],
  MISSING_INIT_GUARD: [],
  DUPLICATE_GLOBAL: [],
  QUERYSELECTORALL_ADDEVENTLISTENER: []
};

// Patterns to detect
const PATTERNS = {
  // MutationObserver watching document.body
  mutationObserverBody: /new\s+MutationObserver[\s\S]*?\.observe\s*\(\s*(document\.body|body)/g,

  // MutationObserver without isProcessing/isAdjusting guard
  mutationObserverCallback: /new\s+MutationObserver\s*\(\s*(?:function\s*\(|[\w\s]*=>|\([\w\s,]*\)\s*=>)\s*\{([\s\S]*?)\}\s*\)/g,

  // DOM modification in callback (classList, setAttribute, appendChild, etc.)
  domModification: /\.(classList\.(add|remove|toggle)|setAttribute|appendChild|insertBefore|removeChild|innerHTML|outerHTML|style\.)/,

  // querySelectorAll followed by forEach + addEventListener (anti-pattern)
  querySelectorAllAddEventListener: /querySelectorAll\s*\([^)]+\)\s*\.\s*forEach\s*\([^)]*\)\s*\{[\s\S]*?addEventListener/g,

  // addEventListener without delegation check
  addEventListenerDirect: /(\w+)\.addEventListener\s*\(\s*['"](\w+)['"]/g,

  // Functions that should have init guards
  initFunction: /function\s+(init|initialize|setup|register)\w*\s*\(/g,

  // Init guard patterns - matches various guard naming conventions
  initGuard: /if\s*\(\s*(this\._|_|State\._|window\._)(\w+(?:Initialized|initialized|Setup|setup|Registered|registered))\s*\)/,

  // Global window assignments (excludes == and === comparisons)
  windowAssignment: /window\.(\w+)\s*=(?!=)/g,

  // document.addEventListener without delegation
  documentAddEventListener: /document\.addEventListener\s*\(\s*['"](\w+)['"]\s*,\s*function/g
};

function analyzeFile(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const relativePath = path.relative(process.cwd(), filePath);
  const lines = content.split('\n');

  // Helper to find line number
  const getLineNumber = (index) => {
    return content.substring(0, index).split('\n').length;
  };

  // 1. Check for MutationObserver watching document.body
  // Skip the unified-mutation-observer.js itself (it's the central manager)
  if (relativePath.includes('unified-mutation-observer')) {
    // This is the central manager, skip checking it
  } else {
    let match;
    const bodyObserverRegex = /\.observe\s*\(\s*document\.body/g;
    while ((match = bodyObserverRegex.exec(content)) !== null) {
      // Check if using UnifiedMutationObserver
      const contextStart = Math.max(0, match.index - 500);
      const context = content.substring(contextStart, match.index);
      if (!context.includes('UnifiedMutationObserver')) {
        ISSUES.MUTATION_OBSERVER_BODY.push({
          file: relativePath,
          line: getLineNumber(match.index),
          issue: 'MutationObserver watching document.body directly (should use UnifiedMutationObserver)'
        });
      }
    }
  }

  // 2. Check MutationObserver callbacks for DOM modification without guards
  const observerRegex = /new\s+MutationObserver\s*\(\s*(?:function\s*\(|\(?\s*\w*\s*\)?\s*=>)\s*\{/g;
  while ((match = observerRegex.exec(content)) !== null) {
    // Find the callback body (rough extraction)
    let braceCount = 1;
    let i = match.index + match[0].length;
    let callbackStart = i;
    while (braceCount > 0 && i < content.length) {
      if (content[i] === '{') braceCount++;
      if (content[i] === '}') braceCount--;
      i++;
    }
    const callbackBody = content.substring(callbackStart, i);

    // Check for DOM modifications
    if (PATTERNS.domModification.test(callbackBody)) {
      // Check for guard
      if (!/if\s*\(\s*(isProcessing|isAdjusting|_isProcessing|this\._isProcessing)/.test(callbackBody)) {
        ISSUES.MUTATION_OBSERVER_MODIFIES_DOM.push({
          file: relativePath,
          line: getLineNumber(match.index),
          issue: 'MutationObserver callback modifies DOM without isProcessing guard (potential cascade)'
        });
      }
    }
  }

  // 3. Check for querySelectorAll + forEach + addEventListener pattern
  const qsaPattern = /querySelectorAll\s*\([^)]+\)[^;]*\.forEach\s*\(\s*(?:function\s*\(\s*(\w+)|(\w+)\s*=>)/g;
  while ((match = qsaPattern.exec(content)) !== null) {
    const varName = match[1] || match[2];
    // Look ahead for addEventListener on this variable
    const lookAhead = content.substring(match.index, match.index + 500);
    if (new RegExp(`${varName}\\.addEventListener`).test(lookAhead)) {
      ISSUES.QUERYSELECTORALL_ADDEVENTLISTENER.push({
        file: relativePath,
        line: getLineNumber(match.index),
        issue: `querySelectorAll().forEach() with addEventListener (use event delegation instead)`
      });
    }
  }

  // 4. Check for init functions without guards
  const initFuncRegex = /function\s+(init|initialize|setup\w*|register\w*)\s*\(\s*\)/g;
  while ((match = initFuncRegex.exec(content)) !== null) {
    // Look at the next 200 chars for a guard
    const funcBody = content.substring(match.index, match.index + 300);
    // Check for various guard patterns
    const hasGuard = PATTERNS.initGuard.test(funcBody) ||
                     /_initialized|_setup|Setup|Initialized|Registered/.test(funcBody);
    if (!hasGuard) {
      // Check if it's a simple function or needs a guard
      const bodyStart = funcBody.indexOf('{');
      if (bodyStart !== -1) {
        const smallBody = funcBody.substring(bodyStart, bodyStart + 200);
        // Only flag if it has DOM operations or event listeners
        if (/addEventListener|querySelector|\.observe\(/.test(smallBody)) {
          ISSUES.MISSING_INIT_GUARD.push({
            file: relativePath,
            line: getLineNumber(match.index),
            issue: `Function '${match[1]}' lacks _initialized guard and has DOM operations`
          });
        }
      }
    }
  }

  // 5. Track global window assignments for duplicates (using PATTERNS.windowAssignment)
  const windowRegex = new RegExp(PATTERNS.windowAssignment.source, 'g');
  while ((match = windowRegex.exec(content)) !== null) {
    const globalName = match[1];
    // Skip common/expected globals and intentional cross-file patterns
    const skipGlobals = [
      'jQuery', '$', 'bootstrap', 'Swal', 'feather',
      // Helpers is intentionally different (helpers.js vs helpers-minimal.js)
      'Helpers',
      // socket is intentionally set conditionally from multiple components
      'socket',
      // SimpleCropperInstance is shared between simple-cropper.js and consumers
      'SimpleCropperInstance'
    ];
    if (!skipGlobals.includes(globalName)) {
      if (!ISSUES.DUPLICATE_GLOBAL[globalName]) {
        ISSUES.DUPLICATE_GLOBAL[globalName] = [];
      }
      ISSUES.DUPLICATE_GLOBAL[globalName].push({
        file: relativePath,
        line: getLineNumber(match.index)
      });
    }
  }
}

function printReport() {
  console.log('\n' + '='.repeat(80));
  console.log('JAVASCRIPT PATTERN AUDIT REPORT');
  console.log('='.repeat(80) + '\n');

  let totalIssues = 0;

  // 1. MutationObserver on body
  if (ISSUES.MUTATION_OBSERVER_BODY.length > 0) {
    console.log('\n🔴 CRITICAL: MutationObservers watching document.body directly');
    console.log('   These should use UnifiedMutationObserver to prevent cascade effects\n');
    ISSUES.MUTATION_OBSERVER_BODY.forEach(issue => {
      console.log(`   ${issue.file}:${issue.line}`);
      console.log(`      ${issue.issue}\n`);
    });
    totalIssues += ISSUES.MUTATION_OBSERVER_BODY.length;
  }

  // 2. MutationObserver modifies DOM
  if (ISSUES.MUTATION_OBSERVER_MODIFIES_DOM.length > 0) {
    console.log('\n🟠 WARNING: MutationObserver callbacks that modify DOM without guards');
    console.log('   Add isProcessing/isAdjusting guard to prevent infinite loops\n');
    ISSUES.MUTATION_OBSERVER_MODIFIES_DOM.forEach(issue => {
      console.log(`   ${issue.file}:${issue.line}`);
      console.log(`      ${issue.issue}\n`);
    });
    totalIssues += ISSUES.MUTATION_OBSERVER_MODIFIES_DOM.length;
  }

  // 3. querySelectorAll + addEventListener
  if (ISSUES.QUERYSELECTORALL_ADDEVENTLISTENER.length > 0) {
    console.log('\n🟠 WARNING: querySelectorAll + forEach + addEventListener pattern');
    console.log('   Use event delegation with document.addEventListener instead\n');
    ISSUES.QUERYSELECTORALL_ADDEVENTLISTENER.forEach(issue => {
      console.log(`   ${issue.file}:${issue.line}`);
      console.log(`      ${issue.issue}\n`);
    });
    totalIssues += ISSUES.QUERYSELECTORALL_ADDEVENTLISTENER.length;
  }

  // 4. Missing init guards
  if (ISSUES.MISSING_INIT_GUARD.length > 0) {
    console.log('\n🟡 INFO: Init functions without _initialized guards');
    console.log('   Consider adding guards to prevent duplicate initialization\n');
    ISSUES.MISSING_INIT_GUARD.forEach(issue => {
      console.log(`   ${issue.file}:${issue.line}`);
      console.log(`      ${issue.issue}\n`);
    });
    totalIssues += ISSUES.MISSING_INIT_GUARD.length;
  }

  // 5. Duplicate globals (only flag if defined in DIFFERENT files)
  const duplicateGlobals = Object.entries(ISSUES.DUPLICATE_GLOBAL)
    .filter(([name, locations]) => {
      // Get unique files
      const uniqueFiles = new Set(locations.map(loc => loc.file));
      return uniqueFiles.size > 1;
    });

  if (duplicateGlobals.length > 0) {
    console.log('\n🟡 INFO: Global variables defined in multiple files');
    console.log('   May cause conflicts or overwrites\n');
    duplicateGlobals.forEach(([name, locations]) => {
      // Only show unique files
      const uniqueFiles = new Set();
      const uniqueLocations = locations.filter(loc => {
        if (uniqueFiles.has(loc.file)) return false;
        uniqueFiles.add(loc.file);
        return true;
      });
      console.log(`   window.${name} defined in ${uniqueLocations.length} files:`);
      uniqueLocations.forEach(loc => {
        console.log(`      ${loc.file}:${loc.line}`);
      });
      console.log('');
    });
    totalIssues += duplicateGlobals.length;
  }

  // Summary
  console.log('\n' + '='.repeat(80));
  if (totalIssues === 0) {
    console.log('✅ No issues found!');
  } else {
    console.log(`Found ${totalIssues} potential issues`);
  }
  console.log('='.repeat(80) + '\n');

  return totalIssues;
}

// Main
function main() {
  console.log('Scanning JavaScript files...\n');

  let fileCount = 0;
  JS_DIRS.forEach(dir => {
    const fullDir = path.join(process.cwd(), dir);
    if (fs.existsSync(fullDir)) {
      const files = glob.sync(path.join(fullDir, '**/*.js'));
      files.forEach(file => {
        analyzeFile(file);
        fileCount++;
      });
    }
  });

  console.log(`Analyzed ${fileCount} files`);

  const issueCount = printReport();
  process.exit(issueCount > 0 ? 1 : 0);
}

main();
