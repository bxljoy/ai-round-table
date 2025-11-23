"""AI CLI process managers using pexpect for I/O handling."""

import queue
import random
import threading
import time
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import pexpect
from pexpect import EOF, TIMEOUT

from .logging_config import get_logger

logger = get_logger(__name__)


class ProcessState(Enum):
    """Process state enumeration."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class AICliError(Exception):
    """Base exception for AI CLI errors."""

    pass


class AICliTimeoutError(AICliError):
    """Raised when CLI operation times out."""

    pass


class AICliProcessError(AICliError):
    """Raised when CLI process crashes or fails."""

    pass


class AICliConnectionError(AICliError):
    """Raised when unable to connect to CLI."""

    pass


def retry_with_exponential_backoff(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    exponential_base: float = 2.0,
    jitter: bool = True,
    retryable_exceptions: tuple = (AICliTimeoutError,),
):
    """
    Decorator for retrying operations with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay in seconds
        max_delay: Maximum delay in seconds
        exponential_base: Base for exponential calculation
        jitter: Whether to add random jitter to delay
        retryable_exceptions: Tuple of exceptions that trigger retry

    Returns:
        Decorated function with retry logic
    """

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs):
            retries = 0
            delay = initial_delay

            while True:
                try:
                    return func(*args, **kwargs)
                except retryable_exceptions as e:
                    retries += 1

                    if retries >= max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) exceeded for {func.__name__}: {e}"
                        )
                        raise

                    # Calculate delay with exponential backoff
                    delay = min(initial_delay * (exponential_base**retries), max_delay)

                    # Add jitter if enabled
                    if jitter:
                        delay = delay * (0.5 + random.random())

                    logger.warning(
                        f"Retry {retries}/{max_retries} for {func.__name__} after {delay:.2f}s: {e}"
                    )

                    time.sleep(delay)

        return wrapper

    return decorator


class AICliManager(ABC):
    """
    Base class for managing AI CLI processes with pexpect.

    Handles process lifecycle, I/O management, and error recovery.
    """

    def __init__(self, cli_name: str, config: Dict[str, Any], project_path: Path):
        """
        Initialize AI CLI manager.

        Args:
            cli_name: Name of the CLI (e.g., 'claude_code', 'codex', 'gemini')
            config: CLI configuration from ConfigManager
            project_path: Path to the project directory
        """
        self.cli_name = cli_name
        self.config = config
        self.project_path = Path(project_path)
        self.process: Optional[pexpect.spawn] = None
        self.state = ProcessState.STOPPED
        self.io_thread: Optional[threading.Thread] = None
        self.output_queue: queue.Queue = queue.Queue()
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

        # Get configuration
        self.timeout = config.get("timeout", 60)
        self.init_command = config.get("init_command", "")
        self.prompt_pattern = config.get("prompt_pattern", r"[\$#>] ")

    @abstractmethod
    def get_spawn_command(self) -> list[str]:
        """
        Get the command to spawn the CLI process.

        Returns:
            List of command arguments (e.g., ['claude', '--headless'])
        """
        pass

    @abstractmethod
    def get_startup_timeout(self) -> int:
        """
        Get timeout for CLI startup.

        Returns:
            Timeout in seconds
        """
        pass

    def start(self) -> bool:
        """
        Start the CLI process.

        Returns:
            True if started successfully, False otherwise

        Raises:
            AICliProcessError: If process fails to start
        """
        with self._lock:
            if self.state == ProcessState.RUNNING:
                logger.warning(f"{self.cli_name} already running")
                return True

            try:
                self.state = ProcessState.STARTING
                logger.info(f"Starting {self.cli_name}...")

                # Spawn process
                command = self.get_spawn_command()
                self.process = pexpect.spawn(
                    command[0],
                    command[1:],
                    cwd=str(self.project_path),
                    encoding="utf-8",
                    timeout=self.timeout,
                )

                # Wait for initial prompt
                startup_timeout = self.get_startup_timeout()
                self._wait_for_prompt(timeout=startup_timeout)

                # Send initialization command if configured
                if self.init_command:
                    self.send_command(self.init_command)

                # Start I/O monitoring thread
                self._start_io_thread()

                self.state = ProcessState.RUNNING
                logger.info(f"{self.cli_name} started successfully")
                return True

            except (EOF, TIMEOUT) as e:
                self.state = ProcessState.ERROR
                error_msg = f"Failed to start {self.cli_name}: {e}"
                logger.error(error_msg)
                self._cleanup()
                raise AICliProcessError(error_msg)

            except Exception as e:
                self.state = ProcessState.ERROR
                error_msg = f"Unexpected error starting {self.cli_name}: {e}"
                logger.error(error_msg)
                self._cleanup()
                raise AICliProcessError(error_msg)

    def send_command(
        self, command: str, timeout: Optional[int] = None
    ) -> Optional[str]:
        """
        Send command to CLI and wait for response.

        Args:
            command: Command to send
            timeout: Timeout in seconds (uses default if None)

        Returns:
            Command output (text before next prompt)

        Raises:
            AICliTimeoutError: If command times out
            AICliProcessError: If process is not running
        """
        if self.state != ProcessState.RUNNING:
            raise AICliProcessError(f"{self.cli_name} is not running")

        if timeout is None:
            timeout = self.timeout

        try:
            with self._lock:
                # Send command
                self.process.sendline(command)
                logger.debug(f"Sent to {self.cli_name}: {command}")

                # Wait for prompt
                self._wait_for_prompt(timeout=timeout)

                # Get output (everything before the prompt)
                output = self.process.before
                if output:
                    output = output.strip()
                    logger.debug(f"Received from {self.cli_name}: {output[:100]}...")

                return output

        except TIMEOUT:
            raise AICliTimeoutError(
                f"Command timed out after {timeout}s: {command[:50]}"
            )

        except EOF:
            self.state = ProcessState.ERROR
            raise AICliProcessError(f"{self.cli_name} process terminated unexpectedly")

    @retry_with_exponential_backoff(
        max_retries=3,
        initial_delay=1.0,
        max_delay=10.0,
        retryable_exceptions=(AICliTimeoutError,),
    )
    def send_command_with_retry(
        self, command: str, timeout: Optional[int] = None
    ) -> Optional[str]:
        """
        Send command to CLI with automatic retry on timeout.

        Uses exponential backoff strategy for retries. This is the recommended
        method for sending commands as it handles transient failures gracefully.

        Args:
            command: Command to send
            timeout: Timeout in seconds (uses default if None)

        Returns:
            Command output (text before next prompt)

        Raises:
            AICliTimeoutError: If all retries exhausted
            AICliProcessError: If process is not running
        """
        return self.send_command(command, timeout)

    def _wait_for_prompt(self, timeout: int) -> None:
        """
        Wait for CLI prompt pattern.

        Args:
            timeout: Timeout in seconds

        Raises:
            TIMEOUT: If prompt not found within timeout
            EOF: If process terminates
        """
        self.process.expect(self.prompt_pattern, timeout=timeout)

    def _start_io_thread(self) -> None:
        """Start background I/O monitoring thread."""
        self._stop_event.clear()
        self.io_thread = threading.Thread(
            target=self._io_monitor, daemon=True, name=f"{self.cli_name}-io"
        )
        self.io_thread.start()
        logger.debug(f"Started I/O thread for {self.cli_name}")

    def _io_monitor(self) -> None:
        """
        Background I/O monitoring thread.

        Continuously reads process output and puts it in queue.
        """
        logger.debug(f"I/O monitor started for {self.cli_name}")

        while not self._stop_event.is_set() and self.state == ProcessState.RUNNING:
            try:
                if self.process and self.process.isalive():
                    # Non-blocking read with small timeout
                    try:
                        output = self.process.read_nonblocking(size=1024, timeout=0.1)
                        if output:
                            self.output_queue.put(output)
                    except TIMEOUT:
                        # No output available, continue
                        pass
                else:
                    # Process died
                    logger.warning(f"{self.cli_name} process died")
                    self.state = ProcessState.ERROR
                    break

            except Exception as e:
                logger.error(f"Error in I/O monitor for {self.cli_name}: {e}")
                break

            time.sleep(0.1)

        logger.debug(f"I/O monitor stopped for {self.cli_name}")

    def stop(self, force: bool = False) -> None:
        """
        Stop the CLI process.

        Args:
            force: If True, use SIGKILL instead of SIGTERM
        """
        with self._lock:
            if self.state == ProcessState.STOPPED:
                return

            logger.info(f"Stopping {self.cli_name}...")

            # Stop I/O thread
            self._stop_event.set()
            if self.io_thread and self.io_thread.is_alive():
                self.io_thread.join(timeout=2.0)

            # Terminate process
            if self.process and self.process.isalive():
                try:
                    if force:
                        self.process.kill(9)  # SIGKILL
                    else:
                        self.process.terminate()  # SIGTERM

                    self.process.wait()
                except Exception as e:
                    logger.error(f"Error stopping {self.cli_name}: {e}")

            self._cleanup()
            self.state = ProcessState.STOPPED
            logger.info(f"{self.cli_name} stopped")

    def _cleanup(self) -> None:
        """Clean up resources."""
        if self.process:
            try:
                self.process.close(force=True)
            except:
                pass
            self.process = None

        # Clear queue
        while not self.output_queue.empty():
            try:
                self.output_queue.get_nowait()
            except queue.Empty:
                break

    def is_alive(self) -> bool:
        """
        Check if process is alive.

        Returns:
            True if process is running and alive
        """
        return (
            self.state == ProcessState.RUNNING
            and self.process is not None
            and self.process.isalive()
        )

    def restart(self, max_attempts: int = 3) -> bool:
        """
        Restart the CLI process with retry logic.

        Args:
            max_attempts: Maximum restart attempts

        Returns:
            True if restarted successfully

        Raises:
            AICliProcessError: If restart fails after max attempts
        """
        logger.info(f"Restarting {self.cli_name}...")

        for attempt in range(1, max_attempts + 1):
            try:
                logger.debug(f"Restart attempt {attempt}/{max_attempts}")

                # Stop current process
                self.stop()
                time.sleep(1)  # Brief pause before restart

                # Start new process
                if self.start():
                    logger.info(f"Successfully restarted {self.cli_name}")
                    return True

                logger.warning(
                    f"Failed to restart {self.cli_name} (attempt {attempt}/{max_attempts})"
                )

            except Exception as e:
                logger.error(
                    f"Error during restart attempt {attempt}/{max_attempts}: {e}"
                )

            # Wait with exponential backoff before next attempt
            if attempt < max_attempts:
                delay = min(2**attempt, 10)  # Cap at 10 seconds
                logger.debug(f"Waiting {delay}s before next restart attempt")
                time.sleep(delay)

        # All attempts failed
        error_msg = f"Failed to restart {self.cli_name} after {max_attempts} attempts"
        logger.error(error_msg)
        raise AICliProcessError(error_msg)

    def recover_from_crash(self) -> bool:
        """
        Attempt to recover from a crashed process.

        This method detects if the process has crashed and attempts to restart it.
        Should be called when process state is ERROR or when is_alive() returns False.

        Returns:
            True if recovery successful, False otherwise
        """
        logger.warning(f"Attempting to recover {self.cli_name} from crash")

        # Check if process is actually dead
        if self.is_alive():
            logger.info(f"{self.cli_name} is still alive, no recovery needed")
            return True

        # Mark as error state
        self.state = ProcessState.ERROR

        try:
            # Attempt restart
            return self.restart(max_attempts=2)

        except AICliProcessError as e:
            logger.error(f"Recovery failed for {self.cli_name}: {e}")
            return False

    def health_check(self) -> bool:
        """
        Perform health check on CLI process.

        Returns:
            True if process is healthy, False otherwise
        """
        if not self.is_alive():
            logger.warning(f"{self.cli_name} health check failed: process not alive")
            return False

        if self.state != ProcessState.RUNNING:
            logger.warning(
                f"{self.cli_name} health check failed: state is {self.state.value}"
            )
            return False

        # Try to send a simple command
        try:
            # Send a no-op or status command (implementation specific)
            logger.debug(f"Performing health check on {self.cli_name}")
            # This is a basic check - subclasses can override for specific health checks
            return True

        except Exception as e:
            logger.error(f"{self.cli_name} health check failed: {e}")
            return False


class ClaudeCodeManager(AICliManager):
    """Manager for Claude Code CLI."""

    def get_spawn_command(self) -> list[str]:
        """Get Claude Code spawn command."""
        return ["claude", "--headless"]

    def get_startup_timeout(self) -> int:
        """Claude Code startup timeout."""
        return 30  # Claude Code can take a while to start


class CodexManager(AICliManager):
    """Manager for Codex CLI."""

    def get_spawn_command(self) -> list[str]:
        """Get Codex spawn command."""
        return ["codex"]

    def get_startup_timeout(self) -> int:
        """Codex startup timeout."""
        return 20


class GeminiManager(AICliManager):
    """Manager for Gemini Code Assist CLI."""

    def get_spawn_command(self) -> list[str]:
        """Get Gemini spawn command."""
        return ["gemini"]

    def get_startup_timeout(self) -> int:
        """Gemini startup timeout."""
        return 20
