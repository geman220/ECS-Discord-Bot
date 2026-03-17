---
name: session-handoff
description: Generate a session handoff document capturing the current working state for the next session.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Session Handoff

Generate a session handoff document capturing the current working state for the next session.

## Workflow

1. Check `git status`, `git branch`, and `git log --oneline -5` for current state.
2. Review the conversation history to identify what was accomplished this session.
3. Write the handoff to `.kiro/context/session-handoff.md` (rolling file — overwrite each time).
4. **Update `CHANGELOG.md`**: Prepend today's date and a concise bulleted summary of "WHAT WE DID THIS SESSION" to `CHANGELOG.md` in the project root. If the file doesn't exist, create it with a `# Changelog` header.

## Required Sections

- **⚠️ BEFORE RESUMING**: Blockers that must be resolved before any work (e.g., expired credentials, Isengard re-auth, VPN, pending merges). This section goes first so the next session doesn't start broken.
- **IMMEDIATE NEXT STEPS**: Numbered list of what to do first next session (deploy, merge, test, etc.).
- **CURRENT STATE**: Branch name, clean/dirty, last commit, phase progress (X/Y tasks), test counts, live URLs.
- **WHAT WE DID THIS SESSION**: Each task completed with details, decisions made, bugs found and fixed.
- **WHAT'S REMAINING**: Table of next tasks with status and notes.
- **AWS RESOURCES**: Cloud resources with IDs, regions, and values (Lambda, S3, SSM params, etc.).
- **KEY FILES**: Table of important file paths grouped by area.
- **KEY DECISIONS**: Numbered list of architectural decisions to carry forward (with rationale).
- **STAKEHOLDER PREFERENCES**: Workflow preferences, naming conventions, review process.
- **MEMORY ENTRIES TO ADD**: Explicit list of new learnings from this session that should be added to `.kiro/steering/memory.md` via `auto-memory`. Format each as a one-liner with date prefix: `[YYYY-MM-DD] {learning}`. This section ensures `auto-memory` captures the right things even if the conversation history is long. Examples:
  - `[2026-03-12] BEDROCK_AGENTCORE_MEMORY_ID is a manual env var — agentcore deploy wipes it`
  - `[2026-03-12] docker buildx + setup-buildx-action required for arm64 cross-compilation on x86_64 runners — docker build alone ignores QEMU`
  - `[2026-03-12] agentcore deploy always builds arm64 via CodeBuild regardless of .bedrock_agentcore.yaml platform setting`

## Rules

- Be specific — include resource IDs, exact commands, and file paths.
- Document decisions and their rationale, not just what was done.
- Note any blockers or environment issues encountered.
- Include test commands for each test suite.
- Include the annual rollover procedure if event config was touched.
- After saving, confirm to the user: "Saved to `.kiro/context/session-handoff.md`."
- After saving, **IMMEDIATELY run the `auto-memory` skill** — do not wait to be asked. This is mandatory, not optional. Capture learnings from this session into `.kiro/steering/memory.md`.
5. **Compliance Audit**: 
   - Count the number of unique skill names mentioned in your responses for this session.
   - Cross-reference with today's `.jsonl` telemetry log.
   - If any invocation is missing a `started` or `completed` entry, backfill it immediately.
   - Report any gaps found and fixed in the final handoff summary.
- After auto-memory, remind the user: "Any skills need refining from this session? Run `improve-skill` if so."
- **Log telemetry** for both `session-handoff` and `auto-memory` skill invocations.
- Refer to the user as "The Brougham 22".
