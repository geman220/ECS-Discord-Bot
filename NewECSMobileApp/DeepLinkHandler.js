// DeepLinkHandler.js
import * as Linking from 'expo-linking';

export const handleDeepLink = (url) => {
  let data = Linking.parse(url);
  console.log('Received deep link:', data);

  // Handle the deep link here
  if (data.path === 'auth' && data.queryParams.code) {
    // This is a Discord auth callback
    // You can dispatch an action or call a function to handle the auth code
    handleDiscordAuthCode(data.queryParams.code);
  }
};

const handleDiscordAuthCode = (code) => {
  // Implement your logic to handle the Discord auth code
  // This might involve sending the code to your backend
  console.log('Handling Discord auth code:', code);
  // You might want to use your existing auth logic here
};

export const setupDeepLinking = (navigation) => {
  Linking.addEventListener('url', (event) => handleDeepLink(event.url));

  // Check for initial URL
  Linking.getInitialURL().then((url) => {
    if (url) {
      handleDeepLink(url);
    }
  });
};