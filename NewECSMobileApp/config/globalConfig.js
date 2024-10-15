const DEV_API_URL = 'http://192.168.1.112:5000/api/v1';
const PROD_API_URL = 'https://portal.ecsfc.com/api/v1';
const DEV_DISCORD_CLIENT_ID = '1196293716055445624';
const PROD_DISCORD_CLIENT_ID = '1194067098658414632';

const isDevEnv = process.env.EXPO_PUBLIC_ENV !== 'production';

const globalConfig = {
    API_URL: isDevEnv ? DEV_API_URL : PROD_API_URL,
    DISCORD_CLIENT_ID: isDevEnv ? DEV_DISCORD_CLIENT_ID : PROD_DISCORD_CLIENT_ID,
};

export default globalConfig;