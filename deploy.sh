#!/bin/bash
#
# Altex Backend Deployment Script
# Comprehensive one-click deployment for FastAPI backend with Admin WebUI
#
# Usage:
#   ./deploy.sh              # Standard deployment
#   ./deploy.sh --fresh      # Fresh installation
#   ./deploy.sh --update     # Update and restart
#   ./deploy.sh --migrate    # Run migrations only
#   ./deploy.sh --logs       # View logs
#   ./deploy.sh --status     # Check service status
#

set -e

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_NAME="altex-backend"
SERVICE_NAME="altex-backend"
VENV_DIR="${SCRIPT_DIR}/.venv"
ENV_FILE="${SCRIPT_DIR}/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/.env.example"
REQUIREMENTS_FILE="${SCRIPT_DIR}/requirements.txt"
LOG_DIR="/var/log/${PROJECT_NAME}"
LOG_FILE="${LOG_DIR}/app.log"

# Default admin credentials (can be overridden via env)
DEFAULT_ADMIN_EMAIL="${ADMIN_EMAIL:-admin@altex.local}"
DEFAULT_ADMIN_PASSWORD="${ADMIN_PASSWORD:-Admin@123456}"

# Database URL from command line or env
DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://postgres:uLFIfDIzxzTuxLbNBdNn@altex-chat.crek440ck7co.ap-northeast-1.rds.amazonaws.com:5432/altex-chat}"

# ─────────────────────────────────────────────────────────────────────────────
# Color Definitions
# ─────────────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║                                                               ║"
    echo "║               ${WHITE}Altex Backend Deployment Script${CYAN}                  ║"
    echo "║                                                               ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${WHITE}▶ $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

print_progress() {
    echo -e "${MAGENTA}⋯ $1${NC}"
}

check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

get_python_version() {
    python3 -c 'import sys; print(".".join(map(str, sys.version_info[:2])))'
}

compare_versions() {
    # Returns 0 if $1 >= $2
    if [ "$(printf '%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; then
        return 0
    else
        return 1
    fi
}

prompt_input() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    
    if [ -n "$default" ]; then
        prompt="${prompt} [${default}]"
    fi
    
    read -p "$(echo -e ${YELLOW}? ${prompt}: ${NC})" value
    value="${value:-$default}"
    eval "$var_name='$value'"
}

confirm() {
    local prompt="$1"
    local default="${2:-n}"
    
    if [ "$default" = "y" ]; then
        prompt="${prompt} [Y/n]"
    else
        prompt="${prompt} [y/N]"
    fi
    
    read -p "$(echo -e ${YELLOW}? ${prompt}: ${NC})" response
    response="${response:-$default}"
    
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# ─────────────────────────────────────────────────────────────────────────────
# System Requirements Check
# ─────────────────────────────────────────────────────────────────────────────

check_system_requirements() {
    print_step "Checking System Requirements"
    
    local errors=0
    
    # Check Python 3.10+
    print_progress "Checking Python installation..."
    if check_command python3; then
        local py_version=$(get_python_version)
        if compare_versions "$py_version" "3.10"; then
            print_success "Python ${py_version} found (>= 3.10)"
        else
            print_error "Python ${py_version} found, but 3.10+ is required"
            ((errors++))
        fi
    else
        print_error "Python 3 not found"
        ((errors++))
    fi
    
    # Check pip
    print_progress "Checking pip installation..."
    if check_command pip3 || check_command pip; then
        print_success "pip found"
    else
        print_error "pip not found"
        ((errors++))
    fi
    
    # Check PostgreSQL client (optional but recommended)
    print_progress "Checking PostgreSQL client..."
    if check_command psql; then
        print_success "PostgreSQL client found"
    else
        print_warning "PostgreSQL client not found (optional for DB operations)"
    fi
    
    # Check git (for version info)
    print_progress "Checking git..."
    if check_command git; then
        print_success "git found"
    else
        print_warning "git not found (optional)"
    fi
    
    # Check systemd
    print_progress "Checking systemd..."
    if pidof systemd &> /dev/null; then
        print_success "systemd detected"
        HAS_SYSTEMD=true
    else
        print_warning "systemd not detected (will use alternative startup method)"
        HAS_SYSTEMD=false
    fi
    
    # Check available memory
    print_progress "Checking system memory..."
    local total_mem=$(free -m 2>/dev/null | awk '/^Mem:/{print $2}')
    if [ -n "$total_mem" ] && [ "$total_mem" -lt 512 ]; then
        print_warning "Low memory detected (${total_mem}MB). Consider increasing for production."
    elif [ -n "$total_mem" ]; then
        print_success "Memory: ${total_mem}MB available"
    fi
    
    if [ $errors -gt 0 ]; then
        print_error "System requirements not met. Please install missing dependencies."
        exit 1
    fi
    
    print_success "All system requirements satisfied!"
}

# ─────────────────────────────────────────────────────────────────────────────
# Environment Setup
# ─────────────────────────────────────────────────────────────────────────────

setup_virtualenv() {
    print_step "Setting Up Virtual Environment"
    
    if [ -d "$VENV_DIR" ]; then
        if [ "$FRESH_INSTALL" = true ]; then
            print_warning "Removing existing virtual environment for fresh installation..."
            rm -rf "$VENV_DIR"
        else
            print_info "Virtual environment already exists at ${VENV_DIR}"
            if confirm "Recreate virtual environment?" "n"; then
                rm -rf "$VENV_DIR"
            else
                print_info "Using existing virtual environment"
                return 0
            fi
        fi
    fi
    
    print_progress "Creating virtual environment..."
    python3 -m venv "$VENV_DIR"
    print_success "Virtual environment created at ${VENV_DIR}"
}

activate_venv() {
    print_progress "Activating virtual environment..."
    source "${VENV_DIR}/bin/activate"
    print_success "Virtual environment activated"
}

install_dependencies() {
    print_step "Installing Dependencies"
    
    if [ ! -f "$REQUIREMENTS_FILE" ]; then
        print_error "requirements.txt not found at ${REQUIREMENTS_FILE}"
        exit 1
    fi
    
    print_progress "Upgrading pip..."
    pip install --upgrade pip wheel setuptools
    
    print_progress "Installing requirements from ${REQUIREMENTS_FILE}..."
    pip install -r "$REQUIREMENTS_FILE"
    
    print_success "All dependencies installed successfully!"
    
    # Show installed packages summary
    local pkg_count=$(pip list --format=freeze 2>/dev/null | wc -l)
    print_info "Total packages installed: ${pkg_count}"
}

setup_env_file() {
    print_step "Configuring Environment"
    
    if [ -f "$ENV_FILE" ]; then
        if [ "$FRESH_INSTALL" = true ]; then
            print_warning "Backing up existing .env file..."
            cp "$ENV_FILE" "${ENV_FILE}.backup.$(date +%Y%m%d%H%M%S)"
            rm "$ENV_FILE"
        else
            print_info "Environment file already exists"
            print_progress "Checking for missing variables..."
            check_missing_env_vars
            return 0
        fi
    fi
    
    if [ -f "$ENV_EXAMPLE" ]; then
        print_progress "Copying ${ENV_EXAMPLE} to ${ENV_FILE}..."
        cp "$ENV_EXAMPLE" "$ENV_FILE"
        print_success "Environment file created"
    else
        print_warning "No .env.example found, creating minimal .env..."
        create_minimal_env
    fi
    
    # Prompt for critical variables
    prompt_critical_variables
}

create_minimal_env() {
    cat > "$ENV_FILE" << 'EOF'
# Altex Backend Environment Configuration
# Generated by deploy.sh

# ── Core ────────────────────────────────────────────────────────
secret_key=
database_url=
environment=production

# ── Server ──────────────────────────────────────────────────────
host=0.0.0.0
port=8000
workers=4
log_level=info

# ── Auth ────────────────────────────────────────────────────────
enable_signup=true
access_token_expire_minutes=10080
refresh_token_expire_days=30

# ── Admin Credentials ───────────────────────────────────────────
admin_email=admin@altex.local
admin_password=Admin@123456
EOF
    print_success "Minimal .env file created"
}

prompt_critical_variables() {
    print_info "Please configure critical environment variables:"
    echo ""
    
    # Check if database_url is set
    if ! grep -q "^database_url=.\+" "$ENV_FILE" 2>/dev/null; then
        prompt_input "Database URL" "$DATABASE_URL" db_url
        sed -i "s|^database_url=.*|database_url=${db_url}|" "$ENV_FILE"
    else
        print_info "Database URL already configured"
    fi
    
    # Check if secret_key is set and generate if needed
    if ! grep -q "^secret_key=.\+" "$ENV_FILE" 2>/dev/null || grep -q "^secret_key=your-super-secret-key" "$ENV_FILE"; then
        print_progress "Generating secure secret key..."
        local secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
        sed -i "s|^secret_key=.*|secret_key=${secret}|" "$ENV_FILE"
        print_success "Secret key generated"
    else
        print_info "Secret key already configured"
    fi
    
    # Prompt for admin credentials
    print_info "Admin credentials for WebUI:"
    prompt_input "Admin email" "$DEFAULT_ADMIN_EMAIL" admin_email
    prompt_input "Admin password" "$DEFAULT_ADMIN_PASSWORD" admin_password
    
    # Update admin credentials in .env
    if grep -q "^admin_email=" "$ENV_FILE"; then
        sed -i "s|^admin_email=.*|admin_email=${admin_email}|" "$ENV_FILE"
    else
        echo "admin_email=${admin_email}" >> "$ENV_FILE"
    fi
    
    if grep -q "^admin_password=" "$ENV_FILE"; then
        sed -i "s|^admin_password=.*|admin_password=${admin_password}|" "$ENV_FILE"
    else
        echo "admin_password=${admin_password}" >> "$ENV_FILE"
    fi
    
    print_success "Environment configuration complete"
}

check_missing_env_vars() {
    local missing=false
    local required_vars=("secret_key" "database_url")
    
    for var in "${required_vars[@]}"; do
        if ! grep -q "^${var}=.\+" "$ENV_FILE" 2>/dev/null || grep -q "^${var}=your-super-secret-key" "$ENV_FILE"; then
            print_warning "Missing or invalid: ${var}"
            missing=true
        fi
    done
    
    if [ "$missing" = true ]; then
        print_info "Please update the missing variables in ${ENV_FILE}"
        if confirm "Edit .env file now?" "y"; then
            ${EDITOR:-nano} "$ENV_FILE"
        fi
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Database Setup
# ─────────────────────────────────────────────────────────────────────────────

run_migrations() {
    print_step "Running Database Migrations"
    
    cd "$SCRIPT_DIR"
    
    # Check if alembic is available
    if ! pip show alembic &> /dev/null; then
        print_error "Alembic not installed. Run with --update first."
        return 1
    fi
    
    # Check alembic.ini exists
    if [ ! -f "${SCRIPT_DIR}/alembic.ini" ]; then
        print_warning "alembic.ini not found, checking for migrations directory..."
        if [ -d "${SCRIPT_DIR}/migrations" ]; then
            print_info "Migrations directory found"
        else
            print_warning "No migrations configured, skipping..."
            return 0
        fi
    fi
    
    print_progress "Checking current migration status..."
    alembic current 2>/dev/null || true
    
    print_progress "Running migrations (alembic upgrade head)..."
    if alembic upgrade head; then
        print_success "Migrations completed successfully!"
    else
        print_error "Migration failed. Please check the database connection and migration files."
        return 1
    fi
}

create_admin_user() {
    print_step "Creating Admin User"
    
    cd "$SCRIPT_DIR"
    
    # Get admin credentials from .env
    local admin_email=$(grep "^admin_email=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    local admin_password=$(grep "^admin_password=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    
    admin_email="${admin_email:-$DEFAULT_ADMIN_EMAIL}"
    admin_password="${admin_password:-$DEFAULT_ADMIN_PASSWORD}"
    
    print_info "Admin email: ${admin_email}"
    
    # Create a Python script to create admin user
    python3 << PYTHON_SCRIPT
import asyncio
import sys
import os

# Add project to path
sys.path.insert(0, "${SCRIPT_DIR}")
os.environ["DATABASE_URL"] = "${DATABASE_URL}"
os.chdir("${SCRIPT_DIR}")

async def create_admin():
    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import text, select
        from passlib.context import CryptContext
        
        pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
        
        engine = create_async_engine("${DATABASE_URL}", echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        
        async with async_session() as session:
            # Check if admin exists
            result = await session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {"email": "${admin_email}"}
            )
            existing = result.fetchone()
            
            if existing:
                print(f"Admin user already exists: ${admin_email}")
                return
            
            # Create admin user
            hashed_password = pwd_context.hash("${admin_password}")
            await session.execute(
                text("""
                    INSERT INTO users (email, hashed_password, is_active, is_admin, created_at, updated_at)
                    VALUES (:email, :hashed_password, true, true, EXTRACT(EPOCH FROM NOW()) * 1000000000, EXTRACT(EPOCH FROM NOW()) * 1000000000)
                """),
                {"email": "${admin_email}", "hashed_password": hashed_password}
            )
            await session.commit()
            print(f"Admin user created: ${admin_email}")
            
    except Exception as e:
        print(f"Error creating admin user: {e}")
        sys.exit(1)

asyncio.run(create_admin())
PYTHON_SCRIPT

    if [ $? -eq 0 ]; then
        print_success "Admin user setup complete"
    else
        print_warning "Could not create admin user (may already exist or tables not ready)"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Service Setup (systemd)
# ─────────────────────────────────────────────────────────────────────────────

create_systemd_service() {
    print_step "Creating Systemd Service"
    
    if [ "$HAS_SYSTEMD" = false ]; then
        print_warning "systemd not available. Creating startup script instead."
        create_startup_script
        return
    fi
    
    local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
    
    print_info "Creating service file at ${service_file}"
    
    cat << EOF | sudo tee "$service_file" > /dev/null
[Unit]
Description=Altex Backend API Server
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=notify
User=${USER}
Group=${USER}
WorkingDirectory=${SCRIPT_DIR}
Environment="PATH=${VENV_DIR}/bin"
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/uvicorn main:app --host 0.0.0.0 --port 8000
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5
TimeoutStartSec=30
TimeoutStopSec=30

# Logging
StandardOutput=append:${LOG_FILE}
StandardError=append:${LOG_FILE}

# Security (adjust as needed)
# NoNewPrivileges=true
# PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

    print_success "Service file created"
    
    # Create log directory
    print_progress "Creating log directory..."
    sudo mkdir -p "$LOG_DIR"
    sudo chown "$USER:$USER" "$LOG_DIR"
    touch "$LOG_FILE"
    print_success "Log directory created at ${LOG_DIR}"
    
    # Reload systemd
    print_progress "Reloading systemd daemon..."
    sudo systemctl daemon-reload
    print_success "Systemd reloaded"
    
    # Enable service
    print_progress "Enabling service..."
    sudo systemctl enable "${SERVICE_NAME}"
    print_success "Service enabled"
}

create_startup_script() {
    print_info "Creating alternative startup script..."
    
    local start_script="${SCRIPT_DIR}/start.sh"
    local stop_script="${SCRIPT_DIR}/stop.sh"
    
    # Start script
    cat > "$start_script" << 'EOF'
#!/bin/bash
cd "$(dirname "$0")"
source .venv/bin/activate
nohup uvicorn main:app --host 0.0.0.0 --port 8000 > /var/log/altex-backend/app.log 2>&1 &
echo $! > .app.pid
echo "Server started with PID $(cat .app.pid)"
EOF
    chmod +x "$start_script"
    
    # Stop script
    cat > "$stop_script" << 'EOF'
#!/bin/bash
if [ -f .app.pid ]; then
    kill $(cat .app.pid) 2>/dev/null
    rm .app.pid
    echo "Server stopped"
else
    echo "No PID file found. Server may not be running."
fi
EOF
    chmod +x "$stop_script"
    
    print_success "Created start.sh and stop.sh scripts"
}

start_service() {
    print_step "Starting Service"
    
    if [ "$HAS_SYSTEMD" = true ]; then
        print_progress "Starting ${SERVICE_NAME} service..."
        sudo systemctl start "${SERVICE_NAME}"
        sleep 2
        
        if sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
            print_success "Service started successfully!"
        else
            print_error "Service failed to start. Check logs with: ./deploy.sh --logs"
            return 1
        fi
    else
        print_progress "Starting server with start.sh..."
        "${SCRIPT_DIR}/start.sh"
    fi
}

stop_service() {
    print_progress "Stopping service..."
    
    if [ "$HAS_SYSTEMD" = true ]; then
        sudo systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    else
        "${SCRIPT_DIR}/stop.sh" 2>/dev/null || true
    fi
    
    print_success "Service stopped"
}

restart_service() {
    print_step "Restarting Service"
    
    if [ "$HAS_SYSTEMD" = true ]; then
        print_progress "Restarting ${SERVICE_NAME} service..."
        sudo systemctl restart "${SERVICE_NAME}"
        sleep 2
        
        if sudo systemctl is-active --quiet "${SERVICE_NAME}"; then
            print_success "Service restarted successfully!"
        else
            print_error "Service failed to restart. Check logs."
            return 1
        fi
    else
        stop_service
        sleep 1
        "${SCRIPT_DIR}/start.sh"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Utility Functions
# ─────────────────────────────────────────────────────────────────────────────

show_status() {
    print_step "Service Status"
    
    if [ "$HAS_SYSTEMD" = true ]; then
        sudo systemctl status "${SERVICE_NAME}" --no-pager
    else
        if [ -f "${SCRIPT_DIR}/.app.pid" ]; then
            local pid=$(cat "${SCRIPT_DIR}/.app.pid")
            if ps -p "$pid" > /dev/null 2>&1; then
                echo -e "${GREEN}Service is running (PID: ${pid})${NC}"
            else
                echo -e "${RED}Service is not running (stale PID file)${NC}"
            fi
        else
            echo -e "${YELLOW}Service is not running${NC}"
        fi
    fi
}

show_logs() {
    print_step "Recent Logs"
    
    if [ "$HAS_SYSTEMD" = true ]; then
        sudo journalctl -u "${SERVICE_NAME}" -n 100 --no-pager -f 2>/dev/null || \
        tail -n 100 -f "$LOG_FILE" 2>/dev/null || \
        echo "No logs available"
    else
        if [ -f "$LOG_FILE" ]; then
            tail -n 100 -f "$LOG_FILE"
        else
            echo "No log file found at ${LOG_FILE}"
        fi
    fi
}

show_info() {
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                   Deployment Complete!                        ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${WHITE}Admin Panel URL:${NC}"
    echo -e "  ${CYAN}http://localhost:8000/admin${NC}"
    echo ""
    echo -e "${WHITE}API Documentation:${NC}"
    echo -e "  ${CYAN}http://localhost:8000/docs${NC}"
    echo ""
    echo -e "${WHITE}Default Credentials:${NC}"
    local admin_email=$(grep "^admin_email=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    local admin_password=$(grep "^admin_password=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    echo -e "  ${YELLOW}Email:${NC}    ${admin_email:-$DEFAULT_ADMIN_EMAIL}"
    echo -e "  ${YELLOW}Password:${NC} ${admin_password:-$DEFAULT_ADMIN_PASSWORD}"
    echo ""
    echo -e "${WHITE}Useful Commands:${NC}"
    echo -e "  ${CYAN}./deploy.sh --status${NC}    Check service status"
    echo -e "  ${CYAN}./deploy.sh --logs${NC}      View logs"
    echo -e "  ${CYAN}./deploy.sh --update${NC}    Update and restart"
    echo -e "  ${CYAN}./deploy.sh --migrate${NC}   Run migrations"
    echo ""
    if [ "$HAS_SYSTEMD" = true ]; then
        echo -e "${WHITE}Systemd Commands:${NC}"
        echo -e "  ${CYAN}sudo systemctl status ${SERVICE_NAME}${NC}"
        echo -e "  ${CYAN}sudo systemctl restart ${SERVICE_NAME}${NC}"
        echo -e "  ${CYAN}sudo systemctl stop ${SERVICE_NAME}${NC}"
        echo ""
    fi
}

update_deployment() {
    print_step "Updating Deployment"
    
    cd "$SCRIPT_DIR"
    
    # Pull latest code if git repo
    if [ -d ".git" ]; then
        print_progress "Pulling latest changes..."
        git pull
        print_success "Code updated"
    fi
    
    # Update dependencies
    activate_venv
    install_dependencies
    
    # Run migrations
    run_migrations
    
    # Restart service
    restart_service
    
    show_info
}

# ─────────────────────────────────────────────────────────────────────────────
# Main Deployment Flow
# ─────────────────────────────────────────────────────────────────────────────

deploy() {
    print_banner
    
    # 1. Check requirements
    check_system_requirements
    
    # 2. Setup virtual environment
    setup_virtualenv
    activate_venv
    
    # 3. Install dependencies
    install_dependencies
    
    # 4. Setup environment
    setup_env_file
    
    # 5. Run migrations
    run_migrations
    
    # 6. Create admin user
    create_admin_user
    
    # 7. Setup and start service
    if [ "$SKIP_SERVICE" != true ]; then
        create_systemd_service
        start_service
    fi
    
    # 8. Show completion info
    show_info
}

# ─────────────────────────────────────────────────────────────────────────────
# Argument Parsing
# ─────────────────────────────────────────────────────────────────────────────

FRESH_INSTALL=false
SKIP_SERVICE=false
ACTION="deploy"

while [[ $# -gt 0 ]]; do
    case $1 in
        --fresh|-f)
            FRESH_INSTALL=true
            ACTION="deploy"
            shift
            ;;
        --update|-u)
            ACTION="update"
            shift
            ;;
        --migrate|-m)
            ACTION="migrate"
            shift
            ;;
        --logs|-l)
            ACTION="logs"
            shift
            ;;
        --status|-s)
            ACTION="status"
            shift
            ;;
        --stop)
            ACTION="stop"
            shift
            ;;
        --restart|-r)
            ACTION="restart"
            shift
            ;;
        --no-service)
            SKIP_SERVICE=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --fresh, -f      Complete fresh installation"
            echo "  --update, -u     Update code and restart service"
            echo "  --migrate, -m    Run migrations only"
            echo "  --logs, -l       Show recent logs (follow mode)"
            echo "  --status, -s     Check service status"
            echo "  --stop           Stop the service"
            echo "  --restart, -r    Restart the service"
            echo "  --no-service     Skip service installation"
            echo "  --help, -h       Show this help message"
            echo ""
            echo "Environment Variables:"
            echo "  DATABASE_URL     PostgreSQL connection URL"
            echo "  ADMIN_EMAIL      Default admin email"
            echo "  ADMIN_PASSWORD   Default admin password"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# ─────────────────────────────────────────────────────────────────────────────
# Execute Action
# ─────────────────────────────────────────────────────────────────────────────

case $ACTION in
    deploy)
        deploy
        ;;
    update)
        print_banner
        update_deployment
        ;;
    migrate)
        print_banner
        activate_venv
        run_migrations
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    stop)
        stop_service
        ;;
    restart)
        restart_service
        ;;
esac
