"""Grok CLI wrapper for executing prompts via the Grok agent."""

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
    """Async wrapper around Grok CLI (grok) or xAI API."""

    def __init__(
        self, 
        project_dir: Optional[str] = None, 
        model: Optional[str] = None,
        force: bool = False,
        use_api: bool = True
    ):
        """Initialize the Grok CLI wrapper.

        Args:
            project_dir: Path to the project directory.
            model: Model to use (optional).
            force: Whether to allow file modifications.
            use_api: If True, use xAI API. If False, try CLI.
        """
        self.project_dir = project_dir or config.get_default_project_dir()
        self.model = model or "grok-2"
        self.force = force
        self.use_api = use_api

    async def execute(
        self,
        prompt: str,
        force: bool = False,
        timeout: Optional[float] = 300.0
    ) -> AsyncGenerator[str, None]:
        """Execute a prompt using Grok CLI or API.

        Args:
            prompt: The prompt to send.
            force: Whether to allow file modifications.
            timeout: Maximum time in seconds to wait for completion.

        Yields:
            Output lines from CLI/API.

        Raises:
            GrokCLIError: If the execution fails.
        """
        use_force = force or self.force
        
        if self.use_api:
            async for line in self._execute_api(prompt, timeout):
                yield line
        else:
            async for line in self._execute_cli(prompt, use_force, timeout):
                yield line

    async def _execute_api(
        self,
        prompt: str,
        timeout: float
    ) -> AsyncGenerator[str, None]:
        """Execute prompt using xAI API."""
        import aiohttp
        
        if not config.grok_api_key:
            raise GrokCLIError("GROK_API_KEY not configured. Add GROK_API_KEY to .env")
        
        endpoint = config.grok_endpoint or "https://api.x.ai/v1/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {config.grok_api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": True
        }
        
        logger.info(f"[GROK] Sending prompt to xAI API (model: {self.model})")
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    endpoint,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"[GROK] API error: {response.status} - {error_text}")
                        raise GrokCLIError(f"API error: {response.status} - {error_text}")
                    
                    # Stream response
                    async for line in response.content:
                        if line:
                            decoded = line.decode('utf-8')
                            if decoded.startswith('data: '):
                                data = decoded[6:]
                                if data.strip() == '[DONE]':
                                    break
                                try:
                                    import json
                                    parsed = json.loads(data)
                                    if 'choices' in parsed:
                                        for choice in parsed['choices']:
                                            if 'delta' in choice and 'content' in choice['delta']:
                                                yield choice['delta']['content']
                                except:
                                    pass
                    
                    logger.info("[GROK] Response complete")
                    
        except ImportError:
            raise GrokCLIError("aiohttp not installed. Run: pip install aiohttp")
        except aiohttp.ClientError as e:
            raise GrokCLIError(f"Connection error: {str(e)}")

    async def _execute_cli(
        self,
        prompt: str,
        force: bool,
        timeout: float
    ) -> AsyncGenerator[str, None]:
        """Execute prompt using Grok CLI."""
        cmd = self._build_command(prompt, force)
        
        logger.info(f"[GROK] Sending prompt to Grok CLI (project: {self.project_dir}, force: {force})")
        logger.info(f"[GROK] Prompt: {prompt[:100]}{'...' if len(prompt) > 100 else ''}")

        env = os.environ.copy()
        
        # Set xAI API key if available
        if config.grok_api_key:
            env["GROK_API_KEY"] = config.grok_api_key

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
                
                for line in output.splitlines():
                    yield line

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.error(f"[GROK] Grok CLI timed out after {timeout} seconds")
                raise GrokCLIError(f"Grok CLI timed out after {timeout} seconds")

        except FileNotFoundError:
            logger.error("[GROK] Grok CLI not found. Falling back to API.")
            # Fall back to API
            async for line in self._execute_api(prompt, timeout):
                yield line

    def _build_command(self, prompt: str, force: bool) -> list[str]:
        """Build the command list for Grok CLI.

        Args:
            prompt: The prompt to execute.
            force: Whether to allow file modifications.

        Returns:
            List of command arguments.
        """
        # Grok CLI command format (if available)
        cmd = ["grok"]
        
        if force:
            cmd.append("--force")
        
        if self.model:
            cmd.extend(["--model", self.model])
        
        cmd.append(prompt)
        return cmd

    async def check_status(self) -> tuple[bool, str]:
        """Check if Grok CLI or API is available.

        Returns:
            Tuple of (is_available, status_message).
        """
        # Try CLI first
        try:
            cmd = ["grok", "--version"]
            env = os.environ.copy()
            if config.grok_api_key:
                env["GROK_API_KEY"] = config.grok_api_key

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
                
        except Exception:
            pass
        
        # Fall back to API check
        if config.grok_api_key:
            return True, f"Grok API is configured (model: {self.model})"
        
        return False, "Grok CLI not found and API key not configured"
