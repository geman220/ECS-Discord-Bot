-- =============================================================================
-- Update AI Prompt Configs for Anti-AI, Transformation-Based Commentary
-- =============================================================================
-- Run this in pgAdmin4 against your database.
-- These updates change the active prompt configs to use the new approach:
--   - Transformation (rewrite ESPN text) instead of generation (make up reactions)
--   - Few-shot examples to set the exact tone
--   - Lower temperature (0.4) and fewer tokens (60) for consistency
-- =============================================================================

-- 1. Deactivate match_thread_context (ID 39) - replaced by factual ESPN data
UPDATE ai_prompt_configs
SET is_active = false, updated_at = NOW()
WHERE id = 39;

-- 2. Sounders Goal (ID 29)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 200 characters. Write only the reaction text.',
    user_prompt_template = 'Rewrite this Sounders goal as a short, happy reaction. Use the specific details from the ESPN text (how it was scored). Include the score.

Match: {match_context}
ESPN event: "{event_description}"
Score after goal: {score}

Examples:
"Morris heads it in from close range. 2-1. Yes."
"Ruidiaz buries the pen. 1-0."
"Rusnak from distance. 3-1. Beauty."
"Roldan taps it in off the rebound. 2-0. Easy."

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 29;

-- 3. Opponent Goal (ID 31)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 200 characters. Write only the reaction text.',
    user_prompt_template = 'Rewrite this opponent goal as a short, disappointed reaction. Use the specific details from the ESPN text (how it was scored). Include the score.

Match: {match_context}
ESPN event: "{event_description}"
Score after goal: {score}

Examples:
"Ferreira from distance. 1-1. Need to close that down quicker."
"They score off the corner. 1-2. Poor marking."
"Penalty given and converted. 0-1. Soft call."
"Counter attack and they finish it. 2-2. Fell asleep."

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 31;

-- 4. Substitution (ID 32)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 200 characters. Write only the reaction text.',
    user_prompt_template = 'Rewrite this substitution as a short, casual reaction. Use the player names from the ESPN text.

Match: {match_context}
ESPN event: "{event_description}"
Clock: {clock}

Examples:
"Roldan on for Lodeiro. Fresh legs for the last 20."
"Ruidiaz comes off. Done his job tonight."
"Triple sub from them. Throwing everything at it."
"Morris on. Time to run at tired legs."

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 32;

-- 5. Yellow Card (ID 33)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 200 characters. Write only the reaction text.',
    user_prompt_template = 'Rewrite this card event as a short, casual reaction. Use the specific details from the ESPN text (what the foul was for).

Match: {match_context}
ESPN event: "{event_description}"
Clock: {clock}

Examples:
"Roldan picks up a yellow. Didn''t need to make that challenge."
"Card for Herrera. He''s been getting away with it all half."
"Yellow on their keeper for time wasting. About time."
"Nouhou booked. Reckless but that''s Nouhou."

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 33;

-- 6. Sounders Red Card (ID 34)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 200 characters. Write only the reaction text.',
    user_prompt_template = 'Rewrite this red card as a short, frustrated reaction. Use the player name from the ESPN text.

Match: {match_context}
ESPN event: "{event_description}"
Clock: {clock}

Examples:
"Red card. Down to 10. This just got a lot harder."
"Sent off. Can''t argue with that one. Stupid challenge."
"Second yellow, he''s off. Going to be a long final 30 minutes."

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 34;

-- 7. Opponent Red Card (ID 35)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 200 characters. Write only the reaction text.',
    user_prompt_template = 'Rewrite this opponent red card as a short, satisfied reaction. Use the player name from the ESPN text.

Match: {match_context}
ESPN event: "{event_description}"
Clock: {clock}

Examples:
"Red card for their #6. Down to 10. Time to make it count."
"He''s off. Been asking for it all game."
"Second yellow and he walks. Couldn''t happen to a nicer guy."

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 35;

-- 8. Halftime Message (ID 36)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 280 characters. Write only the reaction text.',
    user_prompt_template = 'Write a short halftime reaction. Reference the score and how the half went.

Match: {match_context}
Score: {score}

Examples:
"Halftime. 1-0 up. Controlled the half, need another to kill it off."
"Halftime, still 0-0. Not much in it. Second half needs more."
"Down 2-0 at the half. Rough. Need a big response."
"2-1 up at the break. Should be more but we keep giving them chances."

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 36;

-- 9. Full Time Message (ID 37)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 280 characters. Write only the reaction text.',
    user_prompt_template = 'Write a short full-time reaction. Reference the final score and result.

Match: {match_context}
Final score: {score}

Examples:
"Full time. 2-0. Clean sheet and 3 points. Good day."
"Full time. 1-2. Disappointing. Gave away too many chances."
"1-1 at the final whistle. A point on the road, take it and move on."
"3-1. Comfortable in the end. Needed that after last week."

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 37;

-- 10. Match Commentary - generic (ID 38)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 200 characters. Write only the reaction text.',
    user_prompt_template = 'Rewrite this match event as a short, casual reaction. Use the specific details from the ESPN text.

Match: {match_context}
ESPN event: "{event_description}"
Score: {score}

Write only the reaction.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 38;

-- 11. Pre-Match Hype (ID 40)
UPDATE ai_prompt_configs
SET
    system_prompt = 'You write short, casual match reactions. Never use em dashes. One or two sentences max. Under 280 characters. Write only the message text.',
    user_prompt_template = 'Write a short pre-kickoff message. 5 minutes to kick off. Keep it simple.

Match: {match_context}

Examples:
"Sounders and Houston, 5 minutes out. Three points and nothing less."
"Almost time. Let''s have it."
"About to kick off. Time to handle business."

Write only the message.',
    temperature = 0.4,
    max_tokens = 60,
    updated_at = NOW()
WHERE id = 40;

-- =============================================================================
-- Verify the updates
-- =============================================================================
-- SELECT id, name, prompt_type, is_active, temperature, max_tokens
-- FROM ai_prompt_configs
-- WHERE id BETWEEN 29 AND 40
-- ORDER BY id;
