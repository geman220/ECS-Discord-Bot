---
layout: default
---

# Match Dates Commands

This section describes commands related to managing match dates in the ECS Discord bot.

## Command: `/addmatchdate`

- **Description:** Adds a match date.
- **Usage:** `/addmatchdate <date> <competition>`
- **Permissions:** Admin
- **Details:**
  - Adds a new match date to the schedule.
  - Example competitions: `usa.1` (MLS), `usa.open` (US Open Cup)
  - Date format should be `YYYYMMDD`.
- **Example:**
  - `/addmatchdate 20240709 usa.open`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Invalid date format. Use YYYYMMDD." (If the date format is incorrect)
  - "Failed to add match date." (If there is an error processing the command)

## Command: `/updatematchdate`

- **Description:** Updates an existing match date.
- **Usage:** `/updatematchdate <old_date> <new_date> <competition>`
- **Permissions:** Admin
- **Details:**
  - Updates an existing match date in the schedule.
  - Example competitions: `usa.1` (MLS), `usa.open` (US Open Cup)
  - Date format should be `YYYYMMDD`.
- **Example:**
  - `/updatematchdate 20240709 20240710 usa.open`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Invalid date format. Use YYYYMMDD." (If the date format is incorrect)
  - "Failed to update match date." (If there is an error processing the command)

## Command: `/deletematchdate`

- **Description:** Deletes a match date.
- **Usage:** `/deletematchdate <date> <competition>`
- **Permissions:** Admin
- **Details:**
  - Deletes an existing match date from the schedule.
  - Example competitions: `usa.1` (MLS), `usa.open` (US Open Cup)
  - Date format should be `YYYYMMDD`.
- **Example:**
  - `/deletematchdate 20240709 usa.open`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Failed to delete match date." (If there is an error processing the command)

*For more assistance or queries regarding these commands, please contact the bot administrators.*