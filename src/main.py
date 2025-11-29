#!/usr/bin/env python3
"""
Mealie Discord Import Bot
A Discord bot that imports recipes from links to Mealie
"""

import asyncio
import logging
import sys
from pathlib import Path

from bot.discord_bot import MealieBot
from config.settings import Settings

# Add src to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('mealie_bot.log')
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
