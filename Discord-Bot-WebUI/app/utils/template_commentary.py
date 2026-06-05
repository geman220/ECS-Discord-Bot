# app/utils/template_commentary.py

"""
Template ("mad-lib") commentary engine.

Deterministic, human-authored match commentary. Every line that ships was
written by a person in the ECS/Sounders supporter voice; the engine only fills
{slots} with REAL ESPN fields (player, score, minute, assist) and picks one line
with anti-repetition. There is no model in the loop, so the output is
undetectable as AI by construction — which is the whole point.

Design notes:
- Keys are TEMPLATES[event_type][side] -> {'base': [...], <score_state>: [...],
  'rivalry': [...]}. `side` is 'for' (Sounders benefit) / 'against' (opponent)
  or 'neutral' (own goals — see below).
- Own goals are NEUTRAL on purpose: ESPN is inconsistent about which team an
  own-goal keyEvent is attributed to, so we never assert "good/bad for us" on
  them — the Sounders-perspective {score} still conveys the situation.
- The engine REFUSES (returns None) when a load-bearing slot is empty (e.g. a
  goal with no player AND no score), so the caller falls back to the real ESPN
  description rather than posting "Goal by ". This preserves the
  no-silent-mock / surface-the-error contract.
- Score is Sounders-perspective ("2-1" = us-them), computed by the caller.
"""

import logging
import random
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


def detect_rivalry(opponent: str) -> Optional[str]:
    """Single source of truth for Cascadia rivalry detection."""
    o = (opponent or '').lower()
    if 'portland' in o or 'timber' in o:
        return 'portland'
    if 'vancouver' in o or 'whitecap' in o:
        return 'vancouver'
    return None


# event_type -> side -> {'base': [...], score_state: [...], 'rivalry': [...]}
# Slots: {player} {team} {minute} {score} {assist} {player_on} {player_off}
TEMPLATES: Dict[str, Dict[str, Dict[str, List[str]]]] = {
    'goal': {
        'for': {
            'base': [
                "{player} scores. {score}. {minute}'.",
                "{player} puts it away. {score}.",
                "Goal, {player}. {score}. Get in.",
                "{player} finishes it off. {score}. {minute}'.",
                "That's {player}. {score}. Yes.",
                "{player} buries it. {score}.",
            ],
            'us_ahead': [
                "{player} and we're in front. {score}.",
                "{player} nudges us ahead. {score}. {minute}'.",
            ],
            'level': [
                "{player} levels it. {score}. Back in this.",
                "{player} drags us level. {score}.",
            ],
            'behind': [
                "{player} pulls one back. {score}. Still in it.",
            ],
        },
        'against': {
            'base': [
                "{player} scores for {team}. {score}. {minute}'. Need a response.",
                "{team} get one through {player}. {score}. Sort it out.",
                "{player} scores. {score}. Heads up.",
            ],
            'behind': [
                "{player} puts {team} ahead. {score}. Come on now.",
                "Behind. {player}, {score}. React.",
            ],
            'level': [
                "{player} equalises for {team}. {score}. Annoying.",
            ],
            'rivalry': [
                "{player} scores. {score}. Typical {team} shithousing.",
                "{team} ahead through {player}. {score}. Hate it here.",
            ],
        },
    },
    'penalty_goal': {
        'for': {
            'base': [
                "{player} buries the pen. {score}.",
                "Spot kick, {player}. {score}. No fuss.",
                "{player} from the spot. {score}. {minute}'.",
            ],
        },
        'against': {
            'base': [
                "{player} converts from the spot. {score}. {minute}'.",
                "Penalty for {team}, {player} scores. {score}.",
            ],
        },
    },
    'own_goal': {
        'neutral': {
            'base': [
                "Own goal. {score}. {minute}'.",
                "Goes in off {player}. Own goal. {score}.",
                "Own goal, {player}. {score}.",
            ],
        },
    },
    'penalty_missed': {
        'for': {
            'base': [
                "{player} misses from the spot. {minute}'. Ugh.",
                "Penalty wasted by {player}. {minute}'.",
            ],
        },
        'against': {
            'base': [
                "{player} skies the penalty. {minute}'. Reprieve.",
                "{team} miss the pen, {player}. {minute}'. We live.",
            ],
        },
    },
    'penalty_saved': {
        'for': {
            'base': [
                "{player}'s penalty is saved. {minute}'. Frustrating.",
            ],
        },
        'against': {
            'base': [
                "Saved. {player} denied from the spot. {minute}'. Huge.",
                "Keeper gets it. {player}'s pen saved. {minute}'. Massive.",
            ],
        },
    },
    'yellow_card': {
        'for': {
            'base': [
                "Yellow for {player}. {minute}'. Careful now.",
                "{player} booked. {minute}'. Didn't need that.",
            ],
        },
        'against': {
            'base': [
                "{player} goes in the book. {minute}'.",
                "Yellow for {player}. {minute}'. About time.",
            ],
            'rivalry': [
                "{player} booked. {minute}'. Been kicking us all half.",
            ],
        },
    },
    'red_card': {
        'for': {
            'base': [
                "Red for {player}. {minute}'. Down to ten. Dig in.",
            ],
        },
        'against': {
            'base': [
                "{player} sent off. {minute}'. Their problem now.",
                "Red card, {player}. {minute}'. Up a man.",
            ],
            'rivalry': [
                "{player} off. Red card. {minute}'. Couldn't happen to a nicer bloke.",
            ],
        },
    },
    'substitution': {
        'for': {
            'base': [
                "{player_on} on for {player_off}. {minute}'.",
                "Change: {player_off} off, {player_on} on. {minute}'.",
                "Sounders sub. {player_on} on. {minute}'.",
            ],
        },
        'against': {
            'base': [
                "{team} make a change. {minute}'.",
                "{team} sub, {player_on} on. {minute}'.",
            ],
        },
    },
}

# Event types whose templates require a player or score to be meaningful.
_REQUIRES_PLAYER_OR_SCORE = {'goal', 'penalty_goal'}
_REQUIRES_PLAYERS = {'substitution'}


class TemplateCommentaryEngine:
    """Picks a human-written line per event, fills it from ESPN fields."""

    # Maps engine buckets -> AIPromptConfig.prompt_type, so admins can edit the
    # base lines for these from the existing /ai-prompts editor (template_lines
    # field). Buckets not listed (penalties, own goals) stay code-only.
    BUCKET_TO_PROMPT_TYPE = {
        ('goal', 'for'): 'sounders_goal',
        ('goal', 'against'): 'opponent_goal',
        ('yellow_card', 'for'): 'card',
        ('yellow_card', 'against'): 'opponent_card',
        ('red_card', 'for'): 'sounders_red_card',
        ('red_card', 'against'): 'opponent_red_card',
        ('substitution', 'for'): 'substitution',
        ('substitution', 'against'): 'opponent_substitution',
    }

    def __init__(self, recent_per_match: int = 8):
        self._recent: Dict[str, List[str]] = {}  # match_id -> recently chosen template strings
        self._recent_n = recent_per_match
        self._overrides: Dict[str, List[str]] = {}  # prompt_type -> admin-edited base lines

    def set_overrides(self, overrides: Dict[str, List[str]]):
        """Replace the admin line overrides (prompt_type -> [lines]). Inert until set."""
        self._overrides = overrides or {}

    def render(self, ctx: Dict[str, Any]) -> Optional[str]:
        """
        Render commentary for a normalized event context, or None to signal the
        caller to fall back to the ESPN description.

        ctx keys: event_type, is_our_event(bool), player, team, minute, score,
        score_state('us_ahead'|'level'|'behind'), rivalry(str|None), assist,
        player_on, player_off, match_id.
        """
        event_type = (ctx.get('event_type') or '').lower()

        if event_type == 'own_goal':
            side = 'neutral'
        else:
            side = 'for' if ctx.get('is_our_event') else 'against'

        node = TEMPLATES.get(event_type, {}).get(side)
        if not node:
            return None  # unknown event/side -> caller uses ESPN text

        # Base lines: admin DB override (if any) replaces the code defaults;
        # code overlays (score_state / rivalry) still apply on top.
        pt = self.BUCKET_TO_PROMPT_TYPE.get((event_type, side))
        override = self._overrides.get(pt) if pt else None
        pool = list(override) if override else list(node.get('base', []))
        score_state = ctx.get('score_state')
        if score_state and score_state in node:
            pool += node[score_state]
        if ctx.get('rivalry') and 'rivalry' in node:
            pool += node['rivalry']
        if not pool:
            return None

        slots = self._slots(ctx)

        # Refuse on missing load-bearing data so we never post a hollow line.
        if event_type in _REQUIRES_PLAYER_OR_SCORE and not slots['player'] and not slots['score']:
            return None
        if event_type in _REQUIRES_PLAYERS and not slots['player_on'] and not slots['player']:
            return None

        choice = self._pick(str(ctx.get('match_id', '')), pool)
        try:
            text = choice.format(**slots).strip()
        except (KeyError, IndexError, ValueError):
            return None  # malformed template/slot -> fall back, never post a {brace}

        # Collapse any double spaces left by an empty slot, tidy punctuation.
        text = ' '.join(text.split())
        return text or None

    def _pick(self, match_id: str, pool: List[str]) -> str:
        seen = self._recent.setdefault(match_id, [])
        fresh = [t for t in pool if t not in seen[-self._recent_n:]]
        choice = random.choice(fresh or pool)
        seen.append(choice)
        # bound memory
        if len(seen) > self._recent_n * 4:
            self._recent[match_id] = seen[-self._recent_n * 2:]
        return choice

    def clear_match(self, match_id: str) -> None:
        self._recent.pop(str(match_id), None)

    def _slots(self, ctx: Dict[str, Any]) -> Dict[str, str]:
        return {
            'player': (ctx.get('player') or '').strip(),
            'team': (ctx.get('team') or '').strip(),
            'minute': str(ctx.get('minute') or '').strip().rstrip("'"),
            'score': (ctx.get('score') or '').strip(),
            'assist': (ctx.get('assist') or '').strip(),
            'player_on': (ctx.get('player_on') or '').strip(),
            'player_off': (ctx.get('player_off') or '').strip(),
        }


_engine: Optional[TemplateCommentaryEngine] = None


def get_template_engine() -> TemplateCommentaryEngine:
    """Process-wide singleton (mirrors get_sync_ai_client)."""
    global _engine
    if _engine is None:
        _engine = TemplateCommentaryEngine()
    return _engine
