#!/usr/bin/env node
/**
 * Production Build Validation Script
 *
 * Industry Best Practice: Validate builds BEFORE deployment
 * Based on: https://vite.dev/guide/build, https://css-tricks.com/front-end-testing-is-for-everyone/
 *
 * This script validates:
 * 1. JS Module Load Order - Globals defined before use
 * 2. CSS Class Coverage - All HTML classes exist in CSS bundle
 * 3. CSS Bundle Completeness - All source CSS files included
 * 4. Manifest Correctness - All entries valid
 * 5. No Critical Errors - No syntax errors in bundles
 *
 * Usage: node scripts/validate-production-build.js
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const STATIC = path.join(ROOT, 'app/static');
const VITE_DIST = path.join(STATIC, 'vite-dist');
const TEMPLATES = path.join(ROOT, 'app/templates');

const COLORS = {
  reset: '\x1b[0m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  cyan: '\x1b[36m',
};

let errors = [];
let warnings = [];

function log(color, prefix, message) {
  console.log(`${color}${prefix}${COLORS.reset} ${message}`);
}

function error(message) {
  errors.push(message);
  log(COLORS.red, '✗ ERROR:', message);
}

function warn(message) {
  warnings.push(message);
  log(COLORS.yellow, '⚠ WARN:', message);
}

function success(message) {
  log(COLORS.green, '✓', message);
}

function info(message) {
  log(COLORS.cyan, '→', message);
}

function section(title) {
  console.log(`\n${COLORS.blue}═══ ${title} ═══${COLORS.reset}`);
}

// ============================================================================
// 1. MANIFEST VALIDATION
// ============================================================================

function validateManifest() {
  section('1. MANIFEST VALIDATION');

  const manifestPath = path.join(VITE_DIST, '.vite/manifest.json');

  if (!fs.existsSync(manifestPath)) {
    error('Manifest file not found: ' + manifestPath);
    return null;
  }

  let manifest;
  try {
    manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
    success('Manifest parsed successfully');
  } catch (e) {
    error('Failed to parse manifest: ' + e.message);
    return null;
  }

  // Check required entries
  const requiredEntries = ['js/main-entry.js', 'css/main-entry.css'];
  for (const entry of requiredEntries) {
    if (!manifest[entry]) {
      error(`Missing required entry: ${entry}`);
    } else {
      success(`Entry found: ${entry} → ${manifest[entry].file}`);
    }
  }

  // Verify all referenced files exist
  for (const [key, value] of Object.entries(manifest)) {
    const filePath = path.join(VITE_DIST, value.file);
    if (!fs.existsSync(filePath)) {
      error(`Manifest references missing file: ${value.file}`);
    }

    // Check associated CSS files
    if (value.css) {
      for (const cssFile of value.css) {
        const cssPath = path.join(VITE_DIST, cssFile);
        if (!fs.existsSync(cssPath)) {
          error(`Manifest references missing CSS: ${cssFile}`);
        }
      }
    }
  }

  return manifest;
}

// ============================================================================
// 2. JS MODULE DEPENDENCY ORDER VALIDATION
// ============================================================================

function validateJSDependencyOrder() {
  section('2. JS MODULE DEPENDENCY ORDER');

  const mainEntryPath = path.join(STATIC, 'js/main-entry.js');
  if (!fs.existsSync(mainEntryPath)) {
    error('main-entry.js not found');
    return;
  }

  const content = fs.readFileSync(mainEntryPath, 'utf8');
  const imports = [];
  const importRegex = /import\s+['"]([^'"]+)['"]/g;
  let match;

  while ((match = importRegex.exec(content)) !== null) {
    imports.push(match[1]);
  }

  info(`Found ${imports.length} imports in main-entry.js`);

  // Define critical dependency order requirements
  const dependencyOrder = {
    'vendor-globals.js': { mustBefore: ['event-delegation.js', 'modal-manager.js', 'admin-navigation.js'] },
    'event-delegation.js': { mustBefore: ['admin-navigation.js', 'modal-manager.js'] },
    'init-system.js': { mustBefore: ['app-init-registration.js'] },
  };

  const importIndex = {};
  imports.forEach((imp, idx) => {
    const basename = path.basename(imp);
    importIndex[basename] = idx;
  });

  for (const [dep, rules] of Object.entries(dependencyOrder)) {
    if (importIndex[dep] === undefined) continue;

    for (const mustBeBefore of rules.mustBefore) {
      if (importIndex[mustBeBefore] !== undefined) {
        if (importIndex[dep] > importIndex[mustBeBefore]) {
          error(`Load order violation: ${dep} (index ${importIndex[dep]}) must load BEFORE ${mustBeBefore} (index ${importIndex[mustBeBefore]})`);
        } else {
          success(`${dep} correctly loads before ${mustBeBefore}`);
        }
      }
    }
  }
}

// ============================================================================
// 3. GLOBAL VARIABLE AVAILABILITY VALIDATION
// ============================================================================

function validateGlobalVariables() {
  section('3. GLOBAL VARIABLE VALIDATION');

  // Check that modules export to window correctly
  const globalExports = {
    'vendor-globals.js': ['$', 'jQuery', 'bootstrap', 'Swal', 'io', 'Hammer', 'PerfectScrollbar'],
    'event-delegation.js': ['EventDelegation'],
    'init-system.js': ['InitSystem'],
    'modal-manager.js': ['ModalManager'],
  };

  for (const [file, globals] of Object.entries(globalExports)) {
    const filePath = path.join(STATIC, 'js', file);
    if (!fs.existsSync(filePath)) {
      warn(`File not found for global check: ${file}`);
      continue;
    }

    const content = fs.readFileSync(filePath, 'utf8');

    for (const global of globals) {
      // Check for window.X = or window['X'] = or export
      const patterns = [
        new RegExp(`window\\.${global}\\s*=`),
        new RegExp(`window\\['${global}'\\]\\s*=`),
        new RegExp(`window\\["${global}"\\]\\s*=`),
      ];

      const hasExport = patterns.some(p => p.test(content));

      if (hasExport) {
        success(`${file} exports window.${global}`);
      } else {
        warn(`${file} may not export window.${global} - check manually`);
      }
    }
  }
}

// ============================================================================
// 4. CSS BUNDLE COMPLETENESS VALIDATION
// ============================================================================

function validateCSSBundleCompleteness() {
  section('4. CSS BUNDLE COMPLETENESS');

  const mainEntryCSSPath = path.join(STATIC, 'css/main-entry.css');
  if (!fs.existsSync(mainEntryCSSPath)) {
    error('main-entry.css not found');
    return;
  }

  const content = fs.readFileSync(mainEntryCSSPath, 'utf8');
  const imports = [];
  const importRegex = /@import\s+['"]([^'"]+)['"]/g;
  let match;

  while ((match = importRegex.exec(content)) !== null) {
    imports.push(match[1]);
  }

  info(`Found ${imports.length} CSS imports in main-entry.css`);

  let missingCount = 0;
  for (const imp of imports) {
    const cssPath = path.join(STATIC, 'css', imp);
    if (!fs.existsSync(cssPath)) {
      error(`Missing CSS file: ${imp}`);
      missingCount++;
    }
  }

  if (missingCount === 0) {
    success(`All ${imports.length} CSS files exist`);
  }

  // Check that bundle contains content from key files
  const bundlePath = path.join(VITE_DIST, 'css');
  const cssFiles = fs.readdirSync(bundlePath).filter(f => f.endsWith('.css'));

  if (cssFiles.length === 0) {
    error('No CSS files found in vite-dist/css/');
    return;
  }

  // Find the main styles bundle (largest CSS file)
  let largestFile = null;
  let largestSize = 0;

  for (const file of cssFiles) {
    const stat = fs.statSync(path.join(bundlePath, file));
    if (stat.size > largestSize) {
      largestSize = stat.size;
      largestFile = file;
    }
  }

  info(`Main CSS bundle: ${largestFile} (${(largestSize / 1024).toFixed(0)} KB)`);

  const bundleContent = fs.readFileSync(path.join(bundlePath, largestFile), 'utf8');

  // Check for critical CSS classes that should be in the bundle
  const criticalClasses = [
    '.c-stat-card',
    '.c-sidebar',
    '.c-menu',
    '.c-navbar',
    '.c-btn',
    '.c-card',
    '.c-form',
    '.c-table',
    '--color-primary',
    '--text-3xl',
    '--space-4',
  ];

  for (const cls of criticalClasses) {
    if (bundleContent.includes(cls)) {
      success(`Bundle contains: ${cls}`);
    } else {
      error(`Bundle MISSING: ${cls}`);
    }
  }
}

// ============================================================================
// 5. CSS CLASS COVERAGE (HTML vs CSS)
// ============================================================================

function validateCSSClassCoverage() {
  section('5. CSS CLASS COVERAGE (Sample Check)');

  // Read a sample template
  const dashboardPath = path.join(TEMPLATES, 'admin_panel/dashboard.html');
  if (!fs.existsSync(dashboardPath)) {
    warn('Dashboard template not found for class coverage check');
    return;
  }

  const templateContent = fs.readFileSync(dashboardPath, 'utf8');

  // Extract classes from template
  const classRegex = /class=["']([^"']+)["']/g;
  const usedClasses = new Set();
  let match;

  while ((match = classRegex.exec(templateContent)) !== null) {
    match[1].split(/\s+/).forEach(cls => {
      if (cls.startsWith('c-') || cls.startsWith('u-')) {
        usedClasses.add(cls);
      }
    });
  }

  info(`Found ${usedClasses.size} custom classes in dashboard.html`);

  // Check against CSS bundle
  const bundlePath = path.join(VITE_DIST, 'css');
  const cssFiles = fs.readdirSync(bundlePath).filter(f => f.endsWith('.css'));

  let bundleContent = '';
  for (const file of cssFiles) {
    bundleContent += fs.readFileSync(path.join(bundlePath, file), 'utf8');
  }

  let missingClasses = [];
  for (const cls of usedClasses) {
    // Check for .classname in CSS
    if (!bundleContent.includes(`.${cls}`)) {
      missingClasses.push(cls);
    }
  }

  if (missingClasses.length === 0) {
    success(`All ${usedClasses.size} custom classes found in CSS bundle`);
  } else {
    for (const cls of missingClasses) {
      warn(`Class used in template but not in CSS: .${cls}`);
    }
  }
}

// ============================================================================
// 6. BUNDLE SIZE SANITY CHECK
// ============================================================================

function validateBundleSizes() {
  section('6. BUNDLE SIZE VALIDATION');

  const expectedSizes = {
    'js': { min: 500, max: 3000, unit: 'KB' },  // JS bundle should be 500KB-3MB
    'css': { min: 100, max: 2500, unit: 'KB' }, // CSS bundle should be 100KB-2.5MB
  };

  for (const [type, expected] of Object.entries(expectedSizes)) {
    const dir = path.join(VITE_DIST, type);
    if (!fs.existsSync(dir)) {
      error(`Missing directory: ${dir}`);
      continue;
    }

    const files = fs.readdirSync(dir);
    let totalSize = 0;

    for (const file of files) {
      const stat = fs.statSync(path.join(dir, file));
      totalSize += stat.size;
    }

    const sizeKB = totalSize / 1024;

    if (sizeKB < expected.min) {
      error(`${type.toUpperCase()} bundle too small: ${sizeKB.toFixed(0)} KB (expected > ${expected.min} KB) - likely missing content`);
    } else if (sizeKB > expected.max) {
      warn(`${type.toUpperCase()} bundle very large: ${sizeKB.toFixed(0)} KB (expected < ${expected.max} KB) - consider code splitting`);
    } else {
      success(`${type.toUpperCase()} bundle size OK: ${sizeKB.toFixed(0)} KB`);
    }
  }
}

// ============================================================================
// 7. CSS SYNTAX VALIDATION
// ============================================================================

function validateCSSSyntax() {
  section('7. CSS SYNTAX VALIDATION');

  const bundlePath = path.join(VITE_DIST, 'css');
  const cssFiles = fs.readdirSync(bundlePath).filter(f => f.endsWith('.css'));

  for (const file of cssFiles) {
    const content = fs.readFileSync(path.join(bundlePath, file), 'utf8');

    // Check for common CSS issues
    const issues = [];

    // Check for unbalanced braces
    const openBraces = (content.match(/{/g) || []).length;
    const closeBraces = (content.match(/}/g) || []).length;

    if (openBraces !== closeBraces) {
      issues.push(`Unbalanced braces: ${openBraces} open, ${closeBraces} close`);
    }

    // Check for selectors without leading dot that look like class names
    // Exclude @keyframes animation names (e.g., @keyframes c-modal-spin)
    const badSelectors = content.match(/(?<![@.#\-\w])c-[a-z][a-z0-9-]*\s*{/g);
    // Filter out any that are preceded by @keyframes (check in context)
    const filteredBadSelectors = badSelectors ? badSelectors.filter(sel => {
      const idx = content.indexOf(sel);
      const before = content.slice(Math.max(0, idx - 50), idx);
      return !before.includes('@keyframes');
    }) : [];
    if (filteredBadSelectors.length > 0) {
      issues.push(`Possible missing dot in class selectors: ${filteredBadSelectors.slice(0, 3).join(', ')}...`);
    }

    // Check for @charset not at start (if present)
    const charsetMatch = content.match(/@charset/);
    if (charsetMatch && content.indexOf('@charset') > 0) {
      issues.push('@charset must be at the very beginning of CSS');
    }

    if (issues.length === 0) {
      success(`${file}: No syntax issues found`);
    } else {
      for (const issue of issues) {
        error(`${file}: ${issue}`);
      }
    }
  }
}

// ============================================================================
// 8. TEMPLATE PRODUCTION MODE CONDITIONALS
// ============================================================================

function validateTemplateConditionals() {
  section('8. TEMPLATE PRODUCTION MODE CONDITIONALS');

  // Check that key templates have proper production mode conditionals
  const baseTemplatePath = path.join(TEMPLATES, 'base.html');

  if (!fs.existsSync(baseTemplatePath)) {
    error('base.html not found');
    return;
  }

  const content = fs.readFileSync(baseTemplatePath, 'utf8');

  // Check for vite_production_mode usage
  if (content.includes('vite_production_mode')) {
    success('base.html uses vite_production_mode conditional');
  } else {
    error('base.html missing vite_production_mode conditional');
  }

  // Check for vite_asset usage
  if (content.includes('vite_asset')) {
    success('base.html uses vite_asset() helper');
  } else {
    error('base.html missing vite_asset() helper');
  }

  // Check for both JS and CSS asset loading
  if (content.includes("vite_asset('js/main-entry.js')") || content.includes('vite_asset("js/main-entry.js")')) {
    success('base.html loads JS via vite_asset');
  } else {
    error('base.html not loading JS via vite_asset');
  }

  if (content.includes("vite_asset('css/main-entry.css')") || content.includes('vite_asset("css/main-entry.css")')) {
    success('base.html loads CSS via vite_asset');
  } else {
    error('base.html not loading CSS via vite_asset');
  }
}

// ============================================================================
// MAIN
// ============================================================================

function main() {
  console.log(`\n${COLORS.cyan}╔════════════════════════════════════════════════════════════╗`);
  console.log(`║          PRODUCTION BUILD VALIDATION                        ║`);
  console.log(`╚════════════════════════════════════════════════════════════╝${COLORS.reset}`);

  const startTime = Date.now();

  validateManifest();
  validateJSDependencyOrder();
  validateGlobalVariables();
  validateCSSBundleCompleteness();
  validateCSSClassCoverage();
  validateBundleSizes();
  validateCSSSyntax();
  validateTemplateConditionals();

  const duration = Date.now() - startTime;

  section('SUMMARY');
  console.log(`\nCompleted in ${duration}ms`);
  console.log(`${COLORS.red}Errors: ${errors.length}${COLORS.reset}`);
  console.log(`${COLORS.yellow}Warnings: ${warnings.length}${COLORS.reset}`);

  if (errors.length > 0) {
    console.log(`\n${COLORS.red}╔════════════════════════════════════════════════════════════╗`);
    console.log(`║  BUILD VALIDATION FAILED - DO NOT DEPLOY                    ║`);
    console.log(`╚════════════════════════════════════════════════════════════╝${COLORS.reset}`);
    process.exit(1);
  } else if (warnings.length > 0) {
    console.log(`\n${COLORS.yellow}╔════════════════════════════════════════════════════════════╗`);
    console.log(`║  BUILD VALIDATION PASSED WITH WARNINGS                      ║`);
    console.log(`╚════════════════════════════════════════════════════════════╝${COLORS.reset}`);
    process.exit(0);
  } else {
    console.log(`\n${COLORS.green}╔════════════════════════════════════════════════════════════╗`);
    console.log(`║  BUILD VALIDATION PASSED                                    ║`);
    console.log(`╚════════════════════════════════════════════════════════════╝${COLORS.reset}`);
    process.exit(0);
  }
}

main();
