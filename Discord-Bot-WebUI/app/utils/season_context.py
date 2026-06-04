# app/utils/season_context.py

"""
Season / league context resolution for admin pages.

Background
----------
Both Pub League and ECS FC have their own ``is_current=True`` Season row
(``Season.league_type`` is 'Pub League' or 'ECS FC'). So the very common

    Season.query.filter_by(is_current=True).first()

returns an ARBITRARY current season — frequently the ECS FC one — which makes
Pub-League pages (standings, league table, schedule between our internal teams)
silently show empty/wrong data. The ``publeague`` blueprint resolves this
correctly in a ``before_request`` (g.current_pub_league_season), but that hook
does NOT run for ``admin_panel`` routes.

This module gives admin routes a single, league-scoped resolver. Pub-League is
an internal league (Match = home_team vs away_team) with rotating seasons and a
real Standings table, so its pages default to the current Pub League season and
allow picking PAST seasons for history via ?season_id=. ECS FC is a set of
disjoint teams playing EXTERNAL opponents (EcsFcMatch.opponent_name) with no
league table — it keeps its own team-centric section and is not toggled onto
Pub-League pages.
"""

PUB_LEAGUE = 'Pub League'
ECS_FC = 'ECS FC'


def current_pub_league_season():
    """The current Pub League season (league_type-scoped), or None."""
    from app.models import Season
    return Season.query.filter_by(is_current=True, league_type=PUB_LEAGUE).first()


def pub_league_seasons():
    """All Pub League seasons, newest first — for the season-history dropdown."""
    from app.models import Season
    return Season.query.filter_by(league_type=PUB_LEAGUE).order_by(Season.id.desc()).all()


def resolve_pub_league_season(season_id=None):
    """Return the selected Pub League season.

    If ``season_id`` is given and is a valid Pub League season, return that
    (historical view); otherwise fall back to the current Pub League season.
    Never returns an ECS FC season.
    """
    from app.models import Season
    if season_id not in (None, '', 'current'):
        try:
            sid = int(season_id)
        except (TypeError, ValueError):
            sid = None
        if sid:
            s = Season.query.filter_by(id=sid, league_type=PUB_LEAGUE).first()
            if s:
                return s
    return current_pub_league_season()


def pub_league_season_context(season_id=None):
    """Convenience for a page + its selector.

    Returns ``(selected_season, seasons)`` where ``selected_season`` is the
    historical-or-current Pub League season and ``seasons`` is the full
    newest-first list for the dropdown. ``request.args.get('season_id')`` is the
    expected source for ``season_id``.
    """
    return resolve_pub_league_season(season_id), pub_league_seasons()
