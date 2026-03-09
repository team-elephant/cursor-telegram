"""Grok CLI wrapper for executing prompts via the Grok (MiniMax) agent."""

import asyncio
import logging
import os
from typing import AsyncGenerator, Optional

from bot.config import config

logger = logging.getLogger(__name__)


class GrokCLIError(Exception):
    """Exception raised when Grok CLI execution fails."""
    pass


class GrokCLI:
    """Async wrapper around Grok CLI (using MiniMax)."""

    def __init__(
        self, 
        project_dir: Optional[str] = None, 
        model: Optional[str] = None,
        force: bool = False
    ):
        """Initialize the Grok CLI wrapper.

        Args:
            project_dir: Path to the project directory.
            model: Model to use (optional).
            force: Whether to allow file modifications.
        """
        self.project_dir = project_dir or config.get_default_project_dir()
        self.model = model or "MiniMax-M2.5"  # MiniMax recommended model
        self.force = force

    async def execute(
        self,
        prompt: str,
        force: bool = False,
        timeout: Optional[float] = 300.0
    ) -> AsyncGenerator[str, None]:
        """Execute a prompt using Grok CLI.

        Args:
            prompt: The prompt to send.
            force: Whether to allow file modifications.
            timeout: Maximum time in seconds to wait for completion.

        Yields:
            Output lines from CLI.

        Raises:
            GrokCLIError: If the execution fails.
        """
        use_force = force or self.force
        async for line in self._execute_cli(prompt, use_force, timeout):
            yield line

    async def _execute_cli(
        self,
        prompt: str,
        force: bool,
        timeout: float
    ) -> AsyncGenerator[str, None]:
        """Execute prompt using Grok CLI."""
        cmd = self._build_command(prompt, force)

        logger.info(f"[GROK] Sending prompt to Grok CLI (project: {self.project_dir}, force: {force})")
        logger.info(f"[GROK] Command: {' '.join(cmd)}")
        logger.info(f"[GROK] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")

        env = os.environ.copy()

        # Set Grok CLI env vars (used by @vibe-kit/grok-cli)
        if config.grok_api_key:
            env["GROK_API_KEY"] = config.grok_api_key
        if config.grok_base_url:
            env["GROK_BASE_URL"] = config.grok_base_url
        # Set model via env var to override settings file
        if self.model:
            env["GROK_MODEL"] = self.model

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
                    logger.error(f"[GROK] Grok CLI failed: {error_msg}")
                    raise GrokCLIError(f"Grok CLI failed: {error_msg}")

                output = stdout.decode()
                logger.info(f"[GROK] Received response from Grok ({len(output)} chars)")

                # Parse JSON output and extract content
                # Grok CLI outputs JSON lines like: {"role":"assistant","content":"..."}
                try:
                    import json
                    for line in output.strip().split('\n'):
                        if line.startswith('{'):
                            data = json.loads(line)
                            role = data.get('role', '')
                            content = data.get('content', '')
                            
                            # Skip tool calls and thinking blocks
                            if role == 'tool':
                                continue
                            if role == 'assistant':
                                # Remove thinking blocks (<think>...</think>)
                                import re
                                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
                                if content:
                                    yield content
                                continue
                        # Skip non-assistant lines
                except json.JSONDecodeError:
                    # If not JSON, just yield the raw output
                    for line in output.splitlines():
                        yield line

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(f"[GROK] Grok CLI timed out after {timeout} seconds")
                raise GrokCLIError(f"Grok CLI timed out after {timeout} seconds")

        except FileNotFoundError:
            logger.error("[GROK] Grok CLI not found. Please install Grok CLI first.")
            raise GrokCLIError(
                "Grok CLI not found. Please install Grok CLI and ensure 'grok' is in your PATH."
            )

    def _build_command(self, prompt: str, force: bool) -> list[str]:
        """Build the command list for Grok CLI.

        Args:
            prompt: The prompt to execute.
            force: Whether to allow file modifications.

        Returns:
            List of command arguments.
        """
        # Grok CLI command format - use --prompt (not -p) to avoid argument parsing issues
        cmd = ["grok"]
        
        if force:
            cmd.append("--force")
        
        if self.model:
            cmd.extend(["--model", self.model])
        
        # Use --prompt with = to properly pass the prompt
        cmd.append(f"--prompt={prompt}")
        return cmd

    async def check_status(self) -> tuple[bool, str]:
        """Check if Grok CLI is available.

        Returns:
            Tuple of (is_available, status_message).
        """
        try:
            cmd = ["grok", "--version"]
            env = os.environ.copy()
            if config.grok_api_key:
                env["GROK_API_KEY"] = config.grok_api_key
            if config.grok_base_url:
                env["GROK_BASE_URL"] = config.grok_base_url

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
                return True, f"Grok CLI is available. Version: {version}"
            else:
                return False, f"Grok CLI error: {stderr.decode().strip()}"

        except FileNotFoundError:
            return False, "Grok CLI not found. Please install Grok CLI."

        except asyncio.TimeoutError:
            return False, "Grok CLI check timed out"

        except Exception as e:
            return False, f"Error checking Grok CLI: {str(e)}"
