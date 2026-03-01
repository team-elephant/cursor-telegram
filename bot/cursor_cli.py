"""Cursor CLI wrapper for executing prompts via the headless agent."""

import asyncio
import os
from typing import AsyncGenerator, Optional

from bot.config import config


class CursorCLIError(Exception):
    """Exception raised when Cursor CLI execution fails."""
    pass


class CursorCLI:
    """Async wrapper around Cursor's headless CLI (agent -p)."""

    def __init__(self, project_dir: Optional[str] = None):
        """Initialize the Cursor CLI wrapper.

        Args:
            project_dir: Path to the project directory. Defaults to config value.
        """
        self.project_dir = project_dir or config.get_default_project_dir()
        self.api_key = config.cursor_api_key

    async def execute(
        self,
        prompt: str,
        force: bool = False,
        timeout: Optional[float] = 300.0
    ) -> AsyncGenerator[str, None]:
        """Execute a prompt using Cursor's headless CLI.

        Args:
            prompt: The prompt to send to Cursor.
            force: Whether to allow file modifications.
            timeout: Maximum time in seconds to wait for completion.

        Yields:
            Output lines from the Cursor CLI.

        Raises:
            CursorCLIError: If the CLI execution fails.
        """
        cmd = self._build_command(prompt, force)

        env = os.environ.copy()
        env["CURSOR_API_KEY"] = self.api_key
        # Add ~/.local/bin to PATH for agent
        local_bin = os.path.expanduser("~/.local/bin")
        env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
        # Skip workspace trust prompt
        env["CURSOR_SKIP_TRUST"] = "true"

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.project_dir,
                env=env
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout
                )

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    raise CursorCLIError(f"Cursor CLI failed: {error_msg}")

                output = stdout.decode()
                for line in output.splitlines():
                    yield line

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                raise CursorCLIError(f"Cursor CLI timed out after {timeout} seconds")

        except FileNotFoundError:
            raise CursorCLIError(
                "Cursor CLI not found. Make sure Cursor is installed and 'agent' is in your PATH."
            )

    def _build_command(self, prompt: str, force: bool) -> list[str]:
        """Build the command list for Cursor CLI.

        Args:
            prompt: The prompt to execute.
            force: Whether to allow file modifications.

        Returns:
            List of command arguments.
        """
        cmd = ["agent", "-p", "--trust", "--output-format", "text"]
        if force:
            cmd.append("--force")
        cmd.append(prompt)
        return cmd

    async def check_status(self) -> tuple[bool, str]:
        """Check if Cursor CLI is available and authenticated.

        Returns:
            Tuple of (is_available, status_message).
        """
        try:
            cmd = ["agent", "--version"]
            env = os.environ.copy()
            env["CURSOR_API_KEY"] = self.api_key

            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=10.0
            )

            if process.returncode == 0:
                version = stdout.decode().strip()
                return True, f"Cursor CLI is available. Version: {version}"
            else:
                return False, f"Cursor CLI error: {stderr.decode().strip()}"

        except FileNotFoundError:
            return False, "Cursor CLI not found. Is Cursor installed?"

        except asyncio.TimeoutError:
            return False, "Cursor CLI check timed out"

        except Exception as e:
            return False, f"Error checking Cursor CLI: {str(e)}"
