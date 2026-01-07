/**
 * Remove unnecessary !important declarations
 * Skip third-party overrides (sweetalert, bootstrap)
 */
const fs = require('fs');
const path = require('path');
const glob = require('glob');

// Files to skip (third-party overrides need !important)
const skipFiles = [
  'sweetalert-modern.css',  // SweetAlert2 overrides
  'bootstrap-theming.css',   // Bootstrap overrides
];

// Properties that commonly don't need !important with CSS Layers
const safeToRemove = [
  'color',
  'background',
  'background-color',
  'border',
  'border-color',
  'border-radius',
  'padding',
  'margin',
  'font-size',
  'font-weight',
  'display',
  'flex',
  'gap',
  'width',
  'height',
  'min-height',
  'max-width',
  'opacity',
  'transform',
  'transition',
  'box-shadow',
  'text-decoration',
  'cursor',
  'overflow',
  'position',
  'top',
  'left',
  'right',
  'bottom',
  'z-index',
  'visibility',
  'align-items',
  'justify-content',
  'flex-direction',
  'text-align',
  'line-height',
  'letter-spacing',
  'white-space',
  'pointer-events',
];

const cssFiles = glob.sync('app/static/css/components/*.css');

let totalRemoved = 0;
let filesModified = 0;

cssFiles.forEach(file => {
  const basename = path.basename(file);

  // Skip third-party override files
  if (skipFiles.includes(basename)) {
    console.log(`Skipping ${basename} (third-party overrides)`);
    return;
  }

  let content = fs.readFileSync(file, 'utf8');
  let originalContent = content;
  let fileRemoved = 0;

  // Remove !important from safe properties
  safeToRemove.forEach(prop => {
    // Match property: value !important
    const regex = new RegExp(`(${prop}\\s*:\\s*[^;]+)\\s*!important`, 'gi');
    const matches = content.match(regex);
    if (matches) {
      fileRemoved += matches.length;
      content = content.replace(regex, '$1');
    }
  });

  if (content !== originalContent) {
    fs.writeFileSync(file, content);
    console.log(`${basename}: ${fileRemoved} !important removed`);
    totalRemoved += fileRemoved;
    filesModified++;
  }
});

console.log(`\nTotal: ${totalRemoved} !important removed from ${filesModified} files`);
