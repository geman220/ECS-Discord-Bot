---
name: create-spec
description: Orchestrate the full specification pipeline — requirements → high-level design → low-level design → task plan — producing a single unified spec document. This spec is the primary input for `implement-and-review-loop`.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Create Spec

Orchestrate the full specification pipeline — requirements → high-level design → low-level design → task plan — producing a single unified spec document. This spec is the primary input for `implement-and-review-loop`.

## Input

A stream-of-consciousness description of what to build, or "resume" to continue an in-progress spec.

## Output

A single file: `Docs/In-Progress/{feature-name}-spec.md`

## Process

**⚠️ TELEMETRY: Log `{"type":"skill","skill":"create-spec","status":"started"}` BEFORE doing anything else.**

### Phase 0: Research (if AWS/infrastructure features)

If the feature involves AWS APIs, Lambda runtimes, SDK capabilities, or infrastructure patterns:
1. **Use tools to research** — call `aws___search_documentation`, `web_search`, or `aws___read_documentation` to verify assumptions about API capabilities, SDK support, and runtime limitations BEFORE writing requirements.
2. **Document findings** — add a "Research Findings" section to the requirements with what's supported, what's not, and links to docs.
3. **Flag constraints early** — if research reveals a limitation (e.g., "Python Lambda doesn't support native response streaming"), surface it in requirements as a constraint, not as a surprise in HLD.
4. This phase prevents mid-HLD architecture pivots caused by discovering API limitations too late.

### Phase 1: Requirements (delegate to `requirements-doc` in spec mode)

1. Run `requirements-doc` with `mode: spec`.
2. Gather the user's description, ask clarifying questions.
3. Produce the Requirements section of the unified spec.
4. **STOP — present to The Brougham 22 for review.**
5. If feedback given, revise and re-present. Loop until approved.
6. Save the spec file with the Requirements section. Confirm: "Requirements approved. Moving to High-Level Design."

### Phase 2: High-Level Design (delegate to `design-high-level` in spec mode)

1. Run `design-high-level` with `mode: spec`, passing the requirements section as context.
2. Ask the user for any additional design constraints or decisions already made.
3. Produce the High-Level Design section.
4. **STOP — present to The Brougham 22 for review.**
5. If feedback given, revise and re-present. Loop until approved.
6. Update the spec file. Confirm: "HLD approved. Moving to Low-Level Design."

### Phase 2.5: Validate Requirements → HLD Contract

Run `validate-handoff` for the Requirements → HLD boundary. Every FR/NFR must map to at least one HLD component. Fix gaps before proceeding.

### Phase 3: Low-Level Design (delegate to `design-low-level` in spec mode)

1. Run `design-low-level` with `mode: spec`, passing requirements + HLD as context.
2. Ask the user for refinements on component separation.
3. Produce the Low-Level Design section.
4. **STOP — present to The Brougham 22 for review.**
5. If feedback given, revise and re-present. Loop until approved.
6. Update the spec file. Confirm: "LLD approved. Moving to Task Plan."

### Phase 3.5: Validate HLD → LLD Contract

Run `validate-handoff` for the HLD → LLD boundary. Every HLD module must have a corresponding LLD component. Fix gaps before proceeding.

### Phase 4: Task Plan (delegate to `plan-tasks` in spec mode)

1. Run `plan-tasks` with `mode: spec`, passing the full spec as context.
2. Break the LLD into implementation tasks with dependencies.
3. **Validate tasks with tools** — for each task that references AWS APIs, env vars, SDK methods, or CLI commands, verify with tools before writing:
   - Check env var names exist on the target platform (`get_agent_runtime`, Lambda config)
   - **Check API parameters are correct** — use `boto3.client('service').meta.service_model.operation_model('OperationName').input_shape.members.keys()` to get the exact parameter list. Never assume a parameter exists (e.g., `memoryConfiguration` on `update_agent_runtime` does NOT exist — confirmed 2026-03-12).
   - Check IAM action names with `boto3.client('service').meta.service_model.signing_name`
   - Check CDK exports with `aws cloudformation list-exports`
   - Don't trust the spec alone — verify claims against actual code/infra
4. Produce the Task Plan section (task table, dependency graph, detailed definitions).
5. **STOP — present to The Brougham 22 for review.**
6. If feedback given, revise and re-present. Loop until approved.
7. Update the spec file. Confirm: "Spec complete! Ready for `implement-and-review-loop`."

### Phase 4.5: Validate LLD → Task Plan Contract

Run `validate-handoff` for the LLD → Task Plan boundary. Every LLD component must have at least one task. Fix gaps before proceeding.

**⚠️ DEPLOYMENT TASK: If the spec involves Lambda, CDK, or infrastructure changes, the task plan MUST include a deployment validation task as the final task. This task verifies the deployed code works (not just that it builds). The uvicorn startup failure in #299 would have been caught by a smoke test task.**

### Phase 5: Final Summary

Present:
- Spec file path
- Requirement count (FR + NFR)
- Component count from LLD
- Task count with dependency waves
- "Ready to finalize? I will file the GitHub issue, get the ID, and rename the spec file."

### Phase 6: Finalize & File

1. **File GitHub Issue**:
   - Call `gh issue create` using the spec title and body.
   - Use labels: `infrastructure`, `enhancement`, `bug`, etc., based on the spec content.
   - Capture the resulting issue ID (e.g., #480).
2. **Rename Spec File**:
   - Move `Docs/In-Progress/{feature-name}-spec.md` to `Docs/In-Progress/issue-{ID}-{feature-name}-spec.md`.
3. **Update Task Plan**:
   - Ensure the internal task plan in the spec reflects the new ID.
4. **Confirm**: "Issue #{ID} created and spec renamed. Ready for `implement-and-review-loop`."

## Unified Spec Format

```markdown
# Specification: {Feature Name}

## 1. Requirements

### Problem Statement
...

### Users
...

### Functional Requirements
#### Must Have
- FR-1: ...

#### Should Have
- FR-N: ...

#### Nice to Have
- FR-N: ...

### Non-Functional Requirements
- NFR-1: ...

### Constraints
...

### Integrations
...

### Open Questions
...

### Acceptance Criteria
...

## 2. High-Level Design

### Overview
...

### System Context
{Mermaid diagram}

### Architectural Decisions
{ADR table}

### Major Modules
...

### Data Flow
{Mermaid diagram}

### Data Model
...

### API Design
...

### Security Concerns
...

### Infrastructure
...

### Dependencies
...

### Risks and Mitigations
{Risk table}

### Requirements Traceability
{FR/NFR → component mapping}

## 3. Low-Level Design

### Component Design
{Per-component: responsibility, class diagram, key classes, public API, internal logic}

### Component Interactions
{Mermaid sequence diagram}

### Module Separation
...

### Interface Contracts
...

### Configuration
...

### Error Handling Strategy
...

## 4. Task Plan

### Progress Summary
- Total Tasks: X
- Completed: 0
- In Progress: 0
- Not Started: X

### Task Status
| Task | Description | Prerequisites | Status |
|------|-------------|---------------|--------|
| 1.1  | ...         | None          | [ ]    |

### Eligible Tasks
...

### Dependency Graph
{Mermaid graph}

### Detailed Task Definitions
{Per-task: objective, files, prerequisites, instructions, definition of done, effort}
```

## Resuming an In-Progress Spec

If the user says "resume":
1. Find the most recent spec in `Docs/In-Progress/` ending in `-spec.md`.
2. Determine which phase is complete (has content) and which is next.
3. Pick up from the next incomplete phase.

## Rules

- Human review gate after every phase — never auto-advance.
- Refinement loops within each phase are unlimited — keep revising until approved.
- Each phase builds on the previous — HLD references requirements, LLD references HLD, tasks reference LLD.
- Every FR/NFR must be traceable through HLD → LLD → at least one task.
- The unified spec replaces the separate files in `Docs/requirements/` and `Docs/designs/`. Don't create those.
- If a spec already exists for this feature, ask whether to revise it or start fresh.
- After Phase 5 (final summary), commit the spec to the feature branch and push. Don't wait to be asked.
- Refer to the user as "The Brougham 22".
