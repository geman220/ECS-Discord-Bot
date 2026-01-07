/**
 * Migrate Bootstrap classes to BEM in templates
 *
 * Conversions:
 * - btn btn-primary → c-btn c-btn--primary
 * - btn btn-secondary → c-btn c-btn--secondary
 * - card → c-card (already mostly done)
 * - table → c-table (already mostly done)
 */
const fs = require('fs');
const path = require('path');
const glob = require('glob');

// Button class mappings
const btnMappings = [
  // Full button with variant
  { from: /class="([^"]*)\bbtn btn-primary\b([^"]*)"/g, to: 'class="$1c-btn c-btn--primary$2"' },
  { from: /class="([^"]*)\bbtn btn-secondary\b([^"]*)"/g, to: 'class="$1c-btn c-btn--secondary$2"' },
  { from: /class="([^"]*)\bbtn btn-success\b([^"]*)"/g, to: 'class="$1c-btn c-btn--success$2"' },
  { from: /class="([^"]*)\bbtn btn-danger\b([^"]*)"/g, to: 'class="$1c-btn c-btn--danger$2"' },
  { from: /class="([^"]*)\bbtn btn-warning\b([^"]*)"/g, to: 'class="$1c-btn c-btn--warning$2"' },
  { from: /class="([^"]*)\bbtn btn-info\b([^"]*)"/g, to: 'class="$1c-btn c-btn--info$2"' },
  { from: /class="([^"]*)\bbtn btn-light\b([^"]*)"/g, to: 'class="$1c-btn c-btn--light$2"' },
  { from: /class="([^"]*)\bbtn btn-dark\b([^"]*)"/g, to: 'class="$1c-btn c-btn--dark$2"' },
  { from: /class="([^"]*)\bbtn btn-link\b([^"]*)"/g, to: 'class="$1c-btn c-btn--link$2"' },

  // Outline variants
  { from: /class="([^"]*)\bbtn btn-outline-primary\b([^"]*)"/g, to: 'class="$1c-btn c-btn--outline-primary$2"' },
  { from: /class="([^"]*)\bbtn btn-outline-secondary\b([^"]*)"/g, to: 'class="$1c-btn c-btn--outline-secondary$2"' },
  { from: /class="([^"]*)\bbtn btn-outline-success\b([^"]*)"/g, to: 'class="$1c-btn c-btn--outline-success$2"' },
  { from: /class="([^"]*)\bbtn btn-outline-danger\b([^"]*)"/g, to: 'class="$1c-btn c-btn--outline-danger$2"' },
  { from: /class="([^"]*)\bbtn btn-outline-warning\b([^"]*)"/g, to: 'class="$1c-btn c-btn--outline-warning$2"' },
  { from: /class="([^"]*)\bbtn btn-outline-info\b([^"]*)"/g, to: 'class="$1c-btn c-btn--outline-info$2"' },

  // Size modifiers (as additions to existing c-btn)
  { from: /class="([^"]*)\bc-btn([^"]*)\s+btn-sm\b([^"]*)"/g, to: 'class="$1c-btn$2 c-btn--sm$3"' },
  { from: /class="([^"]*)\bc-btn([^"]*)\s+btn-lg\b([^"]*)"/g, to: 'class="$1c-btn$2 c-btn--lg$3"' },

  // Standalone size (when btn-sm is used with btn-*)
  { from: /\bbtn-sm\b/g, to: 'c-btn--sm' },
  { from: /\bbtn-lg\b/g, to: 'c-btn--lg' },
];

// Card mappings (basic)
const cardMappings = [
  { from: /class="([^"]*)\bcard\b(?!-|__)([^"]*)"/g, to: 'class="$1c-card$2"' },
  { from: /class="([^"]*)\bcard-header\b([^"]*)"/g, to: 'class="$1c-card__header$2"' },
  { from: /class="([^"]*)\bcard-body\b([^"]*)"/g, to: 'class="$1c-card__body$2"' },
  { from: /class="([^"]*)\bcard-footer\b([^"]*)"/g, to: 'class="$1c-card__footer$2"' },
  { from: /class="([^"]*)\bcard-title\b([^"]*)"/g, to: 'class="$1c-card__title$2"' },
];

// Table mappings
const tableMappings = [
  { from: /class="([^"]*)\btable\b(?!-|__)([^"]*)"/g, to: 'class="$1c-table$2"' },
  { from: /class="([^"]*)\btable-responsive\b([^"]*)"/g, to: 'class="$1c-table-wrapper$2"' },
  { from: /class="([^"]*)\btable-striped\b([^"]*)"/g, to: 'class="$1c-table--striped$2"' },
  { from: /class="([^"]*)\btable-hover\b([^"]*)"/g, to: 'class="$1c-table--hoverable$2"' },
];

const allMappings = [...btnMappings, ...cardMappings, ...tableMappings];

// Process templates
const templateFiles = glob.sync('app/templates/**/*.html');

let totalReplacements = 0;
let filesModified = 0;

templateFiles.forEach(file => {
  let content = fs.readFileSync(file, 'utf8');
  let originalContent = content;
  let fileReplacements = 0;

  allMappings.forEach(mapping => {
    const matches = content.match(mapping.from);
    if (matches) {
      fileReplacements += matches.length;
      content = content.replace(mapping.from, mapping.to);
    }
  });

  if (content !== originalContent) {
    fs.writeFileSync(file, content);
    console.log(`${path.relative('app/templates', file)}: ${fileReplacements} replacements`);
    totalReplacements += fileReplacements;
    filesModified++;
  }
});

console.log(`\nTotal: ${totalReplacements} replacements in ${filesModified} files`);
