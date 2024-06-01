---
layout: default
---

# Admin Commands

This section describes commands available for administrators in the ECS Discord bot.

## Command: `/update`

- **Description:** Updates the bot from the GitHub repository.
- **Usage:** `/update`
- **Permissions:** Admin or Bot Owner
- **Details:** 
  - Initiates the bot update process, pulling the latest changes from the GitHub repository.
  - Use this command to ensure the bot is running the most recent codebase.
- **Example:**
  - `/update`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Update failed." (If the update process encounters an error)

## Command: `/version`

- **Description:** Displays the current version of the bot.
- **Usage:** `/version`
- **Permissions:** Admin or Bot Owner
- **Details:** 
  - Shows the current version of the ECS Bot, including developer details.
  - Use this command to verify the version of the bot running on the server.
- **Example:**
  - `/version`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Unable to fetch version information." (If there is an error fetching the version)

## Command: `/checkorder`

- **Description:** Checks an ECS membership order.
- **Usage:** `/checkorder`
- **Permissions:** Admin
- **Details:** 
  - Opens a modal for administrators to check the status of an ECS membership order.
  - This command is useful for verifying membership details.
- **Example:**
  - `/checkorder`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Unable to check order status." (If there is an error processing the command)

## Command: `/newseason`

- **Description:** Starts a new season with a new ECS membership role.
- **Usage:** `/newseason`
- **Permissions:** Admin
- **Details:** 
  - Opens a modal to create a new membership role for the upcoming season.
  - Use this command at the beginning of a new season to organize members.
- **Example:**
  - `/newseason`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Unable to start a new season." (If there is an error processing the command)

## Command: `/createschedule`

- **Description:** Creates the team schedule file.
- **Usage:** `/createschedule`
- **Permissions:** Admin
- **Details:** 
  - Generates a team schedule file based on match data, used for other functionalities.
  - Use this command to update the team schedule with new or changed information.
- **Example:**
  - `/createschedule`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Failed to create schedule." (If there is an error processing the command)

*For more assistance or queries regarding these commands, please contact the bot administrators.*