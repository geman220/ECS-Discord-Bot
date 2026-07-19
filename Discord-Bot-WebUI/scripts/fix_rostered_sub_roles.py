#!/usr/bin/env python3
"""
Find (and optionally fix) rostered players who still carry a Pub League
substitute role/pool membership.

Why this exists: going forward the draft + admin-edit paths strip Classic/Premier
sub status when a player becomes rostered (see app/services/sub_status_service.py).
But players who were drafted/moved BEFORE that fix are stuck in the bad state —
e.g. "David Cravens": moved to Premier while still holding his Classic sub role,
which left a stale ECS-FC-PL-CLASSIC-SUB Discord role and blocked his Premier
role. This script cleans up that existing backlog.

"Rostered" = the player's primary_team_id points at a Classic or Premier team.
Substitutes never get primary_team_id set, so this cleanly separates rostered
players from genuine subs. ECS FC sub status is left untouched (a rostered
pub-league player may still legitimately sub for ECS FC).

SAFE to dry-run (default). With --fix it removes the conflicting sub pool row(s)
+ Flask role(s) in a single transaction and queues a Discord role reconcile so
the stale sub role is stripped from Discord too.

Run inside the webui container:
    docker exec -it webui python scripts/fix_rostered_sub_roles.py            # dry run
    docker exec -it webui python scripts/fix_rostered_sub_roles.py --fix      # apply
"""
import argparse
import sys

from app import create_app


PUB_LEAGUE_DIVISIONS = ('classic', 'premier')


def main():
    parser = argparse.ArgumentParser(
        description="Report/fix rostered players still holding a Pub League sub role")
    parser.add_argument('--fix', action='store_true',
                        help="Apply the cleanup (default: dry run / report only)")
    args = parser.parse_args()

    app = create_app()
    with app.app_context():
        from app.core import db
        from app.models import Player, Team, League
        from app.services.sub_status_service import (
            detect_conflicting_sub_status,
            remove_conflicting_sub_status,
            sub_status_removed,
        )

        session = db.session

        # Candidate = rostered on a Classic/Premier team (primary_team_id set).
        rostered = (
            session.query(Player)
            .join(Team, Player.primary_team_id == Team.id)
            .join(League, Team.league_id == League.id)
            .filter(db.func.lower(League.name).in_(PUB_LEAGUE_DIVISIONS))
            .all()
        )

        print(f"Scanning {len(rostered)} rostered Classic/Premier players...\n")

        conflicts = []
        for player in rostered:
            status = detect_conflicting_sub_status(session, player)
            if status['pool_league_types'] or status['role_names']:
                conflicts.append((player, status))

        if not conflicts:
            print("✓ No rostered players are holding a conflicting sub role/pool. Nothing to do.")
            return 0

        print(f"Found {len(conflicts)} rostered player(s) with a stale Pub League sub status:\n")
        for player, status in conflicts:
            team_name = player.primary_team.name if player.primary_team else '?'
            print(f"  • {player.name} (id={player.id}) rostered on '{team_name}'")
            if status['pool_league_types']:
                print(f"      sub pool(s):  {', '.join(status['pool_league_types'])}")
            if status['role_names']:
                print(f"      Flask role(s): {', '.join(status['role_names'])}")

        if not args.fix:
            print("\nDry run only. Re-run with --fix to remove these and reconcile Discord.")
            return 0

        print("\nApplying cleanup...")
        from app.tasks.tasks_discord import assign_roles_to_player_task
        fixed = 0
        reconcile_ids = []
        for player, _status in conflicts:
            summary = remove_conflicting_sub_status(session, player.id)
            if summary['pools_removed'] or summary['roles_removed']:
                fixed += 1
                if sub_status_removed(summary):
                    reconcile_ids.append(player.id)
                print(f"  ✓ {summary['player_name']}: "
                      f"pools={summary['pools_removed']} roles={summary['roles_removed']}")

        session.commit()
        print(f"\nCommitted cleanup for {fixed} player(s).")

        # Queue Discord reconcile (full add+remove) for anyone whose Flask sub role
        # was removed, so the stale Discord sub role is actually stripped.
        for pid in reconcile_ids:
            try:
                assign_roles_to_player_task.delay(player_id=pid, only_add=False)
            except Exception as e:
                print(f"  ! Failed to queue Discord reconcile for player {pid}: {e}")
        print(f"Queued {len(reconcile_ids)} Discord role reconcile task(s).")
        return 0


if __name__ == '__main__':
    sys.exit(main())
