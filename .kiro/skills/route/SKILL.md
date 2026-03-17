---
name: route
description: Detect user intent and automatically chain to the correct skill. This reduces the "which skill do I run?" friction and moves toward auto-activated skills.
metadata:
  author: cascadian-gamers
  version: "1.0"
---
# Route

Detect user intent and automatically chain to the correct skill. This reduces the "which skill do I run?" friction and moves toward auto-activated skills.

## When to Run

When the user gives a natural language request that maps to an existing skill but doesn't explicitly name it.

## Intent Map

| User Says (patterns) | Route To | Notes |
|---|---|---|
| "implement", "build", "code", "next task", "implement all" | `implement-and-review-loop` | Default entry point for all implementation |
| "review", "code review", "check my code" | `review-code` | Full 4-agent review |
| "quick review", "quick check", "glance" | `quick-review` | Fast checklist review |
| "design", "UI", "frontend", "layout", "sidebar", "brand", "CSS" | `design-frontend` | Front-end design and brand strategy |
| "visual review", "how does it look", "check the deploy", "UX issues" | `design-review` | Post-deploy visual review |

**⚠️ AUTO-TRIGGER: When the diff includes Angular template (`.html`) or CSS (`.css`) files, ALWAYS run `design-frontend` during the review phase — even if the user didn't ask for it. CSS changes are invisible to build/test gates.**
| "spec", "design", "plan a feature", "I want to build" | `create-spec` | Full pipeline: requirements → HLD → LLD → tasks |
| "requirements", "what should we build" | `requirements-doc` | Just the requirements phase |
| "high level design", "architecture" | `design-high-level` | Just the HLD phase |
| "low level design", "component design" | `design-low-level` | Just the LLD phase |
| "plan tasks", "break it down", "task plan" | `plan-tasks` | Just the task planning phase |
| "push", "PR", "pull request", "create PR" | `push-and-pr` | Commit, push, create PR |
| "validate", "verify deploy", "did it deploy" | `validate-deployment` | Post-deploy verification |
| "validate SQL", "check the proc", "run proc" | `run-sql-validation` | Stored procedure validation |
| "handoff", "save state", "end session", "wrap up", "changelog" | `session-handoff` | Save state + update `CHANGELOG.md` + sync memory |
| "resume", "where were we", "pick up", "load context" | `session-resume` | Resume from handoff |
| "remember this", "don't forget", "save learning" | `auto-memory` | Persist a learning |
| "improve skill", "fix the skill", "skill was wrong" | `improve-skill` | Refine a skill |
| "create skill", "new skill", "capture workflow" | `capture-skill` | Create a new skill |
| "eval traces", "check chat quality", "review traces" | `eval-chat-traces` | AI chat trace analysis |
| "validate handoff", "check spec", "spec integrity" | `validate-handoff` | Contract validation between phases |
| "run guard rails", "pre-commit check" | `guard-rails` | Deterministic build/test/secrets checks |
| "metrics", "telemetry", "audit", "how often", "skill usage" | `audit-telemetry` | Analyze skill/agent usage metrics |
| "security scan", "scan for secrets", "check for keys", "credential scan" | `security-scan` | Run git-secrets + gitleaks + trufflehog |
| "build", "deploy", "push to ECR", "rotate fargate", "build container" | `build-and-deploy` | Build container, push ECR, rotate Fargate |
| "model eval", "compare models", "test nova vs sonnet", "which model", "evaluate model" | `model-eval` | Side-by-side model comparison on identical queries |
| "close issue", "wrap up issue", "issue is done", "move to done" | `close-issue` | Verify tasks, group findings, deduplicate, create follow-ups, close |
| "evaluate", "should we use", "research service", "adopt", "bring in" | `research-service` | Evaluate AWS service/feature for adoption |

## Process

1. Read the user's message.
2. Match against the intent map above. Use fuzzy matching — the patterns are examples, not exact strings.
3. If a clear match: announce which skill you're running and proceed. Example: "Routing to `implement-and-review-loop` — let's build."
4. If ambiguous (matches multiple): present the top 2-3 options and ask.
5. If no match: respond normally without routing.

## Rules

- Don't over-route. If the user is asking a simple question ("what does this function do?"), just answer it.
- Don't route documentation/explanation requests to skills — skills are for workflows, not Q&A.
- When routing, always announce which skill you're using so the user knows.
- If the user explicitly names a skill, use that one — don't second-guess.
- Refer to the user as "The Brougham 22".
