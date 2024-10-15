// Team.js
import React, { useEffect, useState } from 'react';
import { StyleSheet, ScrollView, Image, TouchableOpacity } from 'react-native';
import { Block, Text, theme } from 'galio-framework';
import { Card, Icon } from '../components';
import axios from 'axios';
import globalConfig from '../config/globalConfig';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { argonTheme, Images } from '../constants';

const Team = ({ route, navigation }) => {
  const { teamId } = route.params;
  const [teamData, setTeamData] = useState(null);
  const [standings, setStandings] = useState(null);

  const fetchTeamData = async () => {
    try {
      const token = await AsyncStorage.getItem('access_token');
      const headers = { Authorization: `Bearer ${token}` };
      const teamResponse = await axios.get(`${globalConfig.API_URL}/teams/${teamId}?include_players=true&include_matches=true`, { headers });
      setTeamData(teamResponse.data);

      // Fetch standings
      const standingsResponse = await axios.get(`${globalConfig.API_URL}/standings`, { headers });
      const teamStanding = standingsResponse.data.find(standing => standing.team_id === teamId);
      setStandings(teamStanding);
    } catch (error) {
      console.error('Error fetching team data:', error);
    }
  };

  useEffect(() => {
    fetchTeamData();
  }, []);

  return (
    <Block flex style={styles.container}>
      <ScrollView showsVerticalScrollIndicator={false}>
        {teamData && (
          <>
            <Block flex style={styles.teamHeader}>
              <Image 
                source={{ uri: teamData.logo_url || Images.DefaultTeamLogo }} 
                style={styles.teamLogo}
              />
              <Text h3 style={styles.teamName}>{teamData.name}</Text>
            </Block>

            {standings && (
              <Block flex style={styles.statsContainer}>
                <Text h4 style={styles.sectionTitle}>Team Stats</Text>
                <Block row space="around">
                  <Block center>
                    <Text size={24} bold color={argonTheme.COLORS.SUCCESS}>{standings.wins}</Text>
                    <Text>Wins</Text>
                  </Block>
                  <Block center>
                    <Text size={24} bold color={argonTheme.COLORS.INFO}>{standings.draws}</Text>
                    <Text>Draws</Text>
                  </Block>
                  <Block center>
                    <Text size={24} bold color={argonTheme.COLORS.ERROR}>{standings.losses}</Text>
                    <Text>Losses</Text>
                  </Block>
                </Block>
                <Block center style={styles.positionContainer}>
                  <Text size={18}>League Position: {standings.position}</Text>
                  <Text>Points: {standings.points}</Text>
                </Block>
              </Block>
            )}

            <Block flex style={styles.playersContainer}>
              <Text h4 style={styles.sectionTitle}>Players</Text>
              {teamData.players && teamData.players.map((player, index) => (
                <TouchableOpacity key={index} onPress={() => navigation.navigate('PlayerProfile', { playerId: player.id })}>
                  <Block row space="between" style={styles.playerItem}>
                    <Image 
                      source={{ uri: player.profile_picture_url || Images.DefaultProfilePicture }} 
                      style={styles.playerImage}
                    />
                    <Block flex>
                      <Text size={16} bold>{player.name}</Text>
                      <Text size={14} color={argonTheme.COLORS.MUTED}>{player.favorite_position || 'Position not specified'}</Text>
                    </Block>
                    <Icon 
                      name="right" 
                      family="AntDesign" 
                      size={20} 
                      color={argonTheme.COLORS.ICON}
                    />
                  </Block>
                </TouchableOpacity>
              ))}
            </Block>

            {teamData.upcoming_matches && teamData.upcoming_matches.length > 0 && (
              <Block flex style={styles.matchesContainer}>
                <Text h4 style={styles.sectionTitle}>Upcoming Matches</Text>
                {teamData.upcoming_matches.map((match, index) => (
                  <TouchableOpacity key={index} onPress={() => navigation.navigate('MatchDetails', { matchId: match.id })}>
                    <Block row space="between" style={styles.matchItem}>
                      <Text>{match.opponent}</Text>
                      <Text>{new Date(match.date).toLocaleDateString()}</Text>
                      <Icon 
                        name="right" 
                        family="AntDesign" 
                        size={20} 
                        color={argonTheme.COLORS.ICON}
                      />
                    </Block>
                  </TouchableOpacity>
                ))}
              </Block>
            )}
          </>
        )}
      </ScrollView>
    </Block>
  );
};

const styles = StyleSheet.create({
    container: {
        backgroundColor: theme.COLORS.WHITE,
        padding: theme.SIZES.BASE,
    },
    positionContainer: {
        marginTop: theme.SIZES.BASE,
    },
    teamHeader: {
        alignItems: 'center',
        marginBottom: theme.SIZES.BASE * 2,
    },
    teamLogo: {
        width: 120,
        height: 120,
        marginBottom: theme.SIZES.BASE,
    },
    teamName: {
        textAlign: 'center',
    },
    sectionTitle: {
        marginBottom: theme.SIZES.BASE,
    },
    statsContainer: {
        marginBottom: theme.SIZES.BASE * 2,
    },
    playersContainer: {
        marginBottom: theme.SIZES.BASE * 2,
    },
    playerItem: {
        marginBottom: theme.SIZES.BASE,
        padding: theme.SIZES.BASE,
        backgroundColor: argonTheme.COLORS.SECONDARY,
        borderRadius: 4,
        alignItems: 'center',
    },
    playerImage: {
        width: 50,
        height: 50,
        borderRadius: 25,
        marginRight: theme.SIZES.BASE,
    },
    matchesContainer: {
        marginBottom: theme.SIZES.BASE * 2,
    },
    matchItem: {
        marginBottom: theme.SIZES.BASE / 2,
        padding: theme.SIZES.BASE,
        backgroundColor: argonTheme.COLORS.SECONDARY,
        borderRadius: 4,
        alignItems: 'center',
    },
});

export default Team;