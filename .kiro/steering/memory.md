# Project Memory

Persistent learnings for the ECS Discord Bot & WebUI project.

## Bug Patterns
- [2026-03-16] `find_customer_info_in_order` fails if `membership_year` is not explicitly passed and `datetime.datetime.now().year` doesn't match the order's membership string. Always pass the target year for verification.
- [2026-03-16] `utils.normalize_string` returns an empty string for non-string inputs. Ensure types are checked before further string operations.

## Stakeholder Preferences
- [2026-03-16] Refer to user as "The Brougham 22" (Keith Hodo, jersey #22, Seattle Sounders ultra, gamertag ssfcultra/ssfcultra74. Named after the Brougham End at Lumen Field where ECS stands).
- [2026-03-16] Prioritize ECS FC and Pub League management features over general Discord bot functionality.
- [2026-03-16] Always run 4-agent code review (never skip).
- [2026-03-16] Use implement-and-review-loop as default, not implement-task standalone.
- [2026-03-16] Log all skill/agent invocations to .kiro/telemetry/ (if telemetry is active).

## Workflow Learnings
- [2026-03-16] Always verify bot command registration in `ECS_Discord_Bot.py` when adding new command modules.
- [2026-03-16] WebUI tests should be run using `python run_tests.py` in the `Discord-Bot-WebUI/` directory to ensure environment variables are set correctly.
- [2026-03-16] When subagents fail to produce useful results, fall back to inline review in main conversation.
