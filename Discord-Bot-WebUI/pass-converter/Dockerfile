FROM node:20-slim

WORKDIR /app

# Install git and gettext (for envsubst)
RUN apt-get update && apt-get install -y git gettext-base && rm -rf /var/lib/apt/lists/*

# Clone pass-converter from Google's official repository
RUN git clone https://github.com/google-wallet/pass-converter.git .

# Install dependencies
RUN npm install

# Create data directory for SQLite database
RUN mkdir -p /app/data

# Copy our configuration template
COPY config.json /app/config.template.json

# Copy entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 3000

# Use entrypoint to substitute env vars at runtime
ENTRYPOINT ["/app/entrypoint.sh"]
