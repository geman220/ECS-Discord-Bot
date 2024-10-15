// DiscordAuth.js
import * as WebBrowser from 'expo-web-browser';
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Alert } from 'react-native';
import * as Linking from 'expo-linking';
import globalConfig from '../config/globalConfig';

const redirectUri = Linking.createURL('auth');
WebBrowser.maybeCompleteAuthSession();

export const useDiscordAuth = (navigation) => {
    const handleDiscordLogin = async () => {
        try {
            // Make a GET request to the /get_discord_auth_url endpoint
            const response = await axios.get(`${globalConfig.API_URL}/get_discord_auth_url`, {
                params: { redirect_uri: redirectUri },
            });

            const { auth_url } = response.data;

            // Open the Discord authorization URL in the browser
            const result = await WebBrowser.openAuthSessionAsync(auth_url, redirectUri);

            if (result.type === 'success') {
                const { code } = Linking.parse(result.url).queryParams;

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