---
layout: default
---

# Match Commands

This section describes commands available for managing match-related activities in the ECS Discord bot.

## Command: `/nextmatch`

- **Description:** List the next scheduled match information.
- **Usage:** `/nextmatch`
- **Permissions:** None
- **Details:**
  - Displays the opponent, date and time (in PST), and venue of the next scheduled match.
  - The match details are fetched from the stored schedule.
- **Example:**
  - `/nextmatch`
- **Error Messages:**
  - "An error occurred: {error_message}" (If an error occurs while fetching the match information)

## Command: `/newmatch`

- **Description:** Create a new match thread.
- **Usage:** `/newmatch`
- **Permissions:** Admin
- **Details:**
  - Creates a new thread for the next match in the designated forum channel.
  - Prepares the match environment and generates weather forecasts if applicable.
- **Example:**
  - `/newmatch`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "No upcoming matches found." (If no matches are scheduled)
  - "A thread has already been created for the next match." (If a thread already exists for the next match)
  - "Forum channel not found or invalid." (If the specified channel does not exist or is not a forum channel)
  - "Failed to process the command: {error_message}" (If an error occurs while creating the match thread)

## Command: `/awaymatch`

- **Description:** Create a new away match thread.
- **Usage:** `/awaymatch [opponent]`
- **Permissions:** Admin
- **Details:**
  - Creates a new thread for an away match, provided that a ticket item is created in the store first.
  - The opponent team name is optional.
- **Example:**
  - `/awaymatch "Portland Timbers"`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "No relevant away match or ticket info found." (If no match or ticket information is found)
  - "A thread for this away match has already been created." (If a thread already exists for the away match)
  - "Failed to process the command: {error_message}" (If an error occurs while creating the away match thread)

## Command: `/predictions`

- **Description:** List predictions for the current match thread.
- **Usage:** `/predictions`
- **Permissions:** None
- **Details:**
  - Lists all predictions made for the current match thread.
  - Displays the prediction and the number of times it was made.
- **Example:**
  - `/predictions`
- **Error Messages:**
  - "This command can only be used in match threads." (If the command is used outside a match thread)
  - "This thread is not associated with an active match prediction." (If the thread is not linked to a match)
  - "No predictions have been made for this match." (If no predictions are available)

## Command: `/predict`

- **Description:** Predict the score of the match.
- **Usage:** `/predict <prediction>`
- **Permissions:** None
- **Details:**
  - Records a user's prediction for the match score.
  - The prediction must be in the format "X-Y" (e.g., 3-0).
- **Example:**
  - `/predict 3-1`
- **Error Messages:**
  - "This command can only be used in match threads." (If the command is used outside a match thread)
  - "This thread is not associated with an active match prediction." (If the thread is not linked to a match)
  - "Predictions are closed for this match." (If predictions are no longer being accepted)
  - "You have already made a prediction for this match." (If the user has already submitted a prediction)

*For more assistance or queries regarding these commands, please contact the bot administrators.*