---
name: implement-task
description: Implement a specific task from the task plan using Test-Driven Development methodology, then verify documentation is current.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Implement Task

Implement a specific task from the task plan using Test-Driven Development methodology, then verify documentation is current.

## Mode

- **interactive** (default): Full workflow with human approval gates. Used when running standalone.
- **loop**: Called by `implement-and-review-loop`. Skips Phase 7 (present for approval) and returns control to the orchestrator after Phase 6 (update spec). No commit in this mode — the orchestrator handles that after the review cycle.

## Input

The user provides a task number (e.g., "2.1", "3.4"), says "next task", or says "implement all open tasks".
Tests are always built alongside implementation using TDD (Red → Green → Refactor).

## Process

### Phase 1: Validate and Select Task

1. Read the task plan from `Docs/In-Progress/` (most recent spec file with a task table).
2. If user said "next task", find the first eligible task (status `[ ]` with all prerequisites `[x]`).
3. If user said "implement all open tasks", find ALL eligible tasks and implement them sequentially, one at a time. Present progress after each task.
4. If user gave a task number, validate:
   - Not already `[x]` completed
   - Warn if `[~]` in progress
   - Check prerequisites are `[x]` completed
5. Read task details: objective, files, instructions, definition of done.

### Phase 2: Mark In Progress

1. Update the task status from `[ ]` to `[~]` in the task plan.

### Phase 3: Git Branch Check

1. Check current branch with `git branch`.
2. If on `main` or `develop`, remind user to create a feature branch per `.kiro/steering/branching.md`.
3. If already on a feature branch, continue on it. Do NOT create per-task branches.

### Phase 4: TDD Implementation

⚠️ **Before writing any code**, read the existing patterns in the target area:
- For CDK: check which stack owns the feature (e.g., `DashboardStack` vs `MonitoringStack` — they have different creation patterns). Read the parent stack (`ExtraLife.CdkStack.cs`) to see how resources are wired.
- For CDK new top-level stacks: **you MUST add the stack to the `cdk deploy` command in both `develop.yml` and `production.yml` workflows**. Check existing deploy commands with `grep "cdk deploy" .github/workflows/*.yml`. Top-level stacks are NOT auto-deployed — they need explicit `cdk deploy StackName` in CI/CD.
- For tests: check `pyproject.toml` or `pytest.ini` for `testpaths` restrictions. Place tests where the test runner can find them. In this project, Python tests go under `src/ai-engagement-tests/test_*/`.
- For workflows: check `develop.yml` as the reference — it's the most battle-tested workflow on self-hosted runners.

For each component of the task, follow strict TDD:

**Red**: Write a failing test first. Run it to confirm it fails for the right reason.
**Green**: Write the minimum code to make the test pass. Run tests.
**Refactor**: Improve code quality while keeping tests green. Run tests again.

Include tests for:
- Happy path (basic functionality)
- Configuration/parameterization
- Error conditions and edge cases (missing env vars, empty inputs, defaults)
- Guardrails (for agents: check system prompt contains safety guidelines)
- **Output quality assertions** (for agent/LLM features): at least one code-based assertion that verifies the output *content* is correct, not just that the code runs without throwing. E.g., "response mentions a participant name when asked about participants", "tool list is non-empty when data query is expected". Cheap deterministic checks catch real quality regressions that unit tests miss.

### Phase 5: Verify Build

1. If Python files changed: run `cd src/ai-engagement && source .venv/bin/activate && PYTHONPATH=. python -m pytest ../ai-engagement-tests/ -v`
2. If .NET files changed: run `dotnet build ExtraLife.sln -c Release` — must be 0 errors.
3. If CDK files changed: run `cdk synth` to verify.
4. If Angular files changed: run `cd Source/ExtraLife.Web.Admin/client && npx ng build`.
5. If a new `@tool` function was created, verify it is imported and registered in the handler/agent that uses it (e.g., `chat_handler.py` tool list).
6. **External API contract validation**: If the change includes hardcoded values for external APIs (Bedrock `reasoningConfig`, AWS SDK parameters, API enum values, etc.), look up the official AWS documentation to verify the exact accepted values, casing, and format. Never trust memory or examples alone — APIs are case-sensitive and enum values change across model versions.
7. **Null vs empty string**: When C# code uses `??` (null-coalescing) on string properties that receive user input from JavaScript/Angular, flag it. JavaScript sends `""` (empty string) for unset fields, not `null`. Use `string.IsNullOrEmpty()` instead of `??` for any string that originates from a frontend request body.
8. **Entity column change checklist**: When adding a column to an entity, verify ALL of these are updated: (1) ALTER TABLE to add column, (2) add property to C# entity, (3) update SqlDataReaderToObject reader, (4) update ALL stored procedure SELECTs that return the entity, (5) update UpsertProc if column is writable. Mock-based unit tests will NOT catch missing columns in stored procedures — mocks provide whatever you set up.
7. **Live API smoke test**: If the change touches external API parameters (model config, request fields, SDK calls), run a minimal live API call to confirm the parameters are accepted. A unit test with mocked responses won't catch contract mismatches (e.g., `"ENABLED"` vs `"enabled"`).
8. Run verification criteria from the task's Definition of Done.
9. **Lambda Web Adapter checklist**: When changing a Lambda handler to `run.sh` (Web Adapter):
   - Always use `python3 -m <module>` not bare `<module>` command. `pip install -t` creates package directories, not binaries on PATH.
   - Use `python3` (guaranteed on Lambda managed runtime), not `python3.12` (may not exist).
   - CDK `Code.FromAsset` does NOT install pip deps — CI/CD pipeline extracts pre-built zip into source dir before synth. Verify the CI/CD build step includes new deps.
   - Test that the FastAPI app starts by invoking the Lambda after deploy and checking for `Runtime.ExitError` in logs.

### Phase 6: Update Spec and Documentation

After implementation passes all tests:

1. Update task status from `[~]` to `[x]` in the task plan.
2. Update the progress summary (Total/Completed/In Progress/Not Started counts).
3. Update the "Eligible Tasks" section with newly unlocked tasks.
4. Check if `README.md` needs updating (new prerequisites, new commands, new project structure).
5. Check if `buildAndTest.sh` needs updating (new test types, new build steps).

### Phase 7: Present for Approval (interactive mode only)

**STOP before committing.** Present to the user:
- Summary of files created/modified
- Test count (total passing)
- Spec progress (X/Y tasks complete)
- Newly eligible tasks
- Any documentation updates made
- "Ready to commit, or would you like to run a code review first?"

In batch mode ("implement all open tasks"), commit after each task and continue to the next. Present a running summary. Offer code review after all tasks are complete rather than after each one.

In **loop mode**, skip this phase entirely — return control to the orchestrator.

### Phase 8: Commit (interactive mode only)

1. Stage specific files (not `git add .`).
2. Commit with message:
   ```
   Implement Task X.Y: {Task Title}

   {Brief description}
   - Key changes as bullet points
   ```

## Task Status Format

```
| Task | Description | Prerequisites | Status |
| 1.1  | Description | None          | [x]    |  ← completed
| 1.2  | Description | 1.1           | [~]    |  ← in progress
| 1.3  | Description | 1.1           | [ ]    |  ← not started
```

## Rules

- Follow branching workflow in `.kiro/steering/branching.md`.
- Match existing project patterns from `.kiro/steering/`.
- Keep changes minimal — only what the task requires.
- Never commit secrets or credentials.
- Always include tests — TDD is the default, not optional.
- Always update the spec after completing a task.
- Always check README.md relevance after completing a task.
- **After any bulk find-replace** (`sed`, search-replace, etc.), always re-run the full test suite before proceeding. Bulk replacements can miss context-dependent values (e.g., a test assertion that hardcodes a different expected value than the source).
- **After CSS/template bulk replacements**, visually verify at least 3 representative pages in the browser or via deploy. Build passing does NOT mean CSS is correct — orphaned classes, Tailwind reset overrides, and missing styles are invisible to the compiler.
- Refer to the user as "The Brougham 22".
