---
name: improve-skill
description: Review the current chat session where a skill was used and improve it based on feedback.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Improve Skill

Review the current chat session where a skill was used and improve it based on feedback.

## Workflow

1. Review the conversation first to identify skill gaps:
   - Where the skill's output diverged from expectations
   - Missing steps that had to be done manually
   - Rules that were violated or missing
   - Output format issues
2. If gaps are obvious from context, propose the specific skills and fixes directly.
   If not clear, ask: "Which skill needs improvement?" and "What went wrong?"
3. Read the current skill file(s) from `.kiro/prompts/`.
4. Multiple skills can be improved in one pass — don't force one-at-a-time.
5. For each skill, describe the change and apply it. Formal diffs are optional —
   a clear description of what changed and why is sufficient.
6. After applying changes, summarize all improvements made.

## Rules

- Don't rewrite the entire skill — make targeted improvements.
- Preserve what's working well.
- Add examples from the current session where they clarify the improvement.
- When a rule was violated, strengthen the rule text (e.g., add ⚠️ MANDATORY markers)
  rather than just restating it.
- Prefer adding guardrails (hard gates, warnings) over relying on behavioral compliance.
- Refer to the user as "The Brougham 22".
