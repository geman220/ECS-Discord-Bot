---
layout: default
---

# Pub League Commands

This section describes commands related to managing pub league teams in the ECS Discord bot.

## Command: `/newpubleague`

- **Description:** Set up a new pub league.
- **Usage:** `/newpubleague`
- **Permissions:** Admin
- **Details:**
  - Initiates the process of setting up a new pub league.
  - Prompts the user for league type (Premier, Classic, ECS FC), team names, and team admins.
  - Creates appropriate roles and channels for the teams and assigns the specified admins.
- **Example:**
  - `/newpubleague`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "You took too long to respond. Please start again." (If the user does not respond in time during the setup process)
  - "The number of admins does not match the number of teams. Please try again." (If the input data is inconsistent)

## Command: `/clearpubleague`

- **Description:** Clears the pub league setup.
- **Usage:** `/clearpubleague <league_type>`
- **Permissions:** Admin
- **Details:**
  - Deletes all roles and channels associated with the specified league type.
  - League types: Premier, Classic, ECS FC.
- **Example:**
  - `/clearpubleague Premier`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Failed to clear the league." (If there is an error processing the command)

*For more assistance or queries regarding these commands, please contact the bot administrators.*