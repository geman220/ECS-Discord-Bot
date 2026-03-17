---
name: auto-memory
description: Capture learnings, patterns, and corrections discovered during this session into persistent project memory. This runs automatically at the end of `session-handoff` and can be invoked standalone.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Auto Memory

Capture learnings, patterns, and corrections discovered during this session into persistent project memory. This runs automatically at the end of `session-handoff` and can be invoked standalone.

## When to Run

- End of every session (chained from `session-handoff`)
- After a bug is found and fixed (capture the pattern)
- After a code review reveals a recurring issue
- When the user says "remember this" or "don't forget"

## Memory File

`.kiro/steering/memory.md` — loaded every session via steering, survives across sessions.

## Process

### Phase 1: Scan Session for Learnings

Review the conversation for:
1. **Bugs found** — what broke, why, how it was caught (e.g., "renderedHtml undefined in loadSession")
2. **API contract surprises** — values that didn't match docs (e.g., `"ENABLED"` vs `"enabled"`)
3. **Pattern corrections** — things the AI got wrong and had to be corrected (e.g., wrong payload format for Lambda invoke)
4. **Stakeholder preferences** — new preferences expressed this session
5. **Tool/SDK gotchas** — things that work differently than expected
6. **Review findings that recur** — if the same finding keeps coming up, it's a pattern to remember

### Phase 2: Deduplicate

Read existing `.kiro/steering/memory.md`. Don't add entries that are already captured.

### Phase 3: Append

Add new entries to the appropriate section. Each entry is one line with a date stamp:

```markdown
# Project Memory

## Bug Patterns
- [2026-02-25] loadSession() must set renderedHtml for assistant messages — template uses [innerHTML] not {{ content }}
- [2026-02-25] Lambda test invocations: payload is raw JSON, NOT wrapped in {"body": "..."} — .NET service sends direct

## API Contracts
- [2026-02-25] AgentCore Memory list_events returns events in reverse chronological order
- [2026-02-25] Bedrock reasoningConfig uses "ENABLED" not "enabled" — case-sensitive enum

## Stakeholder Preferences
- [2026-02-25] No image generation in AI chat
- [2026-02-25] No social media content generation in AI chat

## SDK Gotchas
- [2026-02-25] MemoryClient.list_events max_results default is 100, not unlimited

## Recurring Review Findings
- [2026-02-25] DRY violation in LambdaChatService Lambda invoke pattern — deferred, track for refactor

## Workflow Learnings
- [2026-02-25] Always verify deployed Lambda package contents, not just config timestamps
```

### Phase 4: Confirm

Print: "Updated `.kiro/steering/memory.md` with N new entries."

## Rules

- One line per learning. Keep it scannable.
- Include the date for temporal context.
- Don't duplicate — check before appending.
- Don't editorialize — state facts, not opinions.
- This file is loaded every session via steering — keep it under 200 lines. Archive old entries to `.kiro/context/memory-archive.md` if it grows too large.
- Refer to the user as "The Brougham 22".
