import React, { useState, useEffect } from "react";
import {
    StyleSheet,
    Dimensions,
    ScrollView,
    SafeAreaView,
    ActivityIndicator,
    TouchableOpacity
} from "react-native";
import { Block, Text } from "galio-framework";
import { argonTheme } from "../constants";
import axios from "axios";
import AsyncStorage from '@react-native-async-storage/async-storage';
import globalConfig from '../config/globalConfig';

const { width, height } = Dimensions.get("screen");

const Teams = ({ navigation }) => {
    const [teams, setTeams] = useState([]);
    const [loading, setLoading] = useState(true);
    const [groupedTeams, setGroupedTeams] = useState({});

    useEffect(() => {
        fetchTeams();
    }, []);

    const fetchTeams = async () => {
        try {
            const token = await AsyncStorage.getItem('access_token');
            const headers = { Authorization: `Bearer ${token}` };
            const teamsResponse = await axios.get(`${globalConfig.API_URL}/teams`, { headers });
            const teamsData = teamsResponse.data;
            groupTeamsByLeague(teamsData); // Group teams by league after fetching
        } catch (error) {
            console.error("Error fetching teams:", error);
        } finally {
            setLoading(false);
        }
    };

    const groupTeamsByLeague = (teams) => {
        const grouped = teams.reduce((acc, team) => {
            const leagueName = team.league_name || "Unknown League";
            if (!acc[leagueName]) {
                acc[leagueName] = [];
            }
            acc[leagueName].push(team);
            return acc;
        }, {});
        setGroupedTeams(grouped);
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
            <ScrollView
                showsVerticalScrollIndicator={false}
                contentContainerStyle={styles.scrollViewContent}
            >
                {Object.keys(groupedTeams).length === 0 ? (
                    <Block flex middle>
                        <Text>No teams found.</Text>
                    </Block>
                ) : (
                    Object.keys(groupedTeams).map((league, index) => (
                        <Block key={index} style={styles.leagueSection}>
                            <Text size={20} bold style={styles.leagueTitle}>
                                {league}
                            </Text>
                            {groupedTeams[league].map((team) => (
                                <TouchableOpacity
                                    key={team.id}
                                    style={styles.teamCard}
                                    onPress={() => navigation.navigate('TeamDetails', { teamId: team.id })}
                                >
                                    <Text size={18} bold>{team.name}</Text>
                                    {team.logo_url && (
                                        <Image
                                            source={{ uri: team.logo_url }}
                                            style={styles.teamLogo}
                                        />
                                    )}
                                </TouchableOpacity>
                            ))}
                        </Block>
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
    scrollViewContent: {
        paddingVertical: 20,
        paddingHorizontal: 20,
    },
    leagueSection: {
        marginBottom: 30,
    },
    leagueTitle: {
        marginBottom: 10,
        color: argonTheme.COLORS.PRIMARY,
    },
    teamCard: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: 15,
        marginBottom: 10,
        borderWidth: 1,
        borderColor: argonTheme.COLORS.BORDER,
        borderRadius: 8,
        backgroundColor: argonTheme.COLORS.WHITE,
    },
    teamLogo: {
        width: 50,
        height: 50,
        borderRadius: 25,
    },
});

export default Teams;
