---
name: session-resume
description: Resume a previous working session by loading the latest handoff context.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Session Resume

Resume a previous working session by loading the latest handoff context.

## Workflow

0. **Verify Steering Integrity**:
   - Check if `.gemini/GEMINI.md` is a symlink to `.kiro/steering/memory.md`. If it's a file or missing, suggest re-linking: `ln -sf ../.kiro/steering/memory.md .gemini/GEMINI.md`.
   - Verify `.gemini/settings.json` includes `.kiro/steering` in its search paths to ensure project-specific context is loaded.
1. Read all steering files from `.kiro/steering/` to load project context (structure, tech stack, branching rules, product overview).
2. Read all agent definitions from `.kiro/agents/` to understand available code review and automation agents.
3. Read all skill definitions from `.kiro/prompts/` to understand available workflows.
4. List files in `.kiro/context/` sorted by modification date (newest first).
3. Read the most recent `session-handoff.md` (the rolling latest) — if it doesn't exist, fall back to the most recent `issue-*-session-handoff-*.md` file.
5. Present a summary to The Brougham 22:
   - **Where we left off**: Current branch, phase, and immediate next steps
   - **What's live**: Key resources and endpoints
   - **What's next**: Top 3-5 action items from the handoff
   - **Blockers**: Anything that needs attention before resuming (expired creds, unpushed commits, etc.)
6. Run `git status` and `git branch` to confirm current state matches the handoff doc. Flag any discrepancies.
7. Ask: "Ready to pick up from here, The Brougham 22? Or do you want to pivot to something else?"

## Pre-Resume Checklist (manual)

Before running this skill, the user should:
1. Switch to preferred model: `/model`
2. Trust all tools: `/tools trust-all`

## Rules

- **Steering First**: Always verify that `.gemini/GEMINI.md` is correctly linked to the project memory before summarizing the state. Hallucinations often stem from stale or missing global context.
- Don't dump the entire handoff doc — summarize the actionable parts.
- If git state doesn't match the handoff, call it out clearly.
- If there are unpushed commits or uncommitted changes, mention them first.
- Load steering docs (`.kiro/steering/`) for project context but don't recite them.
- Carry forward stakeholder preferences from the handoff doc.
- Refer to the user as "The Brougham 22".
