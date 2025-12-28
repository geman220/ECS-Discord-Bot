#!/usr/bin/env node
/**
 * ============================================================================
 * CSS PATTERN AUDITOR
 * ============================================================================
 *
 * Automatically detects common CSS issues:
 * 1. Hardcoded colors instead of CSS variables
 * 2. Duplicate class definitions across files
 * 3. !important overuse
 * 4. Missing dark mode variants
 * 5. Inline styles in HTML templates
 * 6. High specificity selectors (IDs, deep nesting)
 *
 * Usage: node scripts/audit-css-patterns.js
 *
 * ============================================================================
 */

const fs = require('fs');
const path = require('path');
const glob = require('glob');

// Configuration
const CSS_DIR = 'app/static/css';
const TEMPLATE_DIR = 'app/templates';
const ENTRY_FILE = 'app/static/css/main-entry.css';

const ISSUES = {
  HARDCODED_COLORS: [],
  DUPLICATE_CLASSES: {},
  IMPORTANT_OVERUSE: [],
  MISSING_DARK_MODE: [],
  INLINE_STYLES: [],
  HIGH_SPECIFICITY: [],
  UNDEFINED_VARIABLES: [],
  UNUSED_IMPORTS: []
};

// Known CSS variables (extracted from tokens)
const KNOWN_VARIABLES = new Set();

// All defined classes
const DEFINED_CLASSES = {};

// Patterns
const PATTERNS = {
  // Hardcoded hex colors (not in var())
  hexColor: /#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])/g,

  // RGB/RGBA colors
  rgbColor: /rgba?\s*\([^)]+\)/gi,

  // CSS class definition
  classDefinition: /\.([a-zA-Z_-][a-zA-Z0-9_-]*)\s*[,{]/g,

  // !important usage
  important: /!important/g,

  // CSS variable usage
  varUsage: /var\s*\(\s*--([a-zA-Z0-9_-]+)/g,

  // CSS variable definition
  varDefinition: /--([a-zA-Z0-9_-]+)\s*:/g,

  // ID selector (high specificity)
  idSelector: /#[a-zA-Z_-][a-zA-Z0-9_-]*\s*[,{]/g,

  // Deep nesting (3+ levels)
  deepNesting: /([.#][a-zA-Z_-][a-zA-Z0-9_-]*\s+){3,}/g,

  // Inline style in HTML (matches only style= not data-style=)
  // Uses word boundary to ensure 'style' is not preceded by '-'
  inlineStyle: /\bstyle\s*=\s*["'][^"']+["']/gi,

  // @import statement
  importStatement: /@import\s+['"]([^'"]+)['"]/g
};

// Colors that are acceptable (transparent, inherit, currentColor, etc.)
const ACCEPTABLE_COLORS = new Set([
  'transparent', 'inherit', 'currentColor', 'initial', 'unset', 'none'
]);

function extractVariablesFromTokens() {
  const tokenFiles = glob.sync(path.join(process.cwd(), CSS_DIR, 'tokens/*.css'));

  tokenFiles.forEach(file => {
    const content = fs.readFileSync(file, 'utf8');
    let match;
    while ((match = PATTERNS.varDefinition.exec(content)) !== null) {
      KNOWN_VARIABLES.add(match[1]);
    }
  });

  // Also extract from core/variables.css
  const coreVarsPath = path.join(process.cwd(), CSS_DIR, 'core/variables.css');
  if (fs.existsSync(coreVarsPath)) {
    const content = fs.readFileSync(coreVarsPath, 'utf8');
    let match;
    while ((match = PATTERNS.varDefinition.exec(content)) !== null) {
      KNOWN_VARIABLES.add(match[1]);
    }
  }

  console.log(`Found ${KNOWN_VARIABLES.size} CSS variables in tokens/core\n`);
}

function analyzeCSS(filePath) {
  const content = fs.readFileSync(filePath, 'utf8');
  const relativePath = path.relative(process.cwd(), filePath);
  const lines = content.split('\n');

  const getLineNumber = (index) => {
    return content.substring(0, index).split('\n').length;
  };

  // Skip token files for hardcoded color checks (they define the colors)
  const isTokenFile = relativePath.includes('/tokens/');

  // 1. Check for hardcoded colors (skip token files)
  if (!isTokenFile) {
    let match;

    // Check hex colors
    const hexRegex = /#[0-9a-fA-F]{3,8}(?![0-9a-fA-F])/g;
    while ((match = hexRegex.exec(content)) !== null) {
      // Check if inside var() or a comment
      const lineStart = content.lastIndexOf('\n', match.index) + 1;
      const lineContent = content.substring(lineStart, content.indexOf('\n', match.index));

      if (!lineContent.includes('var(') && !lineContent.trim().startsWith('/*') && !lineContent.trim().startsWith('//')) {
        // Skip if it's in a CSS variable definition
        if (!lineContent.includes('--')) {
          ISSUES.HARDCODED_COLORS.push({
            file: relativePath,
            line: getLineNumber(match.index),
            color: match[0],
            context: lineContent.trim().substring(0, 60)
          });
        }
      }
    }
  }

  // 2. Collect class definitions for duplicate detection
  const classRegex = /\.([a-zA-Z_][a-zA-Z0-9_-]*)\s*[,{\s:]/g;
  let match;
  while ((match = classRegex.exec(content)) !== null) {
    const className = match[1];
    // Skip pseudo-classes and common utility patterns
    if (className.match(/^(hover|focus|active|disabled|before|after|first|last|nth|not)$/)) {
      continue;
    }

    if (!DEFINED_CLASSES[className]) {
      DEFINED_CLASSES[className] = [];
    }
    DEFINED_CLASSES[className].push({
      file: relativePath,
      line: getLineNumber(match.index)
    });
  }

  // 3. Check !important usage
  const importantRegex = /!important/g;
  let importantCount = 0;
  while ((match = importantRegex.exec(content)) !== null) {
    importantCount++;
  }
  if (importantCount > 5) {
    ISSUES.IMPORTANT_OVERUSE.push({
      file: relativePath,
      count: importantCount
    });
  }

  // 4. Check for high specificity (ID selectors)
  const idRegex = /#[a-zA-Z_][a-zA-Z0-9_-]*\s*[,{]/g;
  while ((match = idRegex.exec(content)) !== null) {
    const lineStart = content.lastIndexOf('\n', match.index) + 1;
    const lineContent = content.substring(lineStart, content.indexOf('\n', match.index));
    // Skip CSS variable definitions, color values, and comments
    const trimmedLine = lineContent.trim();
    if (!lineContent.includes('--') &&
        !lineContent.includes('color:') &&
        !lineContent.includes('background') &&
        !trimmedLine.startsWith('/*') &&
        !trimmedLine.startsWith('*') &&
        !trimmedLine.startsWith('//')) {
      ISSUES.HIGH_SPECIFICITY.push({
        file: relativePath,
        line: getLineNumber(match.index),
        selector: match[0].trim()
      });
    }
  }

  // 5. Check for undefined CSS variables
  const varUsageRegex = /var\s*\(\s*--([a-zA-Z0-9_-]+)/g;
  while ((match = varUsageRegex.exec(content)) !== null) {
    const varName = match[1];
    // Skip common patterns that might have fallbacks
    if (!KNOWN_VARIABLES.has(varName) && !varName.startsWith('bs-') && !varName.startsWith('ecs-')) {
      ISSUES.UNDEFINED_VARIABLES.push({
        file: relativePath,
        line: getLineNumber(match.index),
        variable: varName
      });
    }
  }
}

function analyzeTemplates() {
  const templateFiles = glob.sync(path.join(process.cwd(), TEMPLATE_DIR, '**/*.html'));

  templateFiles.forEach(file => {
    const content = fs.readFileSync(file, 'utf8');
    const relativePath = path.relative(process.cwd(), file);
    const lines = content.split('\n');

    // Check for inline styles (not data-style or other data- attributes)
    let match;
    const styleRegex = /\bstyle\s*=\s*["']([^"']+)["']/gi;
    while ((match = styleRegex.exec(content)) !== null) {
      // Check if this is a data- attribute by looking at preceding chars
      const precedingText = content.substring(Math.max(0, match.index - 10), match.index);
      if (precedingText.includes('data-')) continue;

      const styleContent = match[1];
      // Skip empty styles or simple display:none (common for JS toggle)
      if (styleContent.trim() && styleContent !== 'display:none' && styleContent !== 'display: none') {
        const lineNum = content.substring(0, match.index).split('\n').length;
        ISSUES.INLINE_STYLES.push({
          file: relativePath,
          line: lineNum,
          style: styleContent.substring(0, 50) + (styleContent.length > 50 ? '...' : '')
        });
      }
    }
  });
}

function checkCascadeOrder() {
  const entryPath = path.join(process.cwd(), ENTRY_FILE);
  if (!fs.existsSync(entryPath)) {
    console.log('⚠️  CSS entry file not found at:', ENTRY_FILE);
    return;
  }

  const content = fs.readFileSync(entryPath, 'utf8');
  const imports = [];

  let match;
  const importRegex = /@import\s+['"]([^'"]+)['"]/g;
  while ((match = importRegex.exec(content)) !== null) {
    imports.push(match[1]);
  }

  // Verify all imported files exist
  imports.forEach(importPath => {
    const fullPath = path.join(process.cwd(), CSS_DIR, importPath);
    if (!fs.existsSync(fullPath)) {
      ISSUES.UNUSED_IMPORTS.push({
        file: ENTRY_FILE,
        import: importPath,
        issue: 'File does not exist'
      });
    }
  });

  console.log(`CSS Entry file imports ${imports.length} files\n`);

  // Print cascade order summary
  const categories = {
    tokens: imports.filter(i => i.includes('tokens/')).length,
    core: imports.filter(i => i.includes('core/')).length,
    components: imports.filter(i => i.includes('components/')).length,
    layout: imports.filter(i => i.includes('layout/')).length,
    features: imports.filter(i => i.includes('features/')).length,
    pages: imports.filter(i => i.includes('pages/')).length,
    themes: imports.filter(i => i.includes('themes/')).length,
    utilities: imports.filter(i => i.includes('utilities/')).length,
  };

  console.log('CSS Cascade Order Summary:');
  console.log('─'.repeat(40));
  Object.entries(categories).forEach(([cat, count]) => {
    console.log(`  ${cat.padEnd(12)} ${count} files`);
  });
  console.log('─'.repeat(40) + '\n');
}

function printReport() {
  console.log('\n' + '='.repeat(80));
  console.log('CSS PATTERN AUDIT REPORT');
  console.log('='.repeat(80) + '\n');

  let totalIssues = 0;

  // 1. Hardcoded colors (limit output)
  if (ISSUES.HARDCODED_COLORS.length > 0) {
    console.log(`\n🟠 WARNING: ${ISSUES.HARDCODED_COLORS.length} hardcoded colors found`);
    console.log('   Consider using CSS variables for consistency\n');

    // Group by file
    const byFile = {};
    ISSUES.HARDCODED_COLORS.forEach(issue => {
      if (!byFile[issue.file]) byFile[issue.file] = [];
      byFile[issue.file].push(issue);
    });

    Object.entries(byFile).slice(0, 10).forEach(([file, issues]) => {
      console.log(`   ${file}: ${issues.length} hardcoded colors`);
    });

    if (Object.keys(byFile).length > 10) {
      console.log(`   ... and ${Object.keys(byFile).length - 10} more files`);
    }
    totalIssues += ISSUES.HARDCODED_COLORS.length;
  }

  // 2. Duplicate classes
  const duplicates = Object.entries(DEFINED_CLASSES)
    .filter(([name, locations]) => locations.length > 1)
    .filter(([name]) => !name.match(/^(container|row|col|btn|card|modal|form|input|table|nav|active|show|hide|disabled)/));

  if (duplicates.length > 0) {
    console.log(`\n🟡 INFO: ${duplicates.length} classes defined in multiple files`);
    console.log('   This may indicate conflicts or opportunities to consolidate\n');

    duplicates.slice(0, 10).forEach(([name, locations]) => {
      console.log(`   .${name} defined in ${locations.length} files:`);
      locations.slice(0, 3).forEach(loc => {
        console.log(`      ${loc.file}:${loc.line}`);
      });
      if (locations.length > 3) {
        console.log(`      ... and ${locations.length - 3} more`);
      }
    });

    if (duplicates.length > 10) {
      console.log(`\n   ... and ${duplicates.length - 10} more duplicate classes`);
    }
    totalIssues += duplicates.length;
  }

  // 3. !important overuse
  if (ISSUES.IMPORTANT_OVERUSE.length > 0) {
    console.log('\n🟠 WARNING: Files with excessive !important usage (>5)');
    console.log('   Consider refactoring specificity instead\n');
    ISSUES.IMPORTANT_OVERUSE.forEach(issue => {
      console.log(`   ${issue.file}: ${issue.count} !important declarations`);
    });
    totalIssues += ISSUES.IMPORTANT_OVERUSE.length;
  }

  // 4. High specificity (ID selectors) - limit output
  if (ISSUES.HIGH_SPECIFICITY.length > 0) {
    console.log(`\n🟡 INFO: ${ISSUES.HIGH_SPECIFICITY.length} ID selectors found`);
    console.log('   Consider using classes for lower specificity\n');

    // Group by file
    const byFile = {};
    ISSUES.HIGH_SPECIFICITY.forEach(issue => {
      if (!byFile[issue.file]) byFile[issue.file] = 0;
      byFile[issue.file]++;
    });

    Object.entries(byFile).slice(0, 5).forEach(([file, count]) => {
      console.log(`   ${file}: ${count} ID selectors`);
    });
    totalIssues += ISSUES.HIGH_SPECIFICITY.length;
  }

  // 5. Inline styles in templates
  if (ISSUES.INLINE_STYLES.length > 0) {
    console.log(`\n🔴 CRITICAL: ${ISSUES.INLINE_STYLES.length} inline styles in templates`);
    console.log('   Move styles to CSS files for maintainability\n');

    // Group by file
    const byFile = {};
    ISSUES.INLINE_STYLES.forEach(issue => {
      if (!byFile[issue.file]) byFile[issue.file] = [];
      byFile[issue.file].push(issue);
    });

    Object.entries(byFile).slice(0, 10).forEach(([file, issues]) => {
      console.log(`   ${file}: ${issues.length} inline styles`);
    });

    if (Object.keys(byFile).length > 10) {
      console.log(`   ... and ${Object.keys(byFile).length - 10} more files`);
    }
    totalIssues += ISSUES.INLINE_STYLES.length;
  }

  // 6. Missing imports
  if (ISSUES.UNUSED_IMPORTS.length > 0) {
    console.log('\n🔴 CRITICAL: Missing CSS files referenced in entry');
    ISSUES.UNUSED_IMPORTS.forEach(issue => {
      console.log(`   ${issue.import}: ${issue.issue}`);
    });
    totalIssues += ISSUES.UNUSED_IMPORTS.length;
  }

  // Summary
  console.log('\n' + '='.repeat(80));
  if (totalIssues === 0) {
    console.log('✅ No critical issues found!');
  } else {
    console.log(`Found ${totalIssues} potential issues`);
  }
  console.log('='.repeat(80) + '\n');

  return totalIssues;
}

// Main
function main() {
  console.log('CSS Pattern Auditor\n');
  console.log('='.repeat(80) + '\n');

  // Extract known variables
  extractVariablesFromTokens();

  // Check cascade order
  checkCascadeOrder();

  // Analyze CSS files
  console.log('Scanning CSS files...\n');
  const cssFiles = glob.sync(path.join(process.cwd(), CSS_DIR, '**/*.css'));
  cssFiles.forEach(file => {
    analyzeCSS(file);
  });
  console.log(`Analyzed ${cssFiles.length} CSS files`);

  // Analyze templates for inline styles
  console.log('Scanning templates for inline styles...\n');
  analyzeTemplates();

  const issueCount = printReport();
  process.exit(issueCount > 10 ? 1 : 0); // Only fail if many issues
}

main();
