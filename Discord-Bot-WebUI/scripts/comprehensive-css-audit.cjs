#!/usr/bin/env node
/**
 * Comprehensive CSS Audit Script
 * Identifies all technical debt before visual testing
 */

const fs = require('fs');
const path = require('path');

const CSS_DIR = path.join(__dirname, '../app/static/css');
const MAIN_ENTRY = path.join(CSS_DIR, 'main-entry.css');

const issues = {
  missingImports: [],
  duplicateSelectors: {},
  hardcodedColors: [],
  inconsistentVariables: [],
  zIndexWithoutVars: [],
  btnSmConflicts: [],
  emptyStateConflicts: [],
  duplicateMediaBlocks: []
};

// 1. Check for missing imports
function checkMissingImports() {
  const content = fs.readFileSync(MAIN_ENTRY, 'utf8');
  const imports = content.match(/@import\s+['"]([^'"]+)['"]/g) || [];

  imports.forEach(imp => {
    const filePath = imp.match(/@import\s+['"]\.\/([^'"]+)['"]/);
    if (filePath) {
      const fullPath = path.join(CSS_DIR, filePath[1]);
      if (!fs.existsSync(fullPath)) {
        issues.missingImports.push(filePath[1]);
      }
    }
  });
}

// 2. Find duplicate base selector definitions
function findDuplicateSelectors() {
  const targetSelectors = [
    '.empty-state',
    '.btn-sm',
    '.card-header',
    '.modal-header',
    '.form-control',
    '.nav-link',
    '.badge',
    '.alert',
    '.table',
    '.dropdown-item'
  ];

  function scanDir(dir) {
    const files = fs.readdirSync(dir);
    files.forEach(file => {
      const fullPath = path.join(dir, file);
      const stat = fs.statSync(fullPath);

      if (stat.isDirectory()) {
        scanDir(fullPath);
      } else if (file.endsWith('.css')) {
        const content = fs.readFileSync(fullPath, 'utf8');
        const relativePath = path.relative(CSS_DIR, fullPath);

        targetSelectors.forEach(selector => {
          // Match selector at start of line or after comma/newline (base definition)
          const regex = new RegExp(`^${selector.replace('.', '\\.')}\\s*\\{`, 'gm');
          const matches = content.match(regex);
          if (matches && matches.length > 0) {
            if (!issues.duplicateSelectors[selector]) {
              issues.duplicateSelectors[selector] = [];
            }
            issues.duplicateSelectors[selector].push(relativePath);
          }
        });
      }
    });
  }

  scanDir(CSS_DIR);
}

// 3. Find hardcoded hex colors (not in variables)
function findHardcodedColors() {
  const excludePatterns = ['tokens/colors.css', 'bootstrap-minimal.css'];

  function scanDir(dir) {
    const files = fs.readdirSync(dir);
    files.forEach(file => {
      const fullPath = path.join(dir, file);
      const stat = fs.statSync(fullPath);

      if (stat.isDirectory()) {
        scanDir(fullPath);
      } else if (file.endsWith('.css')) {
        const relativePath = path.relative(CSS_DIR, fullPath);
        if (excludePatterns.some(p => relativePath.includes(p))) return;

        const content = fs.readFileSync(fullPath, 'utf8');
        const lines = content.split('\n');

        lines.forEach((line, idx) => {
          // Skip comments, SVG data URIs, var() functions
          if (line.trim().startsWith('/*') || line.trim().startsWith('*')) return;
          if (line.includes('url(') || line.includes('data:')) return;
          if (line.includes('var(--')) return;

          const hexMatch = line.match(/#[0-9a-fA-F]{3,6}\b/g);
          if (hexMatch) {
            issues.hardcodedColors.push({
              file: relativePath,
              line: idx + 1,
              colors: hexMatch
            });
          }
        });
      }
    });
  }

  scanDir(CSS_DIR);
}

// 4. Check .btn-sm definitions across files
function checkBtnSmConflicts() {
  function scanDir(dir) {
    const files = fs.readdirSync(dir);
    files.forEach(file => {
      const fullPath = path.join(dir, file);
      const stat = fs.statSync(fullPath);

      if (stat.isDirectory()) {
        scanDir(fullPath);
      } else if (file.endsWith('.css')) {
        const content = fs.readFileSync(fullPath, 'utf8');
        const relativePath = path.relative(CSS_DIR, fullPath);

        // Find all .btn-sm rules with their properties
        const regex = /\.btn-sm\s*\{([^}]+)\}/g;
        let match;
        while ((match = regex.exec(content)) !== null) {
          const properties = match[1];
          if (properties.includes('min-height') || properties.includes('font-size') || properties.includes('padding')) {
            issues.btnSmConflicts.push({
              file: relativePath,
              properties: properties.trim().split('\n').map(p => p.trim()).filter(p => p)
            });
          }
        }
      }
    });
  }

  scanDir(CSS_DIR);
}

// 5. Count files with multiple @media blocks at same breakpoint
function countDuplicateMediaBlocks() {
  function scanDir(dir) {
    const files = fs.readdirSync(dir);
    files.forEach(file => {
      const fullPath = path.join(dir, file);
      const stat = fs.statSync(fullPath);

      if (stat.isDirectory()) {
        scanDir(fullPath);
      } else if (file.endsWith('.css')) {
        const content = fs.readFileSync(fullPath, 'utf8');
        const relativePath = path.relative(CSS_DIR, fullPath);

        const matches767 = (content.match(/@media.*max-width.*767/g) || []).length;
        const matches991 = (content.match(/@media.*max-width.*991/g) || []).length;
        const matches575 = (content.match(/@media.*max-width.*575/g) || []).length;

        if (matches767 > 1 || matches991 > 1 || matches575 > 1) {
          issues.duplicateMediaBlocks.push({
            file: relativePath,
            '767px': matches767,
            '991px': matches991,
            '575px': matches575
          });
        }
      }
    });
  }

  scanDir(CSS_DIR);
}

// Run all checks
console.log('================================================================================');
console.log('COMPREHENSIVE CSS AUDIT');
console.log('================================================================================\n');

checkMissingImports();
findDuplicateSelectors();
findHardcodedColors();
checkBtnSmConflicts();
countDuplicateMediaBlocks();

// Report
console.log('1. MISSING IMPORTS');
console.log('─'.repeat(60));
if (issues.missingImports.length === 0) {
  console.log('✅ All imports valid\n');
} else {
  issues.missingImports.forEach(f => console.log(`   ❌ ${f}`));
  console.log();
}

console.log('2. DUPLICATE SELECTOR DEFINITIONS (potential conflicts)');
console.log('─'.repeat(60));
Object.keys(issues.duplicateSelectors).forEach(selector => {
  const files = issues.duplicateSelectors[selector];
  if (files.length > 1) {
    console.log(`\n⚠️  ${selector} defined in ${files.length} files:`);
    files.forEach(f => console.log(`   - ${f}`));
  }
});
console.log();

console.log('3. HARDCODED COLORS (should use CSS variables)');
console.log('─'.repeat(60));
console.log(`   Total instances: ${issues.hardcodedColors.length}`);
// Group by file
const colorsByFile = {};
issues.hardcodedColors.forEach(c => {
  if (!colorsByFile[c.file]) colorsByFile[c.file] = 0;
  colorsByFile[c.file]++;
});
const topFiles = Object.entries(colorsByFile).sort((a, b) => b[1] - a[1]).slice(0, 15);
console.log('   Top files with hardcoded colors:');
topFiles.forEach(([file, count]) => console.log(`   - ${file}: ${count}`));
console.log();

console.log('4. .btn-sm DEFINITIONS (check for conflicts)');
console.log('─'.repeat(60));
console.log(`   Found in ${issues.btnSmConflicts.length} locations`);
issues.btnSmConflicts.forEach(c => console.log(`   - ${c.file}`));
console.log();

console.log('5. FILES WITH MULTIPLE MEDIA BLOCKS (same breakpoint)');
console.log('─'.repeat(60));
issues.duplicateMediaBlocks.sort((a, b) => {
  const totalA = a['767px'] + a['991px'] + a['575px'];
  const totalB = b['767px'] + b['991px'] + b['575px'];
  return totalB - totalA;
}).slice(0, 15).forEach(f => {
  console.log(`   ${f.file}: 767px(${f['767px']}) 991px(${f['991px']}) 575px(${f['575px']})`);
});
console.log();

// Summary
console.log('================================================================================');
console.log('SUMMARY');
console.log('================================================================================');
const duplicateSelectorCount = Object.values(issues.duplicateSelectors).filter(v => v.length > 1).length;
console.log(`Missing imports: ${issues.missingImports.length}`);
console.log(`Selectors defined in multiple files: ${duplicateSelectorCount}`);
console.log(`Hardcoded color instances: ${issues.hardcodedColors.length}`);
console.log(`Files with .btn-sm: ${issues.btnSmConflicts.length}`);
console.log(`Files with duplicate media blocks: ${issues.duplicateMediaBlocks.length}`);
