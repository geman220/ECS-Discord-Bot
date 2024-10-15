// CustomDrawerContent.js

import React from "react";
import { ScrollView, StyleSheet, Image } from "react-native";
import { Block, Text, theme } from "galio-framework";
import { DrawerItem as DrawerCustomItem } from "../components";
import Images from "../constants/Images";

function CustomDrawerContent({ navigation, state, ...rest }) {
    const screens = [
        { title: "Home", navigateTo: "Home" },
        { title: "Profile", navigateTo: "Profile" },
        { title: "Teams", navigateTo: "Teams" },
        { title: "Players", navigateTo: "Players" },
        { title: "Calendar", navigateTo: "Calendar" }, // Ensure Calendar is included
    ];

    return (
        <Block style={styles.container} forceInset={{ top: "always", horizontal: "never" }}>
            <Block flex={0.06} style={styles.header}>
                <Image style={styles.logo} source={Images.Logo} />
            </Block>
            <Block flex style={{ paddingLeft: 8, paddingRight: 14 }}>
                <ScrollView style={{ flex: 1 }} showsVerticalScrollIndicator={false}>
                    {screens.map((item, index) => (
                        <DrawerCustomItem
                            title={item.title}
                            key={index}
                            navigation={navigation}
                            focused={state.index === index}
                            navigateTo={item.navigateTo}
                        />
                    ))}
                </ScrollView>
            </Block>
        </Block>
    );
}

const styles = StyleSheet.create({
    container: {
        flex: 1,
    },
    header: {
        paddingHorizontal: 28,
        paddingBottom: theme.SIZES.BASE,
        paddingTop: theme.SIZES.BASE * 3,
        justifyContent: "center",
    },
    logo: {
        width: 100,
        height: 100,
        resizeMode: "contain",
    },
});

export default CustomDrawerContent;
