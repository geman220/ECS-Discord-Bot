---
name: audit-telemetry
description: Analyze local telemetry logs to produce metrics on skill usage, agent invocations, and workflow patterns.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Audit Telemetry

Analyze local telemetry logs to produce metrics on skill usage, agent invocations, and workflow patterns.

## Input

Optional: date range (default: last 7 days), focus area (e.g., "reviews", "subagents", "decisions").

## Process

### Phase 1: Load Logs

1. List all `.jsonl` files in `.kiro/telemetry/`.
2. Filter to the requested date range.
3. Parse all JSON lines into events.

### Phase 2: Compute Metrics

**Skill Usage:**
| Metric | How |
|--------|-----|
| Total skill invocations | Count `type: "skill"` events |
| Skills by frequency | Group by `skill`, count, sort descending |
| Average duration per skill | Mean `duration_sec` for completed events, grouped by skill |
| Skill success rate | `completed / (completed + failed)` per skill |
| Most common trigger | `user` vs `auto` (chained) ratio |

**Subagent Usage:**
| Metric | How |
|--------|-----|
| Total subagent invocations | Count `type: "subagent"` events |
| Agents by frequency | Group by `agent`, count |
| Average findings per review | Mean `findings` for review agents |
| Subagent failure rate | `failed / total` per agent |

**Review Decisions:**
| Metric | How |
|--------|-----|
| Total decisions | Count `type: "decision"` events |
| Agree/Disagree/Defer ratio | Group by `assessment`, count |
| Most disagreed categories | Group disagreements by skill/category |

**Workflow Patterns:**
| Metric | How |
|--------|-----|
| Skill chains | Count `type: "chain"` events, show most common chains |
| Average review iterations | Count review→fix loops per task |
| Time from implement start to commit | Duration between first `started` and last `completed` for a task |

### Phase 3: Compliance Check

Flag violations:
- Skills that ran without a `started` event (missing start log)
- Skills that have `started` but no `completed`/`failed` (abandoned or forgot to log)
- Subagent invocations without a parent skill (orphaned)
- Review cycles with zero decision events (rubber-stamped)

### Phase 4: Present Report

```
📊 Telemetry Report: 2026-02-19 to 2026-02-25

SKILL USAGE (last 7 days):
| Skill | Invocations | Avg Duration | Success Rate |
|-------|-------------|-------------|--------------|
| implement-and-review-loop | 8 | 7.2 min | 100% |
| review-code | 8 | 1.5 min | 87% |
| session-handoff | 5 | 0.5 min | 100% |
| validate-deployment | 3 | 2.1 min | 100% |
| push-and-pr | 3 | 0.8 min | 100% |

SUBAGENT USAGE:
| Agent | Invocations | Avg Findings | Failure Rate |
|-------|-------------|-------------|--------------|
| review-security | 8 | 2.1 | 0% |
| review-maintainability | 8 | 3.4 | 12% |
| review-test-quality | 8 | 1.8 | 0% |
| review-infrastructure | 8 | 0.9 | 0% |

REVIEW DECISIONS:
  Agree: 12 (35%) | Disagree: 18 (53%) | Defer: 4 (12%)
  Top disagreement: "DRY violation" (5 times)

COMPLIANCE:
  ✅ All skills logged start + end
  ⚠️ 1 subagent invocation without parent skill (2026-02-22)
  ✅ All review cycles have decision events
```

## Rules

- Read-only — this skill never modifies telemetry files.
- Present metrics, don't judge. Let The Brougham 22 draw conclusions.
- Flag compliance violations clearly — these indicate the logging rules aren't being followed.
- If no telemetry files exist, say so and remind that `.kiro/steering/telemetry.md` requires logging.
- Refer to the user as "The Brougham 22".
