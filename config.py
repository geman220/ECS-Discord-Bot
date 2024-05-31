# config.py

import os
from dotenv import load_dotenv

load_dotenv()

def get_env_variable(var_name, default=None):
    return os.getenv(var_name, default)

BOT_CONFIG = {
    'wc_key': get_env_variable('WC_KEY'),
    'wc_secret': get_env_variable('WC_SECRET'),
    'bot_token': get_env_variable('BOT_TOKEN'),
    'wc_url': get_env_variable('URL'),
    'team_name': get_env_variable('TEAM_NAME'),
    'team_id': get_env_variable('TEAM_ID'),
    'openweather_api': get_env_variable('OPENWEATHER_API_KEY'),
    'venue_long': get_env_variable('VENUE_LONG'),
    'venue_lat': get_env_variable('VENUE_LAT'),
    'flask_url': get_env_variable('FLASK_URL'),
    'flask_token': get_env_variable('FLASK_TOKEN'),
    'discord_admin_role': get_env_variable('ADMIN_ROLE'),
    'dev_id': get_env_variable('DEV_ID'),
    'server_id': get_env_variable('SERVER_ID'),
    'serpapi_api': get_env_variable('SERPAPI_API'),
    'wp_username': get_env_variable('WP_USERNAME'),
    'wp_app_password': get_env_variable('WP_APP_PASSWORD'),
    'match_channel_id': get_env_variable('MATCH_CHANNEL_ID'),
    'bot_version': "1.7.0"
}