// MatchDetails.js

import React, { useEffect, useState } from 'react';
import {
    StyleSheet,
    ScrollView,
    TouchableOpacity,
    ImageBackground,
    ActivityIndicator,
    SafeAreaView
} from 'react-native';
import { Block, Text, theme } from 'galio-framework';
import { Button } from '../components';
import axios from 'axios';
import globalConfig from '../config/globalConfig';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { argonTheme, Images } from '../constants';
import { getEventIcon, getEventIconFamily, getEventColor, getRSVPColor } from '../utils/eventHelpers';
import Icon from '../components/Icon'; // Ensure you use the updated Icon component

const MatchDetails = ({ route, navigation }) => {
    const { matchId } = route.params;

    const [matchData, setMatchData] = useState(null);
    const [userAvailability, setUserAvailability] = useState(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        fetchMatchData();
    }, [matchId]);

    const fetchMatchData = async () => {
        try {
            setLoading(true);
            setError(null);
            const token = await AsyncStorage.getItem('access_token');
            const headers = { Authorization: `Bearer ${token}` };
            const url = `${globalConfig.API_URL}/matches/${matchId}?include_events=true&include_teams=true&include_players=true`;
            const response = await axios.get(url, { headers });
            setMatchData(response.data);
            setUserAvailability(response.data.availability ? response.data.availability.response : null);
        } catch (error) {
            console.error('Error fetching match data:', error);
            setError('Failed to load match details. Please try again.');
        } finally {
            setLoading(false);
        }
    };

    const updateAvailability = async (response) => {
        try {
            const token = await AsyncStorage.getItem('access_token');
            const headers = { Authorization: `Bearer ${token}` };
            const url = `${globalConfig.API_URL}/update_availability`;
            await axios.post(url, {
                match_id: matchId,
                availability: response
            }, { headers });
            setUserAvailability(response);
            fetchMatchData();
        } catch (error) {
            console.error('Error updating availability:', error);
            setError('Failed to update availability. Please try again.');
        }
    };

    if (loading) {
        return (
            <SafeAreaView style={styles.container}>
                <ActivityIndicator size="large" color={argonTheme.COLORS.PRIMARY} />
            </SafeAreaView>
        );
    }

    if (error) {
        return (
            <SafeAreaView style={styles.container}>
                <Text style={styles.errorText}>{error}</Text>
                <Button onPress={fetchMatchData} color="primary">Retry</Button>
            </SafeAreaView>
        );
    }

    if (!matchData) {
        return (
            <SafeAreaView style={styles.container}>
                <Text>No match data available.</Text>
            </SafeAreaView>
        );
    }

    const matchDateTime = new Date(`${matchData.date}T${matchData.time}`);

    const renderRSVPButtons = () => (
        <Block row space="between" style={styles.rsvpButtonContainer}>
            {['yes', 'no', 'maybe'].map((status) => (
                <Button
                    key={status}
                    small
                    color={userAvailability === status ? getRSVPColor(status) : "secondary"}
                    style={styles.rsvpButton}
                    onPress={() => updateAvailability(status)}
                    accessibilityLabel={`RSVP ${status}`}
                    accessible={true}
                >
                    <Text style={[
                        styles.buttonText,
                        { color: userAvailability === status ? argonTheme.COLORS.WHITE : argonTheme.COLORS.TEXT }
                    ]}>
                        {status.charAt(0).toUpperCase() + status.slice(1)}
                    </Text>
                </Button>
            ))}
        </Block>
    );

    const renderTeamPlayers = (teamData, teamType) => (
        <Block style={styles.teamSection}>
            <Text h5 style={styles.teamTitle}>{teamData.name}</Text>
            {teamData.players.map((player) => (
                <TouchableOpacity
                    key={player.id}
                    onPress={() => navigation.navigate('PlayerProfile', { playerId: player.id })}
                    accessibilityLabel={`View profile of ${player.name}`}
                    accessible={true}
                    style={styles.touchable}
                >
                    <Block row space="between" style={styles.playerItem}>
                        <Text>{player.name}</Text>
                        <Text style={[styles.rsvpStatus, { color: getRSVPColor(player.availability) }]}>
                            {player.availability ? player.availability.toUpperCase() : 'Not responded'}
                        </Text>
                    </Block>
                </TouchableOpacity>
            ))}
        </Block>
    );

    const renderMatchEvents = () => (
        <Block style={styles.eventsContainer}>
            <Text h5 style={styles.sectionTitle}>Match Events</Text>
            {matchData.events.map((event) => {
                const playerName = getPlayerNameById(event.player_id);
                return (
                    <TouchableOpacity
                        key={event.id}
                        onPress={() => event.player_id && navigation.navigate('PlayerProfile', { playerId: event.player_id })}
                        accessibilityLabel={`View profile of ${playerName}`}
                        accessible={true}
                        style={styles.touchable}
                    >
                        <Block row space="between" style={styles.eventItem}>
                            <Block row>
                                <Icon
                                    name={getEventIcon(event.event_type)}
                                    family={getEventIconFamily(event.event_type)}
                                    color={getEventColor(event.event_type)}
                                    size={20}
                                    style={styles.icon}
                                />
                                <Text>
                                    {event.minute ? `${event.minute}' - ` : ''}{playerName || 'Unknown Player'}
                                </Text>
                            </Block>
                            <Text>{event.event_type.replace('_', ' ').toUpperCase()}</Text>
                        </Block>
                    </TouchableOpacity>
                );
            })}
        </Block>
    );

    const getPlayerNameById = (playerId) => {
        const allPlayers = [...matchData.home_team.players, ...matchData.away_team.players];
        const player = allPlayers.find(p => p.id === playerId);
        return player ? player.name : 'Unknown Player';
    };

    return (
        <SafeAreaView style={styles.container}>
            <ScrollView>
                <ImageBackground
                    source={Images.DefaultMatchImage}
                    style={styles.headerBackground}
                >
                    <Block flex style={styles.headerContent}>
                        <Text h3 bold color={theme.COLORS.WHITE}>
                            {matchData.home_team.name} vs {matchData.away_team.name}
                        </Text>
                        <Text h5 color={theme.COLORS.WHITE}>
                            {matchDateTime.toLocaleDateString()} at {matchDateTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </Text>
                        <Text h2 bold color={theme.COLORS.WHITE} style={styles.score}>
                            {matchData.home_team_score || 0} - {matchData.away_team_score || 0}
                        </Text>
                    </Block>
                </ImageBackground>

                <Block flex style={styles.contentContainer}>
                    <Block flex style={styles.rsvpContainer}>
                        <Text h4 style={styles.sectionTitle}>RSVP</Text>
                        {renderRSVPButtons()}
                    </Block>

                    {renderTeamPlayers(matchData.home_team, 'home')}
                    {renderTeamPlayers(matchData.away_team, 'away')}

                    {renderMatchEvents()}

                    <Block flex style={styles.notesContainer}>
                        <Text h4 style={styles.sectionTitle}>Match Notes</Text>
                        <Text>{matchData.notes || 'No match notes available.'}</Text>
                    </Block>
                </Block>
            </ScrollView>
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    container: {
        flex: 1,
        backgroundColor: argonTheme.COLORS.BLOCK,
    },
    headerBackground: {
        width: '100%',
        height: 200,
    },
    headerContent: {
        flex: 1,
        justifyContent: 'center',
        alignItems: 'center',
        backgroundColor: 'rgba(0,0,0,0.5)',
        padding: theme.SIZES.BASE,
    },
    score: {
        marginTop: theme.SIZES.BASE,
    },
    contentContainer: {
        padding: theme.SIZES.BASE,
        backgroundColor: argonTheme.COLORS.BLOCK,
    },
    rsvpContainer: {
        marginBottom: theme.SIZES.BASE * 2,
    },
    rsvpButtonContainer: {
        marginTop: theme.SIZES.BASE,
    },
    rsvpButton: {
        width: '30%',
        borderWidth: 1,
        borderColor: argonTheme.COLORS.BORDER,
    },
    buttonText: {
        fontSize: 14,
        fontWeight: '600',
    },
    sectionTitle: {
        marginBottom: theme.SIZES.BASE,
    },
    teamSection: {
        marginBottom: theme.SIZES.BASE * 2,
    },
    teamTitle: {
        marginBottom: theme.SIZES.BASE,
        color: argonTheme.COLORS.PRIMARY,
    },
    playerItem: {
        paddingVertical: theme.SIZES.BASE / 2,
        borderBottomWidth: 1,
        borderBottomColor: argonTheme.COLORS.BORDER,
    },
    icon: {
        marginRight: theme.SIZES.BASE / 2,
    },
    rsvpStatus: {
        fontWeight: '600',
    },
    eventsContainer: {
        marginBottom: theme.SIZES.BASE * 2,
    },
    eventItem: {
        paddingVertical: theme.SIZES.BASE / 2,
        borderBottomWidth: 1,
        borderBottomColor: argonTheme.COLORS.BORDER,
    },
    notesContainer: {
        marginBottom: theme.SIZES.BASE,
    },
    errorText: {
        color: argonTheme.COLORS.ERROR,
        marginBottom: theme.SIZES.BASE,
        textAlign: 'center',
    },
    touchable: {
        padding: 10, // Ensure adequate touchable area
    },
});

export default MatchDetails;
