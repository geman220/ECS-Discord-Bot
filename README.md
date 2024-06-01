# ECS Discord Bot

## Overview
ECS Discord Bot is a custom Discord bot designed specifically for the Emerald City Supporters. It enhances the user experience by managing match threads, providing real-time team statistics, handling ticket information, and more.

## Features
- **Match Thread Management:** Automatically create and manage match threads.
- **Real-time Team Statistics:** Fetch and display team statistics.
- **Ticket Information Handling:** Provide links and information for tickets.
- **Weather Updates:** Provide weather updates for match days.
- **WooCommerce Integration:** Integrate with WooCommerce for ticket sales.
- **Admin Commands:** Custom commands for bot management.
- **Live Match Reporting:** Provide live updates during matches.
- **Member Verification:** Verify ECS membership with order numbers.
- **Pub League Team Management:** Manage pub league teams and channels.
- **Multiple League/Cup Support:** Support for various leagues and cups.

## Getting Started

### Prerequisites
To use the ECS Discord Bot, ensure you have the following environment variables set:

- `WC_KEY`: WooCommerce Key
- `WC_SECRET`: WooCommerce Secret
- `BOT_TOKEN`: Discord Bot Token
- `URL`: Site URL
- `TEAM_NAME`: MLS Team Name
- `TEAM_ID`: ESPN Team ID
- `OPENWEATHER_API_KEY`: OpenWeather API Key
- `VENUE_LONG`: Venue Longitude
- `VENUE_LAT`: Venue Latitude
- `FLASK_URL`: Flask URL
- `FLASK_TOKEN`: Flask Token
- `DEV_ID`: Discord Developer ID
- `ADMIN_ROLE`: Discord Admin Role ID
- `SERVER_ID`: Discord Server ID
- `SERPAPI_API`: SerpApi Key
- `WP_USERNAME`: WordPress Username
- `WP_APP_PASSWORD`: WordPress Application Password

### Match_dates.json Setup
The `match_dates.json` file contains all known match dates for the current season. You can find your endpoint at [ESPN Soccer Competitions](https://www.espn.com/soccer/competitions). Select the competition and copy the last endpoint from the new URL (e.g., `concacaf.league` from `https://www.espn.com/soccer/league/_/name/concacaf.league`).

```json
{
  "matches": [
    { "date": "YYYYMMDD", "competition": "endpoint" }
  ]
}
```

- **date:** `YYYYMMDD` format
- **competition:** ESPN endpoint for league/cup

#### Endpoint Examples
- MLS: `usa.1`
- US Open Cup: `usa.open`
- FIFA Club World Cup: `fifa.cwc`
- Concacaf: `concacaf.league`

### Step-by-Step Setup
1. **Clone the Repository:**
    ```bash
    git clone https://github.com/yourusername/ECS-Discord-Bot.git
    cd ECS-Discord-Bot
    ```
2. **Install Required Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
3. **Set Up the `.env` File:**
    ```env
    WC_KEY=your_wc_key
    WC_SECRET=your_wc_secret
    BOT_TOKEN=your_bot_token
    URL=your_site_url
    TEAM_NAME=your_team_name
    TEAM_ID=your_team_id
    OPENWEATHER_API_KEY=your_openweather_api_key
    VENUE_LONG=your_venue_longitude
    VENUE_LAT=your_venue_latitude
    FLASK_URL=your_flask_url
    FLASK_TOKEN=your_flask_token
    DEV_ID=your_developer_id
    ADMIN_ROLE=your_admin_role_id
    SERVER_ID=your_server_id
    SERPAPI_API=your_serpapi_key
    WP_USERNAME=your_wp_username
    WP_APP_PASSWORD=your_wp_app_password
    ```
4. **Configure `match_dates.json`:**
    - Add match dates and competitions.
5. **Run the Bot:**
    ```bash
    python ECS_Discord_Bot.py
    ```
6. **Execute the `/createschedule` Command as Admin:**
    - This will update the schedule with new or changed information.

## Contributions
Contributions are welcome! If you'd like to contribute, feel free to fork the repository and submit a pull request. Please refer to the [Contributing Guidelines](CONTRIBUTING.md) for more details.

## Support
For support, questions, or suggestions, please contact the developer or submit an issue on the GitHub repository.

## License
This project is licensed under the MIT License. See the [LICENSE](LICENSE.md) file for details.
