---
layout: default
---

# WooCommerce Commands

This section describes commands available for managing WooCommerce orders in the ECS Discord bot.

## Command: `/ticketlist`

- **Description:** List all tickets for sale.
- **Usage:** `/ticketlist`
- **Permissions:** Required working group role
- **Details:**
  - Lists all home and away tickets currently available for sale.
  - Searches for tickets in the specified categories for the current year.
- **Example:**
  - `/ticketlist`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "No home tickets found." or "No away tickets found." (If no tickets are available in the specified categories)

## Command: `/getorderinfo`

- **Description:** Retrieve order details for a specific product.
- **Usage:** `/getorderinfo <product_title>`
- **Permissions:** None
- **Details:**
  - Retrieves and lists orders for a specified product and its variations.
  - Generates a CSV file containing the order details.
- **Example:**
  - `/getorderinfo "Seattle Sounders FC Home Jersey"`
- **Error Messages:**
  - "Product not found." (If the specified product does not exist)
  - "No orders found for this product or its variations." (If no orders are available)
  - "Failed to generate CSV file." (If there is an error generating the CSV file)

## Command: `/updateorders`

- **Description:** Update local orders database from WooCommerce.
- **Usage:** `/updateorders`
- **Permissions:** Required working group role
- **Details:**
  - Fetches and updates the local orders database with new orders from WooCommerce.
  - Checks for new orders since the last update.
- **Example:**
  - `/updateorders`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Failed to update orders database." (If there is an error updating the database)

## Command: `/subgrouplist`

- **Description:** Create a CSV list of members in each subgroup for a given membership year.
- **Usage:** `/subgrouplist <year>`
- **Permissions:** ECS Leadership role
- **Details:**
  - Looks up the membership plan for the provided year.
  - Pulls member records from WooCommerce Memberships and groups them by the `ECS Subgroup` profile field.
  - Generates and returns a CSV file: subgroup, first name, last name, and email.
- **Example:**
  - `/subgrouplist 2026`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "A membership plan for the year <year> could not be found." (If no yearly plan matches)
  - "Failed to generate subgroup members list." (If there is an error generating the list)

## Command: `/reviewmemberships`

- **Description:** Review recent orders for membership purchases that may be missing matching membership records.
- **Usage:** `/reviewmemberships`
- **Permissions:** Leadership roles
- **Details:**
  - Scans orders from the last 7 days.
  - Uses reconciliation logic to identify orders requiring manual membership review.
  - Returns a "Membership reconciliation" report in Discord.
- **Example:**
  - `/reviewmemberships`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "An error occurred while generating the list: ..." (If reconciliation fails)

## Command: `/reviewsubgroups`

- **Description:** Review recent orders for subgroup purchases that may be disconnected from membership profile data.
- **Usage:** `/reviewsubgroups`
- **Permissions:** Leadership roles
- **Details:**
  - Scans orders from the last 7 days.
  - Detects subgroup purchases that require manual reconciliation.
  - Returns a "Subgroup reconciliation" report in Discord.
- **Example:**
  - `/reviewsubgroups`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "An error occurred while generating the list: ..." (If reconciliation fails)

## Command: `/refreshorders`

- **Description:** Refresh WooCommerce order cache.
- **Usage:** `/refreshorders`
- **Permissions:** Required working group role
- **Details:**
  - Resets the local WooCommerce orders database.
  - Requires a subsequent call to `/updateorders` to repopulate the database.
- **Example:**
  - `/refreshorders`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Failed to reset orders database." (If there is an error resetting the database)

## Command: `/proliferate`

- **Description:** Push subgroup information to WooCommerce membership profile fields based on order history.
- **Usage:** `/proliferate`
- **Permissions:** Leadership roles
- **Details:**
  - Pages through membership-related orders.
  - Finds the member record for each customer and updates profile field `ecs-subgroup` when subgroup data exists in order line items.
  - Intended as an operational reconciliation tool for membership/subgroup alignment.
- **Example:**
  - `/proliferate`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "No orders found to process for subgroup proliferation." (If no matching orders are found)
  - "An error occurred while generating the list: ..." (If processing fails)

*For more assistance or queries regarding these commands, please contact the bot administrators.*