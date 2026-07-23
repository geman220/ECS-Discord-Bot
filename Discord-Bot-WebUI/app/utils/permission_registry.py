# app/utils/permission_registry.py

"""
Permission registry — the single source of truth for what each fine-grained
permission actually *does*, and whether it is enforced anywhere in the code.

Why this exists
---------------
Access to admin *pages* in this app is role-NAME based (``@role_required(...)``,
used ~1300×). The ``Permission`` table / ``has_permission()`` check gates a
smaller, specific set of *content-level* capabilities inside the player, team
and match surfaces (e.g. can a coach see a player's admin notes, edit stats,
report a match). Those are the permissions listed below.

The Access Control → Permissions matrix reads this registry so it can:
  * show a plain description of what each permission controls ("Impacts"),
  * mark which permissions are actually ENFORCED in code vs. which are
    decorative rows that exist in the DB but gate nothing (honest, not theater),
  * group permissions by area for scanning.

Keep this in sync with the ``has_permission('...')`` / ``permission_required('...')``
call sites. A permission that appears in the DB but not here renders as
"not enforced" — that's a signal to either wire it up or delete it, not a bug.
"""

# name -> {label, impacts, category}
# `impacts` is written for a human deciding whether to grant it to a role.
PERMISSION_REGISTRY = {
    # ---- Player profiles ----
    'view_all_player_profiles': {
        'label': 'View All Player Profiles',
        'impacts': 'See every player’s profile page, not just teammates.',
        'category': 'Player profiles',
    },
    'edit_any_player_profile': {
        'label': 'Edit Any Player Profile',
        'impacts': 'Change name, contact and profile fields on anyone’s profile.',
        'category': 'Player profiles',
    },
    'edit_own_profile': {
        'label': 'Edit Own Profile',
        'impacts': 'Edit one’s own player profile fields.',
        'category': 'Player profiles',
    },
    'view_player_contact_info': {
        'label': 'View Player Contact Info',
        'impacts': 'Reveal email / phone on player profiles.',
        'category': 'Player profiles',
    },
    'view_player_admin_notes': {
        'label': 'View Player Admin Notes',
        'impacts': 'Read the private admin-notes section on a player’s 360 profile.',
        'category': 'Player profiles',
    },
    'edit_player_admin_notes': {
        'label': 'Edit Player Admin Notes',
        'impacts': 'Write/modify the private admin notes on a player’s profile.',
        'category': 'Player profiles',
    },
    'edit_player_stats': {
        'label': 'Edit Player Stats',
        'impacts': 'Adjust a player’s recorded goals / assists / cards.',
        'category': 'Player profiles',
    },

    # ---- Teams ----
    'add_player': {
        'label': 'Add Player To Team',
        'impacts': 'Add a player onto a team roster from the team page.',
        'category': 'Teams',
    },
    'upload_team_kit': {
        'label': 'Upload Team Kit',
        'impacts': 'Change a team’s kit/jersey image.',
        'category': 'Teams',
    },
    'view_team_record': {
        'label': 'View Team Record',
        'impacts': 'See the win/loss/draw record block on a team page.',
        'category': 'Teams',
    },

    # ---- Matches ----
    'view_match_page': {
        'label': 'View Match Page',
        'impacts': 'Open the detail page for a match.',
        'category': 'Matches',
    },
    'add_match': {
        'label': 'Add Match',
        'impacts': 'Create a new match/fixture from the team page.',
        'category': 'Matches',
    },
    'report_match': {
        'label': 'Report Match',
        'impacts': 'Submit or edit a match report (score + events).',
        'category': 'Matches',
    },
    'view_match_reporting': {
        'label': 'View Match Reporting',
        'impacts': 'See the match-reporting controls on a match.',
        'category': 'Matches',
    },
    'view_game_results': {
        'label': 'View Game Results',
        'impacts': 'See final scores / results on match and team pages.',
        'category': 'Matches',
    },
    'view_rsvps': {
        'label': 'View RSVPs',
        'impacts': 'See who has RSVP’d to a match.',
        'category': 'Matches',
    },

    # ---- Player detail cards / stats visibility ----
    'view_player_goals_assists': {
        'label': 'View Goals & Assists',
        'impacts': 'See the goals/assists numbers on player and team surfaces.',
        'category': 'Stats visibility',
    },
    'view_player_cards': {
        'label': 'View Discipline Cards',
        'impacts': 'See yellow/red card counts on player and team surfaces.',
        'category': 'Stats visibility',
    },
}

# The set of permission names that are actually checked somewhere in the code.
# Derived from the has_permission('...') / permission_required('...') call sites;
# these are exactly the registry keys above.
ENFORCED_PERMISSIONS = frozenset(PERMISSION_REGISTRY.keys())

# Stable display order for the categories.
CATEGORY_ORDER = ['Player profiles', 'Teams', 'Matches', 'Stats visibility', 'Other']


def describe_permission(name):
    """Return {label, impacts, category, enforced} for a permission name.

    Unknown permissions (present in the DB but not referenced anywhere in code)
    return enforced=False with a generic label so the matrix can flag them as
    decorative rather than silently implying they gate something.
    """
    entry = PERMISSION_REGISTRY.get(name)
    if entry:
        return {
            'label': entry['label'],
            'impacts': entry['impacts'],
            'category': entry['category'],
            'enforced': True,
        }
    return {
        'label': name,
        'impacts': 'Not referenced anywhere in the app — this permission gates nothing today.',
        'category': 'Other',
        'enforced': False,
    }


def build_permission_matrix(session):
    """Build the data the Permissions matrix renders.

    Returns a dict:
      {
        'roles':   [ {id, name}, ... ]            # every role, sorted by name
        'rows':    [ {name, label, impacts, category, enforced,
                      granted: {role_id: bool}}, ... ]   # sorted: enforced first, then name
        'categories': [category, ...]             # in CATEGORY_ORDER, only those present
        'counts':  {'permissions': N, 'enforced': N, 'decorative': N, 'roles': N}
      }

    The row set is the UNION of registry permissions and any Permission rows that
    exist in the DB — so both "enforced but not yet granted to anyone" and
    "granted in the DB but decorative" are visible. No fabrication: grant state
    comes straight from role.permissions.
    """
    from app.models.core import Role, Permission

    roles = session.query(Role).order_by(Role.name).all()
    role_list = [{'id': r.id, 'name': r.name} for r in roles]

    # Grants keyed by permission name -> set of role ids that hold it.
    grants = {}
    for r in roles:
        for p in (r.permissions or []):
            grants.setdefault(p.name, set()).add(r.id)

    db_perm_names = {p.name for p in session.query(Permission).all()}
    all_names = set(PERMISSION_REGISTRY.keys()) | db_perm_names | set(grants.keys())

    rows = []
    for name in all_names:
        d = describe_permission(name)
        held = grants.get(name, set())
        rows.append({
            'name': name,
            'label': d['label'],
            'impacts': d['impacts'],
            'category': d['category'],
            'enforced': d['enforced'],
            'granted': {r['id']: (r['id'] in held) for r in role_list},
        })

    # Enforced permissions first (they matter), then alphabetical.
    rows.sort(key=lambda x: (not x['enforced'], x['category'], x['name']))

    categories = [c for c in CATEGORY_ORDER if any(row['category'] == c for row in rows)]
    enforced_n = sum(1 for row in rows if row['enforced'])
    return {
        'roles': role_list,
        'rows': rows,
        'categories': categories,
        'counts': {
            'permissions': len(rows),
            'enforced': enforced_n,
            'decorative': len(rows) - enforced_n,
            'roles': len(role_list),
        },
    }
