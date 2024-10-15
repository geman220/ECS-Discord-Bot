// Card.js

import React from 'react';
import PropTypes from 'prop-types';
import {
    StyleSheet,
    Image,
    TouchableWithoutFeedback,
} from 'react-native';
import { Block, Text, theme } from 'galio-framework';
import { argonTheme } from '../constants';

const Card = (props) => {
    const {
        item,
        horizontal,
        full,
        style,
        ctaColor,
        imageStyle,
        ctaRight,
    } = props;

    const imageStyles = [
        full ? styles.fullImage : styles.horizontalImage,
        imageStyle,
    ];
    const cardContainer = [styles.card, styles.shadow, style];
    const imgContainer = [
        styles.imageContainer,
        horizontal ? styles.horizontalStyles : styles.verticalStyles,
        styles.shadow,
    ];

    return (
        <Block row={horizontal} card flex style={cardContainer}>
            <TouchableWithoutFeedback
                onPress={item.ctaNavigation}
            >
                <Block flex style={imgContainer}>
                    <Image
                        source={typeof item.image === 'string' ? { uri: item.image } : item.image}
                        style={imageStyles}
                    />
                </Block>
            </TouchableWithoutFeedback>
            <TouchableWithoutFeedback
                onPress={item.ctaNavigation}
            >
                <Block flex space="between" style={styles.cardDescription}>
                    <Block flex>
                        <Text
                            style={[{ fontFamily: 'open-sans-regular' }, styles.cardTitle]}
                            size={14}
                            color={argonTheme.COLORS.TEXT}
                        >
                            {item.title}
                        </Text>
                        {item.body ? (
                            <Block flex left>
                                <Text
                                    style={{ fontFamily: 'open-sans-regular' }}
                                    size={12}
                                    color={argonTheme.COLORS.TEXT}
                                >
                                    {item.body}
                                </Text>
                            </Block>
                        ) : null}
                    </Block>
                    <Block right={ctaRight}>
                        <Text
                            style={{ fontFamily: 'open-sans-bold' }}
                            size={12}
                            muted={!ctaColor}
                            color={ctaColor || argonTheme.COLORS.ACTIVE}
                            bold
                        >
                            {item.cta}
                        </Text>
                    </Block>
                </Block>
            </TouchableWithoutFeedback>
        </Block>
    );
};

Card.propTypes = {
    item: PropTypes.shape({
        image: PropTypes.oneOfType([
            PropTypes.string,
            PropTypes.number, // For local images using require()
        ]).isRequired,
        title: PropTypes.string.isRequired,
        body: PropTypes.string,
        cta: PropTypes.string,
        ctaNavigation: PropTypes.func,
    }).isRequired,
    horizontal: PropTypes.bool,
    full: PropTypes.bool,
    ctaColor: PropTypes.string,
    imageStyle: PropTypes.any,
    ctaRight: PropTypes.bool,
    style: PropTypes.any,
};

const styles = StyleSheet.create({
    card: {
        backgroundColor: theme.COLORS.WHITE,
        marginVertical: theme.SIZES.BASE,
        borderWidth: 0,
        minHeight: 114,
        marginBottom: 4,
    },
    cardTitle: {
        paddingBottom: 6,
    },
    cardDescription: {
        padding: theme.SIZES.BASE / 2,
    },
    imageContainer: {
        borderRadius: 3,
        elevation: 1,
        overflow: 'hidden',
    },
    horizontalImage: {
        height: 122,
        width: 'auto',
    },
    horizontalStyles: {
        borderTopRightRadius: 0,
        borderBottomRightRadius: 0,
    },
    verticalStyles: {
        borderBottomRightRadius: 0,
        borderBottomLeftRadius: 0,
    },
    fullImage: {
        height: 215,
    },
    shadow: {
        shadowColor: '#8898AA',
        shadowOffset: { width: 0, height: 1 },
        shadowRadius: 6,
        shadowOpacity: 0.1,
        elevation: 2,
    },
});

export default Card;
