import Constants from 'expo-constants';

const DEV_API_URL = 'http://192.168.1.112:5000/api/v1';
const PROD_API_URL = 'https://portal.ecsfc.com/api/v1';

// You can set this based on the release channel or Expo's development mode
const isDev = Constants.manifest?.releaseChannel === undefined || Constants.manifest.releaseChannel === 'default';

const globalConfig = {
    API_URL: isDev ? DEV_API_URL : PROD_API_URL,
};

export default globalConfig;
