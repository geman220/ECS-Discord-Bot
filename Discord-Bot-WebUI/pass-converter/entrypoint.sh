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

# Start the application
exec node app.js
