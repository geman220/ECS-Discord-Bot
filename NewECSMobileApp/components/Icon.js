// components/Icon.js

import React from 'react';
import { createIconSetFromIcoMoon } from '@expo/vector-icons';
import { Icon as GalioIcon } from 'galio-framework';
import { FontAwesome, FontAwesome5 } from '@expo/vector-icons'; // Import from @expo/vector-icons

// Import your custom ArgonExtra config and font
import argonConfig from '../assets/config/argon.json';
const IconArgonExtra = createIconSetFromIcoMoon(argonConfig, 'ArgonExtra');

const Icon = ({ name, family, ...rest }) => {
    switch (family) {
        case 'ArgonExtra':
            return <IconArgonExtra name={name} {...rest} />;
        case 'FontAwesome':
            return <FontAwesome name={name} {...rest} />;
        case 'FontAwesome5':
            return <FontAwesome5 name={name} {...rest} />;
        case 'MaterialIcons':
            return <GalioIcon name={name} family={family} {...rest} />;
        default:
            return <GalioIcon name={name} family={family} {...rest} />;
    }
};

export default Icon;
