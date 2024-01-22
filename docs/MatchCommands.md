---
layout: default
---

# Match Commands

This section details the commands related to match threads and predictions in the ECS Discord bot.

## Command: nextmatch

- **Description:** Lists information about the next scheduled match.
- **Usage:** `/nextmatch`
- **Details:** Provides details like opponent, date and time (PST), and venue for the next match.

## Command: newmatch

- **Description:** Creates a new match thread.
- **Usage:** `/newmatch`
- **Permissions:** Requires admin role.
- **Details:** Creates a new match thread with detailed information about the upcoming match, including weather forecast if it's a home game.

## Command: awaymatch

- **Description:** Creates a new away match thread.
- **Usage:** `/awaymatch [opponent]`
- **Parameters:**
  - `opponent`: (Optional) Name of the opponent team.
- **Permissions:** Requires admin role.
- **Details:** Creates an away match thread with details about the match and a link to purchase tickets if available.

## Command: predictions

- **Description:** Lists predictions for the current match thread.
- **Usage:** `/predictions`
- **Details:** Can only be used in match threads. Shows all predictions made for the match.

## Command: predict

- **Description:** Predict the score of the match.
- **Usage:** `/predict [prediction]`
- **Parameters:**
  - `prediction`: Your score prediction (e.g., 3-0).
- **Details:** Can only be used in match threads. Allows users to record their score predictions for the match.

*For more assistance or queries regarding these commands, please contact the bot administrators.*