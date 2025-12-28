#!/usr/bin/env node
/**
 * ============================================================================
 * COMPREHENSIVE FRONTEND AUDIT
 * ============================================================================
 *
 * Runs all audit scripts and generates a combined report.
 * Use this before deployments or after major changes.
 *
 * Usage: node scripts/audit-all.js
 *        npm run audit
 *
 * ============================================================================
 */

const { execSync } = require('child_process');
const path = require('path');

console.log('\n' + '='.repeat(80));
console.log('COMPREHENSIVE FRONTEND AUDIT');
console.log('='.repeat(80) + '\n');

const audits = [
  { name: 'JavaScript Patterns', script: 'audit-js-patterns.cjs' },
  { name: 'CSS Patterns', script: 'audit-css-patterns.cjs' }
];

let hasErrors = false;

audits.forEach(audit => {
  console.log(`\n${'─'.repeat(80)}`);
  console.log(`Running: ${audit.name}`);
  console.log('─'.repeat(80) + '\n');

  try {
    const scriptPath = path.join(__dirname, audit.script);
    execSync(`node "${scriptPath}"`, { stdio: 'inherit' });
  } catch (error) {
    hasErrors = true;
    console.log(`\n⚠️  ${audit.name} found issues\n`);
  }
});

console.log('\n' + '='.repeat(80));
if (hasErrors) {
  console.log('⚠️  AUDIT COMPLETE - Issues found (see above)');
  console.log('='.repeat(80) + '\n');
  process.exit(1);
} else {
  console.log('✅ AUDIT COMPLETE - All checks passed');
  console.log('='.repeat(80) + '\n');
  process.exit(0);
}
