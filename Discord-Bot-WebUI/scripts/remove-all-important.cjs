/**
 * Aggressively remove all !important declarations
 * EXCEPT those with JUSTIFIED comment or in vendor files
 */
const fs = require('fs');
const glob = require('glob');

console.log('================================================================================');
console.log('AGGRESSIVE !important REMOVAL');
console.log('================================================================================\n');

// Files to completely skip
const skipFiles = [
  'bootstrap-minimal.css',
  'sweetalert-modern.css',
  'utilities/mobile-utils.css',
  'mobile/utilities.css',
];

let totalRemoved = 0;
let filesModified = 0;

const cssFiles = glob.sync('app/static/css/**/*.css');

cssFiles.forEach(file => {
  // Skip vendor/utility files
  if (skipFiles.some(skip => file.includes(skip))) {
    return;
  }

  let content = fs.readFileSync(file, 'utf8');
  const originalContent = content;

  // Count !important before
  const beforeCount = (content.match(/!important/g) || []).length;

  // Remove all !important EXCEPT lines with JUSTIFIED
  const lines = content.split('\n');
  const newLines = lines.map(line => {
    if (line.includes('!important') && !line.includes('JUSTIFIED')) {
      return line.replace(/\s*!important/g, '');
    }
    return line;
  });

  content = newLines.join('\n');

  // Count !important after
  const afterCount = (content.match(/!important/g) || []).length;
  const removed = beforeCount - afterCount;

  if (removed > 0) {
    fs.writeFileSync(file, content);
    console.log(`  ${file}: removed ${removed} !important`);
    totalRemoved += removed;
    filesModified++;
  }
});

console.log(`\n================================================================================`);
console.log(`SUMMARY: Removed ${totalRemoved} !important from ${filesModified} files`);
console.log(`================================================================================`);
