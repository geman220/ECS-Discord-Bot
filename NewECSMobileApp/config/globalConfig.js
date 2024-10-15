const DEV_API_URL = 'http://192.168.1.112:5000/api/v1';
const PROD_API_URL = 'https://portal.ecsfc.com/api/v1';

const globalConfig = {
    API_URL: __DEV__ ? DEV_API_URL : PROD_API_URL,
};

export default globalConfig;