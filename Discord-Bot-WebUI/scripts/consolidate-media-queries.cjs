#!/usr/bin/env node
/**
 * Media Query Consolidation Script
 * Consolidates duplicate @media blocks into single blocks per breakpoint
 */

const fs = require('fs');
const path = require('path');

const CSS_DIR = path.join(__dirname, '../app/static/css');

// Files to exclude from processing
const excludeFiles = [
  'bootstrap-minimal.css',
  'tokens/',
];

// Track changes
let totalConsolidated = 0;
const changedFiles = [];

/**
 * Parse CSS and extract @media blocks with their content
 */
function parseMediaBlocks(content) {
  const result = {
    beforeMedia: '',
    mediaBlocks: {},
    afterMedia: ''
  };

  let currentPos = 0;
  let hasMedia = false;

  // Find all @media blocks
  const mediaRegex = /@media\s*([^{]+)\s*\{/g;
  let match;
  let lastMediaEnd = 0;

  // First, collect all @media positions
  const mediaMatches = [];
  while ((match = mediaRegex.exec(content)) !== null) {
    hasMedia = true;
    const startPos = match.index;
    const query = match[1].trim();
    const braceStart = match.index + match[0].length - 1;

    // Find matching closing brace
    let braceCount = 1;
    let pos = braceStart + 1;
    while (braceCount > 0 && pos < content.length) {
      if (content[pos] === '{') braceCount++;
      if (content[pos] === '}') braceCount--;
      pos++;
    }
    const endPos = pos;

    // Extract content inside @media
    const innerContent = content.substring(braceStart + 1, endPos - 1).trim();

    mediaMatches.push({
      query,
      startPos,
      endPos,
      innerContent
    });
  }

  if (!hasMedia) {
    return null; // No @media blocks
  }

  // Get content before first @media
  if (mediaMatches.length > 0) {
    result.beforeMedia = content.substring(0, mediaMatches[0].startPos);
  }

  // Group by query
  for (const m of mediaMatches) {
    const key = m.query;
    if (!result.mediaBlocks[key]) {
      result.mediaBlocks[key] = [];
    }
    result.mediaBlocks[key].push(m.innerContent);
  }

  // Check if consolidation needed
  let needsConsolidation = false;
  for (const key of Object.keys(result.mediaBlocks)) {
    if (result.mediaBlocks[key].length > 1) {
      needsConsolidation = true;
      break;
    }
  }

  if (!needsConsolidation) {
    return null;
  }

  return result;
}

/**
 * Reconstruct CSS with consolidated @media blocks
 */
function reconstructCSS(parsed) {
  let output = parsed.beforeMedia.trimEnd() + '\n\n';

  // Standard order for @media queries
  const queryOrder = [
    // Width breakpoints (mobile-first order)
    '(min-width: 576px)',
    '(min-width: 768px)',
    '(min-width: 992px)',
    '(min-width: 1200px)',
    '(min-width: 1400px)',
    // Width breakpoints (desktop-first order)
    '(max-width: 1399.98px)',
    '(max-width: 1199.98px)',
    '(max-width: 991.98px)',
    '(max-width: 767.98px)',
    '(max-width: 575.98px)',
    // Orientation
    '(orientation: portrait)',
    '(orientation: landscape)',
    // Preferences
    '(prefers-color-scheme: dark)',
    '(prefers-color-scheme: light)',
    '(prefers-reduced-motion: reduce)',
    '(prefers-contrast: more)',
    // Print
    'print',
  ];

  // Sort queries
  const sortedQueries = Object.keys(parsed.mediaBlocks).sort((a, b) => {
    const indexA = queryOrder.findIndex(q => a.includes(q));
    const indexB = queryOrder.findIndex(q => b.includes(q));
    if (indexA === -1 && indexB === -1) return a.localeCompare(b);
    if (indexA === -1) return 1;
    if (indexB === -1) return -1;
    return indexA - indexB;
  });

  for (const query of sortedQueries) {
    const contents = parsed.mediaBlocks[query];
    output += `/* ═══════════════════════════════════════════════════════════════════════════\n`;
    output += ` * @media ${query}\n`;
    output += ` * ═══════════════════════════════════════════════════════════════════════════ */\n`;
    output += `@media ${query} {\n`;

    // Combine all content, removing duplicate selectors
    const combinedContent = contents
      .map(c => c.trim())
      .filter(c => c.length > 0)
      .join('\n\n  ');

    if (combinedContent) {
      output += '  ' + combinedContent.split('\n').join('\n  ') + '\n';
    }

    output += '}\n\n';
  }

  return output.trimEnd() + '\n';
}

function processFile(filePath) {
  const relativePath = path.relative(CSS_DIR, filePath);

  // Skip excluded files
  if (excludeFiles.some(ex => relativePath.includes(ex))) {
    return;
  }

  let content = fs.readFileSync(filePath, 'utf8');

  const parsed = parseMediaBlocks(content);
  if (!parsed) {
    return; // No consolidation needed
  }

  // Count how many duplicates we're consolidating
  let duplicateCount = 0;
  for (const key of Object.keys(parsed.mediaBlocks)) {
    if (parsed.mediaBlocks[key].length > 1) {
      duplicateCount += parsed.mediaBlocks[key].length - 1;
    }
  }

  const newContent = reconstructCSS(parsed);
  fs.writeFileSync(filePath, newContent);

  changedFiles.push({ file: relativePath, consolidated: duplicateCount });
  totalConsolidated += duplicateCount;
}

function walkDir(dir) {
  const files = fs.readdirSync(dir);
  for (const file of files) {
    const fullPath = path.join(dir, file);
    const stat = fs.statSync(fullPath);

    if (stat.isDirectory()) {
      walkDir(fullPath);
    } else if (file.endsWith('.css')) {
      processFile(fullPath);
    }
  }
}

console.log('================================================================================');
console.log('MEDIA QUERY CONSOLIDATION - Combining duplicate @media blocks');
console.log('================================================================================\n');

walkDir(CSS_DIR);

console.log(`\nFiles modified: ${changedFiles.length}`);
console.log(`Total @media blocks consolidated: ${totalConsolidated}\n`);

if (changedFiles.length > 0) {
  console.log('Changed files:');
  changedFiles.sort((a, b) => b.consolidated - a.consolidated);
  changedFiles.forEach(({ file, consolidated }) => {
    console.log(`  ${file}: ${consolidated} blocks consolidated`);
  });
}

console.log('\n================================================================================');
console.log('Consolidation complete. Run build to verify.');
console.log('================================================================================');
