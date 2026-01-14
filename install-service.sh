#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Configuration
SERVICE_USER="mealie-bot"
INSTALL_DIR="/opt/mealie-discord-bot"
CONFIG_DIR="/etc/mealie-discord-bot"
LOG_DIR="/var/log/mealie-discord-bot"

echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Mealie Discord Bot - Service Installer${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""

# Check if running as root
if [[ $EUID -ne 0 ]]; then
   echo -e "${RED}Error: This script must be run as root (use sudo)${NC}"
   exit 1
fi

# Deployment type selection
echo "Select deployment type:"
echo "1) Native Python (runs directly without Docker)"
echo "2) Docker Compose (manages Docker containers via systemd)"
echo ""
read -p "Enter choice [1-2]: " deployment_choice

case $deployment_choice in
    1)
        DEPLOYMENT_TYPE="native"
        SERVICE_FILE="mealie-discord-bot.service"
        ;;
    2)
        DEPLOYMENT_TYPE="docker"
        SERVICE_FILE="mealie-discord-bot-docker.service"
        ;;
    *)
        echo -e "${RED}Invalid choice. Exiting.${NC}"
        exit 1
        ;;
esac

echo ""
echo -e "${YELLOW}Selected: $DEPLOYMENT_TYPE deployment${NC}"
echo ""

# Installation based on deployment type
if [ "$DEPLOYMENT_TYPE" = "native" ]; then
    echo -e "${GREEN}=== Native Python Installation ===${NC}"
    
    # Check dependencies
    echo "Checking dependencies..."
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}Error: python3 is not installed${NC}"
        exit 1
    fi
    
    if ! command -v git &> /dev/null; then
        echo -e "${RED}Error: git is not installed${NC}"
        exit 1
    fi
    
    # Create service user
    echo "Creating service user '$SERVICE_USER'..."
    if ! id "$SERVICE_USER" &>/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
        echo -e "${GREEN}✓ User created${NC}"
    else
        echo -e "${YELLOW}User already exists${NC}"
    fi
    
    # Create directories
    echo "Creating directories..."
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$CONFIG_DIR"
    mkdir -p "$LOG_DIR"
    
    # Copy application files
    echo "Copying application files to $INSTALL_DIR..."
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    
    cp -r "$SCRIPT_DIR/src" "$INSTALL_DIR/"
    cp -r "$SCRIPT_DIR/config" "$INSTALL_DIR/"
    cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"
    
    # Create virtual environment
    echo "Creating Python virtual environment..."
    python3 -m venv "$INSTALL_DIR/venv"
    
    # Install dependencies
    echo "Installing Python dependencies..."
    "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
    "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
    
    # Setup environment file
    if [ -f "$SCRIPT_DIR/.env" ]; then
        echo "Copying .env file to $CONFIG_DIR..."
        cp "$SCRIPT_DIR/.env" "$CONFIG_DIR/.env"
        chmod 600 "$CONFIG_DIR/.env"
    else
        echo -e "${YELLOW}Warning: .env file not found in project directory${NC}"
        echo "Creating template .env file at $CONFIG_DIR/.env"
        cat > "$CONFIG_DIR/.env" << 'EOF'
# Discord Bot Configuration
DISCORD_TOKEN=your_discord_bot_token_here

# Mealie Configuration
MEALIE_BASE_URL=https://your-mealie-instance.com
MEALIE_API_TOKEN=your_mealie_api_token_here

# AI Configuration (Optional)
OPENAI_API_KEY=your_openai_api_key_here
AI_ENABLED=true
AI_MODEL=gpt-3.5-turbo

# Bot Settings
BOT_LOG_LEVEL=INFO
BOT_TIMEOUT=30

# Recipe Settings
DEFAULT_RECIPE_TAGS=Discord Import,Verify
REQUIRE_INSTRUCTIONS=true
REQUIRE_INGREDIENTS=true
EOF
        chmod 600 "$CONFIG_DIR/.env"
        echo -e "${YELLOW}Please edit $CONFIG_DIR/.env with your configuration${NC}"
    fi
    
    # Set permissions
    echo "Setting permissions..."
    chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$CONFIG_DIR"
    chown -R "$SERVICE_USER:$SERVICE_USER" "$LOG_DIR"
    
    echo -e "${GREEN}✓ Native installation completed${NC}"
    
elif [ "$DEPLOYMENT_TYPE" = "docker" ]; then
    echo -e "${GREEN}=== Docker Compose Installation ===${NC}"
    
    # Check dependencies
    echo "Checking dependencies..."
    if ! command -v docker &> /dev/null; then
        echo -e "${RED}Error: docker is not installed${NC}"
        exit 1
    fi
    
    if ! command -v docker-compose &> /dev/null; then
        echo -e "${RED}Error: docker-compose is not installed${NC}"
        exit 1
    fi
    
    # Create installation directory
    echo "Creating installation directory..."
    mkdir -p "$INSTALL_DIR"
    
    # Copy project files
    echo "Copying project files to $INSTALL_DIR..."
    SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
    
    cp -r "$SCRIPT_DIR/"* "$INSTALL_DIR/"
    
    # Setup environment file
    if [ ! -f "$INSTALL_DIR/.env" ]; then
        echo -e "${YELLOW}Warning: .env file not found${NC}"
        echo "Creating template .env file at $INSTALL_DIR/.env"
        cat > "$INSTALL_DIR/.env" << 'EOF'
# Discord Bot Configuration
DISCORD_TOKEN=your_discord_bot_token_here

# Mealie Configuration
MEALIE_BASE_URL=https://your-mealie-instance.com
MEALIE_API_TOKEN=your_mealie_api_token_here

# AI Configuration (Optional)
OPENAI_API_KEY=your_openai_api_key_here
AI_ENABLED=true
AI_MODEL=gpt-3.5-turbo

# Bot Settings
BOT_LOG_LEVEL=INFO
BOT_TIMEOUT=30

# Recipe Settings
DEFAULT_RECIPE_TAGS=Discord Import,Verify
REQUIRE_INSTRUCTIONS=true
REQUIRE_INGREDIENTS=true
EOF
        chmod 600 "$INSTALL_DIR/.env"
        echo -e "${YELLOW}Please edit $INSTALL_DIR/.env with your configuration${NC}"
    fi
    
    echo -e "${GREEN}✓ Docker installation completed${NC}"
fi

# Install systemd service
echo ""
echo "Installing systemd service..."
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cp "$SCRIPT_DIR/systemd/$SERVICE_FILE" "/etc/systemd/system/mealie-discord-bot.service"

# Reload systemd
echo "Reloading systemd daemon..."
systemctl daemon-reload

# Enable service
echo "Enabling service..."
systemctl enable mealie-discord-bot.service

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}Installation Complete!${NC}"
echo -e "${GREEN}=========================================${NC}"
echo ""
echo "Service management commands:"
echo "  Start:   sudo systemctl start mealie-discord-bot"
echo "  Stop:    sudo systemctl stop mealie-discord-bot"
echo "  Restart: sudo systemctl restart mealie-discord-bot"
echo "  Status:  sudo systemctl status mealie-discord-bot"
echo "  Logs:    sudo journalctl -u mealie-discord-bot -f"
echo ""

if [ "$DEPLOYMENT_TYPE" = "docker" ]; then
    echo "Docker logs:"
    echo "  sudo docker-compose -f $INSTALL_DIR/docker-compose.yml logs -f"
    echo ""
fi

read -p "Do you want to start the service now? [y/N]: " start_now
if [[ $start_now =~ ^[Yy]$ ]]; then
    echo "Starting service..."
    systemctl start mealie-discord-bot.service
    sleep 2
    echo ""
    echo "Service status:"
    systemctl status mealie-discord-bot.service --no-pager
fi

echo ""
echo -e "${GREEN}Done!${NC}"
