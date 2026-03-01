"""Configuration module for the Remote Cursor Telegram Bot."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


class Config:
    """Configuration class that loads and validates environment variables."""

    def __init__(self, env_file: Optional[str] = None):
        """Initialize configuration by loading from .env file.

        Args:
            env_file: Path to .env file. Defaults to .env in project root.
        """
        if env_file is None:
            env_file = os.path.join(os.path.dirname(__file__), "..", ".env")

        load_dotenv(env_file)

        self.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.telegram_allowed_user_id = os.getenv("TELEGRAM_ALLOWED_USER_ID", "")
        self.cursor_api_key = os.getenv("CURSOR_API_KEY", "")
        # Support both new and old config keys
        self.cursor_default_project_dir = os.getenv(
            "CURSOR_DEFAULT_PROJECT_DIR",
            os.getenv("CURSOR_PROJECT_DIR", "")
        )
        self.cursor_force_mode = os.getenv("CURSOR_FORCE_MODE", "false").lower() == "true"

        # Runtime default project (can be changed with /project command)
        self._runtime_default_project: Optional[str] = None

    def get_default_project_dir(self) -> Optional[str]:
        """Get the effective default project directory.

        Returns:
            The runtime default if set, otherwise the configured default.
        """
        return self._runtime_default_project or self.cursor_default_project_dir

    def set_default_project_dir(self, path: str) -> bool:
        """Set the runtime default project directory.

        Args:
            path: Path to set as default.

        Returns:
            True if path is valid, False otherwise.
        """
        if Path(path).is_dir():
            self._runtime_default_project = path
            return True
        return False

    def reset_default_project_dir(self) -> None:
        """Reset runtime default to use configured default."""
        self._runtime_default_project = None

    def validate(self) -> list[str]:
        """Validate required configuration fields.

        Returns:
            List of validation error messages. Empty if valid.
        """
        errors = []

        if not self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN is required")

        if not self.telegram_allowed_user_id:
            errors.append("TELEGRAM_ALLOWED_USER_ID is required")
        elif not self.telegram_allowed_user_id.isdigit():
            errors.append("TELEGRAM_ALLOWED_USER_ID must be a numeric string")

        if not self.cursor_api_key:
            errors.append("CURSOR_API_KEY is required")

        # Only validate default project if it's set and runtime default is not set
        default_dir = self.get_default_project_dir()
        if default_dir and not Path(default_dir).is_dir():
            errors.append(f"CURSOR_DEFAULT_PROJECT_DIR '{default_dir}' is not a valid directory")

        return errors

    def is_user_allowed(self, user_id: str) -> bool:
        """Check if a Telegram user is allowed to use the bot.

        Args:
            user_id: The Telegram user ID to check.

        Returns:
            True if user is allowed, False otherwise.
        """
        return str(user_id) == str(self.telegram_allowed_user_id)

    def get_cursor_command_base(self) -> list[str]:
        """Get the base command for Cursor CLI.

        Returns:
            List of command arguments.
        """
        cmd = ["agent", "-p"]
        if self.cursor_force_mode:
            cmd.append("--force")
        cmd.extend(["--output-format", "text"])
        return cmd


config = Config()
