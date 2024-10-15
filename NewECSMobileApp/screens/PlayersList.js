import React, { useState, useEffect } from "react";
import {
    StyleSheet,
    Dimensions,
    ScrollView,
    SafeAreaView,
    ActivityIndicator,
    TextInput,
    TouchableOpacity,
    Image,
} from "react-native";
import { Block, Text } from "galio-framework";
import { argonTheme } from "../constants";
import axios from "axios";
import AsyncStorage from '@react-native-async-storage/async-storage';
import globalConfig from '../config/globalConfig';

const { width } = Dimensions.get("screen");

const PlayersList = ({ navigation }) => {
    const [players, setPlayers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchQuery, setSearchQuery] = useState("");

    useEffect(() => {
        fetchPlayers();
    }, [searchQuery]);

    const fetchPlayers = async () => {
        try {
            const token = await AsyncStorage.getItem('access_token');
            const headers = { Authorization: `Bearer ${token}` };
            const response = await axios.get(`${globalConfig.API_URL}/players?search=${searchQuery}`, { headers });
            setPlayers(response.data);
        } catch (error) {
            console.error("Error fetching players:", error);
        } finally {
            setLoading(false);
        }
    };

    if (loading) {
        return (
            <Block flex center>
                <ActivityIndicator size="large" color={argonTheme.COLORS.PRIMARY} />
            </Block>
        );
    }

    return (
        <SafeAreaView style={styles.safeArea}>
            <TextInput
                style={styles.searchBar}
                placeholder="Search players..."
                value={searchQuery}
                onChangeText={setSearchQuery}
            />
            <ScrollView
                showsVerticalScrollIndicator={false}
                contentContainerStyle={styles.scrollViewContent}
            >
                {players.length === 0 ? (
                    <Block flex middle>
                        <Text>No players found.</Text>
                    </Block>
                ) : (
                    players.map((player, index) => (
                        <TouchableOpacity
                            key={player.id}
                            style={styles.playerCard}
                            onPress={() => navigation.navigate('PlayerProfile', { playerId: player.id })}
                        >
                            <Block style={styles.playerInfo}>
                                <Image
                                    source={{ uri: player.profile_picture_url }}
                                    style={styles.playerImage}
                                />
                                <Block style={styles.playerDetails}>
                                    <Text size={18} bold>{player.name}</Text>
                                    <Text size={14} muted>{player.team_name}</Text>
                                    <Text size={14} muted>{player.league_name}</Text>
                                </Block>
                            </Block>
                        </TouchableOpacity>
                    ))
                )}
            </ScrollView>
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    safeArea: {
        flex: 1,
        backgroundColor: argonTheme.COLORS.WHITE,
    },
    searchBar: {
        height: 40,
        borderColor: argonTheme.COLORS.BORDER,
        borderWidth: 1,
        borderRadius: 8,
        margin: 15,
        paddingLeft: 10,
    },
    scrollViewContent: {
        paddingBottom: 30,
    },
    playerCard: {
        flexDirection: 'row',
        padding: 10,
        marginBottom: 10,
        borderWidth: 1,
        borderColor: argonTheme.COLORS.BORDER,
        borderRadius: 8,
        backgroundColor: argonTheme.COLORS.WHITE,
    },
    playerInfo: {
        flexDirection: 'row',
        alignItems: 'center',
    },
    playerImage: {
        width: 60,
        height: 60,
        borderRadius: 30,
        marginRight: 10,
    },
    playerDetails: {
        flexDirection: 'column',
    },
});

export default PlayersList;