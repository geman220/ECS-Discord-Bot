/**
 * Audit for orphaned CSS and JS files
 */
const fs = require('fs');
const path = require('path');
const glob = require('glob');

console.log('=== ORPHAN AUDIT ===\n');

// Read main-entry.css
const mainEntryCss = fs.readFileSync('app/static/css/main-entry.css', 'utf8');
const mobileIndexCss = fs.readFileSync('app/static/css/mobile/index.css', 'utf8');

// Get all CSS files
const allCssFiles = glob.sync('app/static/css/**/*.css');
const orphanedCss = [];

allCssFiles.forEach(file => {
  const basename = path.basename(file);
  if (basename === 'main-entry.css') return;

  // Check if imported in main-entry.css or mobile/index.css
  if (!mainEntryCss.includes(basename) && !mobileIndexCss.includes(basename)) {
    // Check if imported by any other CSS file
    let importedElsewhere = false;
    allCssFiles.forEach(otherFile => {
      if (otherFile !== file) {
        const content = fs.readFileSync(otherFile, 'utf8');
        if (content.includes(basename)) {
          importedElsewhere = true;
        }
      }
    });

    if (!importedElsewhere) {
      const lines = fs.readFileSync(file, 'utf8').split('\n').length;
      orphanedCss.push({ file, lines });
    }
  }
});

console.log('ORPHANED CSS FILES:');
if (orphanedCss.length === 0) {
  console.log('  None found! ✓');
} else {
  orphanedCss.forEach(f => console.log(`  ${f.file} (${f.lines} lines)`));
}

// Read main-entry.js
const mainEntryJs = fs.readFileSync('app/static/js/main-entry.js', 'utf8');

// Get all template content for JS file checks
const templateFiles = glob.sync('app/templates/**/*.html');
const allTemplateContent = templateFiles.map(f => fs.readFileSync(f, 'utf8')).join('\n');

// Get all JS files in js/ directory
const jsFiles = glob.sync('app/static/js/*.js');
const orphanedJs = [];

jsFiles.forEach(file => {
  const basename = path.basename(file);
  if (basename === 'main-entry.js') return;
  if (basename === 'service-worker.js') return; // Special case - registered differently

  // Check if in main-entry.js OR loaded by any template
  if (!mainEntryJs.includes(basename) && !allTemplateContent.includes(basename)) {
    const lines = fs.readFileSync(file, 'utf8').split('\n').length;
    orphanedJs.push({ file, lines });
  }
});

console.log('\nORPHANED JS FILES (in js/):');
if (orphanedJs.length === 0) {
  console.log('  None found! ✓');
} else {
  orphanedJs.forEach(f => console.log(`  ${f.file} (${f.lines} lines)`));
}

// Check custom_js files not in main-entry and not loaded by templates
const customJsFiles = glob.sync('app/static/custom_js/*.js');
// Note: templateFiles and allTemplateContent already loaded above

const unusedCustomJs = [];
customJsFiles.forEach(file => {
  const basename = path.basename(file);
  if (!mainEntryJs.includes(basename) && !allTemplateContent.includes(basename)) {
    const lines = fs.readFileSync(file, 'utf8').split('\n').length;
    unusedCustomJs.push({ file, lines });
  }
});

console.log('\nUNUSED CUSTOM_JS FILES:');
if (unusedCustomJs.length === 0) {
  console.log('  None found! ✓');
} else {
  unusedCustomJs.forEach(f => console.log(`  ${f.file} (${f.lines} lines)`));
}

// Summary
const totalOrphaned = orphanedCss.length + orphanedJs.length + unusedCustomJs.length;
console.log(`\n=== SUMMARY ===`);
console.log(`Orphaned CSS: ${orphanedCss.length}`);
console.log(`Orphaned JS: ${orphanedJs.length}`);
console.log(`Unused custom_js: ${unusedCustomJs.length}`);
console.log(`Total: ${totalOrphaned}`);
