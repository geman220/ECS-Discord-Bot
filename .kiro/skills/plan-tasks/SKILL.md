---
name: plan-tasks
description: Create an implementation task plan with status tracking and dependency graph from a design document.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Plan Tasks

Create an implementation task plan with status tracking and dependency graph from a design document.

## Mode

- **interactive** (default): Full standalone workflow. Reads from `Docs/designs/`, saves to `Docs/In-Progress/{feature-name}-tasks.md`.
- **spec**: Called by `create-spec`. Reads the full unified spec, produces the `## 4. Task Plan` section in the same file.

## Input

**Interactive mode**: Optional path to design document. Defaults to most recent file in `Docs/designs/` ending in `-lld.md`, falling back to `-hld.md`.
**Spec mode**: The unified spec passed by the orchestrator (reads sections 1-3 for context).

## Process

### Phase 1: Read the Design

1. Read the design document.
2. Identify classes/modules to implement, dependencies between them, external dependencies, and file structure.

### Phase 2: Define Tasks

Break implementation into tasks following these principles:

- **One to two files per task** — keeps reviews manageable
- **Bootstrap first** — project setup before code
- **Bottom-up order** — implement dependencies before dependents
- **Tests with implementation** — each task includes tests when applicable

For each task, define:
- **Task number** — hierarchical (1.1, 1.2, 2.1) grouped by layer/phase
- **Description** — brief summary
- **Objective** — what this task accomplishes
- **Files** — the files to create/modify (1-2 max)
- **Instructions** — specific implementation details
- **Definition of Done** — how to verify (build passes, test passes, endpoint responds)
- **Estimated effort** — Small / Medium / Large

### Phase 3: Build Dependency Graph

- Determine prerequisites for each task
- Identify parallel tracks (tasks with no dependencies between them)
- Group into execution waves

### Phase 4: Write Plan Files

Create `Docs/In-Progress/{feature-name}-tasks.md` (interactive mode) or append the `## 4. Task Plan` section to the unified spec (spec mode):

```markdown
# Task Plan: {Feature Name}

## Progress Summary
- Total Tasks: X
- Completed: 0
- In Progress: 0
- Not Started: X

## Task Status

| Task | Description | Prerequisites | Status |
|------|-------------|---------------|--------|
| 1.1  | Description | None          | [ ]    |
| 1.2  | Description | 1.1           | [ ]    |

## Eligible Tasks
Tasks ready to start (prerequisites complete):
- **1.1** — Description

## Dependency Graph

```mermaid
graph TD
    T1[Task 1.1] --> T3[Task 2.1]
    T2[Task 1.2] --> T3
```

## Detailed Task Definitions

### Task 1.1: {Title}
**Objective**: What this accomplishes.
**Files**: `path/to/file.cs`
**Prerequisites**: None
**Instructions**:
- Step by step implementation details
**Definition of Done**:
- Build passes
- Specific verification criteria
**Effort**: Small
```

5. Present the plan to the user for review before saving.

## Rules

- Tasks must be completable in a single context window — if in doubt, split.
- Every task must have a verifiable Definition of Done.
- Match the format used in existing Phase specs in `Docs/In-Progress/`.
- Refer to the user as "The Brougham 22".
