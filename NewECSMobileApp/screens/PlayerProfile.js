import React, { useState, useEffect } from "react";
import {
    StyleSheet,
    Dimensions,
    ScrollView,
    Image,
    ImageBackground,
    Platform,
    SafeAreaView,
} from "react-native";
import { Block, Text, theme } from "galio-framework";
import { Button } from "../components";
import { Images, argonTheme } from "../constants";
import { HeaderHeight } from "../constants/utils";
import globalConfig from '../config/globalConfig';
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';

const { width, height } = Dimensions.get("screen");

const PlayerProfile = ({ route, navigation }) => {
    const { playerId } = route.params;
    const [playerData, setPlayerData] = useState(null);

    useEffect(() => {
        fetchPlayerData();
    }, []);

    const fetchPlayerData = async () => {
        try {
            const token = await AsyncStorage.getItem('access_token');
            const headers = { Authorization: `Bearer ${token}` };
            const playerResponse = await axios.get(`${globalConfig.API_URL}/players/${playerId}?include_stats=true`, { headers });
            setPlayerData(playerResponse.data);
        } catch (error) {
            console.error('Error fetching player data:', error);
        }
    };

    const formatPositions = (positions) => {
        if (!positions) return 'N/A';
        return positions.replace(/[{}]/g, '').split(',').map(pos => pos.trim()).join(', ');
    };

    const renderInfoItem = (label, value, multiline = false) => (
        <Block style={styles.infoItem}>
            <Text size={14} color={argonTheme.COLORS.TEXT}>{label}</Text>
            {multiline ? (
                <Block style={styles.multilineInfo}>
                    <Text bold size={14} color="#525F7F" style={styles.multilineText}>{value || 'N/A'}</Text>
                </Block>
            ) : (
                <Text bold size={14} color="#525F7F">{value || 'N/A'}</Text>
            )}
        </Block>
    );

    const renderSection = (title, content) => (
        <Block style={styles.section}>
            <Text bold size={16} color="#525F7F" style={styles.sectionTitle}>{title}</Text>
            {content}
        </Block>
    );

    if (!playerData) {
        return <Block flex middle><Text>Loading...</Text></Block>;
    }

    return (
        <SafeAreaView style={styles.safeArea}>
            <ImageBackground
                source={Images.ProfileBackground}
                style={styles.profileContainer}
                imageStyle={styles.profileBackground}
            >
                <ScrollView
                    showsVerticalScrollIndicator={false}
                    style={styles.scrollView}
                    contentContainerStyle={styles.scrollViewContent}
                >
                    <Block style={styles.profileCard}>
                        <Block middle style={styles.avatarContainer}>
                            <Image
                                source={{ uri: playerData.profile_picture_url || Images.DefaultProfilePicture }}
                                style={styles.avatar}
                            />
                        </Block>
                        <Block middle style={styles.nameInfo}>
                            <Text bold size={28} color="#32325D">{playerData.name}</Text>
                            <Text size={16} color="#32325D" style={{ marginTop: 10 }}>
                                {playerData.favorite_position || 'Position not set'}
                            </Text>
                        </Block>

                        {renderSection("Personal Information", (
                            <Block>
                                {renderInfoItem("Email", playerData.email)}
                                {renderInfoItem("Phone", playerData.phone)}
                                {renderInfoItem("Preferred Pronouns", playerData.pronouns)}
                            </Block>
                        ))}

                        {renderSection("Soccer Preferences", (
                            <Block>
                                {renderInfoItem("Favorite Position", playerData.favorite_position)}
                                {renderInfoItem("Other Positions Enjoyed", formatPositions(playerData.other_positions), true)}
                                {renderInfoItem("Positions to Avoid", formatPositions(playerData.positions_not_to_play), true)}
                                {renderInfoItem("Jersey Size", playerData.jersey_size)}
                                {renderInfoItem("Jersey Number", playerData.jersey_number)}
                                {renderInfoItem("Willing to Referee", playerData.willing_to_referee)}
                                {renderInfoItem("Goal Frequency", playerData.frequency_play_goal)}
                            </Block>
                        ))}

                        {renderSection("Availability", (
                            <Block>
                                {renderInfoItem("Available Weeks", playerData.expected_weeks_available)}
                            </Block>
                        ))}

                        {renderSection("Season Stats", (
                            <Block>
                                {renderInfoItem("Goals", playerData.season_stats?.goals)}
                                {renderInfoItem("Assists", playerData.season_stats?.assists)}
                                {renderInfoItem("Yellow Cards", playerData.season_stats?.yellow_cards)}
                                {renderInfoItem("Red Cards", playerData.season_stats?.red_cards)}
                            </Block>
                        ))}

                        {renderSection("Career Stats", (
                            <Block>
                                {renderInfoItem("Goals", playerData.career_stats?.goals)}
                                {renderInfoItem("Assists", playerData.career_stats?.assists)}
                                {renderInfoItem("Yellow Cards", playerData.career_stats?.yellow_cards)}
                                {renderInfoItem("Red Cards", playerData.career_stats?.red_cards)}
                            </Block>
                        ))}

                        {playerData.team_id && (
                            <Block style={styles.viewTeamButton}>
                                <Button
                                    color="primary"
                                    onPress={() => navigation.navigate('Team', { teamId: playerData.team_id })}
                                    style={styles.centeredButton} // Added centered button styling
                                >
                                    VIEW TEAM
                                </Button>
                            </Block>
                        )}
                    </Block>
                </ScrollView>
            </ImageBackground>
        </SafeAreaView>
    );
};

const styles = StyleSheet.create({
    safeArea: {
        flex: 1,
        backgroundColor: theme.COLORS.WHITE,
    },
    profileContainer: {
        width: width,
        height: height,
        padding: 0,
        zIndex: 1,
    },
    profileBackground: {
        width: width,
        height: height / 2,
    },
    scrollView: {
        width: width,
        marginTop: '25%',
    },
    scrollViewContent: {
        paddingBottom: 120, // Increased padding to ensure button is not cut off
    },
    profileCard: {
        padding: theme.SIZES.BASE,
        marginHorizontal: theme.SIZES.BASE,
        marginTop: 65,
        borderTopLeftRadius: 6,
        borderTopRightRadius: 6,
        backgroundColor: theme.COLORS.WHITE,
        shadowColor: "black",
        shadowOffset: { width: 0, height: 0 },
        shadowRadius: 8,
        shadowOpacity: 0.2,
        zIndex: 2,
    },
    avatarContainer: {
        position: "relative",
        marginTop: -80,
    },
    avatar: {
        width: 124,
        height: 124,
        borderRadius: 62,
        borderWidth: 0,
    },
    nameInfo: {
        marginTop: 35,
        alignItems: 'center',
    },
    section: {
        marginTop: 20,
        marginBottom: 20,
    },
    sectionTitle: {
        marginBottom: 10,
    },
    viewTeamButton: {
        marginTop: 20,
        marginBottom: 10,
        alignItems: 'center', // Centering the button horizontally
    },
    centeredButton: {
        width: '80%', // Ensuring button doesn't stretch to full width, looks centered
    },
    infoItem: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        marginBottom: 10,
        paddingBottom: 10,
        borderBottomWidth: 1,
        borderBottomColor: argonTheme.COLORS.BORDER,
    },
    multilineInfo: {
        flex: 1,
        flexDirection: 'row',
        flexWrap: 'wrap', // Ensures content wraps onto the next line
        justifyContent: 'flex-start', // Aligns text to the left
    },
    multilineText: {
        width: '100%', // Ensures the text takes the full width of the container
        textAlign: 'right',
        marginVertical: 5, // Adds some space between lines if it wraps
    },
});

export default PlayerProfile;
