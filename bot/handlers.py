"""Telegram command and message handlers for the Remote Cursor bot."""

import asyncio
import os
import re
from pathlib import Path
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes

from bot.config import config
from bot.cursor_cli import CursorCLI, CursorCLIError

MAX_MESSAGE_LENGTH = 4096


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command - send welcome message."""
    if not _is_allowed_user(update):
        return

    default_dir = config.get_default_project_dir() or "(not set)"
    runtime_dir = config._runtime_default_project

    welcome_text = """🤖 *Remote Cursor Bot*

Control Cursor on your MacBook remotely from Telegram.

*Commands:*
/start - Show this welcome message
/prompt \`<text>\` - Send a read-only prompt
/prompt \`<project path>\` \`<text>\` - Prompt in specific project
/yolo \`<text>\` - Send a prompt with file modifications allowed
/yolo \`<project path>\` \`<text>\` - Prompt with file mods in specific project
/project - Show current default project
/project \`<path>\` - Set default project for this session
/project reset - Reset to configured default
/status - Check Cursor CLI status

*Direct Messages:*
You can also just send a prompt directly (treated as read-only).

*Notes:*
• Configured default: `{default_dir}`
• Current runtime default: `{runtime_dir}`
• Default mode: `{force_mode}`
""".format(
        default_dir=default_dir,
        runtime_dir=runtime_dir or "(configured default)",
        force_mode="read-write" if config.cursor_force_mode else "read-only"
    )

    await update.message.reply_text(welcome_text, parse_mode="Markdown")


async def prompt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /prompt command - execute read-only prompt."""
    if not _is_allowed_user(update):
        return

    project_dir, prompt_text = _extract_project_and_prompt(update.message.text, "/prompt")
    if not prompt_text:
        await update.message.reply_text(
            "Usage: `/prompt <your prompt>` or `/prompt /path/to/project <your prompt>`",
            parse_mode="Markdown"
        )
        return

    if project_dir and not _validate_project_path(update, project_dir):
        return

    await _execute_prompt(update, prompt_text, force=False, project_dir=project_dir)


async def yolo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /yolo command - execute prompt with file modifications allowed."""
    if not _is_allowed_user(update):
        return

    project_dir, prompt_text = _extract_project_and_prompt(update.message.text, "/yolo")
    if not prompt_text:
        await update.message.reply_text(
            "Usage: `/yolo <your prompt>` or `/yolo /path/to/project <your prompt>`",
            parse_mode="Markdown"
        )
        return

    if project_dir and not _validate_project_path(update, project_dir):
        return

    await _execute_prompt(update, prompt_text, force=True, project_dir=project_dir)


async def project_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /project command - show or set default project."""
    if not _is_allowed_user(update):
        return

    text = update.message.text.strip()
    parts = text.split(maxsplit=1)

    if len(parts) == 1:
        # Show current default
        current = config.get_default_project_dir()
        runtime = config._runtime_default_project

        if runtime:
            msg = f"Current default: `{runtime}`\n(Configured: `{current}`)"
        elif current:
            msg = f"Current default: `{current}`"
        else:
            msg = "No default project set. Specify a project path in your command."

        await update.message.reply_text(msg, parse_mode="Markdown")

    elif parts[1] == "reset":
        # Reset to configured default
        config.reset_default_project_dir()
        default = config.cursor_default_project_dir or "(none)"
        await update.message.reply_text(f"Reset to configured default: `{default}`", parse_mode="Markdown")

    else:
        # Set new default
        path = parts[1].strip()
        if config.set_default_project_dir(path):
            await update.message.reply_text(f"✅ Default project set to: `{path}`", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"❌ Invalid directory: `{path}`", parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command - check Cursor CLI availability."""
    if not _is_allowed_user(update):
        return

    await update.message.reply_text("Checking Cursor CLI status...")

    cli = CursorCLI()
    is_available, status_message = await cli.check_status()

    if is_available:
        await update.message.reply_text(f"✅ {status_message}")
    else:
        await update.message.reply_text(f"❌ {status_message}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle direct text messages as prompts (read-only)."""
    if not _is_allowed_user(update):
        return

    if not update.message or not update.message.text:
        return

    # Ignore commands
    if update.message.text.startswith("/"):
        return

    await _execute_prompt(update, update.message.text, force=False, project_dir=None)


async def _execute_prompt(
    update: Update,
    prompt: str,
    force: bool,
    project_dir: Optional[str]
) -> None:
    """Execute a prompt and send response back to Telegram.

    Args:
        update: Telegram update object.
        prompt: The prompt to execute.
        force: Whether to allow file modifications.
        project_dir: Optional project directory to run in.
    """
    status_msg = await update.message.reply_text(
        "⏳ Processing your prompt...",
        parse_mode=None
    )

    # Use specified project, or fall back to default
    effective_project_dir = project_dir or config.get_default_project_dir()

    if not effective_project_dir:
        await status_msg.edit_text(
            "❌ No project directory specified. Use `/project <path>` to set a default,\n"
            "or specify a project in your command: `/prompt /path/to/project <prompt>`",
            parse_mode="Markdown"
        )
        return

    cli = CursorCLI(project_dir=effective_project_dir)

    try:
        output_parts = []
        async for line in cli.execute(prompt, force=force):
            output_parts.append(line)

        full_output = "\n".join(output_parts)

        if not full_output.strip():
            full_output = "(No output)"

        await _send_long_message(update, status_msg, full_output, effective_project_dir)

    except CursorCLIError as e:
        await status_msg.edit_text(f"❌ Error: {str(e)}")

    except Exception as e:
        await status_msg.edit_text(f"❌ Unexpected error: {str(e)}")


async def _send_long_message(
    update: Update,
    status_msg,
    text: str,
    project_dir: Optional[str] = None
) -> None:
    """Send a message, splitting if it exceeds Telegram's length limit.

    Args:
        update: Telegram update object.
        status_msg: The status message to edit or reply to.
        text: The text to send.
        project_dir: The project directory used (for context).
    """
    project_info = f"\n\n📁 Project: `{project_dir}`" if project_dir else ""
    await status_msg.edit_text(f"✅ Done! Sending response...{project_info}", parse_mode="Markdown")

    if len(text) <= MAX_MESSAGE_LENGTH:
        await update.message.reply_text(text)
    else:
        # Split into chunks
        chunks = _split_message(text)
        for i, chunk in enumerate(chunks):
            if i == 0:
                await update.message.reply_text(chunk)
            else:
                await update.message.reply_text(f"[{i + 1}/{len(chunks)}]\n{chunk}")


def _split_message(text: str) -> list[str]:
    """Split a message into chunks that fit Telegram's limit.

    Args:
        text: The text to split.

    Returns:
        List of text chunks.
    """
    chunks = []
    current_chunk = ""

    for line in text.split("\n"):
        if len(current_chunk) + len(line) + 1 > MAX_MESSAGE_LENGTH - 10:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = line
        else:
            if current_chunk:
                current_chunk += "\n" + line
            else:
                current_chunk = line

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _extract_project_and_prompt(text: str, command: str) -> tuple[Optional[str], str]:
    """Extract optional project path and prompt text from a command.

    Args:
        text: The full message text.
        command: The command prefix (e.g., '/prompt').

    Returns:
        Tuple of (project_dir, prompt_text). project_dir is None if not specified.
    """
    # Pattern: /command /path/to/project <prompt>
    # The project path must start with / and be a valid-looking path
    pattern = rf"^{re.escape(command)}\s+(/\S+)\s+(.+)$"
    match = re.match(pattern, text, re.DOTALL)

    if match:
        project_path = match.group(1).strip()
        prompt = match.group(2).strip()
        return project_path, prompt

    # Fallback: just extract prompt (no project path)
    prompt = _extract_prompt_simple(text, command)
    return None, prompt


def _extract_prompt_simple(text: str, command: str) -> str:
    """Extract prompt text from a command message (simple version).

    Args:
        text: The full message text.
        command: The command prefix.

    Returns:
        The extracted prompt, or empty string if not found.
    """
    pattern = rf"^{re.escape(command)}\s*`?(.+?)`?\s*$"
    match = re.match(pattern, text, re.DOTALL)

    if match:
        return match.group(1).strip()

    pattern = rf"^{re.escape(command)}\s*(.+)$"
    match = re.match(pattern, text, re.DOTALL)

    if match:
        return match.group(1).strip()

    return ""


def _extract_prompt(text: str, command: str) -> str:
    """Extract the prompt text from a command message.

    Args:
        text: The full message text.
        command: The command prefix (e.g., '/prompt').

    Returns:
        The extracted prompt, or empty string if not found.
    """
    # Remove command and leading/trailing whitespace
    pattern = rf"^{re.escape(command)}\s*`?(.+?)`?\s*$"
    match = re.match(pattern, text, re.DOTALL)

    if match:
        return match.group(1).strip()

    # Try without backticks
    pattern = rf"^{re.escape(command)}\s*(.+)$"
    match = re.match(pattern, text, re.DOTALL)

    if match:
        return match.group(1).strip()

    return ""


def _validate_project_path(update: Update, path: str) -> bool:
    """Validate that a project path exists and is a directory.

    Args:
        update: Telegram update object.
        path: The path to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not Path(path).is_dir():
        return False

    if not os.access(path, os.R_OK):
        return False

    return True


def _is_allowed_user(update: Update) -> bool:
    """Check if the user is allowed to use the bot.

    Args:
        update: Telegram update object.

    Returns:
        True if user is allowed, False otherwise.
    """
    if not update.message or not update.message.from_user:
        return False

    user_id = str(update.message.from_user.id)
    return config.is_user_allowed(user_id)
