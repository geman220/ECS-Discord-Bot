#!/usr/bin/env python3
"""
Index-health gate — fails (exit 1) if the DB grows a NEW redundant index.

Why this exists: this database accumulated ~120 duplicate/redundant indexes
over years because indexes were added via ad-hoc pgAdmin SQL and never written
back into the models, producing idx_*/ix_*/*_key triplets on the same columns.
This script is the recurrence guard — wire it into CI or a pre-deploy step.

What it checks (mirrors sql/index_health.sql):
  1. EXACT DUPLICATES   — two+ indexes with identical columns on a table.
  2. COVERED SINGLES    — a non-partial single/short index whose columns are the
                          leading prefix of a longer non-partial composite.

Intentional, known-good overlaps (partial indexes, GIN-vs-btree) are allowlisted
below so they don't trip the gate. Add to ALLOWLIST only after confirming via
`pg_get_indexdef` that the overlap is deliberate.

Usage:
    DATABASE_URL=postgresql://... python scripts/check_index_health.py
    # exit 0 = clean, exit 1 = new redundancy found (prints offenders)

Connection: uses $DATABASE_URL, else the app's SQLAlchemy config. Read-only.
"""
import os
import sys

# Pairs/groups that are intentional overlaps — keyed by frozenset of index names.
# These are partial indexes or different access methods (GIN vs btree) that the
# column-only detectors flag but which serve genuinely different query shapes.
ALLOWLIST = {
    frozenset({"idx_notifications_user_unread", "idx_notifications_user_id_read_created_at"}),
    frozenset({"idx_player_name_active", "idx_player_name"}),
    frozenset({"idx_player_name_gin", "idx_players_name_lower"}),
    frozenset({"idx_team_name_gin", "idx_teams_name_lower"}),
    frozenset({"idx_substitute_requests_match_team", "uq_sub_request_open_match_team"}),
    frozenset({"idx_match_check_in_token_match", "idx_match_check_in_token_active"}),
    # Two redundant UNIQUE constraints left in place by choice (low-write tables):
    frozenset({"player_discord_id_key", "users_via_player_discord_uniq"}),
    frozenset({"draft_order_history_season_id_league_id_draft_position_key",
               "unique_draft_position_per_season_league"}),
}

EXACT_DUP_SQL = """
SELECT indrelid::regclass::text AS tbl,
       array_agg(indexrelid::regclass::text ORDER BY indexrelid) AS idxs
FROM pg_index
GROUP BY indrelid, indkey
HAVING count(*) > 1;
"""

COVERED_SINGLE_SQL = """
SELECT s.indrelid::regclass::text AS tbl,
       si.relname AS redundant,
       ki.relname AS covered_by
FROM pg_index s
JOIN pg_index k  ON s.indrelid = k.indrelid AND s.indexrelid <> k.indexrelid
JOIN pg_class si ON si.oid = s.indexrelid
JOIN pg_class ki ON ki.oid = k.indexrelid
WHERE NOT s.indisunique AND NOT s.indisprimary
  AND s.indpred IS NULL AND k.indpred IS NULL
  AND array_length(string_to_array(s.indkey::text, ' '), 1)
        < array_length(string_to_array(k.indkey::text, ' '), 1)
  AND (string_to_array(k.indkey::text, ' '))[1:array_length(string_to_array(s.indkey::text, ' '), 1)]
        = string_to_array(s.indkey::text, ' ');
"""


def _connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        # Fall back to the app's configured engine.
        from app import create_app  # noqa
        from app.core import db  # noqa
        app = create_app()
        with app.app_context():
            return db.engine.raw_connection()
    import psycopg2
    return psycopg2.connect(url)


def main() -> int:
    conn = _connect()
    cur = conn.cursor()

    offenders = []

    cur.execute(EXACT_DUP_SQL)
    for tbl, idxs in cur.fetchall():
        if frozenset(idxs) in ALLOWLIST:
            continue
        offenders.append(f"EXACT DUP   {tbl}: {', '.join(idxs)}")

    cur.execute(COVERED_SINGLE_SQL)
    for tbl, redundant, covered_by in cur.fetchall():
        if frozenset({redundant, covered_by}) in ALLOWLIST:
            continue
        offenders.append(f"COVERED     {tbl}: {redundant}  (prefix of {covered_by})")

    cur.close()
    conn.close()

    if offenders:
        print("Index health check FAILED — redundant indexes found:\n")
        for line in sorted(offenders):
            print("  " + line)
        print(
            "\nFix: drop the redundant index (keep the unique/composite), and remove its "
            "db.Index from the model. If the overlap is intentional (partial / GIN), add it "
            "to ALLOWLIST in this script with a comment explaining why."
        )
        return 1

    print("Index health check passed — no new redundant indexes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
