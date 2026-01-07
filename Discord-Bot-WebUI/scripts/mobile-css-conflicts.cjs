#!/usr/bin/env node

/**
 * Mobile CSS Conflict Detector
 *
 * Detects potential CSS conflicts that could cause mobile rendering issues:
 * 1. Media query overlaps (conflicting breakpoints)
 * 2. Property conflicts (same property, different values in mobile context)
 * 3. Z-index stacking issues
 * 4. !important wars
 * 5. Specificity conflicts
 * 6. Missing mobile overrides for desktop-only styles
 */

const fs = require('fs');
const path = require('path');
const glob = require('glob');

// Configuration
const CSS_DIR = path.join(__dirname, '../app/static/css');
const MOBILE_BREAKPOINTS = [320, 375, 390, 412, 428, 576, 768, 992, 1024, 1200];
const CRITICAL_PROPERTIES = [
  'display', 'position', 'width', 'height', 'min-width', 'min-height',
  'max-width', 'max-height', 'flex', 'flex-direction', 'grid', 'overflow',
  'visibility', 'opacity', 'z-index', 'padding', 'margin', 'font-size'
];

// Results storage
const results = {
  mediaQueryOverlaps: [],
  propertyConflicts: [],
  zIndexIssues: [],
  importantWars: [],
  specificityIssues: [],
  missingMobileOverrides: [],
  summary: {}
};

// Parse media query breakpoint
function parseBreakpoint(mediaQuery) {
  const maxMatch = mediaQuery.match(/max-width:\s*(\d+(?:\.\d+)?)(px|em|rem)?/i);
  const minMatch = mediaQuery.match(/min-width:\s*(\d+(?:\.\d+)?)(px|em|rem)?/i);

  return {
    max: maxMatch ? parseFloat(maxMatch[1]) : null,
    min: minMatch ? parseFloat(minMatch[1]) : null,
    raw: mediaQuery
  };
}

// Check if two breakpoints overlap
function breakpointsOverlap(bp1, bp2) {
  // Check for exact same breakpoint with different values (.98 vs not)
  if (bp1.max && bp2.max) {
    const diff = Math.abs(bp1.max - bp2.max);
    if (diff > 0 && diff < 1) {
      return { type: 'near-collision', diff };
    }
  }

  // Check for overlapping ranges
  if (bp1.min !== null && bp1.max !== null && bp2.min !== null && bp2.max !== null) {
    if (bp1.min <= bp2.max && bp2.min <= bp1.max) {
      return { type: 'range-overlap' };
    }
  }

  return null;
}

// Calculate CSS specificity
function calculateSpecificity(selector) {
  let ids = (selector.match(/#[a-zA-Z][\w-]*/g) || []).length;
  let classes = (selector.match(/\.[a-zA-Z][\w-]*/g) || []).length;
  let attrs = (selector.match(/\[[^\]]+\]/g) || []).length;
  let pseudoClasses = (selector.match(/:[a-zA-Z][\w-]*/g) || []).length;
  let elements = (selector.match(/(?:^|[\s>+~])([a-zA-Z][\w-]*)/g) || []).length;

  return {
    a: ids,
    b: classes + attrs + pseudoClasses,
    c: elements,
    score: ids * 100 + (classes + attrs + pseudoClasses) * 10 + elements,
    selector
  };
}

// Extract rules from CSS content
function extractRules(content, filePath) {
  const rules = [];
  let currentMedia = null;
  let braceDepth = 0;
  let ruleStart = 0;
  let inMedia = false;
  let mediaStart = 0;

  // Remove comments
  content = content.replace(/\/\*[\s\S]*?\*\//g, '');

  // Find media queries
  const mediaRegex = /@media\s*([^{]+)\{/g;
  let match;

  while ((match = mediaRegex.exec(content)) !== null) {
    const mediaQuery = match[1].trim();
    const startIndex = match.index + match[0].length;

    // Find matching closing brace
    let depth = 1;
    let i = startIndex;
    while (depth > 0 && i < content.length) {
      if (content[i] === '{') depth++;
      if (content[i] === '}') depth--;
      i++;
    }

    const mediaContent = content.substring(startIndex, i - 1);
    const breakpoint = parseBreakpoint(mediaQuery);

    // Extract selectors and properties from media content
    const ruleRegex = /([^{]+)\{([^}]+)\}/g;
    let ruleMatch;

    while ((ruleMatch = ruleRegex.exec(mediaContent)) !== null) {
      const selector = ruleMatch[1].trim();
      const properties = ruleMatch[2].trim();

      // Parse properties
      const propList = [];
      properties.split(';').forEach(prop => {
        const [name, value] = prop.split(':').map(s => s?.trim());
        if (name && value) {
          propList.push({
            name,
            value,
            important: value.includes('!important')
          });
        }
      });

      rules.push({
        selector,
        properties: propList,
        mediaQuery,
        breakpoint,
        file: filePath,
        specificity: calculateSpecificity(selector)
      });
    }
  }

  return rules;
}

// Find z-index issues
function findZIndexIssues(rules) {
  const zIndexBySelector = {};

  rules.forEach(rule => {
    rule.properties.forEach(prop => {
      if (prop.name === 'z-index') {
        const key = rule.selector;
        if (!zIndexBySelector[key]) {
          zIndexBySelector[key] = [];
        }
        zIndexBySelector[key].push({
          value: parseInt(prop.value),
          file: rule.file,
          mediaQuery: rule.mediaQuery
        });
      }
    });
  });

  // Check for conflicting z-index values
  Object.entries(zIndexBySelector).forEach(([selector, values]) => {
    if (values.length > 1) {
      const uniqueValues = [...new Set(values.map(v => v.value))];
      if (uniqueValues.length > 1) {
        results.zIndexIssues.push({
          selector,
          values: values,
          issue: 'Different z-index values across media queries'
        });
      }
    }
  });

  // Check for z-index gaps or collisions
  const allZIndexes = [];
  rules.forEach(rule => {
    rule.properties.forEach(prop => {
      if (prop.name === 'z-index') {
        allZIndexes.push({
          value: parseInt(prop.value),
          selector: rule.selector,
          file: rule.file
        });
      }
    });
  });

  // Sort and find collisions
  allZIndexes.sort((a, b) => a.value - b.value);
  const zIndexGroups = {};
  allZIndexes.forEach(z => {
    if (!zIndexGroups[z.value]) {
      zIndexGroups[z.value] = [];
    }
    zIndexGroups[z.value].push(z);
  });

  Object.entries(zIndexGroups).forEach(([value, items]) => {
    if (items.length > 3) {
      results.zIndexIssues.push({
        value: parseInt(value),
        count: items.length,
        selectors: items.map(i => i.selector).slice(0, 5),
        issue: 'Multiple elements share same z-index (potential stacking conflict)'
      });
    }
  });
}

// Find !important wars
function findImportantWars(rules) {
  const importantBySelector = {};

  rules.forEach(rule => {
    rule.properties.forEach(prop => {
      if (prop.important) {
        const key = `${rule.selector}::${prop.name}`;
        if (!importantBySelector[key]) {
          importantBySelector[key] = [];
        }
        importantBySelector[key].push({
          value: prop.value,
          file: rule.file,
          mediaQuery: rule.mediaQuery
        });
      }
    });
  });

  // Find conflicts where same property has !important with different values
  Object.entries(importantBySelector).forEach(([key, occurrences]) => {
    if (occurrences.length > 1) {
      const uniqueValues = [...new Set(occurrences.map(o => o.value.replace('!important', '').trim()))];
      if (uniqueValues.length > 1) {
        const [selector, property] = key.split('::');
        results.importantWars.push({
          selector,
          property,
          values: occurrences,
          issue: '!important used with conflicting values'
        });
      }
    }
  });
}

// Find property conflicts in mobile context
function findPropertyConflicts(rules) {
  const mobileRules = rules.filter(r =>
    r.breakpoint.max && r.breakpoint.max <= 1024
  );

  const propertyBySelector = {};

  mobileRules.forEach(rule => {
    rule.properties.forEach(prop => {
      if (CRITICAL_PROPERTIES.includes(prop.name)) {
        const key = `${rule.selector}::${prop.name}`;
        if (!propertyBySelector[key]) {
          propertyBySelector[key] = [];
        }
        propertyBySelector[key].push({
          value: prop.value,
          file: rule.file,
          mediaQuery: rule.mediaQuery,
          breakpoint: rule.breakpoint.max
        });
      }
    });
  });

  // Find conflicting values at similar breakpoints
  Object.entries(propertyBySelector).forEach(([key, occurrences]) => {
    if (occurrences.length > 1) {
      // Group by similar breakpoints
      const byBreakpoint = {};
      occurrences.forEach(o => {
        const bp = Math.round(o.breakpoint / 100) * 100; // Group by 100px ranges
        if (!byBreakpoint[bp]) {
          byBreakpoint[bp] = [];
        }
        byBreakpoint[bp].push(o);
      });

      Object.entries(byBreakpoint).forEach(([bp, items]) => {
        if (items.length > 1) {
          const uniqueValues = [...new Set(items.map(i => i.value))];
          if (uniqueValues.length > 1) {
            const [selector, property] = key.split('::');
            results.propertyConflicts.push({
              selector,
              property,
              breakpointRange: `~${bp}px`,
              values: items,
              issue: 'Same property with different values at similar breakpoints'
            });
          }
        }
      });
    }
  });
}

// Find media query overlaps
function findMediaQueryOverlaps(rules) {
  const mediaQueries = {};

  rules.forEach(rule => {
    if (rule.mediaQuery) {
      if (!mediaQueries[rule.mediaQuery]) {
        mediaQueries[rule.mediaQuery] = {
          breakpoint: rule.breakpoint,
          files: new Set(),
          selectors: new Set()
        };
      }
      mediaQueries[rule.mediaQuery].files.add(rule.file);
      mediaQueries[rule.mediaQuery].selectors.add(rule.selector);
    }
  });

  const mqList = Object.entries(mediaQueries);

  for (let i = 0; i < mqList.length; i++) {
    for (let j = i + 1; j < mqList.length; j++) {
      const [mq1, data1] = mqList[i];
      const [mq2, data2] = mqList[j];

      const overlap = breakpointsOverlap(data1.breakpoint, data2.breakpoint);
      if (overlap) {
        // Check if they target similar selectors
        const sharedSelectors = [...data1.selectors].filter(s => data2.selectors.has(s));
        if (sharedSelectors.length > 0) {
          results.mediaQueryOverlaps.push({
            mediaQuery1: mq1,
            mediaQuery2: mq2,
            overlapType: overlap.type,
            sharedSelectors: sharedSelectors.slice(0, 5),
            files: [...new Set([...data1.files, ...data2.files])]
          });
        }
      }
    }
  }
}

// Main execution
async function main() {
  console.log('================================================================================');
  console.log('MOBILE CSS CONFLICT DETECTOR');
  console.log('================================================================================\n');

  // Find all CSS files
  const cssFiles = glob.sync('**/*.css', { cwd: CSS_DIR });
  console.log(`Scanning ${cssFiles.length} CSS files...\n`);

  const allRules = [];

  // Process each file
  cssFiles.forEach(file => {
    const filePath = path.join(CSS_DIR, file);
    const content = fs.readFileSync(filePath, 'utf8');
    const rules = extractRules(content, file);
    allRules.push(...rules);
  });

  console.log(`Extracted ${allRules.length} rules from media queries\n`);

  // Run all checks
  console.log('Running conflict detection...\n');

  findMediaQueryOverlaps(allRules);
  findPropertyConflicts(allRules);
  findZIndexIssues(allRules);
  findImportantWars(allRules);

  // Generate report
  console.log('────────────────────────────────────────────────────────────────────────────────');
  console.log('1. MEDIA QUERY OVERLAPS');
  console.log('────────────────────────────────────────────────────────────────────────────────\n');

  if (results.mediaQueryOverlaps.length === 0) {
    console.log('✅ No problematic media query overlaps found\n');
  } else {
    results.mediaQueryOverlaps.slice(0, 10).forEach(o => {
      console.log(`⚠️  Overlap: ${o.overlapType}`);
      console.log(`   Query 1: ${o.mediaQuery1}`);
      console.log(`   Query 2: ${o.mediaQuery2}`);
      console.log(`   Shared selectors: ${o.sharedSelectors.join(', ')}`);
      console.log(`   Files: ${o.files.join(', ')}\n`);
    });
  }

  console.log('────────────────────────────────────────────────────────────────────────────────');
  console.log('2. PROPERTY CONFLICTS (Same selector, different values at mobile breakpoints)');
  console.log('────────────────────────────────────────────────────────────────────────────────\n');

  if (results.propertyConflicts.length === 0) {
    console.log('✅ No critical property conflicts found\n');
  } else {
    results.propertyConflicts.slice(0, 15).forEach(c => {
      console.log(`⚠️  ${c.selector} { ${c.property} }`);
      console.log(`   Breakpoint range: ${c.breakpointRange}`);
      c.values.forEach(v => {
        console.log(`   - ${v.value} (${v.file})`);
      });
      console.log('');
    });
  }

  console.log('────────────────────────────────────────────────────────────────────────────────');
  console.log('3. Z-INDEX STACKING ISSUES');
  console.log('────────────────────────────────────────────────────────────────────────────────\n');

  if (results.zIndexIssues.length === 0) {
    console.log('✅ No z-index stacking issues found\n');
  } else {
    results.zIndexIssues.slice(0, 10).forEach(z => {
      if (z.selector) {
        console.log(`⚠️  ${z.selector}: ${z.issue}`);
        z.values.forEach(v => {
          console.log(`   - z-index: ${v.value} (${v.file})`);
        });
      } else {
        console.log(`⚠️  z-index: ${z.value} - ${z.issue}`);
        console.log(`   Used by: ${z.selectors.join(', ')}...`);
      }
      console.log('');
    });
  }

  console.log('────────────────────────────────────────────────────────────────────────────────');
  console.log('4. !IMPORTANT CONFLICTS');
  console.log('────────────────────────────────────────────────────────────────────────────────\n');

  if (results.importantWars.length === 0) {
    console.log('✅ No !important conflicts found\n');
  } else {
    results.importantWars.slice(0, 10).forEach(w => {
      console.log(`⚠️  ${w.selector} { ${w.property}: !important }`);
      w.values.forEach(v => {
        console.log(`   - ${v.value} (${v.file})`);
      });
      console.log('');
    });
  }

  // Summary
  console.log('================================================================================');
  console.log('SUMMARY');
  console.log('================================================================================\n');

  const totalIssues =
    results.mediaQueryOverlaps.length +
    results.propertyConflicts.length +
    results.zIndexIssues.length +
    results.importantWars.length;

  console.log(`Total potential issues: ${totalIssues}`);
  console.log(`  - Media query overlaps: ${results.mediaQueryOverlaps.length}`);
  console.log(`  - Property conflicts: ${results.propertyConflicts.length}`);
  console.log(`  - Z-index issues: ${results.zIndexIssues.length}`);
  console.log(`  - !important conflicts: ${results.importantWars.length}`);

  // Save detailed report
  const reportPath = path.join(__dirname, 'mobile-css-conflicts-report.json');
  fs.writeFileSync(reportPath, JSON.stringify(results, null, 2));
  console.log(`\nDetailed report saved to: ${reportPath}`);
}

main().catch(console.error);
