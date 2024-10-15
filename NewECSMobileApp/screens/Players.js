import React, { useState, useEffect } from 'react';
import { StyleSheet, Dimensions, ScrollView, RefreshControl } from 'react-native';
import { Block, Text, theme } from "galio-framework";
import { Card } from '../components';
import { argonTheme } from "../constants";
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width } = Dimensions.get('screen');

const Players = ({ navigation }) => {
    const [players, setPlayers] = useState([]);
    const [refreshing, setRefreshing] = useState(false);

    const fetchPlayers = async () => {
        try {
            const token = await AsyncStorage.getItem('access_token');
            const response = await axios.get('http://YOUR_FLASK_API_URL/api/v1/players', {
                headers: { Authorization: `Bearer ${token}` }
            });
            setPlayers(response.data);
        } catch (error) {
            console.error('Error fetching players:', error);
        }
    };

    useEffect(() => {
        fetchPlayers();
    }, []);

    const onRefresh = React.useCallback(() => {
        setRefreshing(true);
        fetchPlayers().then(() => setRefreshing(false));
    }, []);

    return (
        <Block flex center style={styles.home}>
            <ScrollView
                showsVerticalScrollIndicator={false}
                contentContainerStyle={styles.articles}
                refreshControl={
                    <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
                }
            >
                <Block flex>
                    {players.map((player, index) => (
                        <Card
                            key={`player-${index}`}
                            item={{
                                title: player.name,
                                image: player.profile_picture_url || 'https://via.placeholder.com/150',
                                cta: 'View player',
                                horizontal: true
                            }}
                            horizontal
                            style={styles.card}
                            onPress={() => navigation.navigate('PlayerDetails', { playerId: player.id })}
                        />
                    ))}
                </Block>
            </ScrollView>
        </Block>
    );
}

const styles = StyleSheet.create({
    home: {
        width: width,
    },
    articles: {
        width: width - theme.SIZES.BASE * 2,
        paddingVertical: theme.SIZES.BASE,
    },
    card: {
        marginVertical: theme.SIZES.BASE,
    }
});

export default Players;