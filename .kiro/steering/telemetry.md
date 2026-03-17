# Telemetry

## ⚠️ MANDATORY — Every Skill and Agent Invocation Must Be Logged

All skill executions and subagent invocations MUST be logged to `.kiro/telemetry/`. This is non-negotiable. If you run a skill or invoke a subagent without logging, you are violating project policy.

## Log Format

Append one JSON line per event to `.kiro/telemetry/YYYY-MM-DD.jsonl` (one file per day).

### Skill Execution Event

```json
{"ts":"2026-02-25T14:05:00-08:00","type":"skill","skill":"implement-and-review-loop","mode":"interactive","task":"1.6","trigger":"user","duration_sec":null,"status":"started"}
{"ts":"2026-02-25T14:12:00-08:00","type":"skill","skill":"implement-and-review-loop","mode":"interactive","task":"1.6","trigger":"user","duration_sec":420,"status":"completed","outcome":"5 files changed, 7 tests added"}
```

### Subagent Invocation Event

```json
{"ts":"2026-02-25T14:06:00-08:00","type":"subagent","agent":"review-security","parent_skill":"review-code","files_reviewed":4,"status":"completed","findings":3,"duration_sec":15}
```

### Skill Chain Event (skill calling another skill)

```json
{"ts":"2026-02-25T14:05:30-08:00","type":"chain","from":"implement-and-review-loop","to":"guard-rails","reason":"Phase 1.5 verification"}
```

### Decision Event

```json
{"ts":"2026-02-25T14:08:00-08:00","type":"decision","skill":"review-code","finding":"DRY violation in LambdaChatService","assessment":"disagree","reason":"intentional duplication, 15 lines each"}
```

## Required Fields

| Field | Required | Description |
|-------|----------|-------------|
| `ts` | ✅ | ISO 8601 timestamp with timezone |
| `type` | ✅ | `skill`, `subagent`, `chain`, `decision` |
| `status` | ✅ | `started`, `completed`, `failed`, `skipped` |
| `skill` or `agent` | ✅ | Name of the skill or agent |
| `trigger` | For skills | `user` (explicit invocation) or `auto` (chained from another skill) |
| `duration_sec` | On completion | Wall clock seconds |
| `outcome` | On completion | One-line summary of what happened |

## When to Log

1. **Skill start**: Log `status: "started"` when entering a skill.
2. **Subagent invocation**: Log each subagent call with the parent skill.
3. **Skill chain**: Log when one skill delegates to another.
4. **Decision**: Log review assessments (agree/disagree/defer) with reasoning.
5. **Skill end**: Log `status: "completed"` or `"failed"` with duration and outcome.

## How to Log

Append to the day's file using `fs_write` with `append` command:

```
Path: .kiro/telemetry/YYYY-MM-DD.jsonl
Content: {"ts":"...","type":"skill",...}
```

## Rules

- One JSONL file per day. Never overwrite — always append.
- Log at the START and END of every skill. This lets us measure duration.
- **⚠️ COMPLETION IS MANDATORY: Every `started` entry MUST have a matching `completed` or `failed` entry. If you finish a skill and realize you forgot to log completion, log it immediately with estimated duration. A `started` without `completed` is a compliance violation.**
- **⚠️ INLINE LOGGING: Log completion IMMEDIATELY after the skill finishes — in the same turn, before moving to the next task. Do NOT defer logging to session-handoff. Deferred logging leads to missed entries.**
- Log every subagent invocation, even if it fails.
- Log every review decision (agree/disagree/defer) — this is the audit trail.
- Don't log file contents or secrets — just metadata.
- If a skill is skipped (e.g., "only docs changed, skipping full review"), log it as `status: "skipped"` with the reason.
- This directory is gitignored — telemetry stays local.
