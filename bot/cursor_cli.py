"""Cursor CLI wrapper for executing prompts via the headless agent or custom LLM."""

import asyncio
import json
import logging
import os
from typing import AsyncGenerator, Optional

from bot.config import config

logger = logging.getLogger(__name__)


class CursorCLIError(Exception):
    """Exception raised when Cursor CLI execution fails."""
    pass


class CursorCLI:
    """Async wrapper around Cursor's headless CLI (agent -p) or custom LLM."""

    def __init__(
        self, 
        project_dir: Optional[str] = None, 
        model: Optional[str] = None,
        provider: str = "cursor",
        llm_id: Optional[str] = None
    ):
        """Initialize the Cursor CLI wrapper.

        Args:
            project_dir: Path to the project directory. Defaults to config value.
            model: Model to use (e.g., 'sonnet-4.6' for Cursor, 'gpt-4o' for OpenAI).
            provider: Provider type (cursor, openai, anthropic, custom).
            llm_id: Custom LLM ID if provider is custom.
        """
        self.project_dir = project_dir or config.get_default_project_dir()
        self.api_key = config.cursor_api_key
        self.model = model
        self.provider = provider
        self.llm_id = llm_id

    async def execute(
        self,
        prompt: str,
        force: bool = False,
        timeout: Optional[float] = 300.0
    ) -> AsyncGenerator[str, None]:
        """Execute a prompt using Cursor or custom LLM.

        Args:
            prompt: The prompt to send.
            force: Whether to allow file modifications (only for Cursor).
            timeout: Maximum time in seconds to wait for completion.

        Yields:
            Output lines from the CLI or LLM.

        Raises:
            CursorCLIError: If the execution fails.
        """
        if self.provider == "cursor":
            async for line in self._execute_cursor(prompt, force, timeout):
                yield line
        elif self.provider in ("openai", "anthropic", "grok", "custom"):
            async for line in self._execute_custom_llm(prompt, timeout):
                yield line
        else:
            raise CursorCLIError(f"Unknown provider: {self.provider}")

    async def _execute_cursor(
        self,
        prompt: str,
        force: bool,
        timeout: float
    ) -> AsyncGenerator[str, None]:
        """Execute prompt using Cursor CLI."""
        cmd = self._build_command(prompt, force)
        
        logger.info(f"[CURSOR] Sending prompt to Cursor (project: {self.project_dir}, force: {force}, model: {self.model})")
        logger.info(f"[CURSOR] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")

        env = os.environ.copy()
        env["CURSOR_API_KEY"] = self.api_key
        local_bin = os.path.expanduser("~/.local/bin")
        env["PATH"] = f"{local_bin}:{env.get('PATH', '')}"
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
                    logger.error(f"[CURSOR] Cursor CLI failed: {error_msg}")
                    raise CursorCLIError(f"Cursor CLI failed: {error_msg}")

                output = stdout.decode()
                logger.info(f"[CURSOR] Received response from Cursor ({len(output)} chars)")
                
                for line in output.splitlines():
                    yield line

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(f"[CURSOR] Cursor CLI timed out after {timeout} seconds")
                raise CursorCLIError(f"Cursor CLI timed out after {timeout} seconds")

        except FileNotFoundError:
            logger.error("[CURSOR] Cursor CLI not found. Make sure Cursor is installed.")
            raise CursorCLIError(
                "Cursor CLI not found. Make sure Cursor is installed and 'agent' is in your PATH."
            )

    async def _execute_custom_llm(
        self,
        prompt: str,
        timeout: float
    ) -> AsyncGenerator[str, None]:
        """Execute prompt using custom LLM API."""
        from bot import llms as llms_module
        
        # Get LLM configuration
        if self.provider == "custom" and self.llm_id:
            llm = llms_module.get_llm(self.llm_id)
            if not llm:
                raise CursorCLIError("Custom LLM not found")
            api_key = llm['api_key']
            endpoint = llm['endpoint']
        else:
            # Look for API key and endpoint in environment
            prefix = self.provider.upper()
            api_key = os.getenv(f"{prefix}_API_KEY")
            endpoint = os.getenv(f"{prefix}_ENDPOINT")
            
            if not api_key:
                raise CursorCLIError(f"API key not found for {prefix}. Add {prefix}_API_KEY to .env")
            if not endpoint:
                raise CursorCLIError(f"Endpoint not found for {prefix}. Add {prefix}_ENDPOINT to .env")

        logger.info(f"[LLM] Sending prompt to {self.provider} (model: {self.model})")
        
        # Build request based on provider
        headers = {
            "Content-Type": "application/json"
        }
        
        if self.provider == "openai":
            headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True
            }
        elif self.provider == "anthropic":
            headers["x-api-key"] = api_key
            headers["anthropic-version"] = "2023-06-01"
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 4096,
                "stream": True
            }
        else:
            # Custom/OpenAI-compatible
            headers["Authorization"] = f"Bearer {api_key}"
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": True
            }

        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"[LLM] API error: {response.status} - {error_text}")
                        raise CursorCLIError(f"API error: {response.status} - {error_text}")
                    
                    # Stream response
                    async for line in response.content:
                        if line:
                            decoded = line.decode('utf-8')
                            if decoded.startswith('data: '):
                                data = decoded[6:]
                                if data.strip() == '[DONE]':
                                    break
                                try:
                                    parsed = json.loads(data)
                                    if self.provider == "openai" or self.provider == "custom":
                                        if 'choices' in parsed:
                                            for choice in parsed['choices']:
                                                if 'delta' in choice and 'content' in choice['delta']:
                                                    content = choice['delta']['content']
                                                    yield content
                                    elif self.provider == "anthropic":
                                        if 'delta' in parsed and 'text' in parsed['delta']:
                                            yield parsed['delta']['text']
                                except json.JSONDecodeError:
                                    pass
                    
                    logger.info(f"[LLM] Response complete")

        except ImportError:
            raise CursorCLIError("aiohttp not installed. Run: pip install aiohttp")
        except aiohttp.ClientError as e:
            raise CursorCLIError(f"Connection error: {str(e)}")

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
        if self.model:
            cmd.extend(["--model", self.model])
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
