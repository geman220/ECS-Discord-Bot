---
layout: default
---

# General Commands

This section describes the general commands available in the ECS Discord bot.

## Command: `/record`

- **Description:** Lists the Sounders season stats.
- **Usage:** `/record`
- **Permissions:** None
- **Details:**
  - Fetches and displays the current season statistics for the Sounders.
  - The statistics include various performance metrics for the season.
- **Example:**
  - `/record`
- **Error Messages:**
  - "Error fetching record." (If an error occurs while fetching the team record)

## Command: `/awaytickets`

- **Description:** Get a link to the latest away tickets.
- **Usage:** `/awaytickets [opponent]`
- **Permissions:** None
- **Details:**
  - Provides a link to purchase tickets for the upcoming away match.
  - Optionally, the opponent team name can be provided to filter the search.
- **Example:**
  - `/awaytickets`
  - `/awaytickets "Portland Timbers"`
- **Error Messages:**
  - "No upcoming away matches found." (If no upcoming away matches are found)

## Command: `/verify`

- **Description:** Verify your ECS membership with your Order #.
- **Usage:** `/verify`
- **Permissions:** None
- **Details:**
  - Opens a modal for the user to input their Order # to verify their ECS membership.
  - Verification helps ensure that only valid members have access to certain features or roles.
- **Example:**
  - `/verify`
- **Error Messages:**
  - None specific to this command.

*For more assistance or queries regarding these commands, please contact the bot administrators.*