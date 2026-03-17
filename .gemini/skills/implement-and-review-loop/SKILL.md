---
name: implement-and-review-loop
description: Orchestrate an automated implement → review → fix cycle for tasks in a spec. Chains the `implement-task` and `review-code` skills in a loop until code is clean.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Implement and Review Loop

Orchestrate an automated implement → review → fix cycle for tasks in a spec. Chains the `implement-task` and `review-code` skills in a loop until code is clean.

**⚠️ THIS IS THE DEFAULT ENTRY POINT for implementation work.** When the user asks to "implement", "build", "code", or use the "agentic code skill", use THIS skill — not `implement-task` standalone. The standalone skill is only for cases where the user explicitly wants to skip the review cycle.

## Input

Same as `implement-task`: a task number, "next task", or "implement all open tasks".
The spec is read from `Docs/In-Progress/` — either a unified spec (`*-spec.md` from `create-spec`) or a standalone task plan (`*-tasks.md` from `plan-tasks`). Unified specs are preferred as they contain requirements, design, and tasks in one document for full context.

## Process

### Phase 1: Implement (delegate to `implement-task` in loop mode)

**⚠️ TELEMETRY: Log `{"type":"skill","skill":"implement-and-review-loop","status":"started"}` BEFORE doing anything else. If you forget, you are violating project policy.**

Run the `implement-task` skill with `mode: loop`:
1. Phases 1–5 execute normally (validate → mark in progress → branch check → TDD → verify build).
2. Phase 6 (update spec) executes normally.
3. Phase 7 (present for approval) is **skipped** — control returns here instead.

### Phase 1.5: Verify Test Coverage

**⚠️ MANDATORY — DO NOT SKIP. Run guard-rails after every implementation, before review.**

After implementation and before review, run the `guard-rails` skill:
1. All build gates must pass (hard fail blocks the loop).
2. All test gates must pass (hard fail blocks the loop).
3. New code coverage check — flag untested public functions.
4. Secrets scan — block if detected.
5. Branch check — block if on main/develop.
6. **YAML validation** — after ANY edit to a `.yml` or `.yaml` file, run `python3 -c "import yaml; yaml.safe_load(open('PATH'))"` AND verify the affected lines with `sed -n 'START,ENDp' PATH`. YAML syntax can be valid while structure is wrong (e.g., `str_replace` merging a `steps:` key onto the previous line). Both checks are required.
7. Report test counts in the Phase 5 summary (e.g., "245 Python ✅ | 245 .NET ✅ | 49 Angular ✅").

### Phase 2: Review (delegate to `review-code` in loop mode)

**⚠️ MANDATORY — DO NOT SKIP THIS PHASE. Every implementation must be reviewed before committing. No exceptions, even when batching multiple tasks.**

**⚠️ COMMIT GATE: If you committed code without running Phase 2, you MUST amend the commit after review. Run `git commit --amend` after fixing review findings. Never leave an unreviewed commit in the history. If you catch yourself about to commit without review, STOP — run the review first.**

**⚠️ SKIP DETECTION: If you catch yourself about to justify skipping review ("it's small", "it's just tests", "it's trivial"), STOP. Log `{"type":"decision","skill":"implement-and-review-loop","finding":"attempted review skip","assessment":"blocked","reason":"..."}` to telemetry, then run the review. Every skip attempt is a telemetry event — no exceptions.**

**⚠️ MUST USE PARALLEL REVIEW via native agent tools. Inline review (doing all 5 categories yourself) is NOT acceptable unless the required agents are not registered as tools. If you default to inline without attempting subagents, you are violating this skill.**

**⚠️ ANGULAR CHANGES: When reviewing Angular/TypeScript changes, include Angular-specific concerns in the subagent queries: RxJS patterns (forkJoin vs nested subscribes), view encapsulation impact on CSS, Angular lifecycle hooks, and dependency injection patterns. The subagents are Python-focused by default — you must add Angular context to the query string.**

**⚠️ NEW AGENT TOOLS: When adding a new agent with tools that call AWS APIs, verify BEFORE committing: (1) the Lambda that hosts the agent has the required env vars in CDK, (2) the Lambda's IAM role has permissions for those API calls. Check BOTH the AI Chat Lambda (AIChatComputeStack + AIEngagementFoundationStack) AND any standalone Lambdas. Missing env vars cause silent runtime failures that only surface during post-deploy validation.**

Run the `review-code` skill with `mode: loop`:
1. Steps 1–3 execute normally (gather changes → read code → invoke 5 review subagents in parallel: `review_security`, `review_maintainability`, `review_test_quality`, `review_infrastructure`, `review_performance`).
2. Step 4 (assess findings) executes normally.
3. Step 5 returns structured findings conforming to the Finding Schema (see `review-code`).
   - Each finding has: `severity`, `file`, `issue`, `category`, `assessment`, `action`
   - Only items with `action: "fix"` are actionable.
   - Items with `action: "log"` are recorded in the spec.
   - Items with `action: "skip"` are discarded.
   - Items with `action: "escalate"` are presented to the user.
4. **Retry on malformed output**: If a subagent returns output that can't be parsed into the Finding Schema, retry that subagent once with a clarifying prompt: "Please return findings as a structured list with severity (🔴/🟡/🟢), file, issue, and suggested fix." If the retry also fails, fall back to inline review for that category.
5. 🟢 Nits are logged but not acted on.

### Phase 3: Fix (if actionable findings exist)

1. For each actionable finding (🔴 Agree + 🟡 Agree), apply the fix.
2. Re-run the relevant test suite(s) from `implement-task` Phase 5.
3. If tests fail, feed the error back and retry the fix (max 2 retries per finding).

### Phase 4: Re-review (if fixes were applied)

1. Run `quick-review` (not the full 5-agent review) on the fix diff only.
2. If new 🔴 or 🟡 findings emerge, loop back to Phase 3.
3. **Max 3 total review→fix iterations** to prevent infinite loops. If still unresolved after 3 passes, present remaining findings to user for manual decision.

### Phase 5: Present Final State

**After presenting, offer**: "Want me to build and deploy so you can see it live? (runs `build-and-deploy` skill)"

**Full chain when approved**: After commit, automatically offer the full deployment chain:
1. `build-and-deploy` — container build → ECR → Fargate rotation (if Angular/ECS changes)
2. `push-and-pr` — push branch, create PR via `gh pr create`
3. `session-handoff` — save state for next session
Don't wait to be asked for each step — offer the chain: "Ready to build-deploy → push-PR → handoff?"

**STOP here.** Present to The Brougham 22:
- Summary of files created/modified
- Test count (total passing)
- Spec progress (X/Y tasks complete)
- Review iterations completed (e.g., "2 review passes, 3 findings fixed")
- Any remaining findings that couldn't be auto-resolved
- Newly eligible tasks
- Decision log summary (key decisions made during this task)
- "Ready to commit, or do you want to review the changes manually?"

**Decision Log**: Throughout Phases 1–4, append key decisions to the spec under a `### Decision Log` section for the current task. Each entry: `[timestamp] Decision: {what} | Reason: {why} | Alternative: {what was rejected}`. This creates an audit trail for why the code looks the way it does. Examples:
- "Used fire-and-forget pattern | Reason: mirrors _save_question | Alternative: async background task (over-engineered)"
- "Disagreed with DRY finding | Reason: 15-line functions are clearer than parameterized | Alternative: extract shared helper"

### Phase 6: Commit (only after approval)

**⚠️ TELEMETRY: Log `{"type":"skill","skill":"implement-and-review-loop","status":"completed"}` with duration and outcome BEFORE committing. If you're about to commit and haven't logged completion, STOP and log first.**

1. Stage specific files (not `git add .`).
2. Commit with message:
   ```
   Implement Task X.Y: {Task Title}

   {Brief description}
   - Key changes as bullet points
   - Review: {N} findings fixed across {M} iterations
   ```

### Phase 7: Next Task (batch mode only)

If running "implement all open tasks", move to the next eligible task and repeat from Phase 1. Present a running summary after each task. Offer a final comprehensive review after all tasks complete.

## Tiered Merge Gates

Inspired by Codex's tiered code review approach:
- **Non-critical tasks** (config, docs, minor features): The Brougham 22 can approve from the Phase 5 summary alone.
- **Critical tasks** (core logic, security, infrastructure, CDK): recommend full manual review before commit. Flag these in the Phase 5 summary with "⚠️ Critical — manual review recommended".

A task is "critical" if it touches: CDK/infrastructure, authentication/authorization, database schema, stored procedures, Lambda handlers, or financial/donation logic.

## Rules

- **NEVER skip Phase 2 (review)**. Every task gets a 5-agent code review. This is non-negotiable.
- **When batching tasks**: implement one task → review → fix → commit → next task. Do NOT batch multiple tasks into a single review. Each task gets its own implement→review→commit cycle.
- Preserve all subagent usage from `implement-task` and `review-code` — this skill orchestrates, it doesn't replace them.
- Subagent limit is 4 per invocation. Batch if more are needed (run 4, wait, run remainder).
- Max 3 review→fix iterations. Escalate to human after that.
- Never commit without user approval.
- Follow branching workflow in `.kiro/steering/branching.md`.
- Refer to the user as "The Brougham 22".
