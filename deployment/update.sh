#!/bin/bash
set -e

echo "=========================================="
echo "Naked Forex API - Update Script"
echo "=========================================="

GREEN='\033[0;32m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

# Pull latest code (if using git)
if [ -d ".git" ]; then
    log_info "Pulling latest code from git..."
    git pull
fi

# Rebuild and restart
log_info "Rebuilding Docker image..."
docker-compose build

log_info "Restarting containers..."
docker-compose up -d

log_info "Waiting for container to start..."
sleep 15

log_info "Update completed!"
log_info "Check status: docker-compose ps"
log_info "Check logs: docker-compose logs -f"
