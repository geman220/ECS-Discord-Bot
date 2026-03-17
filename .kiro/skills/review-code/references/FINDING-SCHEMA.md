## Finding Schema (Typed Contract)

Every finding from every reviewer MUST conform to this schema. Findings that don't match are discarded with a warning.

```
{
  severity: "🔴" | "🟡" | "🟢",
  file: string,           // relative path
  line: number | null,    // line number if known
  issue: string,          // one-sentence description
  category: "security" | "maintainability" | "test-quality" | "infrastructure" | "performance",
  assessment: "agree" | "disagree" | "defer",
  reason: string,         // why this assessment (required for disagree/defer)
  auto_fixable: boolean,
  action: "fix" | "log" | "skip" | "escalate"
}
```

**Action schema** (constrained set — no other actions allowed):
- `fix` — apply the fix now (only for `agree` + `🔴`/`🟡`)
- `log` — record in spec but don't act (for `🟢` nits and `defer`)
- `skip` — discard (for `disagree`)
- `escalate` — present to user for manual decision (for ambiguous findings)

When parsing subagent output, extract findings into this schema. If a subagent returns prose instead of structured findings, parse it best-effort into the schema. If a finding can't be parsed, log it as `escalate` with the raw text.
