// DeepLinkHandler.js
import * as Linking from 'expo-linking';

export const handleDeepLink = (url) => {
  let data = Linking.parse(url);
  console.log('Received deep link:', data);

  if (data.path === 'auth' && data.queryParams.code) {
    handleDiscordAuthCode(data.queryParams.code);
  }
};

const handleDiscordAuthCode = (code) => {
  console.log('Handling Discord auth code:', code);

};

export const setupDeepLinking = (navigation) => {
  Linking.addEventListener('url', (event) => handleDeepLink(event.url));

  Linking.getInitialURL().then((url) => {
    if (url) {
      handleDeepLink(url);
    }
  });
};