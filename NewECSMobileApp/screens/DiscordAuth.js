// DiscordAuth.js
import * as WebBrowser from 'expo-web-browser';
import { makeRedirectUri, useAuthRequest } from 'expo-auth-session';
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Alert } from 'react-native';
import * as Linking from 'expo-linking';
import globalConfig from '../config/globalConfig';

const redirectUri = Linking.createURL('auth');

WebBrowser.maybeCompleteAuthSession();

// Endpoint
const discovery = {
    authorizationEndpoint: 'https://discord.com/api/oauth2/authorize',
    tokenEndpoint: 'https://discord.com/api/oauth2/token',
};

export const useDiscordAuth = (navigation) => {
    const [request, response, promptAsync] = useAuthRequest(
        {
            clientId: globalConfig.DISCORD_CLIENT_ID,
            scopes: ['identify', 'email'],
            redirectUri: redirectUri,
        },
        discovery
    );

    const handleDiscordLogin = async () => {
        try {
            const result = await promptAsync();
            if (result.type === 'success') {
                const { code } = result.params;
                // Send the code to your backend
                const backendResponse = await axios.post(`${globalConfig.API_URL}/discord_callback`, {
                    code,
                    redirect_uri: redirectUri,
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