---
name: mass-remediate-pattern
description: Safe, project-wide remediation of a dangerous or incorrect code pattern using structured search and replace.
metadata:
  author: ssfcultra
  version: "1.0"
---
# Mass Remediate Pattern

Safe, project-wide remediation of a dangerous or incorrect code pattern using structured search and replace (grep + sed/replace).

## Input

- **Target Pattern**: The dangerous code pattern to find (e.g., `jsonify({'error': str(e)})`).
- **Replacement Pattern**: The safe replacement (e.g., `jsonify({'error': 'Internal Server Error'})`).
- **Scope**: Directories or file types to target.

## Process

### Phase 1: Discovery
1. Use `grep_search` to identify all occurrences of the pattern across the codebase.
2. Log the total count and list of unique files affected.
3. Present a sample of the matches to the user to confirm the pattern is correctly identified.

### Phase 2: Strategy & Testing
1. Draft a `sed` command or a series of `replace` calls.
2. **CRITICAL**: Test the replacement on a single representative file first.
3. Verify the fix in the test file (check syntax, run local unit tests if applicable).

### Phase 3: Execution
1. Run the mass replacement across the full scope.
2. Use `git status` and `git diff` to verify the scale of changes.

### Phase 4: Validation
1. Run the project's test suite (`pytest`, `npm test`, etc.).
2. If specific tests were failing due to the pattern, verify they now pass (or fail differently/later).
3. If new errors are introduced, revert and refine the pattern.

## Output

A summary of the remediation:
- Total files modified.
- Total occurrences replaced.
- Verification results (test pass/fail).

## Rules

- Always test on one file before applying to the whole project.
- Use generic error messages for security-related remediations (Information Exposure).
- Prefer `textContent` over `innerHTML` for DOM-related remediations.
- Ensure replacements maintain correct indentation and syntax.
- Refer to the user as "The Brougham 22".
