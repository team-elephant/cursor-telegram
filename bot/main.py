"""Main entry point for the Remote Cursor Telegram Bot."""

import logging
import sys
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from bot.config import config
from bot import handlers
from bot import callbacks


# Suppress ALL logging from telegram, HTTP and httpx libraries BEFORE any imports
for name in ["telegram", "telegram.ext", "http", "http.client", "urllib3", "httpx", "aiohttp"]:
    logging.getLogger(name).setLevel(logging.CRITICAL)

# Configure our own logging AFTER suppressing others
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    stream=sys.stdout
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

    # Register callback handler (must be before command handlers for priority)
    application.add_handler(callbacks.get_callback_handler())

    # Register command handlers
    application.add_handler(CommandHandler("start", handlers.start_command))
    application.add_handler(CommandHandler("prompt", handlers.prompt_command))
    application.add_handler(CommandHandler("yolo", handlers.yolo_command))
    application.add_handler(CommandHandler("project", handlers.project_command))
    application.add_handler(CommandHandler("status", handlers.status_command))
    application.add_handler(CommandHandler("cancel", handlers.handle_cancel))
    
    # Group chat commands
    application.add_handler(CommandHandler("link", handlers.link_command))
    application.add_handler(CommandHandler("unlink", handlers.unlink_command))

    # Register message handler for group chats (must be after commands)
    # This handles tagged messages like @cursor, @claude, etc.
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & (filters.ChatType.GROUP | filters.ChatType.SUPERGROUP),
            handlers.handle_group_message
        )
    )

    # Register message handler for direct messages (1-on-1)
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
            handlers.handle_message
        )
    )

    logger.info("Handlers registered. Starting polling...")

    # Start polling
    application.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
