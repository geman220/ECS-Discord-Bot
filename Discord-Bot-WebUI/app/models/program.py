# app/models/program.py

"""
Program Registry
================

ONE row per program (Premier, Classic, ECS FC, and the new third Pub-League-like
program that launched as "Summer Sprint League"). This is the single source of
truth for everything that is currently hardcoded in six unsynchronised places:

    Season.league_type          'Pub League' | 'ECS FC'
    League.name                 'Premier' | 'Classic' | 'ECS FC'      (free text!)
    LeagueMembership.league_type 'classic' | 'premier' | 'ecs_fc'
    approval/admin form values  'classic' | 'premier' | 'ecs-fc' | 'sub-*'
    Flask role names            'pl-premier' | 'Premier Coach' | 'Premier Sub'
    Discord role/category names 'ECS-FC-PL-PREMIER' | 'ECS FC PL Premier'

Those vocabularies were bridged only by substring matching
(`league_membership_sync._norm_league_type`), which silently no-ops on a rename
-- see `player_division_service.py:57` which logs exactly that hazard. Every
column below exists because some call site currently derives it from a string
literal or a substring test.

WHY `key` IS OPAQUE
-------------------
`key` is the permanent identity and is NEVER shown to a human. `display_name` is
the only thing anyone reads. That split is the whole point: the third program is
expected to be renamed (Summer Sprint League -> Premier Plus or similar) once it
stops being a one-off, and a rename must be a single UPDATE, not a data
migration across league_membership lanes, Flask role names and Discord roles.

For the same reason the Discord columns store IDs *as well as* names. Discord
roles and categories are currently resolved BY NAME every time
(`discord_utils.get_or_create_role` / `get_or_create_category`, the latter behind
a process-global cache that is never invalidated), so renaming a category today
orphans the old one and silently creates a duplicate on the next worker restart.
Storing the id lets a rename be a PATCH against the same object, preserving every
member's role assignment.

STATUS: additive and behaviour-neutral on its own. Seeding the four rows from the
values already in the database changes nothing; call sites migrate onto
`app/services/program_registry.py` incrementally.
"""

from datetime import datetime

from app.core import db


class Program(db.Model):
    """A program/division and every identifier the rest of the app derives from it."""
    __tablename__ = 'program'
    __table_args__ = (
        db.UniqueConstraint('key', name='uq_program_key'),
        db.Index('ix_program_league_name', 'league_name'),
        db.Index('ix_program_season_league_type', 'season_league_type'),
        db.Index('ix_program_membership_lane', 'membership_lane'),
    )

    id = db.Column(db.Integer, primary_key=True)

    # --- identity -----------------------------------------------------------
    # Opaque + permanent. Never rendered. Renaming the program does NOT touch it.
    key = db.Column(db.String(32), nullable=False)
    # The only human-facing string. Safe to change at any time.
    display_name = db.Column(db.String(100), nullable=False)
    short_name = db.Column(db.String(32), nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=100)

    # --- binding onto the existing schema -----------------------------------
    # Season.league_type value this program's seasons carry. Programs sharing a
    # value share a season (Premier + Classic both live under 'Pub League');
    # a program needing its own dates/rollover cadence needs its own value.
    season_league_type = db.Column(db.String(50), nullable=False)
    # League.name value. This is unconstrained free text in the league table, so
    # it is stored here rather than matched by substring at ~40 call sites.
    league_name = db.Column(db.String(100), nullable=False)
    # LeagueMembership.league_type lane value (see league_membership.LEAGUE_TYPES).
    membership_lane = db.Column(db.String(16), nullable=False)
    # The value approval/admin forms and mobile payloads use ('classic', 'ecs-fc').
    form_value = db.Column(db.String(32), nullable=True)

    # --- Flask roles --------------------------------------------------------
    flask_league_role = db.Column(db.String(50), nullable=True)   # 'pl-premier'
    flask_coach_role = db.Column(db.String(50), nullable=True)    # 'Premier Coach'
    flask_sub_role = db.Column(db.String(50), nullable=True)      # 'Premier Sub'

    # --- Discord ------------------------------------------------------------
    # Slug inserted into ECS-FC-PL-{slug}. Kept separate from `key` because the
    # existing guild uses 'ECS-FC' where the key is 'ecs_fc'.
    discord_role_slug = db.Column(db.String(32), nullable=True)
    discord_category_name = db.Column(db.String(100), nullable=True)
    # Prefer the id over the name at resolve time -- see module docstring.
    discord_category_id = db.Column(db.String(30), nullable=True)
    discord_division_role_id = db.Column(db.String(30), nullable=True)
    discord_coach_role_id = db.Column(db.String(30), nullable=True)
    discord_sub_role_id = db.Column(db.String(30), nullable=True)
    # ECS FC's sub role is ECS-FC-LEAGUE-SUB, not ECS-FC-PL-ECS-FC-SUB. Rather
    # than special-case it in the calculator, the exception is stored.
    discord_sub_role_name = db.Column(db.String(100), nullable=True)

    # --- SeasonConfiguration.league_type ------------------------------------
    # A seventh vocabulary: uppercase with an underscore ('PREMIER', 'CLASSIC',
    # 'ECS_FC'). Derived today by an else-chain that DEFAULTS to 'ECS_FC'
    # (auto_schedule_routes.py:78), so a new program would silently inherit ECS
    # FC's week counts and playoff structure. Cannot be derived from
    # discord_role_slug -- that is 'ECS-FC' (hyphen), this is 'ECS_FC'.
    season_config_type = db.Column(db.String(20), nullable=True)

    # --- behaviour flags ----------------------------------------------------
    # Replaces `Season.league_type == 'Pub League'` (~20 queries) and the three
    # separate `PUB_LEAGUE_TYPES = ('Classic','Premier')` tuples.
    is_pub_league_like = db.Column(db.Boolean, nullable=False, default=True)
    uses_draft = db.Column(db.Boolean, nullable=False, default=True)
    uses_schedule_generator = db.Column(db.Boolean, nullable=False, default=True)
    # ECS FC lets one player sit on several teams in the same league; Pub League
    # does not (`ecs_fc.is_ecs_fc_league` is currently a substring test).
    allows_multi_team = db.Column(db.Boolean, nullable=False, default=False)
    # ECS FC players are approval-activated and never pay, so is_current_player
    # must not gate them -- see reference_is_current_player_is_a_paywall.
    requires_pass = db.Column(db.Boolean, nullable=False, default=True)
    # ECS FC runs one continuous season and is exempt from rollover + phase
    # auto-advance.
    rolls_over = db.Column(db.Boolean, nullable=False, default=True)
    # Whether team assignments are hidden until make_teams_public is flipped.
    hide_until_reveal = db.Column(db.Boolean, nullable=False, default=True)
    # Whether Discord channels/roles are torn down at rollover (ECS FC: no).
    discord_cleanup_on_rollover = db.Column(db.Boolean, nullable=False, default=True)

    # --- WooCommerce --------------------------------------------------------
    # CSV of Woo product ids. Matching on product ID rather than a name regex is
    # the fix for the Summer product, whose title contains neither
    # (Spring|Fall) nor (Classic|Premier) and therefore matches nothing today.
    woo_product_ids = db.Column(db.String(255), nullable=True)
    woo_product_slug = db.Column(db.String(255), nullable=True)
    # Regex matched against the Woo product NAME. Fallback for orders that
    # arrive before an admin fills in woo_product_ids.
    woo_name_pattern = db.Column(db.String(255), nullable=True)

    # --- presentation -------------------------------------------------------
    color = db.Column(db.String(16), nullable=True)
    icon = db.Column(db.String(64), nullable=True)

    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow, onupdate=datetime.utcnow)

    # ------------------------------------------------------------------ derived
    @property
    def division_role_name(self):
        """e.g. 'ECS-FC-PL-PREMIER'. None when the program has no Discord slug."""
        return f"ECS-FC-PL-{self.discord_role_slug}" if self.discord_role_slug else None

    @property
    def coach_role_name(self):
        """e.g. 'ECS-FC-PL-PREMIER-COACH'."""
        return f"ECS-FC-PL-{self.discord_role_slug}-COACH" if self.discord_role_slug else None

    @property
    def sub_role_name(self):
        """e.g. 'ECS-FC-PL-PREMIER-SUB', or the stored override for ECS FC."""
        if self.discord_sub_role_name:
            return self.discord_sub_role_name
        return f"ECS-FC-PL-{self.discord_role_slug}-SUB" if self.discord_role_slug else None

    @property
    def woo_product_id_list(self):
        """woo_product_ids parsed to a list of ints; [] when unset or malformed."""
        raw = (self.woo_product_ids or '').strip()
        if not raw:
            return []
        out = []
        for chunk in raw.split(','):
            chunk = chunk.strip()
            if chunk.isdigit():
                out.append(int(chunk))
        return out

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'display_name': self.display_name,
            'short_name': self.short_name,
            'sort_order': self.sort_order,
            'season_league_type': self.season_league_type,
            'league_name': self.league_name,
            'membership_lane': self.membership_lane,
            'form_value': self.form_value,
            'flask_league_role': self.flask_league_role,
            'flask_coach_role': self.flask_coach_role,
            'flask_sub_role': self.flask_sub_role,
            'discord_role_slug': self.discord_role_slug,
            'discord_category_name': self.discord_category_name,
            'discord_category_id': self.discord_category_id,
            'discord_sub_role_name': self.discord_sub_role_name,
            'season_config_type': self.season_config_type,
            'division_role_name': self.division_role_name,
            'coach_role_name': self.coach_role_name,
            'sub_role_name': self.sub_role_name,
            'is_pub_league_like': self.is_pub_league_like,
            'uses_draft': self.uses_draft,
            'uses_schedule_generator': self.uses_schedule_generator,
            'allows_multi_team': self.allows_multi_team,
            'requires_pass': self.requires_pass,
            'rolls_over': self.rolls_over,
            'hide_until_reveal': self.hide_until_reveal,
            'discord_cleanup_on_rollover': self.discord_cleanup_on_rollover,
            'color': self.color,
            'icon': self.icon,
            'is_active': self.is_active,
        }

    def __repr__(self):
        return f"<Program {self.key} ({self.display_name})>"
