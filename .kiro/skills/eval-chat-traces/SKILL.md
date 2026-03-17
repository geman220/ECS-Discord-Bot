---
name: eval-chat-traces
description: Systematically review AI chat traces to find failure patterns using error analysis methodology (inspired by Hamel Husain's evals framework).
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Eval Chat Traces

Systematically review AI chat traces to find failure patterns using error analysis methodology (inspired by Hamel Husain's evals framework).

## Input

Optional: time range (default: last 7 days), sample size (default: 30 traces).

## Process

### Phase 1: Pull Traces

1. Query CloudWatch Logs Insights on `/aws/lambda/extralife-ai-engagement-agent` for `ChatQuery` logs.
2. Query for `ChatFeedback` logs from `/ecs/ExtraLifeWebAdmin`.
3. Prioritize: negative feedback traces first, then outliers (response_time_ms > P90, empty tools_invoked, error responses), then random sample to fill remaining.
4. For Athena deep dives: `SELECT * FROM extralife_chat_logs.chat_logs WHERE ...`

### Phase 2: Present Traces for Review

Present traces in a structured table for efficient binary judgment:

```
| # | Query (truncated) | Tools | Time | Len | Feedback | Verdict? |
|---|-------------------|-------|------|-----|----------|----------|
| 1 | "Any errors today?" | keeper_check | 24s | 1245 | 👎 | _____ |
```

**Prioritize presentation order**:
1. Negative feedback traces (pre-labeled failures) — review first
2. Outliers: response_time > 25s, empty tools_invoked, response_length < 200
3. Random sample to fill remaining

**Group by pattern** before asking for judgment:
- Guardrail queries (blocked correctly? → likely auto-PASS)
- Data queries (tool routed correctly? → needs judgment)
- System health queries (accurate? → needs judgment)
- Trivial/test queries (auto-PASS)

Offer: "I've pre-grouped these. Want to auto-PASS the guardrails and trivials, then focus judgment on the data and health queries?"

Ask The Brougham 22 for a binary **Pass/Fail** judgment on each trace, plus open-ended notes on what went wrong (if fail). Don't use Likert scales — binary forces clear thinking.

### Phase 3: Axial Coding

After reviewing all traces:
1. Group the failure notes into categories (e.g., "wrong agent routed", "stale data", "hallucinated participant", "slow response").
2. Count failures per category.
3. Present a failure taxonomy table sorted by frequency.

### Phase 4: Report

Output a summary:
```
| Failure Mode | Count | Example | Suggested Fix |
|-------------|-------|---------|---------------|
| ...         | ...   | ...     | ...           |
```

- Total traces reviewed
- Pass/fail ratio
- Top 3 failure modes with suggested fixes
- Recommendation: which failures warrant automated evals vs. prompt fixes

## Rules

- Binary pass/fail only — no 1-5 scales.
- Surface negative feedback traces first — they're pre-labeled failures.
- Focus on the first failure in each trace, not downstream cascades.
- Don't build automated evals for issues you can fix with a prompt change — fix the prompt first.
- Re-run every 2-4 weeks or after significant agent changes.
- Refer to the user as "The Brougham 22".
