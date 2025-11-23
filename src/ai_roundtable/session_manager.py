"""Session management and persistence for AI Roundtable."""

import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from .logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class SessionInfo:
    """Session information data class."""

    session_id: str
    project_path: str
    created_at: str
    last_active: str
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    cli_pids: Dict[str, int] = field(default_factory=dict)
    state: str = "stopped"
    metadata: Dict[str, Any] = field(default_factory=dict)


class SessionManagerError(Exception):
    """Base exception for session manager errors."""

    pass


class SessionManager:
    """
    Manages AI Roundtable sessions across projects.

    Handles:
    - Session creation and unique ID generation
    - Session state persistence to disk
    - Multi-project session tracking
    - Active session detection via PID tracking
    - Session recovery after crashes
    - Conversation history management
    """

    def __init__(self, session_dir: Optional[Path] = None):
        """
        Initialize SessionManager.

        Args:
            session_dir: Directory for session files (defaults to ~/.ai-roundtable/sessions)
        """
        if session_dir is None:
            session_dir = Path.home() / ".ai-roundtable" / "sessions"

        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"SessionManager initialized with dir: {self.session_dir}")

    def create_session(
        self, project_path: Path, session_id: Optional[str] = None
    ) -> SessionInfo:
        """
        Create a new session for a project.

        Args:
            project_path: Path to the project
            session_id: Optional custom session ID (auto-generated if None)

        Returns:
            SessionInfo object

        Raises:
            SessionManagerError: If session creation fails
        """
        try:
            # Generate session ID if not provided
            if session_id is None:
                session_id = self._generate_session_id(project_path)

            # Create session info
            session_info = SessionInfo(
                session_id=session_id,
                project_path=str(project_path.absolute()),
                created_at=datetime.now().isoformat(),
                last_active=datetime.now().isoformat(),
                state="running",
            )

            # Save to disk
            self._save_session(session_info)

            logger.info(f"Created session {session_id} for {project_path}")
            return session_info

        except Exception as e:
            raise SessionManagerError(f"Failed to create session: {e}")

    def _generate_session_id(self, project_path: Path) -> str:
        """
        Generate unique session ID.

        Uses timestamp + project name for uniqueness.

        Args:
            project_path: Path to project

        Returns:
            Unique session ID
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = project_path.name
        return f"session_{project_name}_{timestamp}"

    def load_session(self, session_id: str) -> Optional[SessionInfo]:
        """
        Load session from disk.

        Args:
            session_id: Session ID to load

        Returns:
            SessionInfo if found, None otherwise
        """
        session_file = self.session_dir / f"{session_id}.json"

        if not session_file.exists():
            logger.warning(f"Session file not found: {session_file}")
            return None

        try:
            with open(session_file, "r") as f:
                data = json.load(f)

            session_info = SessionInfo(**data)
            logger.debug(f"Loaded session {session_id}")
            return session_info

        except Exception as e:
            logger.error(f"Failed to load session {session_id}: {e}")
            return None

    def _save_session(self, session_info: SessionInfo) -> None:
        """
        Save session to disk.

        Args:
            session_info: SessionInfo to save

        Raises:
            SessionManagerError: If save fails
        """
        session_file = self.session_dir / f"{session_info.session_id}.json"

        try:
            # Update last active timestamp
            session_info.last_active = datetime.now().isoformat()

            # Convert to dict and save
            data = asdict(session_info)

            with open(session_file, "w") as f:
                json.dump(data, f, indent=2)

            logger.debug(f"Saved session {session_info.session_id}")

        except Exception as e:
            raise SessionManagerError(f"Failed to save session: {e}")

    def update_session(
        self,
        session_id: str,
        cli_pids: Optional[Dict[str, int]] = None,
        state: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Update session with new information.

        Args:
            session_id: Session ID to update
            cli_pids: Optional CLI PIDs to update
            state: Optional state to update
            metadata: Optional metadata to merge

        Returns:
            True if updated successfully
        """
        session_info = self.load_session(session_id)
        if not session_info:
            logger.warning(f"Session {session_id} not found for update")
            return False

        # Update fields
        if cli_pids is not None:
            session_info.cli_pids = cli_pids

        if state is not None:
            session_info.state = state

        if metadata is not None:
            session_info.metadata.update(metadata)

        # Save
        try:
            self._save_session(session_info)
            return True
        except SessionManagerError as e:
            logger.error(f"Failed to update session {session_id}: {e}")
            return False

    def save_conversation(
        self, session_id: str, conversation_entry: Dict[str, Any]
    ) -> bool:
        """
        Save a conversation entry to session history.

        Args:
            session_id: Session ID
            conversation_entry: Conversation entry to save

        Returns:
            True if saved successfully
        """
        session_info = self.load_session(session_id)
        if not session_info:
            logger.warning(f"Session {session_id} not found for conversation save")
            return False

        # Add timestamp if not present
        if "timestamp" not in conversation_entry:
            conversation_entry["timestamp"] = datetime.now().isoformat()

        # Append to history
        session_info.conversation_history.append(conversation_entry)

        # Save
        try:
            self._save_session(session_info)
            logger.debug(f"Saved conversation to session {session_id}")
            return True
        except SessionManagerError as e:
            logger.error(f"Failed to save conversation: {e}")
            return False

    def list_sessions(self, active_only: bool = False) -> List[SessionInfo]:
        """
        List all sessions.

        Args:
            active_only: If True, only return sessions with running processes

        Returns:
            List of SessionInfo objects
        """
        sessions = []

        # Find all session files
        for session_file in self.session_dir.glob("*.json"):
            session_id = session_file.stem

            session_info = self.load_session(session_id)
            if not session_info:
                continue

            # Check if active if requested
            if active_only:
                if not self._is_session_active(session_info):
                    continue

            sessions.append(session_info)

        # Sort by last active (most recent first)
        sessions.sort(key=lambda s: s.last_active, reverse=True)

        return sessions

    def _is_session_active(self, session_info: SessionInfo) -> bool:
        """
        Check if session has active processes.

        Args:
            session_info: SessionInfo to check

        Returns:
            True if any CLI process is running
        """
        if not session_info.cli_pids:
            return False

        # Check if any PID is still running
        for cli_name, pid in session_info.cli_pids.items():
            try:
                process = psutil.Process(pid)
                if process.is_running():
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return False

    def get_session_by_project(self, project_path: Path) -> Optional[SessionInfo]:
        """
        Find active session for a project.

        Args:
            project_path: Path to project

        Returns:
            SessionInfo if found, None otherwise
        """
        project_str = str(project_path.absolute())

        # Search all sessions
        for session_info in self.list_sessions():
            if session_info.project_path == project_str:
                # Return most recent session for this project
                return session_info

        return None

    def cleanup_session(self, session_id: str, remove_file: bool = False) -> bool:
        """
        Clean up session.

        Args:
            session_id: Session ID to clean up
            remove_file: If True, delete the session file

        Returns:
            True if cleaned up successfully
        """
        try:
            session_info = self.load_session(session_id)
            if not session_info:
                logger.warning(f"Session {session_id} not found for cleanup")
                return False

            # Terminate any running processes
            for cli_name, pid in session_info.cli_pids.items():
                try:
                    process = psutil.Process(pid)
                    if process.is_running():
                        logger.info(f"Terminating {cli_name} (PID {pid})")
                        process.terminate()
                        # Wait for termination
                        process.wait(timeout=5)
                except (psutil.NoSuchProcess, psutil.TimeoutExpired):
                    pass
                except Exception as e:
                    logger.warning(f"Error terminating process {pid}: {e}")

            # Update state
            session_info.state = "stopped"
            session_info.cli_pids = {}
            self._save_session(session_info)

            # Remove file if requested
            if remove_file:
                session_file = self.session_dir / f"{session_id}.json"
                session_file.unlink(missing_ok=True)
                logger.info(f"Removed session file for {session_id}")

            logger.info(f"Cleaned up session {session_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to cleanup session {session_id}: {e}")
            return False

    def cleanup_stale_sessions(self, max_age_hours: int = 24) -> int:
        """
        Clean up stale sessions (no activity for max_age_hours).

        Args:
            max_age_hours: Maximum age in hours

        Returns:
            Number of sessions cleaned up
        """
        cleaned = 0
        current_time = time.time()
        max_age_seconds = max_age_hours * 3600

        for session_info in self.list_sessions():
            # Parse last active time
            try:
                last_active = datetime.fromisoformat(session_info.last_active)
                age_seconds = current_time - last_active.timestamp()

                # Check if stale
                if age_seconds > max_age_seconds:
                    # Only clean up if not active
                    if not self._is_session_active(session_info):
                        logger.info(
                            f"Cleaning up stale session {session_info.session_id} "
                            f"(age: {age_seconds / 3600:.1f} hours)"
                        )
                        self.cleanup_session(session_info.session_id, remove_file=True)
                        cleaned += 1

            except Exception as e:
                logger.warning(
                    f"Error checking session {session_info.session_id}: {e}"
                )
                continue

        return cleaned

    def get_session_summary(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Get summary of session.

        Args:
            session_id: Session ID

        Returns:
            Summary dict or None if not found
        """
        session_info = self.load_session(session_id)
        if not session_info:
            return None

        # Check active status
        is_active = self._is_session_active(session_info)

        return {
            "session_id": session_info.session_id,
            "project_path": session_info.project_path,
            "created_at": session_info.created_at,
            "last_active": session_info.last_active,
            "state": session_info.state,
            "is_active": is_active,
            "conversation_count": len(session_info.conversation_history),
            "active_clis": [
                cli
                for cli, pid in session_info.cli_pids.items()
                if self._is_pid_running(pid)
            ],
        }

    def _is_pid_running(self, pid: int) -> bool:
        """
        Check if PID is running.

        Args:
            pid: Process ID

        Returns:
            True if running
        """
        try:
            process = psutil.Process(pid)
            return process.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def recover_session(self, session_id: str) -> Optional[SessionInfo]:
        """
        Attempt to recover a crashed session.

        Args:
            session_id: Session ID to recover

        Returns:
            SessionInfo if recovered, None otherwise
        """
        session_info = self.load_session(session_id)
        if not session_info:
            logger.warning(f"Cannot recover session {session_id}: not found")
            return None

        # Remove dead PIDs
        dead_pids = []
        for cli_name, pid in session_info.cli_pids.items():
            if not self._is_pid_running(pid):
                dead_pids.append(cli_name)
                logger.info(f"Removing dead PID for {cli_name}: {pid}")

        for cli_name in dead_pids:
            del session_info.cli_pids[cli_name]

        # Update state
        if session_info.cli_pids:
            session_info.state = "running"
        else:
            session_info.state = "stopped"

        # Save recovered state
        try:
            self._save_session(session_info)
            logger.info(f"Recovered session {session_id}")
            return session_info
        except SessionManagerError as e:
            logger.error(f"Failed to save recovered session: {e}")
            return None
