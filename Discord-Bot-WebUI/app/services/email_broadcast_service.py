# app/services/email_broadcast_service.py

"""
Email Broadcast Service

Business logic for resolving recipients, creating campaigns,
personalizing content, and tracking progress.
"""

import logging
from datetime import datetime

from sqlalchemy import select, or_
from sqlalchemy.orm import joinedload

from app.core import db
from app.models.core import User, Role, Season, League, user_roles
from app.models.players import Player, Team, player_teams, PlayerTeamSeason
from app.models.wallet import WalletPass, WalletPassType
from app.models.email_campaigns import EmailCampaign, EmailCampaignRecipient
from app.models.pub_league_order import PubLeagueOrder, PubLeagueOrderLineItem


# email_notifications is nullable with a Python-side default, so rows created
# before the column existed (or via raw SQL) hold NULL. NULL means "never
# opted out" — only an explicit False excludes someone.
def _not_opted_out():
    return or_(User.email_notifications == True,  # noqa: E712
               User.email_notifications.is_(None))

logger = logging.getLogger(__name__)


class EmailBroadcastService:
    """Service for email broadcast operations."""

    def resolve_recipients(self, session, filter_criteria, force_send=False):
        """
        Resolve a list of recipient (user_id, display_name) tuples based on filter criteria.

        Args:
            session: Database session.
            filter_criteria (dict): Filter definition with 'type' key and optional params.
            force_send (bool): If True, include users with email_notifications=False.

        Returns:
            list[dict]: List of {'user_id': int, 'name': str} dicts.
        """
        filter_type = filter_criteria.get('type', 'all_active')

        # specific_users bypasses the base query filters - it targets exact user IDs
        if filter_type == 'specific_users':
            return self._resolve_specific_users(session, filter_criteria, force_send)

        base_query = session.query(User.id, User.username).filter(
            User.is_active == True,
            User.is_approved == True,
            User.encrypted_email.isnot(None),
        )

        if not force_send:
            base_query = base_query.filter(_not_opted_out())

        if filter_type == 'all_active':
            users = base_query.all()

        elif filter_type == 'current_season_players':
            # All players flagged as current (registered/active this season)
            sub = session.query(Player.user_id).filter(
                Player.is_current_player == True,
                Player.user_id.isnot(None),
            )
            users = base_query.filter(User.id.in_(sub.scalar_subquery())).all()

        elif filter_type == 'pub_league_purchasers':
            # Everyone attached to a non-cancelled Pub League order for the
            # current season: linked pass holders plus the purchasing account.
            # Deliberately bypasses base_query's is_approved gate — paid but
            # pending-approval players must still get season emails.
            current_season_ids = session.query(Season.id).filter(
                Season.league_type == 'Pub League',
                Season.is_current == True,
            )
            live_order_ids = session.query(PubLeagueOrder.id).filter(
                PubLeagueOrder.season_id.in_(current_season_ids.scalar_subquery()),
                PubLeagueOrder.status != 'cancelled',
            )
            linked_user_ids = session.query(Player.user_id).join(
                PubLeagueOrderLineItem,
                PubLeagueOrderLineItem.assigned_player_id == Player.id,
            ).filter(
                PubLeagueOrderLineItem.order_id.in_(live_order_ids.scalar_subquery()),
                Player.user_id.isnot(None),
            )
            assigned_user_ids = session.query(PubLeagueOrderLineItem.assigned_user_id).filter(
                PubLeagueOrderLineItem.order_id.in_(live_order_ids.scalar_subquery()),
                PubLeagueOrderLineItem.assigned_user_id.isnot(None),
            )
            purchaser_ids = session.query(PubLeagueOrder.primary_user_id).filter(
                PubLeagueOrder.id.in_(live_order_ids.scalar_subquery()),
                PubLeagueOrder.primary_user_id.isnot(None),
            )
            query = session.query(User.id, User.username).filter(
                User.is_active == True,
                User.encrypted_email.isnot(None),
                or_(
                    User.id.in_(linked_user_ids.scalar_subquery()),
                    User.id.in_(assigned_user_ids.scalar_subquery()),
                    User.id.in_(purchaser_ids.scalar_subquery()),
                ),
            )
            if not force_send:
                query = query.filter(_not_opted_out())
            users = query.all()

        elif filter_type == 'ecs_members':
            sub = session.query(WalletPass.user_id).join(
                WalletPassType, WalletPass.pass_type_id == WalletPassType.id
            ).filter(
                WalletPassType.code == 'ecs_membership',
                WalletPass.status == 'active',
                WalletPass.user_id.isnot(None),
            )
            users = base_query.filter(User.id.in_(sub.scalar_subquery())).all()

        elif filter_type == 'by_team':
            # Multi-select: team_ids (array) with backwards compat for team_id (single)
            team_ids = filter_criteria.get('team_ids', [])
            if not team_ids and filter_criteria.get('team_id'):
                team_ids = [filter_criteria['team_id']]
            team_ids = [int(tid) for tid in team_ids]
            if not team_ids:
                users = []
            else:
                sub = session.query(Player.user_id).join(
                    player_teams, Player.id == player_teams.c.player_id
                ).filter(
                    player_teams.c.team_id.in_(team_ids),
                    Player.is_current_player == True,
                    Player.user_id.isnot(None),
                )
                users = base_query.filter(User.id.in_(sub.scalar_subquery())).all()

        elif filter_type == 'by_league':
            # Multi-select: league_ids (array) with backwards compat for league_id (single)
            league_ids = filter_criteria.get('league_ids', [])
            if not league_ids and filter_criteria.get('league_id'):
                league_ids = [filter_criteria['league_id']]
            league_ids = [int(lid) for lid in league_ids]
            active_only = filter_criteria.get('active_only', False)
            if not league_ids:
                users = []
            else:
                sub = session.query(Player.user_id).filter(
                    Player.primary_league_id.in_(league_ids),
                    Player.user_id.isnot(None),
                )
                if active_only:
                    sub = sub.filter(Player.is_current_player == True)
                users = base_query.filter(User.id.in_(sub.scalar_subquery())).all()

        elif filter_type == 'by_role':
            # Multi-select: role_names (array) with backwards compat for role_name (single)
            role_names = filter_criteria.get('role_names', [])
            if not role_names and filter_criteria.get('role_name'):
                role_names = [filter_criteria['role_name']]
            if not role_names:
                users = []
            else:
                sub = session.query(user_roles.c.user_id).join(
                    Role, user_roles.c.role_id == Role.id
                ).filter(Role.name.in_(role_names))
                users = base_query.filter(User.id.in_(sub.scalar_subquery())).all()

        elif filter_type == 'by_discord_role':
            discord_role = filter_criteria.get('discord_role', '')
            if not discord_role:
                users = []
            else:
                # discord_roles is a JSON column on Player - filter in Python
                player_rows = session.query(Player.user_id, Player.discord_roles).filter(
                    Player.is_current_player == True,
                    Player.user_id.isnot(None),
                    Player.discord_roles.isnot(None),
                ).all()
                matching_user_ids = set()
                for user_id, roles in player_rows:
                    if isinstance(roles, list):
                        for r in roles:
                            role_name_val = r.get('name', '') if isinstance(r, dict) else str(r)
                            if role_name_val == discord_role:
                                matching_user_ids.add(user_id)
                                break
                if matching_user_ids:
                    users = base_query.filter(User.id.in_(matching_user_ids)).all()
                else:
                    users = []

        elif filter_type == 'rostered_this_season':
            user_ids = self._resolve_rostered(session, filter_criteria, coaches_only=False)
            users = base_query.filter(User.id.in_(user_ids)).all() if user_ids else []

        elif filter_type == 'coaches_this_season':
            user_ids = self._resolve_rostered(session, filter_criteria, coaches_only=True)
            users = base_query.filter(User.id.in_(user_ids)).all() if user_ids else []

        elif filter_type == 'no_discord_linked':
            # Deliberately simpler than drafted_not_in_discord: no roster join and
            # no bot round-trip. Catches registered-but-undrafted people that the
            # roster-based audience misses by construction.
            sub = session.query(Player.user_id).filter(
                Player.discord_id.is_(None),
                Player.is_current_player == True,  # noqa: E712
                Player.user_id.isnot(None),
            )
            users = base_query.filter(User.id.in_(sub.scalar_subquery())).all()

        elif filter_type == 'drafted_not_in_discord':
            user_ids = self._resolve_drafted_not_in_discord(session, filter_criteria)
            if user_ids:
                users = base_query.filter(User.id.in_(user_ids)).all()
            else:
                users = []

        else:
            logger.warning(f"Unknown filter type: {filter_type}")
            users = []

        return [{'user_id': u.id, 'name': u.username} for u in users]

    def _resolve_rostered(self, session, filter_criteria, coaches_only=False):
        """User ids of people on a team this season.

        Roster source is player_teams (the live roster) joined through
        Team -> League -> Season, which is the same shape
        _resolve_drafted_not_in_discord uses. PlayerTeamSeason is a snapshot that
        drifts when a mid-season move only touches player_teams, so it is not
        used here.

        coaches_only flips to player_teams.is_coach, which is the per-TEAM coach
        flag rather than Player.is_coach.
        """
        league_ids = filter_criteria.get('league_ids', [])
        if not league_ids and filter_criteria.get('league_id'):
            league_ids = [filter_criteria['league_id']]
        league_ids = [int(lid) for lid in league_ids]
        season_id = filter_criteria.get('season_id')

        q = (session.query(Player.user_id)
             .join(player_teams, player_teams.c.player_id == Player.id)
             .join(Team, Team.id == player_teams.c.team_id)
             .join(League, League.id == Team.league_id)
             .filter(Player.user_id.isnot(None)))

        if league_ids:
            q = q.filter(League.id.in_(league_ids))
        if season_id:
            q = q.filter(League.season_id == int(season_id))
        if not league_ids and not season_id:
            # Fall back to the CURRENT season rather than "everyone ever
            # rostered" -- this audience runs unattended.
            q = (q.join(Season, Season.id == League.season_id)
                 .filter(Season.is_current.is_(True)))

        if coaches_only:
            q = q.filter(player_teams.c.is_coach.is_(True))

        return [r[0] for r in q.distinct().all()]

    def _resolve_drafted_not_in_discord(self, session, filter_criteria):
        """User IDs of players rostered this season who are NOT in the Discord server.

        Roster source is player_teams (the live roster), season-scoped through
        Team -> League -> Season. PlayerTeamSeason is the durable snapshot and can
        drift when a mid-season move only touches player_teams, so it is not used
        here. DraftOrderHistory is not required either: its writes are explicitly
        best-effort (wrapped in a swallowed SAVEPOINT in the socket draft path),
        so an inner join would silently drop legitimately-rostered players.

        "Not in Discord" deliberately includes players with no discord_id at all --
        they have not linked an account, which is exactly the problem this email
        exists to fix.

        Args:
            session: Database session.
            filter_criteria (dict): Supports 'league_ids' (list) or 'league_id',
                'season_id', and 'include_coaches' (default False).

        Returns:
            list[int]: Matching user IDs.
        """
        league_ids = filter_criteria.get('league_ids', [])
        if not league_ids and filter_criteria.get('league_id'):
            league_ids = [filter_criteria['league_id']]
        league_ids = [int(lid) for lid in league_ids]
        season_id = filter_criteria.get('season_id')
        include_coaches = filter_criteria.get('include_coaches', False)

        q = (
            session.query(Player.user_id)
            .join(player_teams, player_teams.c.player_id == Player.id)
            .join(Team, Team.id == player_teams.c.team_id)
            .join(League, League.id == Team.league_id)
            .filter(Player.user_id.isnot(None))
        )

        if league_ids:
            q = q.filter(League.id.in_(league_ids))
        if season_id:
            q = q.filter(League.season_id == int(season_id))
        if not league_ids and not season_id:
            # Never fall back to "every player who was ever on a team".
            logger.warning("drafted_not_in_discord called without league_ids or season_id")
            return []

        if not include_coaches:
            # isnot(True), NOT is_(False): is_coach is nullable with only a
            # Python-side default, so legacy rows hold NULL and is_(False) would
            # silently drop those players from the audience.
            q = q.filter(player_teams.c.is_coach.isnot(True))

        # discord_in_server is nullable: NULL = never checked. Treat unknown as
        # "not in server" so nobody is silently skipped; the automation refreshes
        # stale rows against the bot before resolving, so NULL here means the
        # check genuinely could not be completed.
        q = q.filter(
            or_(Player.discord_id.is_(None),
                Player.discord_in_server.is_(None),
                Player.discord_in_server.is_(False))
        )

        return [row[0] for row in q.distinct().all()]

    def _resolve_specific_users(self, session, filter_criteria, force_send):
        """Resolve specific users by user_id list."""
        user_ids = filter_criteria.get('user_ids', [])
        if not user_ids:
            return []

        # Ensure ints
        user_ids = [int(uid) for uid in user_ids]

        query = session.query(User.id, User.username).filter(
            User.id.in_(user_ids),
            User.encrypted_email.isnot(None),
        )

        if not force_send:
            query = query.filter(_not_opted_out())

        users = query.all()
        return [{'user_id': u.id, 'name': u.username} for u in users]

    def create_campaign(self, session, data, created_by_id):
        """
        Create a campaign and populate recipient rows.

        Args:
            session: Database session.
            data (dict): Campaign data including name, subject, body_html,
                         send_mode, force_send, bcc_batch_size, filter_criteria.
            created_by_id (int): User ID of the creator.

        Returns:
            EmailCampaign: The created campaign.
        """
        force_send = data.get('force_send', False)
        filter_criteria = data['filter_criteria']

        recipients = self.resolve_recipients(session, filter_criteria, force_send)

        campaign = EmailCampaign(
            name=data['name'],
            subject=data['subject'],
            body_html=data['body_html'],
            template_id=data.get('template_id'),
            send_mode=data.get('send_mode', 'bcc_batch'),
            force_send=force_send,
            bcc_batch_size=data.get('bcc_batch_size', 100),
            filter_criteria=filter_criteria,
            filter_description=data.get('filter_description', ''),
            status='draft',
            total_recipients=len(recipients),
            created_by_id=created_by_id,
        )
        session.add(campaign)
        session.flush()  # Get campaign.id

        for r in recipients:
            recipient = EmailCampaignRecipient(
                campaign_id=campaign.id,
                user_id=r['user_id'],
                recipient_name=r['name'],
                status='pending',
            )
            session.add(recipient)

        session.flush()
        return campaign

    def personalize_content(self, session, subject, body, user_id):
        """
        Replace personalization tokens in subject and body.

        Supported tokens: {name}, {first_name}, {team}, {league}, {season}

        Args:
            session: Database session.
            subject (str): Email subject with tokens.
            body (str): Email body HTML with tokens.
            user_id (int): User ID to personalize for.

        Returns:
            tuple: (personalized_subject, personalized_body)
        """
        user = session.query(User).get(user_id)
        if not user:
            return subject, body

        player = session.query(Player).filter(Player.user_id == user_id).first()

        name = user.username or ''
        first_name = name.split()[0] if name else ''
        team_name = ''
        league_name = ''
        season_name = ''

        if player:
            if player.primary_team_id:
                team = session.query(Team).get(player.primary_team_id)
                if team:
                    team_name = team.name
            if player.primary_league_id:
                league = session.query(League).get(player.primary_league_id)
                if league:
                    league_name = league.name
                    if league.season:
                        season_name = league.season.name

        replacements = {
            '{name}': name,
            '{first_name}': first_name,
            '{team}': team_name,
            '{league}': league_name,
            '{season}': season_name,
        }

        p_subject = subject
        p_body = body
        for token, value in replacements.items():
            p_subject = p_subject.replace(token, value)
            p_body = p_body.replace(token, value)

        return p_subject, p_body

    def get_campaign_progress(self, session, campaign_id):
        """
        Get campaign progress counts.

        Returns:
            dict: {total, sent, failed, pending, status}
        """
        campaign = session.query(EmailCampaign).get(campaign_id)
        if not campaign:
            return None

        return {
            'id': campaign.id,
            'status': campaign.status,
            'total': campaign.total_recipients,
            'sent': campaign.sent_count,
            'failed': campaign.failed_count,
            'pending': campaign.total_recipients - campaign.sent_count - campaign.failed_count,
        }

    def build_filter_description(self, session, filter_criteria):
        """Build a human-readable description of the filter criteria."""
        filter_type = filter_criteria.get('type', 'all_active')

        if filter_type == 'all_active':
            return 'All active users'
        elif filter_type == 'current_season_players':
            return 'Current season players (all teams)'
        elif filter_type == 'pub_league_purchasers':
            return 'Pub League purchasers (current season orders, incl. pending approval)'
        elif filter_type == 'ecs_members':
            return 'ECS members (active membership)'
        elif filter_type == 'by_team':
            team_ids = filter_criteria.get('team_ids', [])
            if not team_ids and filter_criteria.get('team_id'):
                team_ids = [filter_criteria['team_id']]
            if team_ids:
                names = []
                for tid in team_ids:
                    team = session.query(Team).get(int(tid))
                    if team:
                        names.append(team.name)
                if len(names) <= 3:
                    return f'Teams: {", ".join(names)}'
                return f'Teams: {", ".join(names[:2])} +{len(names) - 2} more'
            return 'By team'
        elif filter_type == 'by_league':
            league_ids = filter_criteria.get('league_ids', [])
            if not league_ids and filter_criteria.get('league_id'):
                league_ids = [filter_criteria['league_id']]
            active_only = filter_criteria.get('active_only', False)
            suffix = ' (active only)' if active_only else ' (all players)'
            if league_ids:
                names = []
                for lid in league_ids:
                    league = session.query(League).get(int(lid))
                    if league:
                        names.append(league.name)
                if len(names) <= 3:
                    return f'Leagues: {", ".join(names)}{suffix}'
                return f'Leagues: {", ".join(names[:2])} +{len(names) - 2} more{suffix}'
            return 'By league'
        elif filter_type == 'by_role':
            role_names = filter_criteria.get('role_names', [])
            if not role_names and filter_criteria.get('role_name'):
                role_names = [filter_criteria['role_name']]
            if role_names:
                return f'Roles: {", ".join(role_names)}'
            return 'By role'
        elif filter_type == 'by_discord_role':
            return f'Discord role: {filter_criteria.get("discord_role", "Unknown")}'
        elif filter_type == 'rostered_this_season':
            return 'Everyone on a team this season'
        elif filter_type == 'coaches_this_season':
            return 'Coaches of teams this season'
        elif filter_type == 'no_discord_linked':
            return 'Active players with no Discord account linked'
        elif filter_type == 'drafted_not_in_discord':
            league_ids = filter_criteria.get('league_ids', [])
            if not league_ids and filter_criteria.get('league_id'):
                league_ids = [filter_criteria['league_id']]
            names = []
            for lid in league_ids:
                league = session.query(League).get(int(lid))
                if league:
                    names.append(league.name)
            scope = ', '.join(names) if names else 'current season'
            coaches = '' if filter_criteria.get('include_coaches') else ', excluding coaches'
            return f'Rostered players not in Discord ({scope}{coaches})'
        elif filter_type == 'specific_users':
            user_ids = filter_criteria.get('user_ids', [])
            count = len(user_ids)
            if count <= 3:
                names = []
                for uid in user_ids:
                    user = session.query(User.username).filter(User.id == int(uid)).first()
                    if user:
                        names.append(user.username)
                return f'Specific users: {", ".join(names)}'
            return f'Specific users ({count} selected)'
        return 'Custom filter'


email_broadcast_service = EmailBroadcastService()
