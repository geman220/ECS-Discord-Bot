#!/bin/sh
# Substitute environment variables in config.json
# This allows us to inject GOOGLE_WALLET_ISSUER_ID at runtime

CONFIG_FILE="/app/config.json"
CONFIG_TEMPLATE="/app/config.template.json"

# If template exists, use it; otherwise use existing config
if [ -f "$CONFIG_TEMPLATE" ]; then
    # Substitute environment variables
    envsubst < "$CONFIG_TEMPLATE" > "$CONFIG_FILE"
    echo "Config generated from template with GOOGLE_WALLET_ISSUER_ID=${GOOGLE_WALLET_ISSUER_ID}"
else
    echo "Warning: No config template found, using existing config.json"
fi

# Patch app.js to use publicUrl from config instead of request headers
# This fixes the issue where internal Docker URLs are used for Google Wallet images
if [ -n "$PUBLIC_URL" ]; then
    echo "Patching app.js to use PUBLIC_URL=${PUBLIC_URL}"
    sed -i "s|req.fullUrl = \`\${req.protocol}://\${req.get('host')}\${req.originalUrl}\`;|req.fullUrl = config.publicUrl ? \`\${config.publicUrl}/convert/\` : \`\${req.protocol}://\${req.get('host')}\${req.originalUrl}\`;|g" /app/app.js
fi

# Start the application
exec node app.js
