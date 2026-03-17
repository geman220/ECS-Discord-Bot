---
name: review-code
description: Run a multi-faceted code review on uncommitted changes using specialized review subagents.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Review Code

Run a multi-faceted code review on uncommitted changes using specialized review subagents.

## Mode

- **interactive** (default): Full workflow with human-facing presentation. Used when running standalone.
- **loop**: Called by `implement-and-review-loop`. Returns structured findings instead of presenting a table. Skips "Want me to fix?" prompt — the orchestrator decides.

## Finding Schema

See [Finding Schema](references/FINDING-SCHEMA.md) for the typed contract.


## Workflow

### Step 1: Gather Changes

1. Run `git diff HEAD --name-only` and `git ls-files --others --exclude-standard` to identify changed files.
2. Separate files into: code files (substantive) vs. documentation-only files.
3. If only documentation changed, run the `quick-review` skill instead — the full 5-agent review is overkill for docs.

### Step 2: Read All Code Files

Read the full content of every substantive changed/new file. This is critical — subagents need the actual code, not just file names.

### Step 3: Invoke Code Reviewers

Invoke the 5 specialized review subagents. These are now native tools that can be invoked in parallel:

**Parallel Invocation:**
- `review_security` — authentication, input validation, secrets, IAM, data exposure
- `review_maintainability` — code organization, naming, duplication, DRY, configuration
- `review_test_quality` — coverage gaps, edge cases, assertion quality, test isolation
- `review_infrastructure` — CDK patterns, CI/CD, deployment, monitoring, cost
- `review_performance` — resource allocation, latency, memory, cold starts, algorithmic efficiency

**Merge all findings into a single assessment table in Step 4.**

**⚠️ CRITICAL — Subagent source code delivery:**
Native subagents **cannot read files directly from your context**. The ONLY way to get code to a subagent is to **embed the full source code directly in the `query` string**. This means:
- Read every changed file
- Paste the full file contents into the `query` parameter as fenced code blocks
- Include the file path as a label above each code block so the reviewer knows which file it's reviewing

Example query structure:
```
Review the following files for security concerns...

FILE 1 - src/tools/data_tools.py:
\`\`\`python
<full file contents here>
\`\`\`
```

If native subagents are unavailable or fail to produce useful results, fall back to running the review directly in the main conversation using the same 5 categories. Read the full diff with `git diff HEAD~1` and produce a single findings table covering all categories.

### Step 4: Assess Findings

After receiving the review report, provide an honest assessment of each finding:

For each finding, state:
- **Agree** — valid issue, should fix
- **Disagree** — explain why (e.g., "by design", "tracked in future task", "not a real risk for this context")
- **Defer** — valid but belongs in a later phase, reference the task number

This prevents rubber-stamping and also prevents over-engineering fixes for non-issues.

⚠️ **Don't re-litigate settled decisions.** If a finding was assessed as "Disagree" in a previous review pass during this session (e.g., "CFN exports vs SSM" or "broad exception handling by design"), don't raise it again. Subagents don't have memory of prior assessments — you do. Skip findings that repeat previously settled decisions and note "Previously assessed — [reason]" in the table.

### Step 5: Present to User

**Interactive mode:** Present findings as a summary table:

```
| # | Severity | File | Issue | Assessment |
|---|----------|------|-------|------------|
| 1 | 🔴 | file.py | Description | Agree — should fix |
| 2 | 🟡 | file.py | Description | Defer to Task X.Y |
| 3 | 🟡 | file.py | Description | Disagree — by design |
```

End with:
- Count by severity
- List of items to fix now
- List of items deferred (with task references)
- "Want me to fix the agreed items?"

**Loop mode:** Return structured findings to the orchestrator as a list:
```
- severity: 🔴/🟡/🟢
- file: path/to/file
- issue: description
- assessment: Agree/Disagree/Defer
- auto_fixable: yes/no
```
Only items with assessment "Agree" and severity 🔴 or 🟡 are actionable. 🟢 Nits are logged but not acted on.

### Step 6: Fix (interactive mode, or when called directly)

Fix all agreed items. Run tests after fixes. Present updated test results.

## Severity Definitions

See [Severity Definitions](references/SEVERITY-DEFINITIONS.md) for the full rubric.


## Rules

- Always read the actual code before reviewing — never review based on file names alone.
- Skip trivial changes (XML doc comments, whitespace, gitignore additions).
- Focus on new files and substantive modifications.
- The `reviews/` folder is gitignored — review artifacts don't go into source control.
- Be honest about findings — disagree with the subagents when they're wrong.
- Don't flag items that are explicitly tracked in future tasks (check the Phase spec).
- **Hardcoded API values**: When code contains hardcoded enum values, parameter names, or config for external APIs (Bedrock, AWS SDK, DonorDrive, etc.), flag them for documentation verification. The `"ENABLED"` vs `"enabled"` bug shipped because no reviewer checked the Bedrock API spec. If you see a hardcoded API value, ask: "Has this been verified against the official docs?"
- **IAM action verification**: When reviewing IAM policy statements (CDK, CloudFormation, or inline policies), **verify the service prefix with tools before flagging as incorrect**. The correct IAM prefix is the `signing_name` from the boto3 service model, NOT a guess based on the service name. Example: `bedrock-agentcore` is correct (not `bedrock-agent`). Run `python3 -c "import boto3; print(boto3.client('service-name').meta.service_model.signing_name)"` to verify. The Wave 2 infrastructure subagent incorrectly flagged `bedrock-agentcore:InvokeAgentRuntime` as wrong — tool verification would have prevented this.
- **CSS framework migration**: When Tailwind is present alongside component CSS, verify that `var(--color-*)` references resolve correctly. Tailwind 4's `@layer base` reset can override component `background-color` and `color`. Flag any component using CSS custom properties for background/color that hasn't been visually verified.
- Refer to the user as "The Brougham 22".
