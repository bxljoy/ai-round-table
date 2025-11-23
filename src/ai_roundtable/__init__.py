"""AI Roundtable - Orchestrate multiple AI CLIs for collaborative development."""

from .config import ConfigManager
from .logging_config import LoggingConfig, get_logger
from .orchestrator import MonoRepoOrchestrator, OrchestratorError, PartialStartupError
from .session_manager import SessionManager, SessionManagerError

__version__ = "0.1.0"

__all__ = [
    "ConfigManager",
    "LoggingConfig",
    "get_logger",
    "MonoRepoOrchestrator",
    "OrchestratorError",
    "PartialStartupError",
    "SessionManager",
    "SessionManagerError",
]
