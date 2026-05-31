#!/bin/bash
#
# Altex Backend - Systemd Service Installation Script
# Installs and configures the backend as a systemd service
#
# Usage:
#   ./install-service.sh              # Install service
#   ./install-service.sh --uninstall  # Uninstall service
#   ./install-service.sh --status     # Check status
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
LOG_DIR="/var/log/${PROJECT_NAME}"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ─────────────────────────────────────────────────────────────────────────────
# Color Definitions
# ─────────────────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# ─────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ─────────────────────────────────────────────────────────────────────────────

print_banner() {
    echo -e "${CYAN}"
    echo "╔═══════════════════════════════════════════════════════════════╗"
    echo "║          ${GREEN}Altex Backend - Service Installer${CYAN}                   ║"
    echo "╚═══════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

print_step() {
    echo -e "\n${BLUE}▶ $1${NC}"
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

check_root() {
    if [ "$EUID" -ne 0 ]; then
        print_error "This script requires root privileges."
        print_info "Run with: sudo $0 $@"
        exit 1
    fi
}

check_systemd() {
    if ! pidof systemd &> /dev/null; then
        print_error "systemd is not available on this system."
        print_info "This script only works on systems with systemd."
        exit 1
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# Service Installation
# ─────────────────────────────────────────────────────────────────────────────

install_service() {
    print_banner
    print_step "Installing Altex Backend Service"
    
    # Check prerequisites
    check_systemd
    
    # Check if venv exists
    if [ ! -d "$VENV_DIR" ]; then
        print_error "Virtual environment not found at ${VENV_DIR}"
        print_info "Please run deploy.sh first to set up the environment."
        exit 1
    fi
    
    # Check if .env exists
    if [ ! -f "$ENV_FILE" ]; then
        print_warning ".env file not found at ${ENV_FILE}"
        print_info "Service will start but may fail without proper configuration."
    fi
    
    # Get the actual user (even when running with sudo)
    local actual_user=${SUDO_USER:-$USER}
    local actual_group=$(id -gn "$actual_user")
    
    print_info "Service will run as user: ${actual_user}"
    
    # Create log directory
    print_step "Creating log directory"
    mkdir -p "$LOG_DIR"
    chown "${actual_user}:${actual_group}" "$LOG_DIR"
    chmod 755 "$LOG_DIR"
    print_success "Log directory created at ${LOG_DIR}"
    
    # Get port from .env or use default
    local port=$(grep "^port=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    port="${port:-8000}"
    
    # Get workers from .env or use default
    local workers=$(grep "^workers=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    workers="${workers:-4}"
    
    # Create service file
    print_step "Creating systemd service file"
    
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Altex Backend API Server
Documentation=https://github.com/altex/backend
After=network.target network-online.target postgresql.service
Wants=network-online.target postgresql.service

[Service]
Type=notify
User=${actual_user}
Group=${actual_group}
WorkingDirectory=${SCRIPT_DIR}
Environment="PATH=${VENV_DIR}/bin:/usr/local/bin:/usr/bin:/bin"
EnvironmentFile=-${ENV_FILE}

# Main process
ExecStart=${VENV_DIR}/bin/uvicorn main:app \\
    --host 0.0.0.0 \\
    --port ${port} \\
    --workers ${workers} \\
    --log-level info

# Reload signal
ExecReload=/bin/kill -HUP \$MAINPID

# Restart policy
Restart=always
RestartSec=5
TimeoutStartSec=30
TimeoutStopSec=30

# Logging
StandardOutput=append:${LOG_DIR}/app.log
StandardError=append:${LOG_DIR}/app.log

# Security hardening (comment out if causing issues)
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=read-only
ReadWritePaths=${SCRIPT_DIR} ${LOG_DIR}

# Resource limits (adjust as needed)
LimitNOFILE=65536
# MemoryMax=1G
# CPUQuota=100%

[Install]
WantedBy=multi-user.target
EOF

    print_success "Service file created at ${SERVICE_FILE}"
    
    # Reload systemd
    print_step "Reloading systemd daemon"
    systemctl daemon-reload
    print_success "Systemd reloaded"
    
    # Enable service
    print_step "Enabling service"
    systemctl enable "${SERVICE_NAME}"
    print_success "Service enabled for auto-start on boot"
    
    # Start service
    print_step "Starting service"
    systemctl start "${SERVICE_NAME}"
    sleep 2
    
    # Check status
    if systemctl is-active --quiet "${SERVICE_NAME}"; then
        print_success "Service started successfully!"
    else
        print_error "Service failed to start!"
        print_info "Check logs with: journalctl -u ${SERVICE_NAME} -n 50"
        exit 1
    fi
    
    # Show summary
    show_summary
}

# ─────────────────────────────────────────────────────────────────────────────
# Service Uninstallation
# ─────────────────────────────────────────────────────────────────────────────

uninstall_service() {
    print_banner
    print_step "Uninstalling Altex Backend Service"
    
    check_systemd
    
    # Check if service exists
    if [ ! -f "$SERVICE_FILE" ]; then
        print_warning "Service file not found. Service may not be installed."
        exit 0
    fi
    
    # Stop service
    print_step "Stopping service"
    systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
    print_success "Service stopped"
    
    # Disable service
    print_step "Disabling service"
    systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
    print_success "Service disabled"
    
    # Remove service file
    print_step "Removing service file"
    rm -f "$SERVICE_FILE"
    print_success "Service file removed"
    
    # Reload systemd
    print_step "Reloading systemd daemon"
    systemctl daemon-reload
    print_success "Systemd reloaded"
    
    # Ask about log directory
    if [ -d "$LOG_DIR" ]; then
        read -p "$(echo -e ${YELLOW}? Remove log directory ${LOG_DIR}? [y/N]: ${NC})" response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            rm -rf "$LOG_DIR"
            print_success "Log directory removed"
        fi
    fi
    
    print_success "Service uninstalled successfully!"
}

# ─────────────────────────────────────────────────────────────────────────────
# Service Status
# ─────────────────────────────────────────────────────────────────────────────

show_status() {
    print_banner
    print_step "Service Status"
    
    if [ ! -f "$SERVICE_FILE" ]; then
        print_warning "Service is not installed"
        print_info "Run: sudo $0 --install"
        exit 0
    fi
    
    echo ""
    systemctl status "${SERVICE_NAME}" --no-pager
    echo ""
    
    # Show recent logs
    print_info "Recent logs (last 20 lines):"
    echo ""
    journalctl -u "${SERVICE_NAME}" -n 20 --no-pager
}

# ─────────────────────────────────────────────────────────────────────────────
# Summary Display
# ─────────────────────────────────────────────────────────────────────────────

show_summary() {
    local port=$(grep "^port=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    port="${port:-8000}"
    
    local admin_email=$(grep "^admin_email=" "$ENV_FILE" 2>/dev/null | cut -d'=' -f2)
    admin_email="${admin_email:-admin@altex.local}"
    
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║               Service Installed Successfully!                 ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${WHITE}Service Name:${NC}     ${SERVICE_NAME}"
    echo -e "${WHITE}Admin Panel:${NC}      http://localhost:${port}/admin"
    echo -e "${WHITE}API Docs:${NC}         http://localhost:${port}/docs"
    echo -e "${WHITE}Log File:${NC}         ${LOG_DIR}/app.log"
    echo -e "${WHITE}Admin Email:${NC}      ${admin_email}"
    echo ""
    echo -e "${WHITE}Useful Commands:${NC}"
    echo -e "  ${CYAN}sudo systemctl status ${SERVICE_NAME}${NC}    Check status"
    echo -e "  ${CYAN}sudo systemctl restart ${SERVICE_NAME}${NC}   Restart service"
    echo -e "  ${CYAN}sudo systemctl stop ${SERVICE_NAME}${NC}      Stop service"
    echo -e "  ${CYAN}sudo journalctl -u ${SERVICE_NAME} -f${NC}    Follow logs"
    echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# Argument Parsing
# ─────────────────────────────────────────────────────────────────────────────

ACTION="install"

while [[ $# -gt 0 ]]; do
    case $1 in
        --install|-i)
            ACTION="install"
            shift
            ;;
        --uninstall|-u)
            ACTION="uninstall"
            shift
            ;;
        --status|-s)
            ACTION="status"
            shift
            ;;
        --help|-h)
            echo "Usage: sudo $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --install, -i     Install the systemd service (default)"
            echo "  --uninstall, -u   Uninstall the systemd service"
            echo "  --status, -s      Check service status"
            echo "  --help, -h        Show this help message"
            echo ""
            echo "Examples:"
            echo "  sudo $0 --install     # Install service"
            echo "  sudo $0 --uninstall   # Remove service"
            echo "  sudo $0 --status      # Check status"
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
    install)
        check_root "$@"
        install_service
        ;;
    uninstall)
        check_root "$@"
        uninstall_service
        ;;
    status)
        show_status
        ;;
esac
