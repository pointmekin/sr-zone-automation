#!/bin/bash
set -e

# Ensure log and cache directories exist with proper permissions
mkdir -p /app/logs /app/cache

# Fix permissions if running as root, otherwise skip
if [ "$(id -u)" = "0" ]; then
    chown -R appuser:appuser /app/logs /app/cache
fi

# Run the main command as appuser
if [ "$(id -u)" = "0" ]; then
    exec gosu appuser "$@"
else
    exec "$@"
fi
