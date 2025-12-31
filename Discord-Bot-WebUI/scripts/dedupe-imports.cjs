#!/usr/bin/env node
/**
 * Deduplicate Import Statements
 *
 * Removes duplicate import statements from all JS files.
 */

const fs = require('fs');
const path = require('path');
const { glob } = require('glob');

async function main() {
    console.log('🔄 Deduplicating import statements...\n');

    const jsFiles = await glob('app/static/js/**/*.js', { ignore: ['**/vendor/**', '**/vite-dist/**', '**/gen/**'] });
    const customJsFiles = await glob('app/static/custom_js/**/*.js');
    const assetsJsFiles = await glob('app/static/assets/js/**/*.js');

    const allFiles = [...jsFiles, ...customJsFiles, ...assetsJsFiles];

    let fixed = 0;

    for (const filePath of allFiles) {
        try {
            const content = fs.readFileSync(filePath, 'utf8');
            const lines = content.split('\n');

            // Extract import statements and their positions
            const importLines = [];
            const nonImportLines = [];
            const seenImports = new Set();

            let inImportBlock = true;
            let firstNonImportFound = false;

            for (let i = 0; i < lines.length; i++) {
                const line = lines[i];
                const trimmed = line.trim();

                // Check if this is an import line
                if (trimmed.startsWith('import ') || trimmed.startsWith("import{")) {
                    // Normalize the import for deduplication
                    const normalized = trimmed.replace(/\s+/g, ' ').trim();

                    if (!seenImports.has(normalized)) {
                        seenImports.add(normalized);
                        importLines.push(line);
                    }
                } else if (trimmed === '' && !firstNonImportFound) {
                    // Skip empty lines between imports at the top
                    continue;
                } else if (trimmed.startsWith("'use strict'") || trimmed.startsWith('"use strict"')) {
                    // Keep use strict at top, before imports
                    if (importLines.length === 0) {
                        importLines.unshift(line);
                    }
                } else {
                    firstNonImportFound = true;
                    nonImportLines.push(line);
                }
            }

            // Rebuild content
            let newContent;
            if (importLines.length > 0) {
                // Check if 'use strict' is first
                let useStrict = '';
                let imports = importLines;

                if (importLines[0].includes('use strict')) {
                    useStrict = importLines[0] + '\n';
                    imports = importLines.slice(1);
                }

                newContent = useStrict + imports.join('\n') + '\n\n' + nonImportLines.join('\n');
            } else {
                newContent = lines.join('\n');
            }

            // Clean up multiple consecutive newlines
            newContent = newContent.replace(/\n{3,}/g, '\n\n');

            if (newContent !== content) {
                fs.writeFileSync(filePath, newContent, 'utf8');
                console.log(`✅ Fixed: ${filePath}`);
                fixed++;
            }
        } catch (error) {
            console.error(`❌ Error processing ${filePath}: ${error.message}`);
        }
    }

    console.log(`\n📊 Fixed ${fixed} files with duplicate imports.`);
}

main().catch(console.error);
