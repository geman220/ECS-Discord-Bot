# app/utils/commentary_validator.py

"""
Commentary Validation & Anti-AI Detection

Final gate between GPT output and Discord. Enforces tone rules in code
(not just in the prompt), rejects AI-sounding output, prevents repetition,
and enforces character limits.

Usage:
    from app.utils.commentary_validator import validate_commentary, CommentaryType

    result = validate_commentary(text, CommentaryType.MATCH_EVENT)
    if result.is_valid:
        post_to_discord(result.text)
    else:
        # result.rejection_reason tells you why
        use_fallback()
"""

import re
import logging
from enum import Enum
from typing import Optional, List, Dict
from dataclasses import dataclass, field
from collections import deque

logger = logging.getLogger(__name__)


class CommentaryType(Enum):
    """Types of commentary with their character limits."""
    MATCH_EVENT = 200
    PRE_MATCH = 280
    HALFTIME = 280
    FULLTIME = 280
    THREAD_CONTEXT = 200


@dataclass
class ValidationResult:
    """Result of validating a piece of commentary."""
    is_valid: bool
    text: str
    rejection_reason: Optional[str] = None
    was_cleaned: bool = False


# --- AI-ism detection patterns ---

# Phrases that scream "a language model wrote this".
# Philosophy: ban genuinely AI/sportswriter/narrator voice. Do NOT ban normal
# supporter words like "clinical", "come on Seattle", "let's go Sounders",
# "the boys", "our boys", "absolutely", "brilliant" — those are fine in
# moderation. Anti-repetition tracker + prompt variety handle overuse.
AI_PHRASES = [
    # Stock sportswriter openers
    r"\bwhat a\b",

    # Adjective stacks that scream ESPN/AI
    r"\bincredible\b",
    r"\bunbelievable\b",
    r"\bstunning\b",
    r"\bmagnificent\b",
    r"\bsensational\b",
    r"\bspectacular\b",
    r"\bexquisite\b",
    r"\bdelightful\b",
    r"\btremendous\b",
    r"\bfantastic\b",
    r"\bwonderful\b",
    r"\bphenomenal\b",
    r"\belectrifying\b",
    r"\bremarkable\b",
    r"\bextraordinary\b",
    r"\bimpressive display\b",

    # Narrator / press-release voice
    r"\blooking to (extend|continue|secure|chase|claim|maintain)\b",
    r"\bseeking to\b",
    r"\baiming to\b",
    r"\bwill be (hoping|looking) to\b",
    r"\banticipation (is|was) building\b",
    r"\ba crucial (fixture|moment|opportunity|test)\b",
    r"\ba defining moment\b",
    r"\ba pivotal (moment|match)\b",

    # Corporate / business-speak
    r"\bshowcase[sd]?\b",
    r"\bdemonstrat(e[sd]?|ing)\b",
    r"\bmaster class\b",
    r"\bmasterclass\b",
    r"\bworld.?class\b",
    r"\bnothing short of\b",

    # Coachy filler & performative takeaways
    r"\bprove[sd]? once again\b",
    r"\bonce again prove\b",
    r"\bexactly how (we|you) (need|have) to play\b",
    r"\btake the learnings\b",
    r"\bplenty to build on\b",
    r"\bcontinues? to demonstrate\b",

    # Epic/mythic framing
    r"\bcements?\b.*(legacy|place|status)",
    r"\bwriting the narrative\b",
    r"\bscript couldn'?t\b",
    r"\byou couldn'?t script\b",
    r"\bdream(s)? (do )?come true\b",
    r"\bfairytale\b",
    r"\bfairy.?tale\b",
    r"\bstorybook\b",
    r"\binstant classic\b",
    r"\bone for the ages\b",
    r"\bfor the history books\b",

    # Platitude slogans
    r"\bthat'?s what it'?s all about\b",
    r"\bthis is what (it'?s|we'?re) all about\b",
    r"\bthis is why we\b",
    r"\bthis team never\b",
    r"\bheart and soul\b",
    r"\bblood,? sweat,? and tears\b",
    r"\bpassion and pride\b",
    r"\bpassionate display\b",
    r"\bbelieve\b.*\b(magic|team|boys)\b",
    r"\bdig deep\b",
    r"\bshow(ing)? (their|our|what).*(made of|quality|character|class)\b",
    r"\bdelivers? when it matters\b",
    r"\bwhen it matters most\b",
    r"\brise to the occasion\b",
    r"\bstep up\b.*(big|when|moment)",

    # Branded / hashtag-style community phrasing (AI pattern-matches this)
    r"\brave green (magic|army|pride|faithful|nation)\b",
    r"\becs (erupts?|faithful|army|nation)\b",
    r"\bthe faithful\b",
    r"\bwherever (we|sounders) (are|play)\b",

    # Staged crowd description (AI loves stadium-cam narration)
    r"\bthe (whole|entire) (stadium|crowd|place)\b.*(erupt|goes|went|roar)",
    r"\bthunder(ous|ing)?\b",
    r"\b(crowd|stadium|place) (goes|went) (wild|crazy|nuts|mental|mad|bananas)\b",
    r"\bwild celebrations\b",

    # Abstract emotion stacks
    r"\bpure (joy|emotion|elation|class|quality)\b",
    r"\bsheer (brilliance|quality|determination|class)\b",
    r"\bembodiment of\b",
    r"\btestament to\b",
    r"\bepitom(e|ize)\b",
]

# Corporate/marketing speak
CORPORATE_PHRASES = [
    r"\bshowcas(e[sd]?|ing)\b",
    r"\bleverage[sd]?\b",
    r"\bsynerg\b",
    r"\bgame.?changer\b",
    r"\bgame.?changing\b",
    r"\bnext.?level\b",
    r"\bworld.?class\b",
    r"\btop.?notch\b",
    r"\btop.?tier\b",
    r"\belite mentality\b",
    r"\bwinning mentality\b",
    r"\bchampion(ship)? (dna|mentality|caliber|quality)\b",
]

# Compile all patterns once
_AI_PATTERNS = [re.compile(p, re.IGNORECASE) for p in AI_PHRASES]
_CORPORATE_PATTERNS = [re.compile(p, re.IGNORECASE) for p in CORPORATE_PHRASES]


# --- Recent output tracking for anti-repetition ---

class RecentOutputTracker:
    """
    Tracks recent outputs per match to prevent repetition.
    Uses a ring buffer per match_id, stores last N outputs.
    """

    def __init__(self, max_per_match: int = 30):
        self._buffers: Dict[str, deque] = {}
        self._max = max_per_match

    def is_too_similar(self, match_id: str, text: str, threshold: float = 0.6) -> bool:
        """
        Check if text is too similar to any recent output for this match.
        Uses word overlap ratio as a simple, fast similarity metric.
        """
        if match_id not in self._buffers:
            return False

        text_words = set(text.lower().split())
        if not text_words:
            return False

        for recent in self._buffers[match_id]:
            recent_words = set(recent.lower().split())
            if not recent_words:
                continue

            # Jaccard similarity
            intersection = text_words & recent_words
            union = text_words | recent_words
            similarity = len(intersection) / len(union) if union else 0

            if similarity >= threshold:
                return True

        return False

    def record(self, match_id: str, text: str):
        """Record an output for anti-repetition tracking."""
        if match_id not in self._buffers:
            self._buffers[match_id] = deque(maxlen=self._max)
        self._buffers[match_id].append(text)

    def clear_match(self, match_id: str):
        """Clear tracking for a finished match."""
        self._buffers.pop(match_id, None)


# Global tracker instance
_tracker = RecentOutputTracker()


def get_tracker() -> RecentOutputTracker:
    """Get the global output tracker."""
    return _tracker


# --- Core validation ---

def _check_formatting_rules(text: str) -> Optional[str]:
    """
    Check hard formatting rules. Returns rejection reason or None if clean.
    """
    # Em dashes
    if '\u2014' in text or '\u2013' in text:
        return "contains em dash or en dash"

    # Runs of exclamation marks ("!!", "!!!", etc) — spammy/cringe.
    # Single "!" at sentence boundaries is fine even across multiple clauses,
    # e.g. "Roldan! 2-1! Fuck the Timbers!" is real supporter energy, not AI.
    if '!!' in text:
        return "contains consecutive exclamation marks"

    # Hashtags
    if re.search(r'#\w+', text):
        return "contains hashtag"

    # Starts with "What a" (case insensitive)
    if re.match(r'^what a\b', text, re.IGNORECASE):
        return "starts with 'What a'"

    # Excessive emoji (more than 2)
    emoji_pattern = re.compile(
        "[\U0001F600-\U0001F64F"  # emoticons
        "\U0001F300-\U0001F5FF"  # symbols & pictographs
        "\U0001F680-\U0001F6FF"  # transport & map
        "\U0001F1E0-\U0001F1FF"  # flags
        "\U00002702-\U000027B0"
        "\U000024C2-\U0001F251"
        "\U0001f900-\U0001f9FF"  # supplemental symbols
        "\U00002600-\U000026FF"  # misc symbols
        "]+", flags=re.UNICODE
    )
    emojis = emoji_pattern.findall(text)
    # Count individual emoji characters
    emoji_count = sum(len(e) for e in emojis)
    if emoji_count > 2:
        return f"too many emojis ({emoji_count})"

    return None


def _check_ai_patterns(text: str) -> Optional[str]:
    """
    Check for AI-sounding phrases. Returns the matched phrase or None.
    """
    for pattern in _AI_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"AI phrase detected: '{match.group()}'"

    for pattern in _CORPORATE_PATTERNS:
        match = pattern.search(text)
        if match:
            return f"corporate phrase detected: '{match.group()}'"

    return None


def _clean_text(text: str) -> str:
    """
    Apply light cleaning that can salvage borderline output.
    Only fixes things that don't change meaning.
    """
    # Strip quotes
    text = text.strip('"\'')

    # Remove hashtags
    text = re.sub(r'#\w+', '', text)

    # Replace em/en dashes with regular dashes
    text = text.replace('\u2014', '-').replace('\u2013', '-')

    # Collapse multiple exclamation marks to one
    text = re.sub(r'!{2,}', '!', text)

    # Collapse multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()

    # Remove trailing period after exclamation
    text = re.sub(r'!\.$', '!', text)

    return text


def validate_commentary(
    text: str,
    commentary_type: CommentaryType = CommentaryType.MATCH_EVENT,
    match_id: Optional[str] = None,
    strict: bool = True
) -> ValidationResult:
    """
    Validate a piece of AI-generated commentary.

    Args:
        text: The generated text to validate
        commentary_type: Type of commentary (determines char limit)
        match_id: Match ID for anti-repetition tracking (optional)
        strict: If True, reject on AI phrase detection. If False, just log warnings.

    Returns:
        ValidationResult with is_valid, cleaned text, and rejection reason
    """
    if not text or not text.strip():
        return ValidationResult(
            is_valid=False,
            text="",
            rejection_reason="empty output"
        )

    # Step 1: Light cleaning (always applied)
    cleaned = _clean_text(text)
    was_cleaned = (cleaned != text.strip())

    # Step 2: Character limit (hard enforce)
    char_limit = commentary_type.value
    if len(cleaned) > char_limit:
        # Try to truncate at sentence boundary
        truncated = cleaned[:char_limit]
        last_period = truncated.rfind('.')
        last_question = truncated.rfind('?')
        last_break = max(last_period, last_question)
        if last_break > char_limit * 0.5:
            cleaned = truncated[:last_break + 1]
        else:
            cleaned = truncated.rstrip() + "."
        was_cleaned = True

    # Step 3: Formatting rules (hard reject)
    format_issue = _check_formatting_rules(cleaned)
    if format_issue:
        logger.warning(f"Commentary rejected (formatting): {format_issue} | text: '{cleaned[:80]}'")
        return ValidationResult(
            is_valid=False,
            text=cleaned,
            rejection_reason=format_issue,
            was_cleaned=was_cleaned
        )

    # Step 4: AI-ism detection
    ai_issue = _check_ai_patterns(cleaned)
    if ai_issue:
        if strict:
            logger.warning(f"Commentary rejected (AI-ism): {ai_issue} | text: '{cleaned[:80]}'")
            return ValidationResult(
                is_valid=False,
                text=cleaned,
                rejection_reason=ai_issue,
                was_cleaned=was_cleaned
            )
        else:
            logger.info(f"Commentary AI warning (non-strict): {ai_issue}")

    # Step 5: Anti-repetition check
    if match_id:
        tracker = get_tracker()
        if tracker.is_too_similar(match_id, cleaned):
            logger.warning(f"Commentary rejected (repetition): too similar to recent output for match {match_id}")
            return ValidationResult(
                is_valid=False,
                text=cleaned,
                rejection_reason="too similar to recent output",
                was_cleaned=was_cleaned
            )

    # Passed all checks
    return ValidationResult(
        is_valid=True,
        text=cleaned,
        was_cleaned=was_cleaned
    )


def validate_and_record(
    text: str,
    commentary_type: CommentaryType = CommentaryType.MATCH_EVENT,
    match_id: Optional[str] = None,
    strict: bool = True
) -> ValidationResult:
    """
    Validate commentary AND record it to the anti-repetition tracker if valid.
    Use this as the main entry point when you're about to post.
    """
    result = validate_commentary(text, commentary_type, match_id, strict)
    if result.is_valid and match_id:
        get_tracker().record(match_id, result.text)
    return result


def generate_with_validation(
    generate_fn,
    fallback_fn,
    commentary_type: CommentaryType = CommentaryType.MATCH_EVENT,
    match_id: Optional[str] = None,
    max_attempts: int = 2,
    strict: bool = True
) -> str:
    """
    Generate commentary with validation loop. Retries on rejection, falls back if all fail.

    Args:
        generate_fn: Callable that returns a string (the AI generation call)
        fallback_fn: Callable that returns a string (the static fallback)
        commentary_type: Type of commentary for validation rules
        match_id: Match ID for anti-repetition
        max_attempts: How many times to try AI generation before falling back
        strict: Whether to reject on AI-ism detection

    Returns:
        Validated commentary string (either from AI or fallback)
    """
    for attempt in range(max_attempts):
        try:
            text = generate_fn()
            if not text:
                continue

            result = validate_and_record(text, commentary_type, match_id, strict)
            if result.is_valid:
                if result.was_cleaned:
                    logger.info(f"Commentary cleaned and accepted (attempt {attempt + 1})")
                return result.text
            else:
                logger.info(
                    f"Commentary rejected attempt {attempt + 1}/{max_attempts}: "
                    f"{result.rejection_reason}"
                )
        except Exception as e:
            logger.warning(f"Commentary generation attempt {attempt + 1} failed: {e}")

    # All AI attempts failed validation - use fallback
    logger.info("All AI attempts rejected, using fallback")
    fallback_text = fallback_fn()
    if fallback_text and match_id:
        # Record fallback too for anti-repetition
        get_tracker().record(match_id, fallback_text)
    return fallback_text or ""


async def async_generate_with_validation(
    generate_coro_fn,
    fallback_fn,
    commentary_type: CommentaryType = CommentaryType.MATCH_EVENT,
    match_id: Optional[str] = None,
    max_attempts: int = 2,
    strict: bool = True
) -> str:
    """
    Async version of generate_with_validation for the async AI clients.

    Args:
        generate_coro_fn: Callable that returns a coroutine (the async AI call)
        fallback_fn: Callable that returns a string (the static fallback)
        commentary_type: Type for validation
        match_id: Match ID for anti-repetition
        max_attempts: Retry count
        strict: AI-ism strictness

    Returns:
        Validated commentary string
    """
    for attempt in range(max_attempts):
        try:
            text = await generate_coro_fn()
            if not text:
                continue

            result = validate_and_record(text, commentary_type, match_id, strict)
            if result.is_valid:
                if result.was_cleaned:
                    logger.info(f"Commentary cleaned and accepted (attempt {attempt + 1})")
                return result.text
            else:
                logger.info(
                    f"Commentary rejected attempt {attempt + 1}/{max_attempts}: "
                    f"{result.rejection_reason}"
                )
        except Exception as e:
            logger.warning(f"Async commentary generation attempt {attempt + 1} failed: {e}")

    # All AI attempts failed - use fallback
    logger.info("All async AI attempts rejected, using fallback")
    fallback_text = fallback_fn()
    if fallback_text and match_id:
        get_tracker().record(match_id, fallback_text)
    return fallback_text or ""
