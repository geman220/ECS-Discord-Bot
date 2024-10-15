// Home.js

import React, { useState, useEffect } from 'react';
import { StyleSheet, ScrollView, RefreshControl } from 'react-native';
import { Block, Text, theme } from 'galio-framework';
import { argonTheme, Images } from '../constants';
import globalConfig from '../config/globalConfig';
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Button, Card } from "../components";

const Home = ({ navigation }) => {
    const [userData, setUserData] = useState(null);
    const [nextMatches, setNextMatches] = useState([]);
    const [refreshing, setRefreshing] = useState(false);

    const fetchData = async () => {
        try {
            const token = await AsyncStorage.getItem('access_token');
            const headers = { Authorization: `Bearer ${token}` };

            console.log('Fetching user profile and upcoming matches...');
            const [userResponse, matchesResponse] = await Promise.all([
                axios.get(`${globalConfig.API_URL}/user_profile`, { headers }),
                axios.get(`${globalConfig.API_URL}/matches?upcoming=true&include_availability=true`, { headers })
            ]);

            console.log('User Response:', JSON.stringify(userResponse.data, null, 2));
            console.log('Matches Response:', JSON.stringify(matchesResponse.data, null, 2));

            setUserData(userResponse.data);
            setNextMatches(matchesResponse.data);
        } catch (error) {
            console.error('Error fetching data:', error);
            if (error.response) {
                console.error('Error Response:', error.response.data);
                console.error('Error Status:', error.response.status);
            } else if (error.request) {
                console.error('Error Request:', error.request);
            } else {
                console.error('Error Message:', error.message);
            }
        }
    };

    useEffect(() => {
        fetchData();
    }, []);

    const onRefresh = React.useCallback(() => {
        setRefreshing(true);
        fetchData().then(() => setRefreshing(false));
    }, []);

    // Helper function to get the profile picture URL
    const getProfilePictureUrl = () => {
        const pictureUrl = userData?.profile_picture_url;
        if (pictureUrl) {
            return pictureUrl;
        } else {
            return Images.DefaultProfilePicture;
        }
    };

    // Create item objects for the cards
    const profileItem = userData && {
        image: getProfilePictureUrl(),
        title: userData.player_name || userData.username,
        body: userData.team_name
            ? `${userData.team_name} - ${userData.league_name}`
            : 'No team assigned',
        cta: 'Update Profile',
        ctaNavigation: () => navigation.navigate('Profile'),
    };

    const teamItem = userData && userData.team_name && {
        image: userData.team_logo_url || Images.DefaultTeamLogo,
        title: userData.team_name,
        body: userData.league_name,
        cta: 'View My Team',
        ctaNavigation: () => navigation.navigate('Teams', { screen: 'Team', params: { teamId: userData.team_id } }),
    };

    return (
        <Block flex style={styles.home}>
            <ScrollView
                refreshControl={
                    <RefreshControl refreshing={refreshing} onRefresh={onRefresh} />
                }
            >
                {profileItem && (
                    <Card
                        item={profileItem}
                        style={styles.card}
                        horizontal={false}
                        ctaRight={false}
                    />
                )}

                {teamItem && (
                    <Card
                        item={teamItem}
                        style={styles.card}
                        horizontal={false}
                        ctaRight={false}
                    />
                )}

                {nextMatches.length > 0 && (
                    <Block>
                        <Text h5 style={styles.sectionTitle}>
                            My Next Matches
                        </Text>
                        {nextMatches.map((match, index) => {
                            const homeTeamName = match.home_team.name || 'Unknown Team';
                            const awayTeamName = match.away_team.name || 'Unknown Team';
                            const matchDateTime = new Date(`${match.date}T${match.time}`);

                            const matchItem = {
                                image: match.match_image_url || Images.DefaultMatchImage,
                                title: `${homeTeamName} vs ${awayTeamName}`,
                                body: `${matchDateTime.toLocaleDateString()} at ${matchDateTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`,
                                cta: 'View Match Details',
                                ctaNavigation: () => navigation.navigate('MatchDetails', { matchId: match.id }),
                            };

                            return (
                                <Card
                                    key={index}
                                    item={matchItem}
                                    style={styles.card}
                                    horizontal={false}
                                    ctaRight={false}
                                />
                            );
                        })}
                    </Block>
                )}
            </ScrollView>
        </Block>
    );
};

const styles = StyleSheet.create({
    home: {
        backgroundColor: theme.COLORS.WHITE,
    },
    card: {
        margin: theme.SIZES.BASE,
    },
    sectionTitle: {
        marginLeft: theme.SIZES.BASE,
        marginTop: theme.SIZES.BASE,
    },
});

export default Home;
