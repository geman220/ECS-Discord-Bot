// App.js

import React, { useCallback, useEffect, useState } from "react";
import * as SplashScreen from "expo-splash-screen";
import * as Font from "expo-font";
import { Asset } from "expo-asset";
import { Block, GalioProvider } from "galio-framework";
import { NavigationContainer } from "@react-navigation/native";
import { Image } from "react-native";
import { enableScreens } from "react-native-screens";
import { SafeAreaProvider } from 'react-native-safe-area-context';
import RootNavigator from "./navigation/Screens";
import { Images, articles, argonTheme } from "./constants";
import { FontAwesome, FontAwesome5 } from '@expo/vector-icons';
import * as Linking from 'expo-linking';

// Enable screens for better performance with react-navigation
enableScreens();

// Keep the splash screen visible while we fetch resources
SplashScreen.preventAutoHideAsync();

// Cache app images
const assetImages = [
    Images.Onboarding,
    Images.LogoOnboarding,
    Images.Logo,
    Images.Pro,
    Images.ArgonLogo,
    Images.iOSLogo,
    Images.androidLogo,
];

// Cache product images
articles.forEach((article) => assetImages.push(article.image));

// Function to cache images
const cacheImages = (images) => {
    return images.map((image) => {
        if (typeof image === "string") {
            return Image.prefetch(image);
        } else {
            return Asset.fromModule(image).downloadAsync();
        }
    });
};

// Function to load fonts
const loadFonts = () => {
    return Font.loadAsync({
        "open-sans-regular": require("./assets/font/OpenSans-Regular.ttf"),
        "open-sans-light": require("./assets/font/OpenSans-Light.ttf"),
        "open-sans-bold": require("./assets/font/OpenSans-Bold.ttf"),
        "ArgonExtra": require("./assets/font/argon.ttf"),
        ...FontAwesome.font,
        ...FontAwesome5.font,
    });
};

export default function App() {
    const [appIsReady, setAppIsReady] = useState(false);

    useEffect(() => {
        async function prepare() {
            try {
                // Load Resources: Images and Fonts
                await Promise.all([
                    ...cacheImages(assetImages),
                    loadFonts(),
                ]);
            } catch (e) {
                console.warn(e);
            } finally {
                setAppIsReady(true);
            }
        }
        prepare();
    }, []);

    const linking = {
        prefixes: ['ecs-fc-scheme://'],
        config: {
            screens: {
                Login: 'auth',
                Home: 'home',
                Profile: 'profile',
            },
        },
    };

    const onLayoutRootView = useCallback(async () => {
        if (appIsReady) {
            await SplashScreen.hideAsync();
        }
    }, [appIsReady]);

    if (!appIsReady) {
        return null;
    }

    return (
        <SafeAreaProvider onLayout={onLayoutRootView}>
            <NavigationContainer linking={linking}>
                <GalioProvider theme={argonTheme}>
                    <Block flex>
                        <RootNavigator />
                    </Block>
                </GalioProvider>
            </NavigationContainer>
        </SafeAreaProvider>
    );
}