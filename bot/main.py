"""Main entry point for the Remote Cursor Telegram Bot."""

import asyncio
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.config import config
from bot import handlers

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Run after application initialization."""
    bot = application.bot
    me = await bot.get_me()
    logger.info(f"Bot started: @{me.username} (ID: {me.id})")


async def post_shutdown(application: Application) -> None:
    """Run after application shutdown."""
    logger.info("Bot stopped gracefully")


def main() -> None:
    """Main function to start the bot."""
    # Validate configuration
    errors = config.validate()
    if errors:
        logger.error("Configuration errors:")
        for error in errors:
            logger.error(f"  - {error}")
        logger.error("\nPlease fix these issues in your .env file and try again.")
        return

    logger.info("Starting Remote Cursor Telegram Bot...")

    # Build application
    application = (
        Application.builder()
        .token(config.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Register handlers
    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("prompt", handlers.prompt_command))
    application.add_handler(CommandHandler("yolo", handlers.yolo_command))
    application.add_handler(CommandHandler("project", handlers.project_command))
    application.add_handler(CommandHandler("status", handlers.status_command))
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handlers.handle_message
        )
    )

    logger.info("Handlers registered. Starting polling...")

    # Start polling
    application.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
