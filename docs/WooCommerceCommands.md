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

- **Description:** Create a CSV list of members in each subgroup.
- **Usage:** `/subgrouplist`
- **Permissions:** Admin
- **Details:**
  - Generates a CSV list of members belonging to various subgroups.
  - Fetches and processes WooCommerce orders to compile the member information.
- **Example:**
  - `/subgrouplist`
- **Error Messages:**
  - "You do not have the necessary permissions." (If the user lacks the required permissions)
  - "Failed to generate subgroup members list." (If there is an error generating the list)

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

*For more assistance or queries regarding these commands, please contact the bot administrators.*