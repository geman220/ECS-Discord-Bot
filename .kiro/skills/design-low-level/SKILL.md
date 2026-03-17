---
name: design-low-level
description: Produce a detailed component-level design from a high-level design document.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Low Level Design

Produce a detailed component-level design from a high-level design document.

## Mode

- **interactive** (default): Full standalone workflow. Reads from `Docs/designs/`, saves to `Docs/designs/{feature-name}-lld.md`.
- **spec**: Called by `create-spec`. Reads the Requirements and HLD sections from the unified spec, produces the `## 3. Low-Level Design` section in the same file.

## Workflow

1. **Interactive mode**: Look for high-level design docs in `Docs/designs/` (files ending in `-hld.md`). If multiple exist, ask the user which one to use.
   **Spec mode**: Read the `## 1. Requirements` and `## 2. High-Level Design` sections from the unified spec passed by the orchestrator.
2. Read the high-level design document thoroughly.
3. Read the corresponding requirements doc for context.
4. Ask the user if they have refinements or decisions about component separation.
5. Produce a low-level design document at `Docs/designs/{feature-name}-lld.md` (interactive mode) or as the `## 3. Low-Level Design` section of the unified spec (spec mode) covering:

## Output Format

```markdown
# Low Level Design: {Feature Name}

## Overview
Brief summary linking back to the HLD.

## Component Design

### {Component Name}
For each major component from the HLD:

**Responsibility**: What this component does.

**Class Diagram**:
```mermaid
classDiagram
    ...
```

**Key Classes/Modules**:
| Class/Module | Responsibility | Dependencies |
|-------------|---------------|--------------|
| ... | ... | ... |

**Public API**:
```
Method/Endpoint signature
  Input: ...
  Output: ...
  Errors: ...
```

**Internal Logic**: Key algorithms or decision flows.

### Component Interactions
```mermaid
sequenceDiagram
    ...
```

## Module Separation
How code is organized into projects/packages/modules. For this project:
- .NET projects in `Source/`
- Angular modules in `Source/ExtraLife.Web.Admin/client/src/app/`
- Python packages in `src/`
- CDK stacks in `Source/ExtraLife.CDK/`

## Interface Contracts
Detailed API contracts between components — request/response shapes, error codes, headers.

## Configuration
All configuration values, their sources (SSM, appsettings, env vars), and defaults.

## Error Handling Strategy
How errors propagate across component boundaries.

## Task Readiness Checklist
- [ ] Each component has clear boundaries and a single responsibility
- [ ] All interfaces between components are defined
- [ ] Data models are specified
- [ ] Error handling is defined at each boundary
- [ ] Configuration is documented
```

6. Present the document to the user for review before saving.

## Rules

- Use Mermaid class diagrams for component structure.
- Use Mermaid sequence diagrams for component interactions.
- Every public API must have input/output/error documented.
- The design should make task breakdown straightforward — if a component is too large for one task, split it.
- Match existing project conventions from `.kiro/steering/structure.md` and `.kiro/steering/tech.md`.
- If a combined spec exists in `Docs/In-Progress/`, note that LLD findings should be consolidated back into it after review. In spec mode, this is automatic — the LLD is already in the unified spec.
- Refer to the user as "The Brougham 22".
