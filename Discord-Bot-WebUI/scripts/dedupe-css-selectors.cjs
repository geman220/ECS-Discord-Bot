/**
 * Deduplicate CSS selectors within same file
 * Merges duplicate selector blocks into one
 */
const fs = require('fs');
const glob = require('glob');
const css = require('css');

console.log('================================================================================');
console.log('CSS SELECTOR DEDUPLICATION');
console.log('================================================================================\n');

let totalMerged = 0;
let filesFixed = 0;

const cssFiles = glob.sync('app/static/css/**/*.css');

// Skip files that are likely to have intentional duplicates
const skipPatterns = [
  'bootstrap',
  'vendor',
  'sweetalert',
];

cssFiles.forEach(file => {
  if (skipPatterns.some(p => file.includes(p))) return;

  try {
    const content = fs.readFileSync(file, 'utf8');

    // Parse CSS
    let parsed;
    try {
      parsed = css.parse(content, { silent: true });
    } catch (e) {
      // Skip unparseable files
      return;
    }

    if (!parsed || !parsed.stylesheet || !parsed.stylesheet.rules) return;

    const rules = parsed.stylesheet.rules;
    const selectorMap = new Map();
    const rulesToRemove = [];
    let mergeCount = 0;

    // Find duplicates (only for regular rules, not media queries)
    rules.forEach((rule, idx) => {
      if (rule.type !== 'rule') return;
      if (!rule.selectors) return;

      const selectorKey = rule.selectors.sort().join(',');

      if (selectorMap.has(selectorKey)) {
        // Merge declarations into existing rule
        const existingIdx = selectorMap.get(selectorKey);
        const existingRule = rules[existingIdx];

        if (existingRule && existingRule.declarations && rule.declarations) {
          // Add new declarations (avoiding exact duplicates)
          const existingDecls = new Set(
            existingRule.declarations
              .filter(d => d.type === 'declaration')
              .map(d => `${d.property}:${d.value}`)
          );

          rule.declarations.forEach(decl => {
            if (decl.type === 'declaration') {
              const key = `${decl.property}:${decl.value}`;
              if (!existingDecls.has(key)) {
                existingRule.declarations.push(decl);
                existingDecls.add(key);
              }
            }
          });

          rulesToRemove.push(idx);
          mergeCount++;
        }
      } else {
        selectorMap.set(selectorKey, idx);
      }
    });

    if (mergeCount > 0) {
      // Remove merged rules (in reverse order to preserve indices)
      rulesToRemove.sort((a, b) => b - a).forEach(idx => {
        rules.splice(idx, 1);
      });

      // Stringify and write back
      const output = css.stringify(parsed, { compress: false });
      fs.writeFileSync(file, output);

      console.log(`  ${file}: merged ${mergeCount} duplicate selectors`);
      totalMerged += mergeCount;
      filesFixed++;
    }
  } catch (err) {
    // Skip files with parse errors
    if (!err.message.includes('Cannot read')) {
      console.log(`  Skipped ${file}: ${err.message}`);
    }
  }
});

console.log(`\n================================================================================`);
console.log(`SUMMARY: Merged ${totalMerged} duplicate selectors in ${filesFixed} files`);
console.log(`================================================================================`);
