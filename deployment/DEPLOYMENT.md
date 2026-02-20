# Deployment Guide - Naked Forex API on Hetzner VPS

This guide covers deploying the Naked Forex API trading automation system to a Hetzner VPS using Docker and GitHub Actions.

## Table of Contents

- [Prerequisites](#prerequisites)
- [VPS Setup](#vps-setup)
- [Manual Deployment](#manual-deployment)
- [GitHub Actions CI/CD](#github-actions-cicd)
- [Management Commands](#management-commands)
- [Monitoring](#monitoring)
- [Troubleshooting](#troubleshooting)
- [Maintenance](#maintenance)

---

## Prerequisites

Before deploying, ensure you have:

- **Hetzner Account** with ability to create VPS
- **Domain Name** (optional, for accessing API)
- **Neon PostgreSQL Account** for cloud database
- **Discord Bot Token** from [Discord Developer Portal](https://discord.com/developers/applications)
- **GitHub Repository** with your code
- **SSH Key** for secure VPS access

---

## VPS Setup

### 1. Create Hetzner VPS

1. Log in to [Hetzner Cloud Console](https://console.hetzner.cloud/)
2. Create a new project
3. Create a new server:
   - **Location:** Choose region closest to your users
   - **Image:** Ubuntu 22.04 LTS or Debian 12 Bookworm
   - **Type:** CX21 or better (minimum 2GB RAM, 1 vCPU)
   - **SSH Key:** Upload your public SSH key
4. Note the server IP address

### 2. Connect to VPS

```bash
ssh root@YOUR_VPS_IP
```

### 3. Update System and Install Docker

```bash
# Update system
apt-get update && apt-get upgrade -y

# Install prerequisites
apt-get install -y curl git

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh

# Install Docker Compose
curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

# Verify installation
docker --version
docker-compose --version

# Enable Docker to start on boot
systemctl enable docker
systemctl start docker
```

### 4. Configure Firewall

```bash
# Install UFW
apt-get install -y ufw

# Allow SSH
ufw allow 22/tcp

# Allow HTTP
ufw allow 80/tcp

# Allow custom port (8100) if needed
ufw allow 8100/tcp

# Enable firewall
ufw enable

# Check status
ufw status
```

### 5. Create Deployment User (Recommended)

```bash
# Create non-root user
useradd -m -s /bin/bash finance

# Add to docker group
usermod -aG docker finance

# Switch to user
su - finance
```

---

## Manual Deployment

### 1. Clone Repository

```bash
# As deployment user
cd ~

# Clone your repository
git clone https://github.com/pointmekin/sr-zone-automation.git finance-automation
cd finance-automation
```

### 2. Configure Environment

```bash
# Create production .env file
cp .env.production .env

# Edit with your values
nano .env
```

**Critical environment variables to set:**

```bash
# Database - Use Neon PostgreSQL connection string
POSTGRES_URL=postgresql+asyncpg://user:password@ep-xxx.region.aws.neon.tech/neondb?ssl=require

# Generate secure secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Discord (if using)
DISCORD_TOKEN=your_bot_token
DISCORD_CHANNEL_ID=your_channel_id

# Trading parameters
DEFAULT_TICKERS=["EURUSD=X", "USDJPY=X", "GBPUSD=X"]
SCAN_INTERVAL_MINUTES=60
```

### 3. Create Necessary Directories

```bash
mkdir -p logs cache backups
```

### 4. Deploy Using Script

```bash
# Make deploy script executable
chmod +x deployment/deploy.sh

# Run deployment
./deployment/deploy.sh
```

**Or manual deployment:**

```bash
# Build image
docker-compose build

# Start container
docker-compose up -d

# Check status
docker-compose ps

# Check logs
docker-compose logs -f
```

### 5. Initialize Database

```bash
# Run database initialization
docker-compose exec finance-automation python scripts/init_db.py
```

### 6. Verify Deployment

```bash
# Check container is healthy
docker-compose ps

# Test health endpoint
curl http://localhost:8100/api/v1/health

# Check background tasks
docker-compose logs | grep "Background scanning started"
```

---

## GitHub Actions CI/CD

### How It Works

When you push code to the `main` branch:
1. GitHub Actions connects to your VPS via SSH
2. Pulls latest code
3. Rebuilds Docker image
4. Restarts container
5. Verifies health check

### GitHub Setup

#### 1. Generate SSH Key for GitHub Actions

```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions" -f ~/.ssh/github_actions

# Copy public key to VPS
ssh-copy-id -i ~/.ssh/github_actions.pub finance@YOUR_VPS_IP

# Copy private key content for GitHub secret
cat ~/.ssh/github_actions
```

#### 2. Add Secrets to GitHub

Go to: **Repository → Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret Name | Value |
|------------|-------|
| `VPS_HOST` | Your VPS IP address (e.g., `123.45.67.89`) |
| `VPS_USERNAME` | VPS username (e.g., `finance`) |
| `VPS_SSH_KEY` | Private SSH key content (from `cat ~/.ssh/github_actions`) |

#### 3. Enable GitHub Actions

```bash
# Add workflow file (already exists in .github/workflows/deploy.yml)
git add .github/workflows/deploy.yml
git commit -m "Add GitHub Actions CI/CD"
git push origin main
```

#### 4. Monitor Deployment

- Go to: **Repository → Actions** tab
- Watch deployment progress in real-time
- View logs for each step

#### 5. Manual Deployment Trigger

If you need to deploy without pushing to `main`:
1. Go to: **Repository → Actions → "Deploy to VPS"**
2. Click **"Run workflow"** button
3. Select branch and click **"Run workflow"**

---

## Management Commands

### Start/Stop/Restart

```bash
docker-compose up -d          # Start
docker-compose stop           # Stop
docker-compose restart        # Restart
docker-compose down           # Stop and remove
```

### View Logs

```bash
docker-compose logs -f                # Follow logs
docker-compose logs --tail=100        # Last 100 lines
docker-compose logs | grep ERROR      # Errors only
```

### Update Application

**Automatic (GitHub Actions):**
```bash
git push origin main
# GitHub Actions handles the rest
```

**Manual:**
```bash
./deployment/update.sh
# Or:
git pull
docker-compose build --no-cache
docker-compose up -d
```

---

## Monitoring

### Health Checks

```bash
# Container health status
docker inspect --format='{{.State.Health.Status}}' finance-automation-app

# API health endpoint
curl http://localhost:8100/api/v1/health
```

### Resource Usage

```bash
# Container resource usage
docker stats finance-automation-app

# System resources
htop
```

### Background Tasks

```bash
# Check if tasks are running
docker-compose logs | grep "Background scanning"

# Check for scan activity
docker-compose logs | grep "periodic scan"
```

### Discord Bot

```bash
# Check bot logs
docker-compose logs | grep discord

# Test in Discord
!status
!scan
```

---

## Troubleshooting

### Container won't start

```bash
# Check logs
docker-compose logs

# Verify .env file exists
ls -la .env

# Validate docker-compose configuration
docker-compose config
```

### Database connection errors

```bash
# Verify POSTGRES_URL format in .env
# Must use: postgresql+asyncpg://user:pass@host/db?ssl=require
# Note: ?ssl=require (not sslmode=require)
```

### Discord bot not connecting

```bash
# Check bot logs
docker-compose logs | grep -i discord

# Verify DISCORD_TOKEN in .env
# Verify bot is invited to server
```

### Out of memory errors

```bash
# Check resource usage
docker stats finance-automation-app

# Increase memory limit in docker-compose.yml
```

---

## Maintenance

### Daily

- [ ] Check container status: `docker-compose ps`
- [ ] Review error logs: `docker-compose logs | grep ERROR`

### Weekly

- [ ] Check resource usage: `docker stats`
- [ ] Review log file sizes: `ls -lh logs/`
- [ ] Test API endpoints

### Monthly

- [ ] Update base image: `docker-compose pull`
- [ ] Review and rotate secrets
- [ ] Clean up old backups
- [ ] Security updates on VPS: `apt-get update && apt-get upgrade -y`

---

## Useful Links

- **API Documentation:** `http://YOUR_VPS_IP:8100/docs`
- **Health Endpoint:** `http://YOUR_VPS_IP:8100/api/v1/health`
- **Hetzner Console:** https://console.hetzner.cloud/
- **Neon Console:** https://console.neon.tech/
- **Discord Developer Portal:** https://discord.com/developers/applications
