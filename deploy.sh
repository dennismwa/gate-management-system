# deploy.sh - Automated Deployment Script
#!/bin/bash

set -e  # Exit on error

# Configuration
DOMAIN="system.zuri.co.ke"
APP_USER="gateapp"
APP_DIR="/home/$APP_USER/gate-management-system"
BACKUP_DIR="/home/$APP_USER/backups"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')] $1${NC}"
}

error() {
    echo -e "${RED}[ERROR] $1${NC}" >&2
}

warning() {
    echo -e "${YELLOW}[WARNING] $1${NC}"
}

info() {
    echo -e "${BLUE}[INFO] $1${NC}"
}

# Check if running as correct user
check_user() {
    if [ "$USER" != "$APP_USER" ]; then
        error "This script must be run as $APP_USER user"
        exit 1
    fi
}

# Backup current deployment
backup_current() {
    log "Creating backup of current deployment..."
    
    if [ -d "$APP_DIR" ]; then
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        BACKUP_FILE="$BACKUP_DIR/deployment_backup_$TIMESTAMP.tar.gz"
        
        mkdir -p "$BACKUP_DIR"
        tar -czf "$BACKUP_FILE" -C "$APP_DIR" . --exclude='venv' --exclude='__pycache__' --exclude='*.pyc'
        
        log "Backup created: $BACKUP_FILE"
    fi
}

# Pull latest code
update_code() {
    log "Updating application code..."
    
    cd "$APP_DIR"
    
    # Stash any local changes
    git stash
    
    # Pull latest changes
    git pull origin main
    
    # Update submodules if any
    git submodule update --init --recursive
    
    log "Code updated successfully"
}

# Update dependencies
update_dependencies() {
    log "Updating dependencies..."
    
    cd "$APP_DIR"
    source venv/bin/activate
    
    pip install --upgrade pip
    pip install -r requirements.txt
    
    log "Dependencies updated"
}

# Run database migrations
run_migrations() {
    log "Running database migrations..."
    
    cd "$APP_DIR"
    source venv/bin/activate
    
    # Add your migration commands here
    # python scripts/migrate.py
    
    log "Migrations completed"
}

# Collect static files
collect_static() {
    log "Collecting static files..."
    
    cd "$APP_DIR"
    
    # Ensure static directories exist
    mkdir -p app/static/css app/static/js app/static/images
    
    # Copy updated static files if needed
    # This step might not be necessary for your setup
    
    log "Static files collected"
}

# Test application
test_application() {
    log "Testing application..."
    
    cd "$APP_DIR"
    source venv/bin/activate
    
    # Run basic tests
    python -c "import run; print('✅ Application imports successfully')"
    
    # Test database connection
    python -c "
import asyncio
from app.database import test_connection
result = asyncio.run(test_connection())
if result:
    print('✅ Database connection successful')
else:
    print('❌ Database connection failed')
    exit(1)
"
    
    log "Application tests passed"
}

# Restart services
restart_services() {
    log "Restarting services..."
    
    # Restart application
    sudo systemctl restart gate-management
    
    # Wait for service to start
    sleep 5
    
    # Check service status
    if sudo systemctl is-active --quiet gate-management; then
        log "✅ Gate Management service restarted successfully"
    else
        error "❌ Failed to restart Gate Management service"
        sudo systemctl status gate-management
        exit 1
    fi
    
    # Restart Nginx
    sudo systemctl reload nginx
    
    if sudo systemctl is-active --quiet nginx; then
        log "✅ Nginx reloaded successfully"
    else
        error "❌ Failed to reload Nginx"
        exit 1
    fi
}

# Health check
health_check() {
    log "Performing health check..."
    
    # Wait for application to be ready
    sleep 10
    
    # Test health endpoint
    HEALTH_URL="https://$DOMAIN/health"
    
    for i in {1..5}; do
        HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" || echo "000")
        
        if [ "$HTTP_CODE" = "200" ]; then
            log "✅ Health check passed - Application is running"
            return 0
        else
            warning "Health check attempt $i failed (HTTP $HTTP_CODE)"
            if [ $i -lt 5 ]; then
                sleep 10
            fi
        fi
    done
    
    error "❌ Health check failed - Application may not be running correctly"
    exit 1
}

# Cleanup old backups
cleanup_backups() {
    log "Cleaning up old backups..."
    
    # Keep only last 5 deployment backups
    cd "$BACKUP_DIR"
    ls -t deployment_backup_*.tar.gz 2>/dev/null | tail -n +6 | xargs -r rm -f
    
    log "Backup cleanup completed"
}

# Main deployment process
main() {
    log "🚀 Starting deployment to $DOMAIN"
    
    check_user
    backup_current
    update_code
    update_dependencies
    run_migrations
    collect_static
    test_application
    restart_services
    health_check
    cleanup_backups
    
    log "🎉 Deployment completed successfully!"
    info "Application is now available at: https://$DOMAIN"
}

# Rollback function
rollback() {
    log "🔄 Rolling back to previous deployment..."
    
    # Find latest backup
    LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/deployment_backup_*.tar.gz 2>/dev/null | head -n 1)
    
    if [ -z "$LATEST_BACKUP" ]; then
        error "No backup found for rollback"
        exit 1
    fi
    
    log "Rolling back to: $LATEST_BACKUP"
    
    # Extract backup
    cd "$APP_DIR"
    tar -xzf "$LATEST_BACKUP"
    
    # Restart services
    restart_services
    health_check
    
    log "✅ Rollback completed"
}

# Handle command line arguments
case "${1:-deploy}" in
    "deploy")
        main
        ;;
    "rollback")
        rollback
        ;;
    "test")
        test_application
        ;;
    "restart")
        restart_services
        health_check
        ;;
    *)
        echo "Usage: $0 {deploy|rollback|test|restart}"
        exit 1
        ;;
esac

---

# scripts/setup_production.sh - Initial Production Setup
#!/bin/bash

set -e

DOMAIN="${1:-system.zuri.co.ke}"
EMAIL="${2:-admin@zuri.co.ke}"

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root for initial setup"
    exit 1
fi

echo "🚀 Setting up production environment for $DOMAIN"

# Update system
apt update && apt upgrade -y

# Install required packages
apt install -y \
    python3-pip \
    python3-venv \
    nginx \
    mysql-server \
    git \
    htop \
    curl \
    ufw \
    fail2ban \
    certbot \
    python3-certbot-nginx \
    supervisor

# Create application user
if ! id "gateapp" &>/dev/null; then
    adduser --disabled-password --gecos "" gateapp
    usermod -aG sudo gateapp
    echo "✅ Created gateapp user"
fi

# Setup firewall
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 'Nginx Full'
ufw --force enable
echo "✅ Firewall configured"

# Secure MySQL
mysql_secure_installation

# Clone application
sudo -u gateapp git clone https://github.com/yourusername/gate-management-system.git /home/gateapp/gate-management-system

# Setup application
cd /home/gateapp/gate-management-system
sudo -u gateapp python3 -m venv venv
sudo -u gateapp venv/bin/pip install -r requirements.txt
sudo -u gateapp venv/bin/pip install gunicorn

# Create directories
sudo -u gateapp mkdir -p uploads logs backups app/static/qr_codes

# Set permissions
chown -R gateapp:gateapp /home/gateapp/gate-management-system
chmod -R 755 /home/gateapp/gate-management-system

echo "✅ Basic setup completed"
echo "Next steps:"
echo "1. Configure database