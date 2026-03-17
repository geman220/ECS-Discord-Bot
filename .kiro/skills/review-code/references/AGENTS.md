# Review Agents

## Subagents (5 parallel)
- `review-security` — Auth, secrets, input validation, IAM, encryption
- `review-maintainability` — DRY, naming, separation of concerns, docs
- `review-test-quality` — Coverage gaps, edge cases, assertion quality
- `review-infrastructure` — CDK, IAM least-privilege, CloudFormation safety
- `review-performance` — Cold start, memory, latency, scaling

## Fallback
- `quick-review` — Fast checklist when subagents are unavailable

## Agent definitions
Located in `.kiro/agents/*.json`
