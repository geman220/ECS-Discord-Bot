// DiscordAuth.js
import * as AuthSession from 'expo-auth-session';
import axios from 'axios';
import globalConfig from '../config/globalConfig';

const discovery = {
    authorizationEndpoint: 'https://discord.com/api/oauth2/authorize',
    tokenEndpoint: 'https://discord.com/api/oauth2/token',
    revocationEndpoint: 'https://discord.com/api/oauth2/token/revoke',
};

export const useDiscordAuth = (navigation) => {
    const [request, response, promptAsync] = AuthSession.useAuthRequest(
        {
            clientId: globalConfig.DISCORD_CLIENT_ID,
            scopes: ['identify', 'email'],
            redirectUri: AuthSession.makeRedirectUri({
                scheme: 'ecs-fc-scheme',
            }),
        },
        discovery
    );

    const handleDiscordLogin = async () => {
        try {
            const result = await promptAsync();
            if (result.type === 'success') {
                const { code } = result.params;
                const backendResponse = await axios.post(`${globalConfig.API_URL}/discord_callback`, {
                    code,
                    redirect_uri: request.redirectUri,
                    code_verifier: request.codeVerifier,
                });

                const data = backendResponse.data;
                if (data.msg === '2FA required') {
                    navigation.navigate('TwoFA', { userId: data.user_id });
                } else if (data.access_token) {
                    await AsyncStorage.setItem('access_token', data.access_token);
                    navigation.replace('App');
                }
            } else {
                console.log('Discord authentication canceled or failed');
            }
        } catch (error) {
            console.error('Error during Discord login:', error.response?.data || error.message);
            Alert.alert('Login Failed', 'An error occurred during Discord login.');
        }
    };

    return { handleDiscordLogin };
};