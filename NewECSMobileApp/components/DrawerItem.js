// DrawerItem.js

import React from "react";
import { StyleSheet, TouchableOpacity, Linking } from "react-native";
import { Block, Text, theme } from "galio-framework";

import Icon from "./Icon";
import argonTheme from "../constants/Theme";

const DrawerItem = ({ title, focused, navigation, navigateTo }) => {
    const renderIcon = () => {
        switch (title) {
            case "Home":
                return (
                    <Icon
                        name="home"
                        family="MaterialIcons"
                        size={14}
                        color={focused ? "white" : argonTheme.COLORS.PRIMARY}
                    />
                );
            case "Elements":
                return (
                    <Icon
                        name="map-big"
                        family="ArgonExtra"
                        size={14}
                        color={focused ? "white" : argonTheme.COLORS.ERROR}
                    />
                );
            case "Articles":
                return (
                    <Icon
                        name="spaceship"
                        family="ArgonExtra"
                        size={14}
                        color={focused ? "white" : argonTheme.COLORS.PRIMARY}
                    />
                );
            case "Profile":
                return (
                    <Icon
                        name="person"
                        family="MaterialIcons"
                        size={14}
                        color={focused ? "white" : argonTheme.COLORS.PRIMARY}
                    />
                );
            case "Teams":
                return (
                    <Icon
                        name="groups"
                        family="MaterialIcons"
                        size={14}
                        color={focused ? "white" : argonTheme.COLORS.PRIMARY}
                    />
                );
            case "Players":
                return (
                    <Icon
                        name="address-card"
                        family="FontAwesome5"
                        size={14}
                        color={focused ? "white" : argonTheme.COLORS.PRIMARY}
                    />
                );
            case "Calendar":
                return (
                    <Icon
                        name="calendar-alt"
                        family="FontAwesome5"
                        size={14}
                        color={focused ? "white" : argonTheme.COLORS.PRIMARY}
                    />
                );
            case "Settings":
                return (
                    <Icon
                        name="calendar-date"
                        family="ArgonExtra"
                        size={14}
                        color={focused ? "white" : argonTheme.COLORS.DEFAULT}
                    />
                );
            case "Getting Started":
                return (
                    <Icon
                        name="spaceship"
                        family="ArgonExtra"
                        size={14}
                        color={focused ? "white" : "rgba(0,0,0,0.5)"}
                    />
                );
            case "Log out":
                return <Icon />;
            default:
                return null;
        }
    };

    const handlePress = () => {
        if (title === "Getting Started") {
            Linking.openURL(
                "https://demos.creative-tim.com/argon-pro-react-native/docs/"
            ).catch((err) => console.error("An error occurred", err));
        } else {
            navigation.navigate(navigateTo);
        }
    };

    const containerStyles = [
        styles.defaultStyle,
        focused ? [styles.activeStyle, styles.shadow] : null,
    ];

    return (
        <TouchableOpacity
            style={{ height: 60 }}
            onPress={handlePress}
            accessibilityLabel={`${title} button`}
            accessibilityRole="button"
        >
            <Block flex row style={containerStyles}>
                <Block middle flex={0.1} style={{ marginRight: 5 }}>
                    {renderIcon()}
                </Block>
                <Block row center flex={0.9}>
                    <Text
                        style={{ fontFamily: "open-sans-regular" }}
                        size={15}
                        bold={focused}
                        color={focused ? "white" : "rgba(0,0,0,0.5)"}
                    >
                        {title}
                    </Text>
                </Block>
            </Block>
        </TouchableOpacity>
    );
};

const styles = StyleSheet.create({
    defaultStyle: {
        paddingVertical: 16,
        paddingHorizontal: 16,
        marginBottom: 2,
    },
    activeStyle: {
        backgroundColor: argonTheme.COLORS.ACTIVE,
        borderRadius: 4,
    },
    shadow: {
        shadowColor: theme.COLORS.BLACK,
        shadowOffset: {
            width: 0,
            height: 2,
        },
        shadowRadius: 8,
        shadowOpacity: 0.1,
    },
});

export default React.memo(DrawerItem);
