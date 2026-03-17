---
name: quick-review
description: Fast checklist-based code review of uncommitted changes. Use this for a quick pass; use `review-code` for the full multi-agent review.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Quick Review

Fast checklist-based code review of uncommitted changes. Use this for a quick pass; use `review-code` for the full multi-agent review.

## Input

Optional: focus areas to emphasize (e.g., "security", "tests", "performance"). Reviews full checklist if none specified.

## Process

### Step 1: Gather Changes

1. Run `git diff HEAD` to get modified tracked files.
2. Run `git status --short` to find untracked files.
3. Read all changed and new files.

### Step 2: Analyze Against Checklist

Review the code for:

1. **Tautological tests** — tests using excessive mocks that don't verify real behavior
2. **Security concerns** — input validation, injection risks, path traversal, secrets
3. **Refactoring opportunities** — complex logic, long functions, repeated code
4. **Missing input validations** — unchecked parameters, type assumptions
5. **Generic exceptions** — opportunities for domain-specific error classes
6. **Missing logging** — operations that should be logged but aren't
7. **Consistency** — does the new code match existing project patterns?

If focus areas were specified, prioritize those sections.

### Step 3: Write Review

Create `reviews/{timestamp}-{descriptive-name}.md` containing:
- Summary of changes reviewed
- Findings organized by checklist category
- Specific code suggestions where applicable
- Verdict: ready to commit, or action items needed

## Output

- Review document saved to `reviews/` directory
- Summary of key findings printed to console

## Rules

- This is a quick pass — flag issues, don't deep-dive.
- For thorough multi-faceted review, use the `review-code` skill instead.
- Refer to the user as "The Brougham 22".
