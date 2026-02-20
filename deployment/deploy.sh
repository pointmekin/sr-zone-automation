#!/bin/bash
set -e

echo "=========================================="
echo "Naked Forex API - Deployment Script"
echo "=========================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="finance-automation"
DOCKER_COMPOSE_FILE="docker-compose.yml"
ENV_FILE=".env"
BACKUP_DIR="./backups"

# Functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

check_env_file() {
    if [ ! -f "$ENV_FILE" ]; then
        log_error "Environment file not found: $ENV_FILE"
        log_info "Create it from template: cp .env.production $ENV_FILE"
        exit 1
    fi
    log_info "Environment file found"
}

backup_current() {
    log_info "Creating backup..."
    mkdir -p "$BACKUP_DIR"

    # Backup .env file
    if [ -f "$ENV_FILE" ]; then
        cp "$ENV_FILE" "$BACKUP_DIR/.env.$(date +%Y%m%d_%H%M%S)"
    fi

    # Backup database if using SQLite
    if [ -f "naked_forex.db" ]; then
        cp "naked_forex.db" "$BACKUP_DIR/naked_forex.db.$(date +%Y%m%d_%H%M%S)"
    fi

    log_info "Backup completed"
}

build_image() {
    log_info "Building Docker image..."
    docker-compose build --no-cache
    log_info "Image build completed"
}

stop_containers() {
    log_info "Stopping existing containers..."
    docker-compose down
    log_info "Containers stopped"
}

start_containers() {
    log_info "Starting containers..."
    docker-compose up -d
    log_info "Containers started"
}

run_migrations() {
    log_info "Running database initialization..."
    docker-compose exec -T finance-automation python scripts/init_db.py
    log_info "Database initialization completed"
}

show_logs() {
    log_info "Showing recent logs (Ctrl+C to exit)..."
    docker-compose logs --tail=50 -f
}

show_status() {
    log_info "Container status:"
    docker-compose ps
}

health_check() {
    log_info "Performing health check..."

    # Wait for container to start
    sleep 10

    if curl -f http://localhost:8100/api/v1/health > /dev/null 2>&1; then
        log_info "Health check passed!"
        return 0
    else
        log_error "Health check failed!"
        return 1
    fi
}

# Main deployment flow
main() {
    log_info "Starting deployment process..."

    # Check prerequisites
    check_env_file

    # Create backup
    backup_current

    # Stop existing containers
    stop_containers

    # Build new image
    build_image

    # Start new containers
    start_containers

    # Show status
    show_status

    # Run health check
    if health_check; then
        log_info "Deployment completed successfully!"
        log_info "API is available at: http://localhost:8100"
        log_info "Documentation: http://localhost:8100/docs"

        # Optional: show logs
        read -p "View logs? (y/n) " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            show_logs
        fi
    else
        log_error "Deployment failed! Check logs: docker-compose logs"
        exit 1
    fi
}

# Run main function
main
