"""Codex CLI wrapper for executing prompts via the OpenAI Codex agent."""

import asyncio
import logging
import os
from typing import AsyncGenerator, Optional

from bot.config import config

logger = logging.getLogger(__name__)


class CodexCLIError(Exception):
    """Exception raised when Codex CLI execution fails."""
    pass


class CodexCLI:
    """Async wrapper around Codex CLI (codex)."""

    def __init__(
        self, 
        project_dir: Optional[str] = None, 
        model: Optional[str] = None,
        force: bool = False
    ):
        """Initialize the Codex CLI wrapper.

        Args:
            project_dir: Path to the project directory.
            model: Model to use (optional).
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
        """Execute a prompt using Codex CLI.

        Args:
            prompt: The prompt to send.
            force: Whether to allow file modifications.
            timeout: Maximum time in seconds to wait for completion.

        Yields:
            Output lines from the CLI.

        Raises:
            CodexCLIError: If the execution fails.
        """
        use_force = force or self.force
        await self._execute_codex(prompt, use_force, timeout)

    async def _execute_codex(
        self,
        prompt: str,
        force: bool,
        timeout: float
    ) -> AsyncGenerator[str, None]:
        """Execute prompt using Codex CLI."""
        cmd = self._build_command(prompt, force)
        
        logger.info(f"[CODEX] Sending prompt to Codex CLI (project: {self.project_dir}, force: {force})")
        logger.info(f"[CODEX] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")

        env = os.environ.copy()
        
        # Set OpenAI API key if available
        if config.openai_api_key:
            env["OPENAI_API_KEY"] = config.openai_api_key

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
                    logger.error(f"[CODEX] Codex CLI failed: {error_msg}")
                    raise CodexCLIError(f"Codex CLI failed: {error_msg}")

                output = stdout.decode()
                logger.info(f"[CODEX] Received response from Codex ({len(output)} chars)")
                
                for line in output.splitlines():
                    yield line

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(f"[CODEX] Codex CLI timed out after {timeout} seconds")
                raise CodexCLIError(f"Codex CLI timed out after {timeout} seconds")

        except FileNotFoundError:
            logger.error("[CODEX] Codex CLI not found. Make sure Codex is installed.")
            raise CodexCLIError(
                "Codex CLI not found. Make sure Codex is installed and 'codex' is in your PATH."
            )

    def _build_command(self, prompt: str, force: bool) -> list[str]:
        """Build the command list for Codex CLI.

        Args:
            prompt: The prompt to execute.
            force: Whether to allow file modifications.

        Returns:
            List of command arguments.
        """
        # Codex CLI command format
        cmd = ["codex"]
        
        if force:
            cmd.append("--force")
        
        if self.model:
            cmd.extend(["--model", self.model])
        
        # Add prompt
        cmd.append(prompt)
        return cmd

    async def check_status(self) -> tuple[bool, str]:
        """Check if Codex CLI is available.

        Returns:
            Tuple of (is_available, status_message).
        """
        try:
            cmd = ["codex", "--version"]
            env = os.environ.copy()
            if config.openai_api_key:
                env["OPENAI_API_KEY"] = config.openai_api_key

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
                return True, f"Codex CLI is available. Version: {version}"
            else:
                return False, f"Codex CLI error: {stderr.decode().strip()}"

        except FileNotFoundError:
            return False, "Codex CLI not found. Is Codex installed?"

        except asyncio.TimeoutError:
            return False, "Codex CLI check timed out"

        except Exception as e:
            return False, f"Error checking Codex CLI: {str(e)}"
