"""Logging configuration with Rich handler support."""

import logging
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler
from rich.traceback import install

# Install rich traceback handler
install(show_locals=True, max_frames=10)


class LoggingConfig:
    """
    Centralized logging configuration for AI Roundtable.

    Features:
    - Rich console formatting with colors and tracebacks
    - File logging with rotation
    - Configurable log levels
    - Module-specific logger configuration
    """

    _initialized = False
    _log_dir: Optional[Path] = None
    _console: Optional[Console] = None

    @classmethod
    def setup(
        cls,
        log_level: str = "INFO",
        log_dir: Optional[Path] = None,
        console: Optional[Console] = None,
        enable_file_logging: bool = True,
    ) -> None:
        """
        Set up logging for the application.

        Args:
            log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_dir: Directory for log files (defaults to ~/.ai-roundtable/logs)
            console: Rich console instance (creates new if None)
            enable_file_logging: Whether to enable file logging
        """
        if cls._initialized:
            return

        # Set up log directory
        if log_dir is None:
            log_dir = Path.home() / ".ai-roundtable" / "logs"

        cls._log_dir = log_dir
        cls._log_dir.mkdir(parents=True, exist_ok=True)

        # Set up console
        if console is None:
            console = Console(stderr=True)
        cls._console = console

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level.upper()))

        # Remove existing handlers
        root_logger.handlers.clear()

        # Add Rich console handler
        console_handler = RichHandler(
            console=console,
            show_time=True,
            show_path=True,
            rich_tracebacks=True,
            tracebacks_show_locals=True,
            markup=True,
        )
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(
            logging.Formatter(
                "%(message)s",
                datefmt="[%X]",
            )
        )
        root_logger.addHandler(console_handler)

        # Add file handler if enabled
        if enable_file_logging:
            file_handler = cls._create_file_handler(log_level)
            root_logger.addHandler(file_handler)

        # Configure third-party loggers to reduce noise
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("pexpect").setLevel(logging.WARNING)

        cls._initialized = True
        root_logger.info("Logging configured successfully")

    @classmethod
    def _create_file_handler(cls, log_level: str) -> logging.FileHandler:
        """
        Create a file handler with rotation.

        Args:
            log_level: Logging level

        Returns:
            Configured file handler
        """
        from logging.handlers import RotatingFileHandler

        log_file = cls._log_dir / "ai_roundtable.log"

        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=10 * 1024 * 1024,  # 10MB
            backupCount=5,
        )
        file_handler.setLevel(getattr(logging, log_level.upper()))
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )

        return file_handler

    @classmethod
    def get_logger(cls, name: str) -> logging.Logger:
        """
        Get a configured logger instance.

        Args:
            name: Logger name (usually __name__)

        Returns:
            Configured logger
        """
        if not cls._initialized:
            cls.setup()

        return logging.getLogger(name)

    @classmethod
    def set_level(cls, log_level: str) -> None:
        """
        Change the logging level for all handlers.

        Args:
            log_level: New logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        """
        level = getattr(logging, log_level.upper())

        root_logger = logging.getLogger()
        root_logger.setLevel(level)

        for handler in root_logger.handlers:
            handler.setLevel(level)

    @classmethod
    def get_log_dir(cls) -> Optional[Path]:
        """Get the log directory path."""
        return cls._log_dir


def get_logger(name: str) -> logging.Logger:
    """
    Convenience function to get a logger.

    Args:
        name: Logger name (usually __name__)

    Returns:
        Configured logger
    """
    return LoggingConfig.get_logger(name)
