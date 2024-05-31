# ECS Discord Bot

## Overview
ECS Discord Bot is a custom Discord bot designed specifically for the Emerald City Supporters. It enhances the user experience by managing match threads, team statistics, ticket information, and more.

## Features
- Match thread management
- Real-time team statistics
- Ticket information handling
- Weather updates for match days
- Integration with WooCommerce for ticket sales
- Custom admin commands for bot management
- Live match reporting
- Member verification
- Pub league team management
- Multiple league/cup support

## Getting Started
To use the ECS Discord Bot, you need to set up a few environment variables. Here is a list of the required variables:

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
Match_dates.json contains all known match dates for the current season.  You can find your endpoint at https://www.espn.com/soccer/competitions, select the competiton and copy the last endpoint from the new URL, for example https://www.espn.com/soccer/league/_/name/concacaf.league

- `date`: `YYYYMMDD` format
- `competition`: `usa.1` (ESPN endpoint for league/cup)
- Endpoint Examples:
- MLS: `usa.1`
- US Open Cup: `usa.open`
- FIFA Club World Cup: `fifa.cwc`
- Concacaf: `concacaf.league`

### Step-by-Step Setup
1. Clone the repository.
2. Install required dependencies.
3. Set up the `.env` file with the above variables.
4. Configure your `match_dates.json`
5. Run the bot
6. As admin execute `/createschedule`

## Contributions
Contributions are welcome! If you'd like to contribute, feel free to fork the repository and submit a pull request.

## Support
For support, questions, or suggestions, please contact the developer or submit an issue on the GitHub repository.