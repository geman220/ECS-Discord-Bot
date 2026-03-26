# ADR: 20260316kh - Split CI Pipeline Strategy

## Status
Accepted

## Context
The project contains both a root-level Discord Bot and a sub-folder WebUI (`Discord-Bot-WebUI/`). The previous CI workflow (`test.yml`) ran WebUI tests (requiring Postgres and Redis services) on every change, including those that only affected the bot core. This was inefficient and slow.

## Decision
Split the CI into two specialized workflows:
1.  `bot-core-ci.yml`: Triggers only on changes to bot core files. It is lightweight and requires no external services.
2.  `test.yml` (WebUI): Restricted via `paths` filter to only trigger when files in `Discord-Bot-WebUI/` are modified.

## Consequences
- **Pros**: Reduced GitHub Actions consumption. Faster feedback loops for bot-only changes.
- **Cons**: Two CI files to maintain instead of one.
- **Maintenance**: Path filters must be updated if new top-level directories are added that require specific test suites.
