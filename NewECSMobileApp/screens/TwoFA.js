import React, { useState } from 'react';
import { StyleSheet, View, Alert } from 'react-native';
import { Input, Button, Text } from 'galio-framework';
import { useNavigation, useRoute } from '@react-navigation/native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import axios from 'axios';
import globalConfig from '../config/globalConfig'; // Import globalConfig

const TwoFA = () => {
    const [token, setToken] = useState('');
    const [loading, setLoading] = useState(false);
    const navigation = useNavigation();
    const route = useRoute();
    const { userId } = route.params;

    const handleVerify = async () => {
        if (!token) {
            Alert.alert('Error', 'Please enter the 2FA token.');
            return;
        }

        setLoading(true);

        try {
            console.log('Sending verification request with:');
            console.log('User ID:', userId);
            console.log('Token:', token);

            // Use globalConfig.API_URL instead of hardcoded URL
            const response = await axios.post(`${globalConfig.API_URL}/verify_2fa`, {
                user_id: userId,
                token: token,
            });

            console.log('Response from server:', response.data);

            const data = response.data;

            if (data.access_token) {
                await AsyncStorage.setItem('access_token', data.access_token);
                setLoading(false);
                navigation.replace('App');
            } else {
                setLoading(false);
                Alert.alert('Verification Failed', data.msg || 'Invalid 2FA token.');
            }
        } catch (error) {
            setLoading(false);
            if (error.response) {
                console.error('Verification Error:', error.response.data);
                Alert.alert('Verification Failed', error.response.data.msg || 'An error occurred during 2FA verification.');
            } else {
                console.error('Verification Error:', error.message);
                Alert.alert('Verification Failed', 'An error occurred during 2FA verification.');
            }
        }
    };

    return (
        <View style={styles.container}>
            <Text h5 style={styles.title}>Enter 2FA Token</Text>
            <Input
                placeholder="2FA Token"
                value={token}
                onChangeText={setToken}
                style={styles.input}
            />
            <Button
                round
                uppercase
                color="primary"
                onPress={handleVerify}
                loading={loading}
            >
                Verify
            </Button>
        </View>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        padding: 20,
    },
    title: {
        marginBottom: 20,
    },
    input: {
        width: '100%',
        marginBottom: 20,
    },
});

export default TwoFA;
