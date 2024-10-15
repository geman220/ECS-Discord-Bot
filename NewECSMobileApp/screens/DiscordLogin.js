import React from 'react';
import { StyleSheet } from 'react-native';
import { Block, Button } from 'galio-framework';
import { useNavigation } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as AuthSession from 'expo-auth-session';
import axios from 'axios';
import globalConfig from '../config/globalConfig';

const CLIENT_ID = '1196293716055445624';

const discovery = {
    authorizationEndpoint: 'https://discord.com/api/oauth2/authorize',
    tokenEndpoint: 'https://discord.com/api/oauth2/token',
    revocationEndpoint: 'https://discord.com/api/oauth2/token/revoke',
};

const DiscordLogin = () => {
    const navigation = useNavigation();

    const initiateDiscordLogin = async () => {
        try {
            // Generate a redirect URI
            const redirectUri = AuthSession.makeRedirectUri({
                useProxy: true, // This ensures compatibility in Expo Go and standalone apps
            });

            // Define scopes
            const scopes = ['identify', 'email'];

            // Create an AuthRequest
            const authRequest = new AuthSession.AuthRequest({
                clientId: CLIENT_ID,
                redirectUri,
                scopes,
                usePKCE: true,
                responseType: AuthSession.ResponseType.Code,
            });

            // Load the discovery document
            const result = await authRequest.promptAsync(discovery, { useProxy: true });

            if (result.type === 'success') {
                const { code } = result.params;

                // Send the authorization code to your backend to exchange for tokens
                const backendResponse = await axios.post(`${globalConfig.API_URL}/discord_callback`, {
                    code,
                    redirect_uri: redirectUri,
                    // Include the code_verifier
                    code_verifier: authRequest.codeVerifier,
                });

                const data = backendResponse.data;

                if (data.msg === '2FA required') {
                    navigation.navigate('TwoFA', { userId: data.user_id });
                } else if (data.access_token) {
                    await AsyncStorage.setItem('access_token', data.access_token);
                    navigation.replace('App');
                }
            } else {
                console.log('Authentication canceled or failed');
            }
        } catch (error) {
            console.error('Error during Discord login:', error);
        }
    };

    return (
        <Block flex middle style={styles.container}>
            <Button round color="primary" onPress={initiateDiscordLogin}>
                Login with Discord
            </Button>
        </Block>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
    },
});

export default DiscordLogin;
