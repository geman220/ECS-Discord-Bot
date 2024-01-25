---
layout: default
---

# WooCommerce Commands

This section covers commands related to WooCommerce integration in the ECS Discord bot.

## Command: ticketlist

- **Description:** Lists all available tickets for sale, both home and away.
- **Usage:** `/ticketlist`
- **Permissions:** Requires specific role permissions to access.
- **Details:** Lists all tickets available in the WooCommerce store, categorized into Home and Away tickets.

## Command: getorderinfo

- **Description:** Retrieve detailed order information for a specific product.
- **Usage:** `/getorderinfo [product_title]`
- **Parameters:**
  - `product_title`: Title of the product for which you want to retrieve order details.
- **Permissions:** Requires specific role permissions to access.
- **Details:** This command fetches detailed order information for the specified product and outputs it in a CSV format. It includes customer details, order status, and other relevant order information.

## Command: updateorders

- **Description:** Update the local database with the latest order information from WooCommerce.
- **Usage:** `/updateorders`
- **Parameters:** None.
- **Permissions:** Requires admin role permissions.
- **Details:** The `updateorders` command fetches all the latest orders from WooCommerce and updates the local database. It ensures that only new orders, which are not already present in the database, are added. This process helps maintain an up-to-date local copy of orders, enabling efficient access and analysis without repeatedly querying the WooCommerce API. The command provides a confirmation message once the database update is complete, indicating the number of new orders added.

## Command: subgroupcount

- **Description:** Count the number of orders for each ECS subgroup.
- **Usage:** `/subgroupcount`
- **Parameters:** None.
- **Permissions:** Requires admin role permissions.
- **Details:** This command performs an automatic update of the local orders database to include any new orders from WooCommerce. It then calculates and displays the total number of orders for each ECS subgroup, such as '253 Defiance', 'Barra Fuerza Verde', 'Heartland Horde', etc. The result is presented in a message format listing each subgroup with its corresponding order count.

## Command: subgrouplist

- **Description:** Generate a CSV list of members for a specific ECS subgroup, including their names and email addresses.
- **Usage:** `/subgrouplist`
- **Parameters:** None.
- **Permissions:** Requires admin role permissions.
- **Details:** Similar to the `subgroupcount` command, `subgrouplist` first updates the local database with the latest orders from WooCommerce. It then generates a CSV file containing the names and email addresses of members in each ECS subgroup. The CSV file is provided as an attachment in the command response for easy download and review.

*For more assistance or queries regarding these commands, please contact the bot administrators.*