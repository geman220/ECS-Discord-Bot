import React, { useState, useEffect } from "react";
import {
    StyleSheet,
    Dimensions,
    ScrollView,
    Image,
    ImageBackground,
    Platform,
    TouchableOpacity,
    ActivityIndicator,
    TextInput,
    View,
} from "react-native";
import { Block, Text, theme } from "galio-framework";
import { Button, Icon } from "../components";
import { Images, argonTheme } from "../constants";
import { HeaderHeight } from "../constants/utils";
import globalConfig from '../config/globalConfig';
import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { Picker } from '@react-native-picker/picker';

const jersey_sizes = [
    { label: 'AXL', value: 'AXL' },
    { label: 'WS', value: 'WS' },
    { label: 'AM', value: 'AM' },
    { label: 'AXXL', value: 'AXXL' },
    { label: 'A4XL', value: 'A4XL' },
    { label: 'WXL', value: 'WXL' },
    { label: 'WM', value: 'WM' },
    { label: 'WXS', value: 'WXS' },
    { label: 'AL', value: 'AL' },
    { label: 'A3XL', value: 'A3XL' },
    { label: 'N/A', value: 'N/A' },
    { label: 'AS', value: 'AS' },
    { label: 'WL', value: 'WL' },
];

const soccer_positions = [
    { label: 'Goalkeeper', value: 'goalkeeper' },
    { label: 'Defender', value: 'defender' },
    { label: 'Midfielder', value: 'midfielder' },
    { label: 'Forward', value: 'forward' },
    { label: 'Winger', value: 'winger' },
    { label: 'Striker', value: 'striker' },
    { label: 'Center Back', value: 'center_back' },
    { label: 'Full Back', value: 'full_back' },
    { label: 'Wing Back', value: 'wing_back' },
    { label: 'Attacking Midfielder', value: 'attacking_midfielder' },
    { label: 'Defensive Midfielder', value: 'defensive_midfielder' },
    { label: 'Central Midfielder', value: 'central_midfielder' },
    { label: 'No Preference', value: 'no_preference' }
];

const goal_frequency_choices = [
    { label: 'Never', value: '0' },
    { label: 'Only if our normal GK is unavailable and there are no other options', value: '1' },
    { label: 'I will fill in as much as needed, but expect to play in the field', value: '2' },
    { label: 'Half of the time', value: '3' },
    { label: 'Every Game', value: '4' }
];

const availability_choices = [
    { label: '1-2', value: '1-2' },
    { label: '3-4', value: '3-4' },
    { label: '5-6', value: '5-6' },
    { label: '7-8', value: '7-8' },
    { label: '9-10', value: '9-10' }
];

const pronoun_choices = [
    { label: 'He/Him', value: 'he/him' },
    { label: 'She/Her', value: 'she/her' },
    { label: 'They/Them', value: 'they/them' },
    { label: 'Other', value: 'other' }
];

const willing_to_referee_choices = [
    { label: 'No', value: 'No' },
    { label: "Yes - I'll ref in Classic only", value: "Yes - I'll ref in Classic only" },
    { label: "Yes - I'll ref in Premier only", value: "Yes - I'll ref in Premier only" },
    { label: "Yes - I'll ref in Premier or Classic", value: "Yes - I'll ref in Premier or Classic" },
    { label: "I am interested in receiving ref training only", value: "I am interested in receiving ref training only" }
];

const { width, height } = Dimensions.get("screen");

const Profile = ({ navigation }) => {
    const [profileData, setProfileData] = useState(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState(null);
    const [activeTab, setActiveTab] = useState('profile');
    const [editingFields, setEditingFields] = useState({});
    const [editedData, setEditedData] = useState({});

    useEffect(() => {
        fetchProfileData();
    }, []);

    const fetchProfileData = async () => {
        try {
            setIsLoading(true);
            const token = await AsyncStorage.getItem('access_token');
            const headers = { Authorization: `Bearer ${token}` };
            const profileResponse = await axios.get(`${globalConfig.API_URL}/user_profile?include_stats=true`, { headers });
            setProfileData(profileResponse.data);
            setEditedData(profileResponse.data);
            setError(null);
        } catch (error) {
            console.error('Error fetching profile data:', error);
            setError('Failed to load profile data. Please check your internet connection and try again.');
        } finally {
            setIsLoading(false);
        }
    };

    const handleSaveProfile = async (field) => {
        try {
            const token = await AsyncStorage.getItem('access_token');
            const headers = { Authorization: `Bearer ${token}` };
            const dataToUpdate = { [field]: editedData[field] };
            await axios.put(`${globalConfig.API_URL}/player/update`, dataToUpdate, { headers });
            setProfileData({ ...profileData, [field]: editedData[field] });
            setEditingFields({ ...editingFields, [field]: false });
        } catch (error) {
            console.error('Error updating profile:', error);
            // Handle error (e.g., show an error message to the user)
        }
    };

    const formatPosition = (position) => {
        if (!position) return '';
        return position.split('_').map(word => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
    };

    const formatPositions = (positions) => {
        if (!positions) return '';
        return positions.replace(/[{}]/g, '').split(',').map(pos => formatPosition(pos.trim())).join(', ');
    };

    const renderProfileItem = (label, value, key) => (
        <Block row space="between" style={styles.profileItem} key={key}>
            <Text size={14} color={argonTheme.COLORS.TEXT}>{label}</Text>
            {editingFields[key] ? (
                <TextInput
                    style={styles.input}
                    value={editedData[key] || ''}
                    onChangeText={(text) => setEditedData({ ...editedData, [key]: text })}
                />
            ) : (
                <Text bold size={14} color="#525F7F">{value}</Text>
            )}
            <TouchableOpacity onPress={() => {
                if (editingFields[key]) {
                    handleSaveProfile();
                }
                setEditingFields({ ...editingFields, [key]: !editingFields[key] });
            }}>
                <Text color={argonTheme.COLORS.PRIMARY}>
                    {editingFields[key] ? "Save" : "Edit"}
                </Text>
            </TouchableOpacity>
        </Block>
    );

    const renderEditableField = (label, value, field, options = null, isMulti = false) => (
        <Block style={styles.fieldContainer}>
            <Text size={14} color={argonTheme.COLORS.TEXT}>{label}</Text>
            {editingFields[field] ? (
                <View style={styles.editContainer}>
                    {options ? (
                        isMulti ? (
                            <View>
                                {options.map((option) => (
                                    <TouchableOpacity
                                        key={option.value}
                                        onPress={() => {
                                            const currentPositions = editedData[field] ? editedData[field].split(',') : [];
                                            const updatedPositions = currentPositions.includes(option.value)
                                                ? currentPositions.filter(pos => pos !== option.value)
                                                : [...currentPositions, option.value];
                                            setEditedData({ ...editedData, [field]: updatedPositions.join(',') });
                                        }}
                                        style={styles.multiSelectItem}
                                    >
                                        <Text>{option.label}</Text>
                                        {editedData[field] && editedData[field].includes(option.value) && (
                                            <Icon name="check" family="FontAwesome" size={20} color={argonTheme.COLORS.PRIMARY} />
                                        )}
                                    </TouchableOpacity>
                                ))}
                            </View>
                        ) : (
                            <Picker
                                selectedValue={editedData[field]}
                                style={styles.picker}
                                onValueChange={(itemValue) => setEditedData({ ...editedData, [field]: itemValue })}
                            >
                                {options.map((option) => (
                                    <Picker.Item key={option.value} label={option.label} value={option.value} />
                                ))}
                            </Picker>
                        )
                    ) : (
                        <TextInput
                            style={styles.input}
                            value={editedData[field] || ''}
                            onChangeText={(text) => setEditedData({ ...editedData, [field]: text })}
                        />
                    )}
                    <TouchableOpacity onPress={() => handleSaveProfile(field)} style={styles.saveButton}>
                        <Text color={argonTheme.COLORS.PRIMARY}>Save</Text>
                    </TouchableOpacity>
                </View>
            ) : (
                <View style={styles.valueContainer}>
                    <Text bold size={14} color="#525F7F">{value}</Text>
                    <TouchableOpacity
                        onPress={() => {
                            setEditingFields({ ...editingFields, [field]: true });
                            setEditedData({ ...editedData, [field]: value });
                        }}
                        style={styles.editButton}
                    >
                        <Text color={argonTheme.COLORS.PRIMARY}>Edit</Text>
                    </TouchableOpacity>
                </View>
            )}
        </Block>
    );

    const renderProfileTab = () => (
        <Block>
            <Block style={styles.section}>
                <Text bold size={16} color="#525F7F" style={styles.sectionTitle}>Personal Information</Text>
                {renderEditableField("Name", profileData.player_name, "player_name")}
                {renderEditableField("Email", profileData.email, "email")}
                {renderEditableField("Phone", profileData.phone, "phone")}
                {renderEditableField("Preferred Pronouns", profileData.pronouns, "pronouns", pronoun_choices)}
            </Block>

            <Block style={styles.section}>
                <Text bold size={16} color="#525F7F" style={styles.sectionTitle}>Soccer Preferences</Text>
                {renderEditableField("Favorite Position", formatPosition(profileData.favorite_position), "favorite_position", soccer_positions)}
                {renderEditableField("Other Positions Enjoyed", formatPositions(profileData.other_positions), "other_positions", soccer_positions, true)}
                {renderEditableField("Positions to Avoid", formatPositions(profileData.positions_not_to_play), "positions_not_to_play", soccer_positions, true)}
                {renderEditableField("Jersey Size", profileData.jersey_size, "jersey_size", jersey_sizes)}
                {renderEditableField("Jersey Number", profileData.jersey_number, "jersey_number")}
                {renderEditableField("Willing to Referee", profileData.willing_to_referee, "willing_to_referee", willing_to_referee_choices)}
                {renderEditableField("Goal Frequency", profileData.frequency_play_goal, "frequency_play_goal", goal_frequency_choices)}
            </Block>

            <Block style={styles.section}>
                <Text bold size={16} color="#525F7F" style={styles.sectionTitle}>Availability</Text>
                {renderEditableField("Available Weeks", profileData.expected_weeks_available, "expected_weeks_available", availability_choices)}
            </Block>
        </Block>
    );

    const renderStatsTab = () => (
        <Block>
            <Block style={styles.section}>
                <Text bold size={16} color="#525F7F" style={styles.sectionTitle}>Season Stats</Text>
                {profileData.season_stats && (
                    <Block>
                        {renderStatItem("Goals", profileData.season_stats.goals)}
                        {renderStatItem("Assists", profileData.season_stats.assists)}
                        {renderStatItem("Yellow Cards", profileData.season_stats.yellow_cards)}
                        {renderStatItem("Red Cards", profileData.season_stats.red_cards)}
                    </Block>
                )}
            </Block>

            <Block style={styles.section}>
                <Text bold size={16} color="#525F7F" style={styles.sectionTitle}>Career Stats</Text>
                {profileData.career_stats && (
                    <Block>
                        {renderStatItem("Goals", profileData.career_stats.goals)}
                        {renderStatItem("Assists", profileData.career_stats.assists)}
                        {renderStatItem("Yellow Cards", profileData.career_stats.yellow_cards)}
                        {renderStatItem("Red Cards", profileData.career_stats.red_cards)}
                    </Block>
                )}
            </Block>
        </Block>
    );

    const renderStatItem = (label, value) => (
        <Block style={styles.fieldContainer}>
            <View style={styles.valueContainer}>
                <Text size={14} color={argonTheme.COLORS.TEXT}>{label}</Text>
                <Text bold size={14} color="#525F7F">{value}</Text>
            </View>
        </Block>
    );

    const renderPositionsModal = () => (
        <Modal
            animationType="slide"
            transparent={true}
            visible={showPositionsModal}
            onRequestClose={() => setShowPositionsModal(false)}
        >
            <Block flex middle style={styles.modalContainer}>
                <Block style={styles.modalContent}>
                    <Text bold size={18} style={styles.modalTitle}>
                        {currentEditingPositions === 'other_positions' ? 'Other Positions' : 'Positions to Avoid'}
                    </Text>
                    <FlatList
                        data={editedData[currentEditingPositions] ? editedData[currentEditingPositions].replace(/[{}]/g, '').split(',') : []}
                        renderItem={({ item }) => (
                            <Block row middle space="between" style={styles.positionItem}>
                                <Text>{formatPosition(item.trim())}</Text>
                                <TouchableOpacity onPress={() => {
                                    const updatedPositions = editedData[currentEditingPositions].replace(/[{}]/g, '').split(',').filter(pos => pos.trim() !== item.trim());
                                    setEditedData({ ...editedData, [currentEditingPositions]: `{${updatedPositions.join(',')}}` });
                                }}>
                                    <Icon name="close" family="AntDesign" size={20} color={argonTheme.COLORS.ERROR} />
                                </TouchableOpacity>
                            </Block>
                        )}
                        keyExtractor={(item, index) => index.toString()}
                    />
                    <Button color="primary" onPress={() => setShowPositionsModal(false)}>
                        <Text bold color={argonTheme.COLORS.WHITE}>Close</Text>
                    </Button>
                </Block>
            </Block>
        </Modal>
    );

    const renderTabs = () => (
        <Block row style={styles.tabsContainer}>
            <TouchableOpacity
                style={[styles.tab, activeTab === 'profile' && styles.activeTab]}
                onPress={() => setActiveTab('profile')}
            >
                <Text style={[styles.tabText, activeTab === 'profile' && styles.activeTabText]}>PROFILE</Text>
            </TouchableOpacity>
            <TouchableOpacity
                style={[styles.tab, activeTab === 'stats' && styles.activeTab]}
                onPress={() => setActiveTab('stats')}
            >
                <Text style={[styles.tabText, activeTab === 'stats' && styles.activeTabText]}>STATS</Text>
            </TouchableOpacity>
        </Block>
    );

    if (isLoading) {
        return (
            <Block flex middle>
                <ActivityIndicator size="large" color={argonTheme.COLORS.PRIMARY} />
            </Block>
        );
    }

    if (error) {
        return (
            <Block flex middle>
                <Text>{error}</Text>
                <Button color="primary" style={styles.button} onPress={fetchProfileData}>
                    <Text bold size={14} color={argonTheme.COLORS.WHITE}>
                        Retry
                    </Text>
                </Button>
            </Block>
        );
    }

    return (
        <Block flex style={styles.profile}>
            <ImageBackground
                source={Images.ProfileBackground}
                style={styles.profileContainer}
                imageStyle={styles.profileBackground}
            >
                <ScrollView
                    showsVerticalScrollIndicator={false}
                    style={{ width }}
                    contentContainerStyle={styles.scrollViewContent}
                >
                    <Block flex style={styles.profileCard}>
                        <Block middle style={styles.avatarContainer}>
                            <Image
                                source={{ uri: profileData.profile_picture_url || Images.DefaultProfilePicture }}
                                style={styles.avatar}
                            />
                        </Block>
                        {renderTabs()}
                        {activeTab === 'profile' ? renderProfileTab() : renderStatsTab()}
                    </Block>
                    <Block style={{ height: 100 }} />
                </ScrollView>
            </ImageBackground>
        </Block>
    );
};

const styles = StyleSheet.create({
    profile: {
        marginTop: Platform.OS === "android" ? -HeaderHeight : 0,
        flex: 1
    },
    profileContainer: {
        width: width,
        height: height,
        padding: 0,
        zIndex: 1
    },
    profileBackground: {
        width: width,
        height: height / 2
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
        zIndex: 2
    },
    info: {
        paddingHorizontal: 40
    },
    avatarContainer: {
        position: "relative",
        marginTop: -80
    },
    avatar: {
        width: 124,
        height: 124,
        borderRadius: 62,
        borderWidth: 0
    },
    nameInfo: {
        marginTop: 35
    },
    profileItem: {
        marginBottom: 6,
        padding: 10,
        borderBottomWidth: 1,
        borderBottomColor: argonTheme.COLORS.BORDER,
    },
    button: {
        width: width * 0.8,
        marginTop: 25
    },
    tabsContainer: {
        flexDirection: 'row',
        marginBottom: 20,
        borderBottomWidth: 1,
        borderBottomColor: argonTheme.COLORS.BORDER,
    },
    tab: {
        flex: 1,
        alignItems: 'center',
        paddingVertical: 10,
    },
    activeTab: {
        borderBottomWidth: 2,
        borderBottomColor: argonTheme.COLORS.PRIMARY,
    },
    tabText: {
        fontSize: 14,
        color: argonTheme.COLORS.MUTED,
    },
    activeTabText: {
        color: argonTheme.COLORS.PRIMARY,
    },
    input: {
        flex: 1,
        borderWidth: 1,
        borderColor: argonTheme.COLORS.BORDER,
        borderRadius: 4,
        padding: 5,
        marginRight: 10,
    },
    statsContainer: {
        marginTop: 16,
        paddingHorizontal: 16,
    },
    bottomButton: {
        position: 'absolute',
        bottom: 20,
        left: 0,
        right: 0,
        alignItems: 'center',
        backgroundColor: 'transparent',
    },
    modalContainer: {
        backgroundColor: 'rgba(0,0,0,0.5)',
    },
    modalContent: {
        backgroundColor: theme.COLORS.WHITE,
        borderRadius: 10,
        padding: 20,
        width: width * 0.9,
    },
    modalTitle: {
        marginBottom: 20,
    },
    positionItem: {
        paddingVertical: 10,
        borderBottomWidth: 1,
        borderBottomColor: argonTheme.COLORS.BORDER,
    },
    scrollViewContent: {
        paddingBottom: 120,
    },
    picker: {
        flex: 1,
        marginRight: 10,
    },
    saveButton: {
        padding: 5,
    },
    editButton: {
        padding: 5,
    },
    section: {
        marginBottom: 20,
    },
    sectionTitle: {
        marginBottom: 10,
    },
    fieldContainer: {
        marginBottom: 10,
        borderBottomWidth: 1,
        borderBottomColor: argonTheme.COLORS.BORDER,
        paddingBottom: 10,
    },
    editContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    valueContainer: {
        flexDirection: 'row',
        alignItems: 'center',
        justifyContent: 'space-between',
    },
    multiSelectItem: {
        flexDirection: 'row',
        justifyContent: 'space-between',
        alignItems: 'center',
        paddingVertical: 8,
        borderBottomWidth: 1,
        borderBottomColor: argonTheme.COLORS.BORDER,
    },
});

export default Profile;