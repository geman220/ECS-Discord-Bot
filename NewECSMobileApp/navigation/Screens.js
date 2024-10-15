// screens.js

import React from "react";
import { createStackNavigator } from "@react-navigation/stack";
import { createDrawerNavigator } from "@react-navigation/drawer";
import { TouchableOpacity } from "react-native";
import Login from "../screens/Login";
import TwoFA from "../screens/TwoFA";
import Home from "../screens/Home";
import Profile from "../screens/Profile";
import Teams from "../screens/Teams";
import Team from "../screens/Team";
import MatchDetails from "../screens/MatchDetails";
import PlayerProfile from "../screens/PlayerProfile";
import Players from "../screens/Players";
import PlayersList from "../screens/PlayersList";
import CustomDrawerContent from "../components/CustomDrawerContent"; // Ensure the correct path
import { argonTheme } from "../constants";
import Icon from "../components/Icon"; // Ensure your Icon component is correctly imported

const Stack = createStackNavigator();
const Drawer = createDrawerNavigator();

// Authentication Stack (No headers)
function AuthStack() {
    return (
        <Stack.Navigator
            screenOptions={{
                headerShown: false,
            }}
        >
            <Stack.Screen name="Login" component={Login} />
            <Stack.Screen name="TwoFA" component={TwoFA} />
        </Stack.Navigator>
    );
}

// Helper function to determine if the current screen is the initial route
const getHeaderLeft = (navigation, route, initialRouteName) => {
    if (route.name === initialRouteName) {
        return () => (
            <TouchableOpacity onPress={() => navigation.toggleDrawer()} style={{ marginLeft: 15 }}>
                <Icon name="align-justify" family="FontAwesome" size={20} color="#fff" />
            </TouchableOpacity>
        );
    }
    return undefined; // Default back arrow
};

// Home Stack with renamed Home screen
function HomeStack({ navigation, route }) {
    return (
        <Stack.Navigator
            initialRouteName="HomeMain" // Explicitly set the initial route
            screenOptions={({ route, navigation }) => ({
                headerStyle: { backgroundColor: argonTheme.COLORS.PRIMARY },
                headerTintColor: "#fff",
                headerTitleStyle: { fontWeight: "bold" },
                headerLeft: getHeaderLeft(navigation, route, "HomeMain"),
            })}
        >
            <Stack.Screen name="HomeMain" component={Home} options={{ title: "Home" }} />
            <Stack.Screen
                name="MatchDetails"
                component={MatchDetails}
                options={{ title: "Match Details" }}
            />
            <Stack.Screen
                name="PlayerProfile"
                component={PlayerProfile}
                options={{ title: "Player Profile" }}
            />
        </Stack.Navigator>
    );
}

// Profile Stack
function ProfileStack({ navigation, route }) {
    return (
        <Stack.Navigator
            screenOptions={({ route, navigation }) => ({
                headerStyle: { backgroundColor: argonTheme.COLORS.PRIMARY },
                headerTintColor: "#fff",
                headerTitleStyle: { fontWeight: "bold" },
                headerLeft: getHeaderLeft(navigation, route, "Profile"),
            })}
        >
            <Stack.Screen name="Profile" component={Profile} />
            {/* Add more Profile related screens here if needed */}
        </Stack.Navigator>
    );
}

// Teams Stack (Includes Team)
function TeamsStack({ navigation, route }) {
    return (
        <Stack.Navigator
            screenOptions={({ route, navigation }) => ({
                headerStyle: { backgroundColor: argonTheme.COLORS.PRIMARY },
                headerTintColor: "#fff",
                headerTitleStyle: { fontWeight: "bold" },
                headerLeft: getHeaderLeft(navigation, route, "Teams"),
            })}
        >
            {/* This should now point to the Teams component */}
            <Stack.Screen name="Teams" component={Teams} options={{ title: "Teams" }} />
            {/* Still keeping the Team details page if needed */}
            <Stack.Screen
                name="TeamDetails"
                component={Team}
                options={{ title: "Team Details" }}
            />
        </Stack.Navigator>
    );
}

// Players Stack
function PlayersStack({ navigation, route }) {
    return (
        <Stack.Navigator
            screenOptions={({ route, navigation }) => ({
                headerStyle: { backgroundColor: argonTheme.COLORS.PRIMARY },
                headerTintColor: "#fff",
                headerTitleStyle: { fontWeight: "bold" },
                headerLeft: getHeaderLeft(navigation, route, "Players"),
            })}
        >
            <Stack.Screen name="Players" component={PlayersList} options={{ title: "Players List" }} />
            {/* Add more Players related screens here if needed, such as player profile */}
        </Stack.Navigator>
    );
}


// Calendar Stack
function CalendarStack({ navigation, route }) {
    return (
        <Stack.Navigator
            screenOptions={({ route, navigation }) => ({
                headerStyle: { backgroundColor: argonTheme.COLORS.PRIMARY },
                headerTintColor: "#fff",
                headerTitleStyle: { fontWeight: "bold" },
                headerLeft: getHeaderLeft(navigation, route, "Calendar"),
            })}
        >
            <Stack.Screen name="Calendar" component={Calendar} />
            {/* Add Calendar related sub-pages here */}
        </Stack.Navigator>
    );
}

// Drawer Navigator updated to include Calendar
function DrawerStack() {
    return (
        <Drawer.Navigator
            drawerContent={(props) => <CustomDrawerContent {...props} />}
            screenOptions={{
                headerShown: false, // Headers are managed by individual Stack Navigators
            }}
        >
            <Drawer.Screen name="Home" component={HomeStack} />
            <Drawer.Screen name="Profile" component={ProfileStack} />
            <Drawer.Screen name="Teams" component={TeamsStack} />
            <Drawer.Screen name="Players" component={PlayersStack} />
            <Drawer.Screen name="Calendar" component={CalendarStack} />
            {/* Add other main pages here */}
        </Drawer.Navigator>
    );
}

// Main App Stack (No additional headers)
function AppStack() {
    return (
        <Stack.Navigator
            screenOptions={{
                headerShown: false,
            }}
        >
            <Stack.Screen name="Drawer" component={DrawerStack} />
        </Stack.Navigator>
    );
}

// Root Navigator switching between Auth and App
function RootNavigator() {
    return (
        <Stack.Navigator
            screenOptions={{
                headerShown: false,
            }}
        >
            <Stack.Screen name="Auth" component={AuthStack} />
            <Stack.Screen name="App" component={AppStack} />
        </Stack.Navigator>
    );
}

export default RootNavigator;
