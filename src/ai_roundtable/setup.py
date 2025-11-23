"""Setup and dependency checking for AI Roundtable."""

import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple
from rich.console import Console
from rich.table import Table

console = Console()


class DependencyChecker:
    """Check for required AI CLI dependencies."""

    REQUIRED_CLIS = {
        "claude-code": {
            "command": "claude",
            "description": "Claude Code CLI",
            "install_url": "https://docs.anthropic.com/claude-code",
        },
        "codex": {
            "command": "codex",
            "description": "OpenAI Codex CLI",
            "install_url": "https://github.com/openai/codex",
        },
        "gemini": {
            "command": "gemini",
            "description": "Google Gemini Code Assist",
            "install_url": "https://cloud.google.com/gemini",
        },
    }

    def check_cli_available(self, cli_name: str) -> Tuple[bool, str]:
        """
        Check if a CLI tool is available in PATH.

        Args:
            cli_name: Name of the CLI command to check

        Returns:
            Tuple of (is_available, version_or_error)
        """
        cli_info = self.REQUIRED_CLIS.get(cli_name)
        if not cli_info:
            return False, f"Unknown CLI: {cli_name}"

        command = cli_info["command"]

        # Check if command exists in PATH
        if not shutil.which(command):
            return False, "Not found in PATH"

        # Try to get version
        try:
            result = subprocess.run(
                [command, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            version = result.stdout.strip() or result.stderr.strip()
            return True, version
        except subprocess.TimeoutExpired:
            return True, "Found (version check timeout)"
        except Exception as e:
            return True, f"Found (version check failed: {e})"

    def check_all_dependencies(self) -> Dict[str, Tuple[bool, str]]:
        """
        Check all required CLI dependencies.

        Returns:
            Dictionary mapping CLI names to (is_available, version_or_error) tuples
        """
        results = {}
        for cli_name in self.REQUIRED_CLIS:
            results[cli_name] = self.check_cli_available(cli_name)
        return results

    def display_dependency_status(self, check_only: bool = False) -> bool:
        """
        Display dependency status in a formatted table.

        Args:
            check_only: If True, only check without prompting for installation

        Returns:
            True if all dependencies are satisfied, False otherwise
        """
        console.print("\n[bold cyan]🔍 Checking AI CLI Dependencies[/]\n")

        results = self.check_all_dependencies()

        # Create status table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("CLI Tool", style="cyan", width=20)
        table.add_column("Status", width=15)
        table.add_column("Version / Error", width=40)

        all_satisfied = True
        for cli_name, (is_available, version_info) in results.items():
            cli_info = self.REQUIRED_CLIS[cli_name]
            if is_available:
                status = "[green]✓ Available[/]"
            else:
                status = "[red]✗ Missing[/]"
                all_satisfied = False

            table.add_row(cli_info["description"], status, version_info)

        console.print(table)
        console.print()

        if all_satisfied:
            console.print("[bold green]✓ All required dependencies are satisfied![/]\n")
        else:
            console.print(
                "[bold yellow]⚠️  Some dependencies are missing. Install them to use AI Roundtable.[/]\n"
            )
            if not check_only:
                self.show_installation_instructions(results)

        return all_satisfied

    def show_installation_instructions(self, results: Dict[str, Tuple[bool, str]]):
        """Show installation instructions for missing dependencies."""
        console.print("[bold]Installation Instructions:[/]\n")

        for cli_name, (is_available, _) in results.items():
            if not is_available:
                cli_info = self.REQUIRED_CLIS[cli_name]
                console.print(f"[yellow]• {cli_info['description']}:[/]")
                console.print(f"  {cli_info['install_url']}\n")


def initialize_config_directory() -> Path:
    """
    Initialize the AI Roundtable configuration directory.

    Returns:
        Path to the config directory
    """
    config_dir = Path.home() / ".ai-roundtable"
    config_dir.mkdir(parents=True, exist_ok=True)

    # Create subdirectories
    (config_dir / "sessions").mkdir(exist_ok=True)
    (config_dir / "logs").mkdir(exist_ok=True)

    console.print(f"[green]✓ Configuration directory initialized: {config_dir}[/]")

    # Create default config if it doesn't exist
    config_file = config_dir / "config.yaml"
    if not config_file.exists():
        default_config = """# AI Roundtable Configuration

# Available AI CLIs (will be auto-detected)
clis:
  claude-code:
    enabled: true
    command: claude
  codex:
    enabled: true
    command: codex
  gemini:
    enabled: true
    command: gemini

# Default discussion mode
default_mode: all  # Options: all, seq, review

# Session settings
session:
  auto_save: true
  log_level: info
"""
        config_file.write_text(default_config)
        console.print(f"[green]✓ Default configuration created: {config_file}[/]")

    return config_dir


def run_setup(check_deps_only: bool = False) -> bool:
    """
    Run the setup process.

    Args:
        check_deps_only: If True, only check dependencies without full setup

    Returns:
        True if setup succeeded (or if only checking and all deps satisfied)
    """
    checker = DependencyChecker()

    # Check dependencies
    all_deps_satisfied = checker.display_dependency_status(check_only=check_deps_only)

    if check_deps_only:
        return all_deps_satisfied

    # Initialize config directory
    console.print()
    config_dir = initialize_config_directory()

    # Final summary
    console.print("\n[bold green]✓ AI Roundtable setup complete![/]\n")

    if all_deps_satisfied:
        console.print("[dim]You can now use:[/]")
        console.print("  [cyan]airt start[/]  - Start an orchestrated session")
        console.print("  [cyan]airt ask \"question\"[/]  - Quick question mode")
    else:
        console.print(
            "[yellow]⚠️  Install missing dependencies before using AI Roundtable[/]"
        )

    return all_deps_satisfied
