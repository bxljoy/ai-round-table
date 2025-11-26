"""Core orchestration engine for AI Roundtable."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cli_managers import (
    AICliManager,
    AICliProcessError,
    AICliTimeoutError,
    ClaudeCodeManager,
    CodexManager,
    GeminiManager,
    ProcessState,
)
from .config import ConfigManager
from .context import ContextBuilder
from .logging_config import get_logger

logger = get_logger(__name__)


class OrchestratorState(Enum):
    """Orchestrator state enumeration."""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"


class DiscussionMode(Enum):
    """Discussion mode enumeration."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    REVIEW = "review"


@dataclass
class DiscussionResponse:
    """Response from an AI CLI during discussion."""

    cli_name: str
    response: str
    timestamp: datetime
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionState:
    """Persistent session state."""

    session_id: str
    project_path: str
    started_at: datetime
    active_clis: List[str]
    conversation_history: List[Dict[str, Any]]
    state: OrchestratorState
    metadata: Dict[str, Any] = field(default_factory=dict)


class OrchestratorError(Exception):
    """Base exception for orchestrator errors."""

    pass


class PartialStartupError(OrchestratorError):
    """Raised when some but not all CLIs fail to start."""

    def __init__(self, message: str, successful: List[str], failed: Dict[str, str]):
        super().__init__(message)
        self.successful = successful
        self.failed = failed


class MonoRepoOrchestrator:
    """
    Core orchestrator managing AI CLI lifecycle and discussion modes.

    Handles:
    - Starting/stopping multiple AI CLI processes
    - Sequential, parallel, and review discussion modes
    - Context generation and sharing between CLIs
    - Session state persistence and recovery
    - Error handling and partial failure recovery
    """

    # CLI manager classes
    CLI_MANAGERS = {
        "claude_code": ClaudeCodeManager,
        "codex": CodexManager,
        "gemini": GeminiManager,
    }

    def __init__(
        self,
        project_path: Path,
        config: Optional[ConfigManager] = None,
        session_id: Optional[str] = None,
    ):
        """
        Initialize MonoRepoOrchestrator.

        Args:
            project_path: Path to project directory
            config: ConfigManager instance (creates new if None)
            session_id: Optional session ID for recovery
        """
        self.project_path = Path(project_path)
        self.config = config or ConfigManager()
        self.context_builder = ContextBuilder(self.project_path, self.config.config)

        # CLI managers
        self.ai_managers: Dict[str, AICliManager] = {}

        # State management
        self.state = OrchestratorState.STOPPED
        self.session_id = session_id or self._generate_session_id()
        self.session_state = SessionState(
            session_id=self.session_id,
            project_path=str(self.project_path),
            started_at=datetime.now(),
            active_clis=[],
            conversation_history=[],
            state=self.state,
        )

        # Thread safety
        self._lock = threading.Lock()

        # Session directory
        self.session_dir = Path.home() / ".ai-roundtable" / "sessions" / self.session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def _generate_session_id(self) -> str:
        """Generate unique session ID."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"session_{timestamp}"

    def start_all_clis(self, reinit: bool = False) -> Dict[str, bool]:
        """
        Start all configured AI CLI processes.

        Args:
            reinit: Force regeneration of config files

        Returns:
            Dictionary mapping CLI names to success status

        Raises:
            PartialStartupError: If some CLIs fail to start
        """
        with self._lock:
            if self.state == OrchestratorState.RUNNING:
                logger.warning("Orchestrator already running")
                return {name: True for name in self.ai_managers.keys()}

            try:
                self.state = OrchestratorState.STARTING
                logger.info(f"Initializing AI Roundtable for {self.project_path}")

                # Generate context files if needed
                if reinit or not self._context_files_exist():
                    logger.info("Generating context files...")
                    self._generate_context_files()

                # Analyze project structure
                logger.info("Analyzing project structure...")
                self.context_builder.analyze_project()

                # Initialize each CLI manager (verifies CLI availability)
                results = {}
                successful = []
                failed = {}

                for cli_name, manager_class in self.CLI_MANAGERS.items():
                    try:
                        # Get CLI-specific configuration
                        cli_config = self.config.get_cli_settings(cli_name)

                        # Check if CLI is enabled
                        if not cli_config.get("enabled", True):
                            logger.info(f"Skipping {cli_name} (disabled in config)")
                            results[cli_name] = False
                            continue

                        # Create and verify manager (non-interactive mode)
                        logger.info(f"Checking {cli_name}...")
                        manager = manager_class(
                            cli_name=cli_name,
                            config=cli_config,
                            project_path=self.project_path,
                        )

                        success = manager.start()
                        results[cli_name] = success

                        if success:
                            self.ai_managers[cli_name] = manager
                            successful.append(cli_name)
                            logger.info(f"✓ {cli_name} available")
                        else:
                            failed[cli_name] = "Not available"
                            logger.error(f"✗ {cli_name} not available")

                    except KeyError:
                        # CLI not configured
                        logger.warning(f"CLI '{cli_name}' not found in configuration, skipping")
                        results[cli_name] = False
                        failed[cli_name] = "Not configured"

                    except (AICliProcessError, AICliTimeoutError) as e:
                        logger.error(f"Error checking {cli_name}: {e}")
                        results[cli_name] = False
                        failed[cli_name] = str(e)

                    except Exception as e:
                        logger.error(f"Unexpected error checking {cli_name}: {e}")
                        results[cli_name] = False
                        failed[cli_name] = f"Unexpected error: {e}"

                # Update state
                if successful:
                    self.state = OrchestratorState.RUNNING
                    self.session_state.active_clis = successful
                    self.session_state.state = self.state
                    self._save_session_state()

                    if failed:
                        logger.warning(
                            f"Orchestrator ready with {len(successful)}/{len(self.CLI_MANAGERS)} CLIs "
                            f"({len(failed)} unavailable: {', '.join(failed.keys())})"
                        )
                    else:
                        logger.info(
                            f"Orchestrator ready with {len(successful)}/{len(self.CLI_MANAGERS)} CLIs"
                        )
                else:
                    self.state = OrchestratorState.ERROR
                    logger.error("No CLIs available")
                    raise OrchestratorError("All enabled CLIs are unavailable")

                return results

            except Exception as e:
                self.state = OrchestratorState.ERROR
                logger.error(f"Failed to start orchestrator: {e}")
                raise OrchestratorError(f"Orchestrator startup failed: {e}")

    def _context_files_exist(self) -> bool:
        """Check if context files already exist."""
        context_files = [
            self.project_path / "CLAUDE.md",
            self.project_path / "CODEX.md",
            self.project_path / "GEMINI.md",
        ]
        return all(f.exists() for f in context_files)

    def _generate_context_files(self) -> None:
        """Generate CLAUDE.md, CODEX.md, GEMINI.md for each AI CLI."""
        # Ensure project structure is analyzed
        if not self.context_builder.structure:
            self.context_builder.analyze_project()

        # Generate CLAUDE.md
        claude_md = self.context_builder.generate_claude_md()
        claude_path = self.project_path / "CLAUDE.md"
        claude_path.write_text(claude_md)
        logger.info(f"Generated {claude_path}")

        # Generate CODEX.md
        codex_md = self.context_builder.generate_codex_md()
        codex_path = self.project_path / "CODEX.md"
        codex_path.write_text(codex_md)
        logger.info(f"Generated {codex_path}")

        # Generate GEMINI.md
        gemini_md = self.context_builder.generate_gemini_md()
        gemini_path = self.project_path / "GEMINI.md"
        gemini_path.write_text(gemini_md)
        logger.info(f"Generated {gemini_path}")

    def sequential_discussion(
        self, question: str, cli_order: Optional[List[str]] = None
    ) -> List[DiscussionResponse]:
        """
        Run sequential discussion mode.

        Each AI receives the question plus all previous responses.

        Args:
            question: Question to ask
            cli_order: Optional custom CLI order (defaults to Claude → Codex → Gemini)

        Returns:
            List of responses in order

        Raises:
            OrchestratorError: If orchestrator not running
        """
        if self.state != OrchestratorState.RUNNING:
            raise OrchestratorError("Orchestrator not running")

        # Default order: Claude → Codex → Gemini
        if cli_order is None:
            cli_order = ["claude_code", "codex", "gemini"]

        # Filter to only active CLIs
        cli_order = [cli for cli in cli_order if cli in self.ai_managers]

        logger.info(f"Starting sequential discussion with order: {cli_order}")
        responses = []
        context = question

        for cli_name in cli_order:
            manager = self.ai_managers.get(cli_name)
            if not manager or not manager.is_alive():
                logger.warning(f"Skipping {cli_name} (not available)")
                responses.append(
                    DiscussionResponse(
                        cli_name=cli_name,
                        response="",
                        timestamp=datetime.now(),
                        error=f"{cli_name} not available",
                    )
                )
                continue

            try:
                logger.info(f"Sending to {cli_name}...")
                response = manager.send_command(context)  # Uses configured timeout

                discussion_response = DiscussionResponse(
                    cli_name=cli_name, response=response, timestamp=datetime.now()
                )
                responses.append(discussion_response)

                # Add response to context for next CLI
                context = f"{context}\n\n{cli_name} response:\n{response}"

                logger.info(f"✓ Received response from {cli_name}")

            except (AICliTimeoutError, AICliProcessError) as e:
                logger.error(f"Error from {cli_name}: {e}")
                responses.append(
                    DiscussionResponse(
                        cli_name=cli_name,
                        response="",
                        timestamp=datetime.now(),
                        error=str(e),
                    )
                )

        # Save to conversation history
        self._add_to_history("sequential", question, responses)

        return responses

    def parallel_discussion(
        self, question: str, timeout: int = 300
    ) -> List[DiscussionResponse]:
        """
        Run parallel discussion mode.

        All AIs receive the question simultaneously.

        Args:
            question: Question to ask all AIs
            timeout: Timeout per CLI in seconds

        Returns:
            List of responses (order may vary)

        Raises:
            OrchestratorError: If orchestrator not running
        """
        if self.state != OrchestratorState.RUNNING:
            raise OrchestratorError("Orchestrator not running")

        logger.info(f"Starting parallel discussion with {len(self.ai_managers)} CLIs")
        responses = []

        def query_cli(cli_name: str, manager: AICliManager) -> DiscussionResponse:
            """Query a single CLI (for parallel execution)."""
            if not manager.is_alive():
                return DiscussionResponse(
                    cli_name=cli_name,
                    response="",
                    timestamp=datetime.now(),
                    error=f"{cli_name} not available",
                )

            try:
                logger.info(f"Sending to {cli_name}...")
                response = manager.send_command(question, timeout=timeout)
                logger.info(f"✓ Received response from {cli_name}")

                return DiscussionResponse(
                    cli_name=cli_name, response=response, timestamp=datetime.now()
                )

            except (AICliTimeoutError, AICliProcessError) as e:
                logger.error(f"Error from {cli_name}: {e}")
                return DiscussionResponse(
                    cli_name=cli_name,
                    response="",
                    timestamp=datetime.now(),
                    error=str(e),
                )

        # Use ThreadPoolExecutor for parallel execution
        with ThreadPoolExecutor(max_workers=len(self.ai_managers)) as executor:
            # Submit all queries
            future_to_cli = {
                executor.submit(query_cli, cli_name, manager): cli_name
                for cli_name, manager in self.ai_managers.items()
            }

            # Collect results as they complete
            for future in as_completed(future_to_cli):
                cli_name = future_to_cli[future]
                try:
                    response = future.result()
                    responses.append(response)
                except Exception as e:
                    logger.error(f"Exception from {cli_name}: {e}")
                    responses.append(
                        DiscussionResponse(
                            cli_name=cli_name,
                            response="",
                            timestamp=datetime.now(),
                            error=f"Exception: {e}",
                        )
                    )

        # Save to conversation history
        self._add_to_history("parallel", question, responses)

        return responses

    def review_mode(
        self,
        task: str,
        proposer: str = "claude_code",
        reviewer: str = "codex",
        iterations: int = 1,
    ) -> Dict[str, List[DiscussionResponse]]:
        """
        Run review mode discussion.

        One AI proposes a solution, another reviews it.

        Args:
            task: Task description
            proposer: Name of proposing CLI (default: claude_code)
            reviewer: Name of reviewing CLI (default: codex)
            iterations: Number of review iterations

        Returns:
            Dictionary with 'proposals' and 'reviews' lists

        Raises:
            OrchestratorError: If orchestrator not running or CLIs not available
        """
        if self.state != OrchestratorState.RUNNING:
            raise OrchestratorError("Orchestrator not running")

        if proposer not in self.ai_managers:
            raise OrchestratorError(f"Proposer CLI '{proposer}' not available")

        if reviewer not in self.ai_managers:
            raise OrchestratorError(f"Reviewer CLI '{reviewer}' not available")

        logger.info(f"Starting review mode: {proposer} → {reviewer} ({iterations} iterations)")

        proposals = []
        reviews = []

        current_task = task

        for i in range(iterations):
            logger.info(f"Review iteration {i + 1}/{iterations}")

            # Get proposal
            try:
                proposer_mgr = self.ai_managers[proposer]
                logger.info(f"Getting proposal from {proposer}...")
                proposal_response = proposer_mgr.send_command(current_task, timeout=300)

                proposal = DiscussionResponse(
                    cli_name=proposer,
                    response=proposal_response,
                    timestamp=datetime.now(),
                    metadata={"iteration": i + 1, "role": "proposer"},
                )
                proposals.append(proposal)
                logger.info(f"✓ Received proposal from {proposer}")

            except (AICliTimeoutError, AICliProcessError) as e:
                logger.error(f"Error getting proposal from {proposer}: {e}")
                proposals.append(
                    DiscussionResponse(
                        cli_name=proposer,
                        response="",
                        timestamp=datetime.now(),
                        error=str(e),
                        metadata={"iteration": i + 1, "role": "proposer"},
                    )
                )
                break

            # Get review
            try:
                reviewer_mgr = self.ai_managers[reviewer]
                review_prompt = f"Review this proposal:\n\n{proposal_response}"
                logger.info(f"Getting review from {reviewer}...")
                review_response = reviewer_mgr.send_command(review_prompt, timeout=300)

                review = DiscussionResponse(
                    cli_name=reviewer,
                    response=review_response,
                    timestamp=datetime.now(),
                    metadata={"iteration": i + 1, "role": "reviewer"},
                )
                reviews.append(review)
                logger.info(f"✓ Received review from {reviewer}")

                # Update task for next iteration
                if i < iterations - 1:
                    current_task = f"{task}\n\nPrevious proposal:\n{proposal_response}\n\nReview feedback:\n{review_response}"

            except (AICliTimeoutError, AICliProcessError) as e:
                logger.error(f"Error getting review from {reviewer}: {e}")
                reviews.append(
                    DiscussionResponse(
                        cli_name=reviewer,
                        response="",
                        timestamp=datetime.now(),
                        error=str(e),
                        metadata={"iteration": i + 1, "role": "reviewer"},
                    )
                )
                break

        # Save to conversation history
        self._add_to_history(
            "review", task, proposals + reviews, metadata={"proposer": proposer, "reviewer": reviewer}
        )

        return {"proposals": proposals, "reviews": reviews}

    def stop_all_clis(self, force: bool = False) -> None:
        """
        Stop all AI CLI processes gracefully.

        Args:
            force: If True, force kill processes
        """
        with self._lock:
            if self.state == OrchestratorState.STOPPED:
                logger.debug("Orchestrator already stopped")
                return

            logger.debug(f"Closing {len(self.ai_managers)} CLI sessions...")

            # Close each CLI session
            for cli_name, manager in list(self.ai_managers.items()):
                try:
                    manager.stop(force=force)
                except Exception as e:
                    logger.error(f"Error closing {cli_name}: {e}")

            # Clear managers
            self.ai_managers.clear()

            # Update state
            self.state = OrchestratorState.STOPPED
            self.session_state.active_clis = []
            self.session_state.state = self.state
            self._save_session_state()

            logger.debug("Session ended")

    def pause(self) -> None:
        """Pause the orchestrator without stopping CLIs."""
        with self._lock:
            if self.state == OrchestratorState.RUNNING:
                self.state = OrchestratorState.PAUSED
                self.session_state.state = self.state
                self._save_session_state()
                logger.info("Orchestrator paused")

    def resume(self) -> None:
        """Resume a paused orchestrator."""
        with self._lock:
            if self.state == OrchestratorState.PAUSED:
                # Check all CLIs are still alive
                dead_clis = [
                    name for name, mgr in self.ai_managers.items() if not mgr.is_alive()
                ]

                if dead_clis:
                    logger.warning(f"Some CLIs died during pause: {dead_clis}")
                    # Attempt to restart dead CLIs
                    for cli_name in dead_clis:
                        try:
                            logger.info(f"Restarting {cli_name}...")
                            self.ai_managers[cli_name].restart()
                        except Exception as e:
                            logger.error(f"Failed to restart {cli_name}: {e}")

                self.state = OrchestratorState.RUNNING
                self.session_state.state = self.state
                self._save_session_state()
                logger.info("Orchestrator resumed")

    def _add_to_history(
        self,
        mode: str,
        question: str,
        responses: List[DiscussionResponse],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add discussion to conversation history."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "question": question,
            "responses": [
                {
                    "cli_name": r.cli_name,
                    "response": r.response,
                    "timestamp": r.timestamp.isoformat(),
                    "error": r.error,
                    "metadata": r.metadata,
                }
                for r in responses
            ],
            "metadata": metadata or {},
        }

        self.session_state.conversation_history.append(entry)

        # Save state after each discussion
        self._save_session_state()

    def _save_session_state(self) -> None:
        """Save session state to disk."""
        try:
            state_file = self.session_dir / "state.json"

            state_data = {
                "session_id": self.session_state.session_id,
                "project_path": self.session_state.project_path,
                "started_at": self.session_state.started_at.isoformat(),
                "active_clis": self.session_state.active_clis,
                "conversation_history": self.session_state.conversation_history,
                "state": self.session_state.state.value,
                "metadata": self.session_state.metadata,
            }

            with open(state_file, "w") as f:
                json.dump(state_data, f, indent=2)

            logger.debug(f"Session state saved to {state_file}")

        except Exception as e:
            logger.error(f"Failed to save session state: {e}")

    def load_session_state(self, session_id: str) -> bool:
        """
        Load session state from disk.

        Args:
            session_id: Session ID to load

        Returns:
            True if loaded successfully
        """
        try:
            session_dir = Path.home() / ".ai-roundtable" / "sessions" / session_id
            state_file = session_dir / "state.json"

            if not state_file.exists():
                logger.error(f"Session state file not found: {state_file}")
                return False

            with open(state_file, "r") as f:
                state_data = json.load(f)

            # Restore state
            self.session_id = state_data["session_id"]
            self.session_state = SessionState(
                session_id=state_data["session_id"],
                project_path=state_data["project_path"],
                started_at=datetime.fromisoformat(state_data["started_at"]),
                active_clis=state_data["active_clis"],
                conversation_history=state_data["conversation_history"],
                state=OrchestratorState(state_data["state"]),
                metadata=state_data.get("metadata", {}),
            )

            logger.info(f"Session state loaded from {state_file}")
            return True

        except Exception as e:
            logger.error(f"Failed to load session state: {e}")
            return False

    def get_active_clis(self) -> List[str]:
        """Get list of active CLI names."""
        return [name for name, mgr in self.ai_managers.items() if mgr.is_alive()]

    def get_session_summary(self) -> Dict[str, Any]:
        """Get summary of current session."""
        return {
            "session_id": self.session_id,
            "state": self.state.value,
            "project_path": str(self.project_path),
            "started_at": self.session_state.started_at.isoformat(),
            "active_clis": self.get_active_clis(),
            "total_discussions": len(self.session_state.conversation_history),
            "session_dir": str(self.session_dir),
        }
