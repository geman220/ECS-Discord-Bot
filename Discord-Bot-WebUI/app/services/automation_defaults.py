# app/services/automation_defaults.py

"""
Default copy and configuration for seeded automation rules.

Kept in code (not only in the DB) so the admin UI can offer "reset to default
copy" after someone edits a rule into a corner. The seeded DB rows are created
from these by sql_create_automation_rules.sql; this module stays the source of
truth for the defaults themselves.

Bodies are the INNER content of the email. The EmailTemplate wrapper supplies
the ECS header/footer at send time, so no <html> or <body> tags belong here.
Personalization tokens ({first_name}, {name}, {team}, {league}, {season}) are
substituted per-recipient by email_broadcast_service.personalize_content, which
only runs in 'individual' send mode.

{discord_invite_url} and {support_email} are NOT personalization tokens -- they
are substituted by automation_service at dispatch time from AdminConfig, so the
invite link can be rotated in one place.
"""

SUPPORT_EMAIL = 'ecspubleague@gmail.com'
DEFAULT_DISCORD_INVITE = 'https://discord.gg/weareecs'


DRAFT_DISCORD_INVITE_SUBJECT = "You're on a team — come join us on Discord"

DRAFT_DISCORD_INVITE_BODY = """
<p style="font-size:18px;margin:0 0 16px;"><strong>Hey {first_name}, you've been drafted!</strong></p>

<p>The {league} draft is done and you're officially on <strong>{team}</strong> for {season}.
Preseason nerves, new teammates, the whole thing — it starts now.</p>

<p>One catch: <strong>we can't find you on our Discord.</strong> That's where basically
everything happens — your team's channel, weekly match times and field locations,
last-minute changes, sub requests when you can't make it, and the general nonsense
between matches. If you're not in there, you're going to miss things that matter.</p>

<p style="text-align:center;margin:32px 0;">
  <a href="{discord_invite_url}"
     style="display:inline-block;background:#1a472a;color:#ffffff;text-decoration:none;
            padding:14px 32px;border-radius:8px;font-size:16px;font-weight:bold;">
    Join the ECS Discord
  </a>
</p>

<p style="font-size:14px;color:#6c757d;">
  Or paste this into your browser: {discord_invite_url}
</p>

<h3 style="margin:28px 0 8px;font-size:16px;">Once you're in</h3>
<ul style="margin:0 0 16px;padding-left:20px;">
  <li>Head to the welcome channel and follow the prompts so we can match your
      Discord account to your player profile.</li>
  <li>You'll get pulled into your team's private channel automatically.</li>
  <li>Turn on notifications for your team channel — that's where your coach posts.</li>
</ul>

<p>Already in the server? Then your Discord account probably isn't linked to your
player profile yet, and the same welcome steps will sort it out.</p>

<p>Stuck, or something looks wrong? Just reply to this email or reach us at
<a href="mailto:{support_email}">{support_email}</a> and we'll get you sorted.</p>

<p style="margin-top:24px;">See you out there.<br>
<strong>— ECS Pub League</strong></p>
""".strip()


SEASON_WRAP_SUBJECT = "That's a wrap on {season} — thanks for playing"

SEASON_WRAP_BODY = """
<p style="font-size:18px;margin:0 0 16px;"><strong>Thanks for a great season, {first_name}.</strong></p>

<p>{season} is officially in the books. However it went for {team} — trophy or
bottom of the table — thanks for showing up, week after week, and making this
league what it is.</p>

<p>We'd genuinely like to hear how it went for you. What worked, what didn't,
what you'd change. It takes a couple of minutes and it does actually shape what
we do next season.</p>

<p style="text-align:center;margin:32px 0;">
  <a href="{survey_url}"
     style="display:inline-block;background:#1a472a;color:#ffffff;text-decoration:none;
            padding:14px 32px;border-radius:8px;font-size:16px;font-weight:bold;">
    Share your feedback
  </a>
</p>

<p>Registration for next season opens before you know it, and we'll shout about it
on Discord first. Stick around in there over the offseason — pickup, watch
parties, and the usual chaos don't stop just because the league does.</p>

<p>Questions, ideas, or something you'd rather say privately? We're at
<a href="mailto:{support_email}">{support_email}</a>.</p>

<p style="margin-top:24px;">See you next season.<br>
<strong>— ECS Pub League</strong></p>
""".strip()


# Seeded rules. `key` is the stable slug the SQL migration and code both use.
SEEDED_RULES = [
    {
        'key': 'draft_discord_invite',
        'name': 'Drafted players not in Discord',
        'description': (
            'After a league finishes its draft, wait, then email every rostered '
            'player we cannot find in the Discord server, inviting them in. '
            'Premier and Classic are evaluated independently, so a split draft '
            'date only notifies the league that actually drafted.'
        ),
        'trigger_type': 'draft_complete',
        'trigger_config': {
            'league_type': 'Pub League',
            # Every active team in the league must have at least this many
            # non-coach players before the draft counts as finished. Keeps the
            # coach pre-draft (1 per team, a week earlier) from tripping it.
            'min_players_per_team': 6,
            # Refuse to fire about a draft older than this when the rule is first
            # enabled -- prevents a mid-season toggle from blasting everyone
            # about a draft that happened weeks ago.
            'max_event_age_days': 14,
        },
        'delay_hours': 24,
        'audience_type': 'drafted_not_in_discord',
        'audience_config': {'include_coaches': False},
        'subject': DRAFT_DISCORD_INVITE_SUBJECT,
        'body_html': DRAFT_DISCORD_INVITE_BODY,
        'send_mode': 'individual',
        'force_send': True,
        'enabled': False,
    },
    {
        'key': 'season_wrap_survey',
        'name': 'End-of-season thank you + survey',
        'description': (
            'When the season flips to offseason, thank everyone who played and '
            'point them at the end-of-season survey. Set {survey_url} in the body '
            'before enabling.'
        ),
        'trigger_type': 'season_phase',
        'trigger_config': {
            'league_type': 'Pub League',
            'phase': 'offseason',
            'max_event_age_days': 14,
        },
        'delay_hours': 24,
        'audience_type': 'current_season_players',
        'audience_config': {},
        'subject': SEASON_WRAP_SUBJECT,
        'body_html': SEASON_WRAP_BODY,
        'send_mode': 'individual',
        'force_send': False,
        'enabled': False,
    },
]


def get_seeded_rule(key):
    """Look up a seeded rule definition by key, or None."""
    for rule in SEEDED_RULES:
        if rule['key'] == key:
            return rule
    return None
