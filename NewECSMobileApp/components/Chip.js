// components/Chip.js
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

const Chip = ({ children, style }) => {
    return (
        <View style={[styles.chip, style]}>
            <Text style={styles.chipText}>{children}</Text>
        </View>
    );
};

const styles = StyleSheet.create({
    chip: {
        backgroundColor: '#e0e0e0',
        borderRadius: 16,
        paddingHorizontal: 12,
        paddingVertical: 6,
    },
    chipText: {
        fontSize: 14,
        color: '#424242',
    },
});

export default Chip;