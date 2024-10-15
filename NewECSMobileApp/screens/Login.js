// Login.js

import React, { useState } from 'react';
import {
    StyleSheet,
    ImageBackground,
    Dimensions,
    StatusBar,
    TouchableWithoutFeedback,
    Keyboard,
    Alert,
    View,
    Image,
    TouchableOpacity, // Import added here
} from 'react-native';
import { Block, Text, theme } from 'galio-framework';
import { Button, Icon, Input } from '../components';
import { Images, argonTheme } from '../constants';
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as AuthSession from 'expo-auth-session';
import globalConfig from '../config/globalConfig';

const { width, height } = Dimensions.get('screen');

const CLIENT_ID = '1194067098658414632';
const discovery = {
    authorizationEndpoint: 'https://discord.com/api/oauth2/authorize',
    tokenEndpoint: 'https://discord.com/api/oauth2/token',
    revocationEndpoint: 'https://discord.com/api/oauth2/token/revoke',
};

// DismissKeyboard component to hide keyboard when tapping outside input fields
const DismissKeyboard = ({ children }) => (
    <TouchableWithoutFeedback onPress={() => Keyboard.dismiss()}>
        {children}
    </TouchableWithoutFeedback>
);

const Login = ({ navigation }) => {
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [loading, setLoading] = useState(false);
    const [showEmailLogin, setShowEmailLogin] = useState(false);

    // Handler for Email Login
    const handleEmailLogin = async () => {
        if (!email || !password) {
            Alert.alert('Error', 'Please enter both email and password.');
            return;
        }

        setLoading(true);

        try {
            const response = await axios.post(`${globalConfig.API_URL}/login`, {
                email,
                password,
            });

            const data = response.data;

            if (data.msg === '2FA required') {
                setLoading(false);
                navigation.navigate('TwoFA', { userId: data.user_id });
            } else if (data.access_token) {
                await AsyncStorage.setItem('access_token', data.access_token);
                setLoading(false);
                navigation.replace('App');
            }
        } catch (error) {
            setLoading(false);
            const errorMsg = error.response?.data?.msg || 'An error occurred during login.';
            Alert.alert('Login Failed', errorMsg);
        }
    };

    // Handler for Discord Login
    const handleDiscordLogin = async () => {
        try {
            // Use the custom URI scheme 'ecs-fc-scheme'
            const redirectUri = AuthSession.makeRedirectUri({
                scheme: 'ecs-fc-scheme',  // Use your custom scheme from app.json
            });

            const scopes = ['identify', 'email'];
            const authRequest = new AuthSession.AuthRequest({
                clientId: CLIENT_ID,
                redirectUri,  // Pass in the custom redirect URI
                scopes,
                usePKCE: true,
                responseType: AuthSession.ResponseType.Code,
            });

            // Remove { useProxy: true } for production builds
            const result = await authRequest.promptAsync(discovery);
            if (result.type === 'success') {
                const { code } = result.params;
                const backendResponse = await axios.post(`${globalConfig.API_URL}/discord_callback`, {
                    code,
                    redirect_uri: redirectUri,  // Pass the custom URI to the backend as well
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
                console.log('Discord authentication canceled or failed');
            }
        } catch (error) {
            console.error('Error during Discord login:', error);
            Alert.alert('Login Failed', 'An error occurred during Discord login.');
        }
    };

    return (
        <DismissKeyboard>
            <Block flex middle>
                <StatusBar hidden />
                <ImageBackground
                    source={Images.RegisterBackground}
                    style={styles.background}
                >
                    <Block safe flex middle>
                        <Block style={styles.loginContainer}>
                            {/* Logo and Welcome Message */}
                            <Block style={styles.logoContainer}>
                                <Image
                                    source={require('../assets/imgs/ecs_logo.png')} // Ensure the path is correct
                                    style={styles.logo}
                                    resizeMode="contain"
                                />
                                <Text size={24} color={argonTheme.COLORS.PRIMARY} style={styles.welcomeText}>
                                    Welcome!
                                </Text>
                                <Text size={14} color={argonTheme.COLORS.TEXT} style={styles.instructionText}>
                                    Please login to continue
                                </Text>
                            </Block>

                            {/* Login Options */}
                            <Block style={styles.optionsContainer}>
                                {/* Discord Login Button */}
                                <Button
                                    color="discord" // Ensure 'discord' is defined in your theme
                                    style={styles.discordButton}
                                    onPress={handleDiscordLogin}
                                >
                                    <Block row middle>
                                        <Icon
                                            name="logo-discord"
                                            family="Ionicon"
                                            size={20}
                                            color={argonTheme.COLORS.WHITE}
                                            style={styles.discordIcon}
                                        />
                                        <Text
                                            style={styles.buttonText}
                                            size={14}
                                            color={argonTheme.COLORS.WHITE}
                                        >
                                            LOGIN WITH DISCORD
                                        </Text>
                                    </Block>
                                </Button>

                                {/* Toggle Email Login */}
                                <Block style={styles.toggleContainer}>
                                    <Text size={14} color={argonTheme.COLORS.TEXT}>
                                        Prefer email login?
                                    </Text>
                                    <TouchableOpacity onPress={() => setShowEmailLogin(!showEmailLogin)}>
                                        <Text
                                            size={14}
                                            color={argonTheme.COLORS.PRIMARY}
                                            style={styles.toggleText}
                                        >
                                            {showEmailLogin ? 'Hide' : 'Show'}
                                        </Text>
                                    </TouchableOpacity>
                                </Block>

                                {/* Email Login Form */}
                                {showEmailLogin && (
                                    <View style={styles.emailLoginContainer}>
                                        <Input
                                            placeholder="Email"
                                            onChangeText={setEmail}
                                            value={email}
                                            autoCapitalize="none"
                                            keyboardType="email-address"
                                            iconContent={
                                                <Icon
                                                    size={16}
                                                    color="#ADB5BD"
                                                    name="ic_mail_24px"
                                                    family="ArgonExtra"
                                                    style={styles.inputIcons}
                                                />
                                            }
                                        />
                                        <Input
                                            placeholder="Password"
                                            password
                                            onChangeText={setPassword}
                                            value={password}
                                            iconContent={
                                                <Icon
                                                    size={16}
                                                    color="#ADB5BD"
                                                    name="padlock-unlocked"
                                                    family="ArgonExtra"
                                                    style={styles.inputIcons}
                                                />
                                            }
                                        />
                                        <Button
                                            color="primary"
                                            style={styles.emailLoginButton}
                                            onPress={handleEmailLogin}
                                            loading={loading}
                                        >
                                            <Text
                                                style={styles.buttonText}
                                                size={14}
                                                color={argonTheme.COLORS.WHITE}
                                            >
                                                LOGIN WITH EMAIL
                                            </Text>
                                        </Button>
                                    </View>
                                )}
                            </Block>
                        </Block>
                    </Block>
                </ImageBackground>
            </Block>
        </DismissKeyboard>
    );
};

const styles = StyleSheet.create({
    background: {
        width: width,
        height: height,
        zIndex: 1,
    },
    loginContainer: {
        width: width * 0.9,
        height: height * 0.7, // Set height to 70% of screen
        backgroundColor: '#F4F5F7',
        borderRadius: 12, // Smooth border radius
        shadowColor: argonTheme.COLORS.BLACK,
        shadowOffset: {
            width: 0,
            height: 4,
        },
        shadowRadius: 8,
        shadowOpacity: 0.1,
        elevation: 5, // Prominent shadow
        overflow: 'hidden',
        padding: theme.SIZES.BASE, // Inner padding
        alignItems: 'center', // Center children horizontally
        justifyContent: 'center', // Center children vertically
    },
    logoContainer: {
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: 20, // Added margin to separate from buttons
    },
    logo: {
        width: 120,
        height: 120,
        borderRadius: 60, // Circular logo
    },
    welcomeText: {
        marginTop: 10,
        fontWeight: '700', // Bold text
        textAlign: 'center', // Center the text
    },
    instructionText: {
        marginTop: 5,
        textAlign: 'center',
    },
    optionsContainer: {
        width: '100%', // Ensure it takes full width of loginContainer
        alignItems: 'center', // Center child elements horizontally
    },
    discordButton: {
        width: '100%',
        height: 50,
        borderRadius: 25,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: '#5865F2', // Discord brand color
        marginTop: 10, // Added margin to prevent overlapping
        flexDirection: 'row', // Align icon and text horizontally
    },
    discordIcon: {
        marginRight: 10,
    },
    buttonText: {
        fontFamily: 'open-sans-bold',
        color: '#fff', // Ensure text is visible on button
        fontSize: 16, // Consistent font size
    },
    toggleContainer: {
        marginTop: 15,
        flexDirection: 'row', // Align text and toggle horizontally
        justifyContent: 'center', // Center the toggle elements
    },
    toggleText: {
        marginLeft: 5,
        textDecorationLine: 'underline',
        color: argonTheme.COLORS.PRIMARY, // Match theme color
    },
    emailLoginContainer: {
        width: '100%',
        marginTop: 15,
        alignItems: 'center', // Center email login elements
    },
    emailLoginButton: {
        width: '100%',
        marginTop: 15,
        height: 50,
        borderRadius: 25,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: argonTheme.COLORS.PRIMARY, // Use theme color
    },
    inputIcons: {
        marginRight: 12,
    },
});

export default Login;
