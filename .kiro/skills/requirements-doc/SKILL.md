---
name: requirements-doc
description: Capture a stream-of-consciousness description of requirements and produce a structured requirements document.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Requirements Doc

Capture a stream-of-consciousness description of requirements and produce a structured requirements document.

## Mode

- **interactive** (default): Full standalone workflow. Saves to `Docs/requirements/{feature-name}.md`.
- **spec**: Called by `create-spec`. Produces the Requirements section of the unified spec at `Docs/In-Progress/{feature-name}-spec.md`. Does not create a standalone file.

## Workflow

1. Ask the user: "What are you building? Give me the full stream of consciousness — don't worry about structure, I'll organize it."
2. If the user has already provided the description, proceed directly.
3. Ask clarifying questions where the description is ambiguous or incomplete. Focus on:
   - Who are the users?
   - What problem does this solve?
   - What are the must-haves vs nice-to-haves?
   - Are there constraints (technology, timeline, budget)?
   - Are there integrations with existing systems?
4. Produce a structured Markdown document at `Docs/requirements/{feature-name}.md` (interactive mode) or as the `## 1. Requirements` section of the unified spec (spec mode) with:

## Output Format

```markdown
# Requirements: {Feature Name}

## Problem Statement
What problem are we solving and for whom?

## Users
Who will use this and how?

## Functional Requirements
### Must Have
- FR-1: ...
- FR-2: ...

### Should Have
- FR-N: ...

### Nice to Have
- FR-N: ...

## Non-Functional Requirements
- NFR-1: Performance — ...
- NFR-2: Security — ...
- NFR-3: Scalability — ...

## Constraints
- Technology, timeline, budget, or organizational constraints

## Integrations
- Existing systems this must work with

## Open Questions
- Anything unresolved that needs stakeholder input

## Acceptance Criteria
- How do we know this is done?
```

5. Present the document to the user for review before saving.

## Rules

- Capture everything the user says — don't filter out ideas prematurely.
- Number all requirements for traceability.
- Flag ambiguities as Open Questions rather than making assumptions.
- This is a prerequisite for `design-high-level` and `design-low-level` — always run requirements first, even if the user asks to skip ahead.
- Refer to the user as "The Brougham 22".
