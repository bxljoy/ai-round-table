"""Configuration management for AI Roundtable."""

import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

from .logging_config import get_logger

logger = get_logger(__name__)


# Default configuration schema matching PRD Appendix A
DEFAULT_CONFIG = {
    "version": "0.1.0",
    "default_mode": "sequential",
    "cli_settings": {
        "claude_code": {
            "enabled": True,
            "timeout": 300,  # Increased to 5 minutes for AI thinking time
            "init_command": "",
            "prompt_pattern": r">",  # Simple > prompt that works
        },
        "codex": {
            "enabled": True,  # Can start successfully, but Q&A not working (see README)
            "timeout": 120,
            "init_command": "",
            "prompt_pattern": r">",  # Simple pattern works for startup
        },
        "gemini": {
            "enabled": True,
            "timeout": 300,  # Increased to 5 minutes for AI thinking time
            "init_command": "",
            "prompt_pattern": r">",  # Simple > prompt
        },
    },
    "context": {
        "max_tokens": 100000,
        "compression_threshold": 80000,
    },
    "session": {
        "auto_save": True,
        "history_limit": 1000,
    },
}


class ConfigValidationError(Exception):
    """Raised when configuration validation fails."""

    pass


class ConfigManager:
    """
    Manages AI Roundtable configuration.

    Loads configuration from ~/.ai-roundtable/config.yaml and provides
    accessors for configuration values. Creates default config if none exists.
    """

    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize ConfigManager.

        Args:
            config_path: Path to config file. Defaults to ~/.ai-roundtable/config.yaml
        """
        if config_path is None:
            config_path = Path.home() / ".ai-roundtable" / "config.yaml"

        self.config_path = Path(config_path)
        self.config: Dict[str, Any] = self.load_config()

    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file or create default.

        Returns:
            Configuration dictionary

        Raises:
            ConfigValidationError: If config file is invalid
        """
        # Ensure config directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing config or create default
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    config = yaml.safe_load(f)

                if config is None:
                    # Empty file
                    config = DEFAULT_CONFIG.copy()
                    self.save_config(config)
                else:
                    # Merge with defaults to ensure all keys exist
                    config = self._merge_with_defaults(config)

                return config

            except yaml.YAMLError as e:
                raise ConfigValidationError(f"Invalid YAML in config file: {e}")
            except Exception as e:
                raise ConfigValidationError(f"Error loading config: {e}")
        else:
            # Create default config
            config = DEFAULT_CONFIG.copy()
            self.save_config(config)
            return config

    def _merge_with_defaults(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge user config with defaults to ensure all required keys exist.

        Args:
            config: User configuration

        Returns:
            Merged configuration with all default keys
        """
        merged = DEFAULT_CONFIG.copy()

        # Deep merge for nested dicts
        for key, value in config.items():
            if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value

        return merged

    def save_config(self, config: Optional[Dict[str, Any]] = None) -> None:
        """
        Save configuration to file with atomic write.

        Uses atomic write to prevent corruption from partial writes.

        Args:
            config: Configuration to save. If None, saves current config.

        Raises:
            ConfigValidationError: If config validation fails
        """
        if config is None:
            config = self.config
        else:
            self.config = config

        # Validate before saving
        self._validate_config(config)

        # Ensure directory exists
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: write to temp file then move
        try:
            # Create temp file in same directory to ensure same filesystem
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=self.config_path.parent,
                delete=False,
                suffix=".tmp",
            ) as tmp_file:
                yaml.safe_dump(config, tmp_file, default_flow_style=False, sort_keys=False)
                tmp_path = tmp_file.name

            # Atomic move
            os.replace(tmp_path, self.config_path)

        except Exception as e:
            # Clean up temp file if it exists
            if "tmp_path" in locals():
                try:
                    os.unlink(tmp_path)
                except:
                    pass
            raise ConfigValidationError(f"Error saving config: {e}")

    def _validate_config(self, config: Dict[str, Any]) -> None:
        """
        Validate configuration structure.

        Args:
            config: Configuration to validate

        Raises:
            ConfigValidationError: If validation fails
        """
        required_keys = ["version", "default_mode", "cli_settings", "context", "session"]

        for key in required_keys:
            if key not in config:
                raise ConfigValidationError(f"Missing required config key: {key}")

        # Validate CLI settings
        if not isinstance(config["cli_settings"], dict):
            raise ConfigValidationError("cli_settings must be a dictionary")

        for cli_name, cli_config in config["cli_settings"].items():
            if not isinstance(cli_config, dict):
                raise ConfigValidationError(
                    f"cli_settings.{cli_name} must be a dictionary"
                )

            required_cli_keys = ["enabled", "timeout", "init_command", "prompt_pattern"]
            for cli_key in required_cli_keys:
                if cli_key not in cli_config:
                    raise ConfigValidationError(
                        f"Missing required key in cli_settings.{cli_name}: {cli_key}"
                    )

        # Validate context settings
        if "max_tokens" not in config["context"]:
            raise ConfigValidationError("Missing context.max_tokens")

        if "compression_threshold" not in config["context"]:
            raise ConfigValidationError("Missing context.compression_threshold")

        # Validate session settings
        if "auto_save" not in config["session"]:
            raise ConfigValidationError("Missing session.auto_save")

    def get_cli_settings(self, cli_name: str) -> Dict[str, Any]:
        """
        Get settings for a specific CLI.

        Args:
            cli_name: Name of the CLI (e.g., 'claude_code', 'codex', 'gemini')

        Returns:
            CLI settings dictionary

        Raises:
            KeyError: If CLI not found in config
        """
        if cli_name not in self.config["cli_settings"]:
            raise KeyError(f"CLI '{cli_name}' not found in configuration")

        return self.config["cli_settings"][cli_name]

    def get_default_mode(self) -> str:
        """
        Get the default discussion mode.

        Returns:
            Default mode ('sequential', 'parallel', or 'review')
        """
        return self.config.get("default_mode", "sequential")

    def get_context_settings(self) -> Dict[str, Any]:
        """
        Get context management settings.

        Returns:
            Context settings dictionary
        """
        return self.config["context"]

    def get_session_settings(self) -> Dict[str, Any]:
        """
        Get session management settings.

        Returns:
            Session settings dictionary
        """
        return self.config["session"]

    def get_all_cli_names(self) -> list[str]:
        """
        Get list of all configured CLI names.

        Returns:
            List of CLI names
        """
        return list(self.config["cli_settings"].keys())

    def set_default_mode(self, mode: str) -> None:
        """
        Set the default discussion mode.

        Args:
            mode: Mode to set ('sequential', 'parallel', or 'review')

        Raises:
            ValueError: If mode is invalid
        """
        valid_modes = ["sequential", "parallel", "review"]
        if mode not in valid_modes:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {valid_modes}")

        self.config["default_mode"] = mode
        self.save_config()

    def update_cli_setting(self, cli_name: str, key: str, value: Any) -> None:
        """
        Update a specific CLI setting.

        Args:
            cli_name: Name of the CLI
            key: Setting key to update
            value: New value

        Raises:
            KeyError: If CLI not found
        """
        if cli_name not in self.config["cli_settings"]:
            raise KeyError(f"CLI '{cli_name}' not found in configuration")

        self.config["cli_settings"][cli_name][key] = value
        self.save_config()

    def reload(self) -> None:
        """Reload configuration from file."""
        self.config = self.load_config()
