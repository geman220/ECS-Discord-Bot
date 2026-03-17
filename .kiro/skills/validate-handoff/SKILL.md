---
name: validate-handoff
description: Validate the contract between skill phases to catch broken handoffs early. This is the "schema validation at agent boundaries" pattern from distributed systems.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Validate Handoff

Validate the contract between skill phases to catch broken handoffs early. This is the "schema validation at agent boundaries" pattern from distributed systems.

## When to Run

Called automatically at phase transitions in `create-spec` and `implement-and-review-loop`. Can also be invoked standalone to check spec integrity.

## Contracts

### Requirements → HLD

Validate that the HLD addresses every requirement:
1. Read all FR-* and NFR-* IDs from the Requirements section.
2. Check the HLD's "Requirements Traceability" section.
3. **FAIL** if any FR/NFR is not mapped to at least one HLD component.
4. **WARN** if an HLD component doesn't trace back to any requirement (gold-plating).

### HLD → LLD

Validate that the LLD covers every HLD component:
1. Read all "Major Modules" from the HLD.
2. Check the LLD's "Component Design" section.
3. **FAIL** if any HLD module has no corresponding LLD component.
4. **WARN** if the LLD introduces components not in the HLD (scope creep).

### LLD → Task Plan

Validate that every LLD component has implementation tasks:
1. Read all components from the LLD.
2. Check the Task Plan's detailed task definitions.
3. **FAIL** if any LLD component has no task covering it.
4. **WARN** if a task references files not mentioned in the LLD.

### Task Plan → Implementation

Validate that completed tasks match their definition of done:
1. For each task marked `[x]`, read its Definition of Done.
2. Check that each criterion is verifiable (file exists, test passes, build succeeds).
3. **FAIL** if a completed task has unmet criteria.

### Implementation → Review

Validate that the review covers all changed files:
1. Compare `git diff --name-only` against the review findings.
2. **WARN** if a changed file has zero findings (may indicate the reviewer missed it).

## Output

```
Handoff Validation: Requirements → HLD
  ✅ FR-1 → System Context (AgentCore Memory)
  ✅ FR-2 → Data Flow (read path)
  ✅ FR-3 → Data Flow (chronological ordering)
  ❌ NFR-3 → NOT MAPPED (failure resilience)
  Result: FAIL — 1 unmapped requirement
```

## Rules

- Run validation BEFORE presenting the phase output to the user. Catch gaps before they propagate.
- FAIL blocks the phase transition. The gap must be addressed before moving on.
- WARN is informational — present it but don't block.
- This is a quality gate, not a creativity gate. Don't block good designs because they don't perfectly match requirements wording — use judgment on semantic equivalence.
- Refer to the user as "The Brougham 22".
