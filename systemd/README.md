# Systemd Service Configuration

This directory contains systemd service files for running the Mealie Discord Bot as a system service.

## Available Deployment Options

### 1. Native Python Service (`mealie-discord-bot.service`)

Runs the bot directly using Python without Docker.

**Features:**
- Direct Python execution
- Virtual environment isolation
- Dedicated system user (`mealie-bot`)
- Automatic restart on failure
- Security hardening (NoNewPrivileges, ProtectSystem, etc.)

**Requirements:**
- Python 3.11+
- python3-venv
- git

**Installation Location:**
- Application: `/opt/mealie-discord-bot`
- Configuration: `/etc/mealie-discord-bot/.env`
- Logs: `/var/log/mealie-discord-bot/` + journalctl

### 2. Docker Compose Service (`mealie-discord-bot-docker.service`)

Manages Docker containers via systemd.

**Features:**
- Container isolation
- Uses existing docker-compose.yml
- Graceful shutdown handling
- Automatic restart on failure

**Requirements:**
- Docker
- docker-compose

**Installation Location:**
- Application: `/opt/mealie-discord-bot`
- Configuration: `/opt/mealie-discord-bot/.env`
- Logs: Docker logs + journalctl

## Quick Installation

### Automated Installation (Recommended)

Use the provided installation script from the project root:

```bash
sudo ./install-service.sh
```

The script will:
1. Prompt you to select deployment type (native or docker)
2. Install all necessary dependencies
3. Create required users and directories
4. Copy files to installation location
5. Install and enable systemd service
6. Optionally start the service

### Manual Installation

#### Native Python Deployment

1. Create service user:
```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin mealie-bot
```

2. Create directories:
```bash
sudo mkdir -p /opt/mealie-discord-bot
sudo mkdir -p /etc/mealie-discord-bot
sudo mkdir -p /var/log/mealie-discord-bot
```

3. Copy application files:
```bash
sudo cp -r src config requirements.txt /opt/mealie-discord-bot/
```

4. Create virtual environment:
```bash
sudo python3 -m venv /opt/mealie-discord-bot/venv
sudo /opt/mealie-discord-bot/venv/bin/pip install -r /opt/mealie-discord-bot/requirements.txt
```

5. Configure environment:
```bash
sudo cp .env /etc/mealie-discord-bot/.env
sudo chmod 600 /etc/mealie-discord-bot/.env
```

6. Set permissions:
```bash
sudo chown -R mealie-bot:mealie-bot /opt/mealie-discord-bot
sudo chown -R mealie-bot:mealie-bot /etc/mealie-discord-bot
sudo chown -R mealie-bot:mealie-bot /var/log/mealie-discord-bot
```

7. Verify PYTHONPATH in service file:
The service file should include `Environment="PYTHONPATH=/opt/mealie-discord-bot"` to ensure Python can find the config module.

8. Install service:
```bash
sudo cp systemd/mealie-discord-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable mealie-discord-bot
sudo systemctl start mealie-discord-bot
```

#### Docker Compose Deployment

1. Create installation directory:
```bash
sudo mkdir -p /opt/mealie-discord-bot
```

2. Copy all project files:
```bash
sudo cp -r . /opt/mealie-discord-bot/
```

3. Configure environment:
```bash
sudo cp .env /opt/mealie-discord-bot/.env
sudo chmod 600 /opt/mealie-discord-bot/.env
```

4. Install service:
```bash
sudo cp systemd/mealie-discord-bot-docker.service /etc/systemd/system/mealie-discord-bot.service
sudo systemctl daemon-reload
sudo systemctl enable mealie-discord-bot
sudo systemctl start mealie-discord-bot
```

## Service Management

### Basic Commands

```bash
# Start the service
sudo systemctl start mealie-discord-bot

# Stop the service
sudo systemctl stop mealie-discord-bot

# Restart the service
sudo systemctl restart mealie-discord-bot

# Check service status
sudo systemctl status mealie-discord-bot

# Enable autostart at boot
sudo systemctl enable mealie-discord-bot

# Disable autostart at boot
sudo systemctl disable mealie-discord-bot
```

### Viewing Logs

**Systemd journal logs:**
```bash
# Follow live logs
sudo journalctl -u mealie-discord-bot -f

# View last 100 lines
sudo journalctl -u mealie-discord-bot -n 100

# View logs since boot
sudo journalctl -u mealie-discord-bot -b

# View logs from specific date
sudo journalctl -u mealie-discord-bot --since "2024-01-01"
```

**Native deployment - application logs:**
```bash
# View application log file
sudo tail -f /var/log/mealie-discord-bot/mealie_bot.log
```

**Docker deployment - container logs:**
```bash
# View Docker container logs
sudo docker-compose -f /opt/mealie-discord-bot/docker-compose.yml logs -f

# View specific container
sudo docker logs mealie-discord-bot -f
```

## Configuration

### Environment Variables

Configuration is stored in:
- **Native**: `/etc/mealie-discord-bot/.env`
- **Docker**: `/opt/mealie-discord-bot/.env`

After modifying the `.env` file, restart the service:

```bash
sudo systemctl restart mealie-discord-bot
```

### Service File Customization

Service files are located at `/etc/systemd/system/mealie-discord-bot.service`

After modifying service files, reload systemd:

```bash
sudo systemctl daemon-reload
sudo systemctl restart mealie-discord-bot
```

## Troubleshooting

### Service Won't Start

1. Check service status:
```bash
sudo systemctl status mealie-discord-bot
```

2. View detailed logs:
```bash
sudo journalctl -u mealie-discord-bot -n 50 --no-pager
```

3. Verify configuration:
```bash
# Native
sudo cat /etc/mealie-discord-bot/.env

# Docker
sudo cat /opt/mealie-discord-bot/.env
```

### Permission Issues (Native Deployment)

Ensure correct ownership:
```bash
sudo chown -R mealie-bot:mealie-bot /opt/mealie-discord-bot
sudo chown -R mealie-bot:mealie-bot /etc/mealie-discord-bot
sudo chown -R mealie-bot:mealie-bot /var/log/mealie-discord-bot
```

### Docker Issues

1. Check Docker service:
```bash
sudo systemctl status docker
```

2. Test docker-compose manually:
```bash
cd /opt/mealie-discord-bot
sudo docker-compose up
```

3. Verify Docker images:
```bash
sudo docker images | grep mealie
```

### Port or Network Issues

Check if required ports are available and firewall settings allow connections.

### Configuration Errors

Validate environment variables:
```bash
# Native
sudo -u mealie-bot cat /etc/mealie-discord-bot/.env

# Docker
cat /opt/mealie-discord-bot/.env
```

## Updating the Bot

### Native Deployment

1. Stop the service:
```bash
sudo systemctl stop mealie-discord-bot
```

2. Update application files:
```bash
cd /path/to/project
git pull
sudo cp -r src config /opt/mealie-discord-bot/
```

3. Update dependencies if needed:
```bash
sudo /opt/mealie-discord-bot/venv/bin/pip install -r /opt/mealie-discord-bot/requirements.txt
```

4. Start the service:
```bash
sudo systemctl start mealie-discord-bot
```

### Docker Deployment

1. Stop the service:
```bash
sudo systemctl stop mealie-discord-bot
```

2. Update application files:
```bash
cd /path/to/project
git pull
sudo cp -r . /opt/mealie-discord-bot/
```

3. Rebuild Docker image:
```bash
cd /opt/mealie-discord-bot
sudo docker-compose build
```

4. Start the service:
```bash
sudo systemctl start mealie-discord-bot
```

## Uninstalling

### Native Deployment

```bash
# Stop and disable service
sudo systemctl stop mealie-discord-bot
sudo systemctl disable mealie-discord-bot

# Remove service file
sudo rm /etc/systemd/system/mealie-discord-bot.service
sudo systemctl daemon-reload

# Remove application files
sudo rm -rf /opt/mealie-discord-bot
sudo rm -rf /etc/mealie-discord-bot
sudo rm -rf /var/log/mealie-discord-bot

# Remove service user
sudo userdel mealie-bot
```

### Docker Deployment

```bash
# Stop and disable service
sudo systemctl stop mealie-discord-bot
sudo systemctl disable mealie-discord-bot

# Remove service file
sudo rm /etc/systemd/system/mealie-discord-bot.service
sudo systemctl daemon-reload

# Stop and remove containers
cd /opt/mealie-discord-bot
sudo docker-compose down -v

# Remove application files
sudo rm -rf /opt/mealie-discord-bot
```

## LXC Container Considerations

When running in an LXC container:

1. **Privileged vs Unprivileged**: Docker deployment may require privileged container or proper ID mapping
2. **Nested virtualization**: Enable nesting if using Docker (`lxc.apparmor.profile = unconfined` and `lxc.cgroup.devices.allow = a`)
3. **Native deployment recommended**: For unprivileged containers, native Python deployment is simpler
4. **systemd support**: Ensure systemd is properly configured in the container

Example LXC config snippet for Docker support:
```
lxc.apparmor.profile = unconfined
lxc.cgroup.devices.allow = a
lxc.cap.drop =
```

## Security Notes

### Native Deployment

- Service runs as dedicated user `mealie-bot` with no login shell
- Security hardening enabled: `NoNewPrivileges`, `ProtectSystem`, `ProtectHome`
- Private temporary directory isolation
- Environment file permissions set to 600 (read/write owner only)

### Docker Deployment

- Containers run with Docker's default security settings
- No host network exposure (all networking through Docker)
- Environment file permissions set to 600

### Best Practices

1. Keep `.env` file permissions restricted (600)
2. Use strong, unique API tokens
3. Regularly update the application and dependencies
4. Monitor logs for suspicious activity
5. Use HTTPS for Mealie API connections
6. Rotate API tokens periodically

## Support

For issues related to:
- **Systemd configuration**: Check this README and systemd logs
- **Application errors**: Check main project README and application logs
- **Docker issues**: Consult Docker documentation and container logs
