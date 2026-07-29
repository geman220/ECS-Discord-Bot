# app/cli.py

"""
Command Line Interface (CLI) Module

This module defines CLI commands for the Flask application. In particular,
it provides commands to build and minify static assets, initialize Discord roles,
and synchronize player coach flags with Discord roles.
"""

import click
from flask.cli import with_appcontext
from flask import current_app

from app.core import db


@click.command()
@with_appcontext
def build_assets():
    """Build and minify assets."""
    assets = current_app.extensions['assets']
    for bundle in assets:
        bundle.build()


@click.command()
@with_appcontext
def init_discord_roles():
    """Initialize necessary Discord roles for the application."""
    import asyncio
    import aiohttp
    from app.models import Role
    from app.discord_utils import get_or_create_role

    click.echo("Initializing Discord roles...")
    
    # Ensure the pl-unverified role exists in the database
    try:
        # Check and create the database role
        unverified_role = Role.query.filter_by(name='pl-unverified').first()
        if not unverified_role:
            click.echo("Creating pl-unverified role in database...")
            unverified_role = Role(name='pl-unverified', description='Unverified player awaiting league approval')
            db.session.add(unverified_role)
            db.session.commit()
            click.echo("pl-unverified role created in database.")
        else:
            click.echo("pl-unverified role already exists in database.")
        
        # Create the Discord role
        async def create_discord_role():
            server_id = int(current_app.config['SERVER_ID'])
            click.echo(f"Checking Discord role in server {server_id}...")
            
            async with aiohttp.ClientSession() as session:
                # Check if the ECS-FC-PL-UNVERIFIED role exists
                unverified_role_id = await get_or_create_role(server_id, "ECS-FC-PL-UNVERIFIED", session)
                if unverified_role_id:
                    click.echo(f"ECS-FC-PL-UNVERIFIED role exists or was created with ID: {unverified_role_id}")
                else:
                    click.echo("Failed to create ECS-FC-PL-UNVERIFIED role on Discord")
        
        # Run the async function
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(create_discord_role())
        finally:
            loop.close()
            
        click.echo("Discord role initialization complete!")
        
    except Exception as e:
        click.echo(f"Error initializing Discord roles: {str(e)}")
        db.session.rollback()
        raise

@click.command()
@with_appcontext
def sync_coach_roles():
    """
    Sync player is_coach flags with Discord coach roles.
    
    This command checks all players with Discord IDs and ensures that:
    1. Players with Discord coach roles have is_coach=True in the database
    2. Players without Discord coach roles have is_coach=False in the database
    
    After updating the database, it triggers a full role sync for each player.
    """
    import asyncio
    import aiohttp
    import re
    from app.models import Player
    from app.utils.discord_request_handler import make_discord_request
    from app.tasks.tasks_discord import assign_roles_to_player_task
    from web_config import Config

    click.echo("Syncing coach roles between database and Discord...")
    
    # Create event loop for async operations
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Function to get all player Discord roles
    async def get_player_roles():
        players = Player.query.filter(Player.discord_id.isnot(None)).all()
        click.echo(f"Found {len(players)} players with Discord IDs")
        
        role_pattern = re.compile(r'.*COACH$')
        guild_id = current_app.config['SERVER_ID']
        player_roles = {}
        
        async with aiohttp.ClientSession() as session:
            for player in players:
                url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/members/{player.discord_id}/roles"
                try:
                    response = await make_discord_request('GET', url, session)
                    roles = []
                    if isinstance(response, list):
                        roles = response
                    elif response and 'roles' in response:
                        if isinstance(response['roles'], list):
                            roles = response['roles']
                        elif isinstance(response['roles'], dict):
                            roles = list(response['roles'].values())
                    
                    # Check if any role ends with "COACH"
                    has_coach_role = any(role_pattern.match(role) for role in roles if isinstance(role, str))
                    player_roles[player.id] = {
                        'player': player,
                        'has_coach_role': has_coach_role,
                        'roles': roles
                    }
                    click.echo(f"Player {player.name} {'has' if has_coach_role else 'does not have'} coach role")
                except Exception as e:
                    click.echo(f"Error getting roles for player {player.name}: {str(e)}")
        
        return player_roles
    
    try:
        # Get player roles
        player_roles = loop.run_until_complete(get_player_roles())
        
        # Update player is_coach flag based on Discord roles
        updated_players = 0
        
        for player_id, data in player_roles.items():
            player = data['player']
            has_coach_role = data['has_coach_role']

            if player.is_coach != has_coach_role:
                # Update both player.is_coach AND player_teams.is_coach to maintain consistency
                player.is_coach = has_coach_role

                # Update all team relationships for this player
                from sqlalchemy import text
                db.session.execute(
                    text("UPDATE player_teams SET is_coach = :is_coach WHERE player_id = :player_id"),
                    {"is_coach": has_coach_role, "player_id": player.id}
                )

                updated_players += 1
                click.echo(f"Updated player {player.name} is_coach to {has_coach_role}")

        if updated_players > 0:
            db.session.commit()
            click.echo(f"Updated is_coach flag for {updated_players} players")
        else:
            click.echo("No players needed is_coach flag updates")
        
        # Trigger role sync for all players to ensure Discord roles match database
        for player_id in player_roles:
            assign_roles_to_player_task.delay(player_id=player_id, only_add=False)
        
        click.echo("Role sync initiated for all players")
        
    except Exception as e:
        click.echo(f"Error syncing coach roles: {str(e)}")
        raise
    finally:
        loop.close()


@click.command()
@with_appcontext
def fix_duplicate_user_roles():
    """
    Fix duplicate entries in the user_roles table.

    This command identifies and removes duplicate user-role associations
    that can cause SQLAlchemy StaleDataErrors during user updates.
    """
    from sqlalchemy import text
    from app.core import db

    click.echo("Checking for duplicate user_roles entries...")

    # Find duplicates
    result = db.session.execute(text("""
        SELECT user_id, role_id, COUNT(*) as cnt
        FROM user_roles
        GROUP BY user_id, role_id
        HAVING COUNT(*) > 1
    """))

    duplicates = result.fetchall()

    if not duplicates:
        click.echo("No duplicate user_roles entries found.")
        return

    click.echo(f"Found {len(duplicates)} user-role combinations with duplicates:")

    total_removed = 0
    for user_id, role_id, count in duplicates:
        click.echo(f"  User {user_id}, Role {role_id}: {count} entries (removing {count - 1} duplicates)")

        # Delete all but one entry for each duplicate combination
        # We keep the first one by using ctid (PostgreSQL row identifier)
        db.session.execute(text("""
            DELETE FROM user_roles
            WHERE ctid IN (
                SELECT ctid FROM user_roles
                WHERE user_id = :user_id AND role_id = :role_id
                OFFSET 1
            )
        """), {'user_id': user_id, 'role_id': role_id})

        total_removed += count - 1

    db.session.commit()
    click.echo(f"Successfully removed {total_removed} duplicate entries.")


@click.command()
@with_appcontext
def regenerate_phone_hashes():
    """
    Regenerate phone_hash for all players with encrypted phones but missing hashes.

    Phone numbers are stored encrypted (encrypted_phone) with a searchable hash (phone_hash).
    If the hash is missing, SMS lookups will fail. This command regenerates missing hashes.
    """
    from app.core import db
    from app.models import Player
    from app.utils.pii_encryption import decrypt_value, create_hash

    click.echo("Checking for players with encrypted phones but missing phone_hash...")

    # Find players with encrypted_phone but no phone_hash
    players = Player.query.filter(
        Player.encrypted_phone.isnot(None),
        Player.encrypted_phone != '',
        (Player.phone_hash.is_(None) | (Player.phone_hash == ''))
    ).all()

    if not players:
        click.echo("All players with encrypted phones already have phone_hash values.")
        return

    click.echo(f"Found {len(players)} players needing phone_hash regeneration...")

    updated = 0
    errors = 0

    for player in players:
        try:
            # Decrypt the phone number
            decrypted_phone = decrypt_value(player.encrypted_phone)
            if decrypted_phone:
                # Generate and save the hash
                player.phone_hash = create_hash(decrypted_phone)
                updated += 1
                click.echo(f"  Updated phone_hash for player {player.id} ({player.name})")
            else:
                click.echo(f"  Warning: Could not decrypt phone for player {player.id} ({player.name})")
                errors += 1
        except Exception as e:
            click.echo(f"  Error processing player {player.id} ({player.name}): {e}")
            errors += 1

    if updated > 0:
        db.session.commit()
        click.echo(f"Successfully regenerated phone_hash for {updated} players.")

    if errors > 0:
        click.echo(f"Encountered {errors} errors.")


@click.command()
@with_appcontext
def add_user_roles_constraint():
    """
    Add unique constraint to user_roles table to prevent duplicate role assignments.

    This command:
    1. First removes any existing duplicate entries
    2. Then adds a UNIQUE constraint on (user_id, role_id)

    The constraint allows a user to have multiple different roles, but prevents
    the same role from being assigned twice to the same user.
    """
    from sqlalchemy import text
    from app.core import db

    click.echo("Adding unique constraint to user_roles table...")

    # First, remove any existing duplicates
    click.echo("Step 1: Checking for and removing any duplicate entries...")
    result = db.session.execute(text("""
        SELECT user_id, role_id, COUNT(*) as cnt
        FROM user_roles
        GROUP BY user_id, role_id
        HAVING COUNT(*) > 1
    """))
    duplicates = result.fetchall()

    if duplicates:
        click.echo(f"Found {len(duplicates)} duplicate combinations, removing...")
        for user_id, role_id, count in duplicates:
            db.session.execute(text("""
                DELETE FROM user_roles
                WHERE ctid IN (
                    SELECT ctid FROM user_roles
                    WHERE user_id = :user_id AND role_id = :role_id
                    OFFSET 1
                )
            """), {'user_id': user_id, 'role_id': role_id})
        db.session.commit()
        click.echo("Duplicates removed.")
    else:
        click.echo("No duplicates found.")

    # Check if constraint already exists
    click.echo("Step 2: Checking if constraint already exists...")
    result = db.session.execute(text("""
        SELECT constraint_name
        FROM information_schema.table_constraints
        WHERE table_name = 'user_roles'
        AND constraint_type = 'UNIQUE'
        AND constraint_name = 'unique_user_role'
    """))
    existing = result.fetchone()

    if existing:
        click.echo("Unique constraint 'unique_user_role' already exists.")
        return

    # Add the unique constraint
    click.echo("Step 3: Adding unique constraint...")
    try:
        db.session.execute(text("""
            ALTER TABLE user_roles
            ADD CONSTRAINT unique_user_role UNIQUE (user_id, role_id)
        """))
        db.session.commit()
        click.echo("Successfully added unique constraint 'unique_user_role' on (user_id, role_id).")
        click.echo("This prevents duplicate role assignments at the database level.")
    except Exception as e:
        db.session.rollback()
        click.echo(f"Error adding constraint: {e}")
        raise


@click.command()
@click.option('--dry-run', is_flag=True, help='Preview changes without updating database')
@with_appcontext
def sync_profile_pictures(dry_run):
    """
    Sync profile pictures from filesystem to database.

    Scans the profile_pictures directory, parses player IDs from filenames,
    and updates profile_picture_url for players whose pictures exist on disk
    but aren't recorded in the database.
    """
    import os
    import re
    from app.core import db
    from app.models import Player

    click.echo("Scanning profile pictures directory...")

    # Path to profile pictures
    profile_pics_dir = os.path.join(current_app.root_path, 'static/img/uploads/profile_pictures')

    if not os.path.exists(profile_pics_dir):
        click.echo(f"Profile pictures directory not found: {profile_pics_dir}")
        return

    # Get all PNG files
    files = [f for f in os.listdir(profile_pics_dir) if f.endswith('.png')]
    click.echo(f"Found {len(files)} image files")

    # Pattern to extract player ID from filename (last number before .png)
    # Handles: Name_Name_123.png, name_123.png, etc.
    pattern = re.compile(r'_(\d+)\.png$')

    updated_count = 0
    skipped_count = 0
    not_found_count = 0
    already_set_count = 0

    for filename in sorted(files):
        match = pattern.search(filename)
        if not match:
            click.echo(f"  Skipping (can't parse ID): {filename}")
            skipped_count += 1
            continue

        player_id = int(match.group(1))
        relative_url = f"/static/img/uploads/profile_pictures/{filename}"

        player = db.session.query(Player).get(player_id)
        if not player:
            click.echo(f"  Player ID {player_id} not found in database (file: {filename})")
            not_found_count += 1
            continue

        # Never point a player back at a legacy PNG once they're on the
        # hashed WebP variants (reencode-profile-pictures) — the PNG on disk
        # is a leftover original, not the source of truth.
        if player.profile_picture_url and player.profile_picture_url.endswith('_512.webp'):
            already_set_count += 1
            continue

        # Check if already set correctly
        if player.profile_picture_url == relative_url:
            already_set_count += 1
            continue

        # Check if set to something different or NULL
        if player.profile_picture_url and player.profile_picture_url != relative_url:
            click.echo(f"  {player.name} (ID {player_id}): DB has different URL")
            click.echo(f"    DB:   {player.profile_picture_url}")
            click.echo(f"    File: {relative_url}")

        click.echo(f"  Updating: {player.name} (ID {player_id}) -> {filename}")

        if not dry_run:
            player.profile_picture_url = relative_url
            updated_count += 1
        else:
            updated_count += 1

    if not dry_run and updated_count > 0:
        db.session.commit()
        click.echo(f"\nCommitted {updated_count} updates to database")

    click.echo(f"\n--- Summary ---")
    click.echo(f"Files scanned: {len(files)}")
    click.echo(f"Already correct: {already_set_count}")
    click.echo(f"{'Would update' if dry_run else 'Updated'}: {updated_count}")
    click.echo(f"Player not found: {not_found_count}")
    click.echo(f"Skipped (bad format): {skipped_count}")

    if dry_run:
        click.echo("\n(Dry run - no changes made. Remove --dry-run to apply.)")


@click.command()
@click.option('--dry-run', is_flag=True, help='Preview changes without writing files or updating the database')
@click.option('--delete-originals', is_flag=True, help='Delete the original image files after re-encoding')
@with_appcontext
def reencode_profile_pictures(dry_run, delete_originals):
    """
    One-time re-encode of existing profile pictures to sized WebP variants.

    Converts every locally-stored profile picture to the 512px + 128px WebP
    format that save_cropped_profile_picture now produces, and repoints
    profile_picture_url at the new hashed filename. External (http) URLs and
    already-converted pictures are skipped. Originals are kept unless
    --delete-originals is passed.
    """
    import os
    import re
    from PIL import Image
    from werkzeug.utils import secure_filename
    from app.core import db
    from app.models import Player
    from app.players_helpers import save_image_variants
    from app.image_cache_service import invalidate_player_image_cache

    players = db.session.query(Player).filter(
        Player.profile_picture_url.isnot(None),
        Player.profile_picture_url != ''
    ).order_by(Player.id).all()
    click.echo(f"Found {len(players)} players with a profile picture URL")

    converted = 0
    skipped_done = 0
    skipped_external = 0
    missing = 0
    failed = 0
    legacy_cleaned = 0
    bytes_before = 0
    bytes_after = 0
    originals_to_delete = set()

    for player in players:
        # Re-read the row right before processing so a web upload that lands
        # mid-run isn't clobbered by the URL loaded when the command started.
        if not dry_run:
            try:
                db.session.refresh(player)
            except Exception:
                # Row deleted mid-run — skip, don't abort the whole command
                db.session.rollback()
                continue
        url = (player.profile_picture_url or '').split('?', 1)[0]
        if not url:
            continue
        if url.endswith('_512.webp'):
            skipped_done += 1
            # Second pass with --delete-originals: remove the legacy PNG a
            # previous run without the flag left behind. Also defuses
            # sync-profile-pictures repointing players back at stale PNGs.
            if delete_originals:
                safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', player.name)
                legacy = os.path.join(
                    current_app.root_path, 'static/img/uploads/profile_pictures',
                    secure_filename(f"{safe_name}_{player.id}.png")
                )
                if os.path.isfile(legacy):
                    if dry_run:
                        click.echo(f"  Would delete legacy PNG for {player.name} (ID {player.id})")
                        legacy_cleaned += 1
                    else:
                        try:
                            os.remove(legacy)
                            legacy_cleaned += 1
                        except OSError as e:
                            click.echo(f"    Could not delete legacy {legacy}: {e}")
            continue
        if not url.startswith('/static/'):
            skipped_external += 1
            continue

        orig_path = os.path.join(current_app.root_path, url.lstrip('/'))
        if not os.path.isfile(orig_path):
            click.echo(f"  MISSING file for {player.name} (ID {player.id}): {url}")
            missing += 1
            continue

        orig_size = os.path.getsize(orig_path)
        if dry_run:
            click.echo(f"  Would convert {player.name} (ID {player.id}): {url} ({orig_size // 1024}KB)")
            converted += 1
            bytes_before += orig_size
            continue

        try:
            image = Image.open(orig_path).convert('RGBA')
            safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', player.name)
            base_slug = secure_filename(f"{safe_name}_{player.id}") or f"player_{player.id}"
            upload_folder = os.path.dirname(orig_path)
            url_prefix = os.path.dirname(url)

            # cleanup=False: originals are only removed in the deletion pass below
            new_url = save_image_variants(image, upload_folder, url_prefix, base_slug, cleanup=False)
            player.profile_picture_url = new_url

            # Old PlayerImageCache rows reference the pre-conversion file; drop
            # them so the draft board re-optimizes from the new WebP instead of
            # serving a stale thumbnail or failing on a dead original_url.
            invalidate_player_image_cache(player.id, db.session)

            # Commit per player: an interrupt can never leave a player half done,
            # and no original is deleted before its replacement URL is durable.
            db.session.commit()

            new_path = os.path.join(current_app.root_path, new_url.lstrip('/'))
            new_size = os.path.getsize(new_path)
            bytes_before += orig_size
            bytes_after += new_size
            converted += 1
            click.echo(f"  Converted {player.name} (ID {player.id}): {orig_size // 1024}KB -> {new_size // 1024}KB")

            if os.path.abspath(orig_path) != os.path.abspath(new_path):
                originals_to_delete.add(os.path.abspath(orig_path))
        except Exception as e:
            failed += 1
            db.session.rollback()
            click.echo(f"  FAILED {player.name} (ID {player.id}): {e}")

    # Deletion pass runs only after every conversion is committed, so a file
    # shared by several player rows (forked accounts) is still readable while
    # the later rows convert, and an interrupt never strands a committed URL.
    deleted = 0
    if delete_originals and not dry_run:
        for path in sorted(originals_to_delete):
            try:
                os.remove(path)
                deleted += 1
            except OSError as e:
                click.echo(f"    Could not delete original {path}: {e}")

    click.echo("\n--- Summary ---")
    click.echo(f"{'Would convert' if dry_run else 'Converted'}: {converted}")
    click.echo(f"Already converted: {skipped_done}")
    click.echo(f"External URL (skipped): {skipped_external}")
    click.echo(f"File missing: {missing}")
    click.echo(f"Failed: {failed}")
    if delete_originals:
        click.echo(f"Originals deleted: {deleted}, legacy PNGs cleaned: {legacy_cleaned}")
    if not dry_run and converted > 0:
        click.echo(f"Size: {bytes_before // 1024}KB -> {bytes_after // 1024}KB "
                   f"({100 - (bytes_after * 100 // max(bytes_before, 1))}% smaller, 512px variants only)")
    if dry_run:
        click.echo("\n(Dry run - no changes made. Remove --dry-run to apply.)")


@click.command()
@click.option('--program', 'program_key', required=True,
              help="Program key, e.g. 'pl_third'.")
@click.option('--reconcile', is_flag=True,
              help='DANGEROUS: also REVOKE roles the calculator does not expect. '
                   'Default is add-only, which can never strip anyone.')
@click.option('--dry-run', is_flag=True, help='List who would be synced; queue nothing.')
@with_appcontext
def sync_program_discord_roles(program_key, reconcile, dry_run):
    """Queue a Discord role sync for everyone in ONE program.

    The repair for "these N people never got their division role" — e.g. after a
    membership backfill, or after a program's Flask roles were granted out of
    band. Doing it one player at a time through the admin UI does not scale past
    about three people.

    ⚠️ ADD-ONLY BY DEFAULT. `only_add=True` means the batch GRANTS missing roles
    and never revokes, so a wrong expected-role calculation cannot strip anybody
    — including the Premier/Classic members who are not the target here. Pass
    --reconcile only when you deliberately want removals too.

    Membership: anyone holding one of the program's Flask roles (league, coach or
    sub), UNION anyone with a live membership row in the program's current
    season. The union matters — the two disagree exactly when something is
    broken, which is when you are running this.
    """
    from app.models import Player, User, Role, LeagueMembership
    from app.services import program_registry
    from app.utils.season_context import current_season_for_program
    from app.tasks.tasks_discord import process_discord_role_updates

    program = program_registry.by_key(program_key, include_inactive=True)
    if program is None:
        click.echo(f"No program with key '{program_key}'.")
        return

    flask_roles = [r for r in (program.flask_league_role, program.flask_coach_role,
                               program.flask_sub_role) if r]
    click.echo(f"Program: {program.display_name} ({program.key})")
    click.echo(f"Flask roles: {', '.join(flask_roles) or '(none)'}")

    players = {}

    if flask_roles:
        rows = (db.session.query(Player)
                .join(User, User.id == Player.user_id)
                .filter(User.roles.any(Role.name.in_(flask_roles)),
                        Player.discord_id.isnot(None))
                .all())
        for p in rows:
            players[p.id] = p
    by_role = len(players)

    season = current_season_for_program(program_key, db.session)
    if season is not None:
        rows = (db.session.query(Player)
                .join(LeagueMembership, LeagueMembership.player_id == Player.id)
                .filter(LeagueMembership.season_id == season.id,
                        LeagueMembership.league_type == program.membership_lane,
                        # terminal rows are people who LEFT — syncing them would
                        # be pointless at best and, under --reconcile, wrong.
                        ~LeagueMembership.status.in_(('inactive', 'retired', 'removed')),
                        Player.discord_id.isnot(None))
                .all())
        for p in rows:
            players[p.id] = p
        click.echo(f"Current season: {season.name} (id={season.id})")
    else:
        click.echo("WARNING: this program has no current season; matching on Flask roles only.")

    if not players:
        click.echo("\nNobody to sync. Either nobody holds this program's roles yet, "
                   "or none of them have a linked Discord account.")
        return

    click.echo(f"\n{len(players)} player(s) to sync "
               f"({by_role} by Flask role, {len(players) - by_role} more by membership):")
    for p in sorted(players.values(), key=lambda x: (x.name or '')):
        click.echo(f"  {p.id:>6}  {p.name}")

    mode = 'RECONCILE (adds AND revokes)' if reconcile else 'add-only (never revokes)'
    click.echo(f"\nMode: {mode}")

    if dry_run:
        click.echo("\n(Dry run - nothing queued.)")
        return

    discord_ids = [str(p.discord_id) for p in players.values() if p.discord_id]
    process_discord_role_updates.delay(discord_ids, only_add=not reconcile)
    click.echo(f"\nQueued a Discord role sync for {len(discord_ids)} player(s).")
    click.echo("It runs on the discord worker; follow it with:")
    click.echo("  docker logs -f ecs-discord-bot-celery-discord-worker-1")


@click.command()
@click.option('--batch-size', default=200, show_default=True,
              help='Players per committed batch. Smaller = shorter transactions.')
@click.option('--dry-run', is_flag=True, help='Compute everything, then roll back each batch.')
@with_appcontext
def backfill_league_membership(batch_size, dry_run):
    """Rebuild current-season league_membership rows for EVERY player.

    The spine is normally written only by per-player resync calls hanging off write paths,
    so any player nobody has edited since the season began has no row at all. This sweep
    closes that gap. Idempotent and safe to re-run; commits per batch, so an interrupt
    leaves consistent partial progress.

    Run after every season rollover, and whenever sql_check_league_membership_drift.sql
    reports missing rows.
    """
    from app.services.league_membership_sync import (
        backfill_all_memberships, _current_season_ids,
    )

    current = _current_season_ids(db.session)
    # Report EVERY current season by type, not just the two legacy lanes. The
    # backfill itself has always been program-aware (_season_for_lane resolves
    # per program), but this line named only Pub League and ECS FC — so running
    # it while chasing a missing Summer Sprint row printed a header that looked
    # like Summer was out of scope, when its rows were being written all along.
    _by_type = current.get('_by_season_type') or {}
    if _by_type:
        click.echo("Current seasons: " + ', '.join(
            f"{ltype}={sid}" for ltype, sid in sorted(_by_type.items())))
    else:
        click.echo(f"Current seasons: Pub League={current['pub_league']}, "
                   f"ECS FC={current['ecs_fc']}")
    # Ignore the '_by_season_type' bookkeeping key. `any(current.values())` was
    # true whenever that nested dict was non-empty -- which it almost always is
    # -- so the "nothing to do" guard was dead and both WARNING branches printed
    # together.
    _season_lists = [v for k, v in current.items() if not k.startswith('_')]
    if not any(_season_lists):
        click.echo("No current season for either program - nothing to do.")
        return
    if not current['pub_league']:
        click.echo("WARNING: no current Pub League season; only ECS FC rows will be written.")
    if not current['ecs_fc']:
        click.echo("WARNING: no current ECS FC season; only Pub League rows will be written.")

    if dry_run:
        click.echo("DRY RUN - every batch will be rolled back.\n")

    def _progress(done, total):
        click.echo(f"  {done}/{total} players...")

    stats = backfill_all_memberships(
        db.session, batch_size=batch_size, dry_run=dry_run, progress=_progress,
    )

    click.echo("\n--- Summary ---")
    click.echo(f"Players processed: {stats['players']}")
    click.echo(f"Batches:           {stats['batches']}")
    # The point of the dry run: what it WOULD create. Without this the summary
    # only proved the sweep did not crash, which is not the question anyone is
    # asking when they run it.
    click.echo(f"Membership rows {'to create' if dry_run else 'created':<10}: "
               f"{stats.get('rows_added', 0)}")
    # Retirements are the only existing-row change this makes. A non-zero number
    # here on a Pub League player means a source fact genuinely went away.
    click.echo(f"Rows {'to retire' if dry_run else 'retired':<21}: "
               f"{stats.get('rows_retired', 0)}")
    click.echo(f"Errors:            {stats['errors']}")
    if stats['errors']:
        click.echo("Some players failed - see the application log for tracebacks, then re-run.")
    if dry_run:
        click.echo("\n(Dry run - no changes committed. Remove --dry-run to apply.)")
    else:
        click.echo("\nNow re-run sql_check_league_membership_drift.sql; it should come back empty.")


@click.command()
@click.option('--dry-run', is_flag=True, help='Report what would change without renaming anything in Discord.')
@with_appcontext
def fix_ecs_fc_role_prefix(dry_run):
    """Repair ECS FC League team roles created under the wrong prefix.

    Team channels for ECS FC League used to create their per-team roles as
    "ECS-FC-LEAGUE-<team>-Player/-Coach", but every consumer of those names
    hardcodes "ECS-FC-PL-": get_expected_roles(), get_app_managed_roles(),
    rename_team_roles_async_only() and the reconcile allowlist. The result was a
    channel granting permissions to roles that nobody was ever assigned, so ECS FC
    League players could not see their own channel and coaches got no moderation.

    Channel creation is fixed going forward. This sweep repairs roles that already
    exist. Renaming preserves the Discord role ID, so the channel's permission
    overwrite keeps working and members keep the role.
    """
    import asyncio
    import os
    import aiohttp
    from app.discord_utils import rename_role, normalize_name
    from app.utils.discord_request_handler import make_discord_request
    from web_config import Config

    OLD_PREFIX = "ECS-FC-LEAGUE-"
    NEW_PREFIX = "ECS-FC-PL-"

    async def _run():
        guild_id = int(os.getenv('SERVER_ID'))
        async with aiohttp.ClientSession() as http:
            url = f"{Config.BOT_API_URL}/api/server/guilds/{guild_id}/roles"
            roles = await make_discord_request('GET', url, http)
            if not roles:
                click.echo("Could not fetch guild roles from the bot API. Is the bot running?")
                return

            by_normalized = {normalize_name(r['name']): r for r in roles}

            stale = [r for r in roles
                     if r['name'].startswith(OLD_PREFIX)
                     and (r['name'].endswith('-Player') or r['name'].endswith('-Coach'))]

            if not stale:
                click.echo("No ECS-FC-LEAGUE-* team roles found - nothing to repair.")
                return

            click.echo(f"Found {len(stale)} role(s) with the stale prefix.\n")

            renamed, conflicts = 0, []
            for role in sorted(stale, key=lambda r: r['name']):
                target = NEW_PREFIX + role['name'][len(OLD_PREFIX):]
                existing = by_normalized.get(normalize_name(target))

                if existing and str(existing['id']) != str(role['id']):
                    # The calculators already made their own role under the correct
                    # name and the members are on THAT one. Renaming would leave two
                    # roles sharing a name and make every by-name lookup ambiguous.
                    conflicts.append((role, existing, target))
                    click.echo(f"  CONFLICT {role['name']}")
                    click.echo(f"           '{target}' already exists (id {existing['id']}).")
                    continue

                if dry_run:
                    click.echo(f"  would rename {role['name']}  ->  {target}")
                else:
                    await rename_role(guild_id, role['id'], target, http)
                    click.echo(f"  renamed {role['name']}  ->  {target}")
                renamed += 1

            click.echo("\n--- Summary ---")
            click.echo(f"Renamed:   {renamed}")
            click.echo(f"Conflicts: {len(conflicts)}")

            if conflicts:
                click.echo(
                    "\nConflicts were NOT touched. For each one the correctly-named role\n"
                    "already holds the members, while the team channel's permission\n"
                    "overwrite still points at the stale (empty) role. Fix by repointing\n"
                    "the channel overwrite at the existing role id and updating\n"
                    "teams.discord_player_role_id / discord_coach_role_id to match,\n"
                    "then delete the stale role."
                )
            if dry_run:
                click.echo("\n(Dry run - no roles renamed. Remove --dry-run to apply.)")

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Summer Sprint season seeder
# ---------------------------------------------------------------------------
#
# The fixture list below is HAND-SPECIFIED rather than generated, on purpose.
#
# Counting the pairings it produces: A/B x2, C/D x2, A/C x2, B/D x2, A/D x2,
# B/C x2 -- every pair exactly twice, six games per team. A textbook double
# round-robin. But the WEEKLY distribution is 1, 2, 2, 1 games per team, and
# `auto_schedule_generator` constraint C2 (_validate_all_constraints) requires
# EXACTLY 2 games per team per week, with _generate_4_team_pairings always
# emitting 2. The generator therefore cannot express this season.
#
# Rather than relax a shared constraint that Premier and Classic depend on,
# this seeds the twelve fixtures directly. Nothing here reads or writes any
# other program's rows.

_SUMMER_TEAM_LETTERS = ['M', 'N', 'O', 'P']

# (date, venue, first-kickoff, [(home_letter, away_letter, slot_index), ...], week_type)
# slot_index 0 = first kickoff, 1 = second. Two fields, so same-slot matches
# run in parallel.
_SUMMER_WEEKS = [
    ('2026-08-02', 'Eagle Staff',       '11:30',
     [('A', 'B', 0), ('C', 'D', 0)],                                   'REGULAR'),
    ('2026-08-09', 'Eagle Staff',       '11:30',
     [('A', 'C', 0), ('B', 'D', 0), ('A', 'D', 1), ('B', 'C', 1)],     'REGULAR'),
    ('2026-08-16', 'Eckstein',          '11:00',
     [('A', 'B', 0), ('C', 'D', 0), ('A', 'C', 1), ('B', 'D', 1)],     'REGULAR'),
    ('2026-08-23', 'Eagle Staff',       '11:30',
     [('A', 'D', 0), ('B', 'C', 0)],                                   'REGULAR'),
    # Aug 30 is playoffs: bracket depends on standings, so no fixtures are
    # seeded. The week exists (dated, with its venue) so RSVPs and Discord
    # posting work; matches get filled in from the schedule editor.
    ('2026-08-30', 'Lower Woodland #2', '11:00', [],                    'PLAYOFF'),
]

# Aug 23 also has a "Randomizer/Fun game" after the two fixtures. Not modelled
# as a match: it has no fixed teams and no result. Add it as a FUN week row from
# the schedule editor if it needs to show on the calendar.

_SUMMER_SLOT_MINUTES = 80   # 70-minute match + 10-minute break, as Premier uses
_SUMMER_FIELDS = ['North', 'South']


@click.command()
@click.option('--season-name', default='2026 Summer', show_default=True)
@click.option('--dry-run', is_flag=True, help='Show what would be created, then roll back.')
@with_appcontext
def seed_summer_sprint(season_name, dry_run):
    """Create the Summer Sprint season: league, 4 teams, weeks and 12 fixtures.

    Idempotent -- re-running will not duplicate a season, league, team, week or
    match that already exists.

    Deliberately scoped: every query filters on this season's own league, so it
    cannot read or modify Premier, Classic or ECS FC. It also does NOT create
    Discord channels; run the normal team-resource task afterwards once you are
    happy with the roster.
    """
    from datetime import datetime as _dt, timedelta
    from app.models import Season, League, Team, Match, Schedule, WeekConfiguration
    from app.core.session_manager import managed_session

    with managed_session() as session:
        try:
            from app.services import program_registry
            # include_inactive: the whole point of this command is to set the
            # program up BEFORE it is switched on.
            program = program_registry.by_key('pl_third', include_inactive=True)
        except Exception:
            program = None
        if program is None:
            raise click.ClickException(
                "Program 'pl_third' not found. Run sql_create_program_registry.sql first."
            )

        season_type = program.season_league_type
        league_name = program.league_name

        # --- Flask roles --------------------------------------------------
        # Nothing else creates these. app/init/database.py seeds only
        # pl-unverified and pl-waitlist, so without this every downstream heal
        # degrades to a SILENT no-op rather than an error:
        #   player_division_service -> Role.filter_by(name=...).first() is None
        #   coach_assignment        -> draft coach auto-promotion never fires
        #   approvals               -> 404 "Role <name> not found"
        from app.models import Role
        for _role_name, _desc in (
            (program.flask_league_role, f'{program.display_name} player'),
            (program.flask_coach_role,  f'{program.display_name} division coach'),
            (program.flask_sub_role,    f'{program.display_name} substitute'),
        ):
            if not _role_name:
                continue
            if session.query(Role).filter_by(name=_role_name).first():
                click.echo(f"Role already exists: {_role_name}")
                continue
            session.add(Role(name=_role_name, description=_desc))
            session.flush()
            click.echo(f"Created role {_role_name}")

        # --- Season -------------------------------------------------------
        season = session.query(Season).filter_by(
            name=season_name, league_type=season_type).first()
        if season:
            click.echo(f"Season already exists: {season.name} (id={season.id})")
        else:
            season = Season(
                name=season_name, league_type=season_type,
                # NOT is_current: setting it here would be the only write that
                # could affect another program's "current season" resolution.
                # Flip it deliberately from the admin UI when the season opens.
                is_current=False,
                start_date=_dt.strptime(_SUMMER_WEEKS[0][0], '%Y-%m-%d').date(),
                end_date=_dt.strptime(_SUMMER_WEEKS[-1][0], '%Y-%m-%d').date(),
                phase='preseason',
            )
            session.add(season)
            session.flush()
            click.echo(f"Created season {season.name} (id={season.id}, "
                       f"league_type={season_type}, is_current=False)")

        # --- League -------------------------------------------------------
        league = session.query(League).filter_by(
            name=league_name, season_id=season.id).first()
        if league:
            click.echo(f"League already exists: {league.name} (id={league.id})")
        else:
            league = League(name=league_name, season_id=season.id)
            session.add(league)
            session.flush()
            click.echo(f"Created league {league.name} (id={league.id})")

        # --- Teams --------------------------------------------------------
        # M/N/O/P continues the existing scheme: Classic A-D, Premier E-L.
        teams_by_slot = {}
        for slot, letter in zip('ABCD', _SUMMER_TEAM_LETTERS):
            tname = f"Team {letter}"
            team = session.query(Team).filter_by(name=tname, league_id=league.id).first()
            if not team:
                team = Team(name=tname, league_id=league.id)
                session.add(team)
                session.flush()
                click.echo(f"Created team {tname} (id={team.id})  [slot {slot}]")
            else:
                click.echo(f"Team already exists: {tname} (id={team.id})  [slot {slot}]")
            teams_by_slot[slot] = team

        # --- Weeks + fixtures ---------------------------------------------
        created_matches = 0
        for idx, (date_str, venue, start_str, fixtures, week_type) in enumerate(_SUMMER_WEEKS, start=1):
            wdate = _dt.strptime(date_str, '%Y-%m-%d').date()
            wstart = _dt.strptime(start_str, '%H:%M').time()

            wc = session.query(WeekConfiguration).filter_by(
                league_id=league.id, week_date=wdate).first()
            if not wc:
                wc = WeekConfiguration(
                    league_id=league.id, week_date=wdate, week_type=week_type,
                    week_order=idx, venue=venue, start_time=wstart,
                    field_names=','.join(_SUMMER_FIELDS),
                    is_playoff_week=(week_type == 'PLAYOFF'),
                )
                session.add(wc)
                session.flush()
                click.echo(f"Week {idx}: {wdate} {venue} @ {start_str} ({week_type})")
            else:
                # Keep venue/time in step without clobbering a manual edit to
                # anything else on the row.
                wc.venue, wc.start_time = venue, wstart
                click.echo(f"Week {idx} already exists: {wdate} (venue/time refreshed)")

            for home_slot, away_slot, slot_idx in fixtures:
                home, away = teams_by_slot[home_slot], teams_by_slot[away_slot]
                mtime = (_dt.combine(wdate, wstart) +
                         timedelta(minutes=_SUMMER_SLOT_MINUTES * slot_idx)).time()
                field = _SUMMER_FIELDS[
                    sum(1 for h, a, s in fixtures
                        if s == slot_idx and (h, a) < (home_slot, away_slot)) % len(_SUMMER_FIELDS)
                ]

                existing = session.query(Match).filter_by(
                    date=wdate, home_team_id=home.id, away_team_id=away.id).first()
                if existing:
                    click.echo(f"    exists  {home.name} v {away.name} {mtime} {field}")
                    continue

                # Two Schedule rows per fixture (one per team's perspective) --
                # this mirror pair is what update_match/delete_match resolve on.
                sched_home = Schedule(week=str(idx), date=wdate, time=mtime,
                                      location=field, team_id=home.id,
                                      opponent=away.id, season_id=season.id)
                sched_away = Schedule(week=str(idx), date=wdate, time=mtime,
                                      location=field, team_id=away.id,
                                      opponent=home.id, season_id=season.id)
                session.add_all([sched_home, sched_away])
                session.flush()

                match = Match(date=wdate, time=mtime, location=field, venue=venue,
                              home_team_id=home.id, away_team_id=away.id,
                              schedule_id=sched_home.id, week_type='REGULAR')
                session.add(match)
                created_matches += 1
                click.echo(f"    created {home.name} v {away.name} {mtime} "
                           f"{venue} / {field}")

        # Start this program HIDDEN, explicitly.
        #
        # ⚠️ hide_until_reveal only marks a program as gate-ABLE. With no
        # make_teams_public:<key> row, teams_are_public(key) falls through to the
        # GLOBAL flag -- which is normally TRUE mid-season for Pub League. So
        # flipping is_active=TRUE while Pub League is revealed would publish this
        # program's rosters instantly, before its draft. A spoiled reveal cannot
        # be un-spoiled, so the seeder writes the override rather than trusting
        # an operator to run a SQL snippet at the right moment.
        from app.models.admin_config import AdminConfig
        from app.services.team_visibility import program_reveal_key
        _rk = program_reveal_key(program.key)
        if not session.query(AdminConfig).filter_by(key=_rk).first():
            session.add(AdminConfig(
                key=_rk, value='false',
                description=f'Reveal {program.display_name} team assignments.',
                category='pub_league', data_type='boolean', is_enabled=True))
            click.echo(f"  set {_rk} = false (rosters hidden until reveal)")

        if dry_run:
            session.rollback()
            click.echo(f"\n(Dry run - rolled back. Would have created {created_matches} matches.)")
        else:
            session.commit()
            AdminConfig._l2_invalidate()
            click.echo(f"\nDone. {created_matches} matches created.")
            click.echo("Next: set the season current when ready, draft/assign the "
                       "rosters, then create Discord resources for the 4 teams.")


@click.command()
@click.option('--program', 'program_key', required=True,
              help="Program key, e.g. 'pl_third'.")
@click.option('--apply-renames', is_flag=True,
              help='PATCH live Discord objects whose name no longer matches the registry.')
@click.option('--dry-run', is_flag=True, help='Report only; write nothing.')
@with_appcontext
def sync_program_discord(program_key, apply_renames, dry_run):
    """Bind a program's Discord category/role IDs, and optionally rename them.

    Run WITHOUT --apply-renames first: that only captures the snowflakes of
    objects it can match by name. Run it right after a program's Discord
    resources are created, while names still agree.

    Run WITH --apply-renames after changing a program's display name in the
    registry: it PATCHes each already-bound object to the new name. Renaming by
    ID preserves every member assignment and channel overwrite, which is exactly
    what the name-based get_or_create_* helpers cannot do -- they would create a
    duplicate and silently strip access.
    """
    from app.core.session_manager import managed_session
    from app.services.program_discord_sync import bind_program_discord_ids

    with managed_session() as session:
        report = bind_program_discord_ids(
            session, program_key, apply_renames=apply_renames, dry_run=dry_run)

        for item in report.get('bound', []):
            click.echo(f"  bound    {item['kind']:<9} {item['name']}  -> {item['id']}")
        for item in report.get('renamed', []):
            mark = 'RENAMED ' if item.get('applied') else 'would-be'
            click.echo(f"  {mark} {item['kind']:<9} {item['from']!r} -> {item['to']!r}")
        for item in report.get('unmatched', []):
            note = f"  ({item['note']})" if item.get('note') else ''
            click.echo(f"  no match {item['kind']:<9} {item['name']}{note}")
        for err in report.get('errors', []):
            click.echo(f"  ERROR    {err}")

        if dry_run:
            session.rollback()
            click.echo("\n(Dry run - nothing written.)")
        else:
            session.commit()
            # Invalidate AFTER the commit -- before it, a concurrent read in
            # this process would re-cache the pre-commit state for 300s.
            try:
                from app.services import program_registry
                program_registry.invalidate()
            except Exception:
                pass
            click.echo("\nDone.")
            if report.get('category_cache_cleared') or any(
                    r.get('applied') for r in report.get('renamed', [])):
                click.echo("⚠️  Renames applied. RESTART the webapp and Celery "
                           "workers: the registry cache and the Discord "
                           "category memo are process-local, so those "
                           "processes still hold the old names.")
        if not apply_renames and report.get('renamed'):
            click.echo("Names differ from the registry. Re-run with --apply-renames "
                       "to rename the live Discord objects in place.")


@click.command()
@click.option('--program', 'program_key', required=True, help="Program key, e.g. 'pl_third'.")
@click.option('--dry-run', is_flag=True, help='Show what would be created, then roll back.')
@with_appcontext
def seed_program_automations(program_key, dry_run):
    """Clone the league-scoped automation rules for one program.

    Rules are pinned to a `league_type` in their trigger_config and are
    SQL-seeded -- nothing in the app inserts SEEDED_RULES and there is no admin
    field for that value -- so a program with its own season type gets none.

    ⚠️ BUILT-IN (native_action) RULES ARE DELIBERATELY SKIPPED.

    `rsvp_dm_reminder` and `match_day_reminder` are native senders, and neither
    filters its recipients by league or season: `_dispatch_native` passes no
    league_type/season_id and the collectors query matches globally. A second
    copy therefore does not narrow anything -- it just sends everybody the same
    reminder TWICE. The admin UI refuses to copy them for exactly this reason
    (automations.py: "a second copy would send everybody the same reminder
    twice"); this command honours the same rule rather than routing around it.

    Cloned rules are always created DISABLED. Idempotent.
    """
    from app.core.session_manager import managed_session
    from app.models import AutomationRule
    from app.services.automation_defaults import SEEDED_RULES
    from app.services import program_registry

    with managed_session() as session:
        program = program_registry.by_key(program_key, include_inactive=True)
        if program is None:
            raise click.ClickException(f"No program with key '{program_key}'.")

        created = skipped = refused = 0
        for rule in SEEDED_RULES:
            cfg = dict(rule.get('trigger_config') or {})
            if 'league_type' not in cfg:
                continue    # not league-scoped; a clone would duplicate work

            if rule.get('native_action'):
                click.echo(f"  skipped  {rule['key']}  (built-in sender — a copy "
                           f"would double-send, it does not narrow by league)")
                refused += 1
                continue

            new_key = f"{rule['key']}__{program.key}"
            if session.query(AutomationRule).filter_by(key=new_key).first():
                click.echo(f"  exists   {new_key}")
                skipped += 1
                continue

            cfg['league_type'] = program.season_league_type
            session.add(AutomationRule(
                key=new_key,
                name=f"{rule['name']} ({program.display_name})"[:200],
                description=rule.get('description'),
                # ALWAYS disabled: an admin reviews and enables deliberately.
                enabled=False,
                trigger_type=rule['trigger_type'],
                trigger_config=cfg,
                delay_hours=rule.get('delay_hours', 24),
                audience_type=rule.get('audience_type', 'drafted_not_in_discord'),
                audience_config=rule.get('audience_config'),
                # subject/body_html are NOT NULL with no server default. Omitting
                # them let --dry-run pass (autoflush is off, so nothing flushed
                # before the rollback) and then blew up on the real commit.
                subject=rule.get('subject') or rule['name'],
                body_html=rule.get('body_html') or '',
                send_mode=rule.get('send_mode', 'individual'),
                force_send=rule.get('force_send', False),
                # channels is NOT NULL with a lambda default; passing an
                # explicit None risks tripping the constraint instead of taking
                # the default, so only set it when the source actually has one.
                **({'channels': rule['channels']} if rule.get('channels') else {}),
                **({'short_message': rule['short_message']}
                   if rule.get('short_message') else {}),
            ))
            # Flush now so a NOT NULL / type error surfaces during --dry-run
            # rather than only on the real commit.
            session.flush()
            created += 1
            click.echo(f"  created  {new_key}  (disabled, league_type={cfg['league_type']})")

        if dry_run:
            session.rollback()
            click.echo(f"\n(Dry run - rolled back. Would create {created}, "
                       f"skip {skipped}, refuse {refused}.)")
        else:
            session.commit()
            click.echo(f"\nDone. {created} created (all disabled), {skipped} already "
                       f"present, {refused} built-in rules skipped.")
            click.echo("Enable them at /admin-panel/communication/automations after review.")
