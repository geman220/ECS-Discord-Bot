---
name: close-issue
description: Wrap up a completed issue: verify all tasks done, group deferred findings, deduplicate against existing GH issues, create follow-up issues, close with summary, move spec to Done.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Close Issue

Wrap up a completed issue: verify all tasks done, group deferred findings, deduplicate against existing GH issues, create follow-up issues, close with summary, move spec to Done.

## When to Run

When all tasks in a spec are complete, deployed, and validated.

## Workflow

### Step 0: Check Issue State (NEW)

1. Run `gh issue view {issue-number} --json state` to check if already closed
2. If **CLOSED**:
   - Check if spec is in `Docs/In-Progress/`
   - If yes: Move to `Docs/Done/`, commit with message "Move #{N} spec to Done (was closed but not moved)", skip to end
   - If already in Done: Nothing to do, inform user
3. If **OPEN**: Proceed to Step 1

### Step 1: Verify Completion

1. Read the spec from `Docs/In-Progress/`.
2. Check for any `[ ]` (unchecked) tasks. If any remain, categorize them:
   - **Superseded tasks** — tasks replaced by a v2 equivalent (e.g., Task 1.5 superseded by Task 1.10-v2, Tasks 1.6/1.7/1.8 superseded by Phase 2 work). Mark these `[x]` with a note and proceed.
   - **Genuinely incomplete tasks** — stop and report these to The Brougham 22.
3. Confirm all acceptance criteria are met.

### Step 2: Group Deferred Findings

1. Scan all review findings in the spec for items with action `log`.
2. Group into categories:
   - **Should track** — real work with value (test gaps, known limitations, refactors)
   - **Acceptable as-is** — by design, low risk, or already mitigated
   - **Correctly skipped** — disagreed with reviewer, documented rationale
3. Present the grouped summary to the user.

### Step 3: Deduplicate Against Open Issues

1. Run `gh issue list --state open` to get all open issues.
2. For each "should track" item, check if an existing issue already covers it.
3. Present the deduplication table: finding → existing issue (fold in) or "new issue needed". Include a suggested clubbing if multiple findings fit the same issue.
4. Ask: "Does this look right, or do you want to adjust?" — one round only.

### Step 4: Create Follow-Up Issues

1. For items that need new issues, create them using the project's issue templates.
2. For items that fold into existing issues, add a comment to that issue with the finding details.
3. Link back to the parent issue and spec.

### Step 5: Close the Issue

1. Close the GH issue with a summary comment containing:
   - What shipped (bullet list of key changes)
   - PRs merged (with numbers)
   - Deferred items (with follow-up issue numbers)
   - Test count delta
2. Move the spec from `Docs/In-Progress/` to `Docs/Done/`.
3. Commit and push.

## Rules

- Never close an issue with unchecked tasks.
- Always deduplicate before creating new issues.
- Always ask the user if items can be clubbed before creating multiple issues.
- The closing comment should be a complete record — someone reading it months later should understand what was done and what was deferred.
- Refer to the user as "The Brougham 22".
