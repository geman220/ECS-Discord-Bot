const DEV_API_URL = 'http://192.168.1.112:5000/api/v1';
const PROD_API_URL = 'https://portal.ecsfc.com/api/v1';
const DEV_DISCORD_CLIENT_ID = '1196293716055445624';
const PROD_DISCORD_CLIENT_ID = '1194067098658414632';

const isDev = __DEV__;

const globalConfig = {
    API_URL: isDev ? DEV_API_URL : PROD_API_URL,
    DISCORD_CLIENT_ID: isDev ? DEV_DISCORD_CLIENT_ID : PROD_DISCORD_CLIENT_ID,
};

export default globalConfig;