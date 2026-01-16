#!/usr/bin/env python3
"""
Mealie Discord Import Bot
A Discord bot that imports recipes from links to Mealie
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from bot.discord_bot import MealieBot
from config.settings import Settings

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
log_file = os.getenv('LOG_FILE', '/var/log/mealie-discord-bot/mealie_bot.log')
log_dir = os.path.dirname(log_file)

# Create log directory if it doesn't exist (for Docker/development)
if log_dir and not os.path.exists(log_dir):
    try:
        os.makedirs(log_dir, exist_ok=True)
    except OSError:
        # If we can't create the directory, fall back to current directory
        log_file = 'mealie_bot.log'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_file)
    ]
)

logger = logging.getLogger(__name__)


async def main():
    """Main entry point for the Mealie Discord bot"""
    try:
        # Load settings
        settings = Settings()

        # Create and run bot
        bot = MealieBot(settings)
        await bot.start(settings.discord_token)

    except KeyboardInterrupt:
        logger.info("Bot shutdown requested by user")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
