"""Claude CLI wrapper for executing prompts via the Claude Code agent."""

import asyncio
import logging
import os
from typing import AsyncGenerator, Optional

from bot.config import config

logger = logging.getLogger(__name__)


class ClaudeCLIError(Exception):
    """Exception raised when Claude CLI execution fails."""
    pass


class ClaudeCLI:
    """Async wrapper around Claude's CLI (claude -p)."""

    def __init__(
        self, 
        project_dir: Optional[str] = None, 
        model: Optional[str] = None,
        force: bool = False
    ):
        """Initialize the Claude CLI wrapper.

        Args:
            project_dir: Path to the project directory.
            model: Model to use (optional, for Claude Code).
            force: Whether to allow file modifications.
        """
        self.project_dir = project_dir or config.get_default_project_dir()
        self.model = model
        self.force = force

    async def execute(
        self,
        prompt: str,
        force: bool = False,
        timeout: Optional[float] = 300.0
    ) -> AsyncGenerator[str, None]:
        """Execute a prompt using Claude CLI.

        Args:
            prompt: The prompt to send.
            force: Whether to allow file modifications.
            timeout: Maximum time in seconds to wait for completion.

        Yields:
            Output lines from the CLI.

        Raises:
            ClaudeCLIError: If the execution fails.
        """
        use_force = force or self.force
        await self._execute_claude(prompt, use_force, timeout)

    async def _execute_claude(
        self,
        prompt: str,
        force: bool,
        timeout: float
    ) -> AsyncGenerator[str, None]:
        """Execute prompt using Claude CLI."""
        cmd = self._build_command(prompt, force)
        
        logger.info(f"[CLAUDE] Sending prompt to Claude CLI (project: {self.project_dir}, force: {force})")
        logger.info(f"[CLAUDE] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")

        env = os.environ.copy()
        
        # Set Anthropic API key if available
        if config.anthropic_api_key:
            env["ANTHROPIC_API_KEY"] = config.anthropic_api_key

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
                    logger.error(f"[CLAUDE] Claude CLI failed: {error_msg}")
                    raise ClaudeCLIError(f"Claude CLI failed: {error_msg}")

                output = stdout.decode()
                logger.info(f"[CLAUDE] Received response from Claude ({len(output)} chars)")
                
                for line in output.splitlines():
                    yield line

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(f"[CLAUDE] Claude CLI timed out after {timeout} seconds")
                raise ClaudeCLIError(f"Claude CLI timed out after {timeout} seconds")

        except FileNotFoundError:
            logger.error("[CLAUDE] Claude CLI not found. Make sure Claude is installed.")
            raise ClaudeCLIError(
                "Claude CLI not found. Make sure Claude is installed and 'claude' is in your PATH."
            )

    def _build_command(self, prompt: str, force: bool) -> list[str]:
        """Build the command list for Claude CLI.

        Args:
            prompt: The prompt to execute.
            force: Whether to allow file modifications.

        Returns:
            List of command arguments.
        """
        # Try different command formats
        cmd = ["claude", "-p"]
        
        if force:
            # Claude Code uses --dangerously-skip-permissions for write mode
            cmd.append("--dangerously-skip-permissions")
        
        if self.model:
            # Specify model if provided
            cmd.extend(["--model", self.model])
        
        cmd.append(prompt)
        return cmd

    async def check_status(self) -> tuple[bool, str]:
        """Check if Claude CLI is available.

        Returns:
            Tuple of (is_available, status_message).
        """
        try:
            cmd = ["claude", "--version"]
            env = os.environ.copy()
            if config.anthropic_api_key:
                env["ANTHROPIC_API_KEY"] = config.anthropic_api_key

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
                return True, f"Claude CLI is available. Version: {version}"
            else:
                return False, f"Claude CLI error: {stderr.decode().strip()}"

        except FileNotFoundError:
            return False, "Claude CLI not found. Is Claude installed?"

        except asyncio.TimeoutError:
            return False, "Claude CLI check timed out"

        except Exception as e:
            return False, f"Error checking Claude CLI: {str(e)}"
