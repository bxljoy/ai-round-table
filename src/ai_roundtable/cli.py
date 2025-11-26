"""CLI entry point for AI Roundtable."""

import signal
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.status import Status

from .config import ConfigManager
from .logging_config import LoggingConfig, get_logger
from .orchestrator import (
    MonoRepoOrchestrator,
    OrchestratorError,
    PartialStartupError,
)
from .session_manager import SessionManager, SessionManagerError

console = Console()
logger = get_logger(__name__)

# Global orchestrator reference for signal handlers
_global_orchestrator: Optional[MonoRepoOrchestrator] = None


def _setup_signal_handlers(orchestrator: MonoRepoOrchestrator) -> None:
    """
    Set up signal handlers for graceful shutdown.

    Args:
        orchestrator: Orchestrator instance to clean up on shutdown
    """
    global _global_orchestrator
    _global_orchestrator = orchestrator

    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully."""
        sig_name = signal.Signals(signum).name
        logger.debug(f"Received {sig_name}")
        console.print(f"\n[yellow]Exiting...[/]")

        try:
            if _global_orchestrator:
                _global_orchestrator.stop_all_clis()
                console.print("[green]✓ Session ended[/]")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            console.print(f"[red]✗ Error: {e}[/]")
        finally:
            sys.exit(0)

    # Register handlers for SIGINT (Ctrl+C) and SIGTERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    logger.debug("Signal handlers registered")


@click.group()
@click.version_option(version="0.1.0", prog_name="airt")
@click.option("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")
def main(log_level: str):
    """AI Roundtable - Orchestrate multiple AI CLIs for collaborative development."""
    # Initialize logging
    LoggingConfig.setup(log_level=log_level, console=console)
    logger.debug(f"AI Roundtable CLI initialized with log level: {log_level}")


@main.command()
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
    help="Project directory path",
)
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
def start(project: Path, verbose: bool):
    """Start AI Roundtable interactive session."""
    # Configure logging level
    if verbose:
        LoggingConfig.set_level("DEBUG")
        logger.debug("Verbose logging enabled")

    console.print("[bold green]🎭 AI Roundtable Interactive Mode[/]")
    console.print(f"[dim]Project: {project.absolute()}[/]")
    logger.debug(f"Starting interactive session for project: {project.absolute()}")

    orchestrator = None

    try:
        # Initialize configuration
        logger.debug("Loading configuration")
        config = ConfigManager()
        console.print("[dim]✓ Configuration loaded[/]")

        # Create orchestrator
        logger.debug("Initializing orchestrator")
        orchestrator = MonoRepoOrchestrator(
            project_path=project.absolute(), config=config
        )
        console.print("[dim]✓ Orchestrator initialized[/]")

        # Set up signal handlers for graceful shutdown
        _setup_signal_handlers(orchestrator)
        logger.debug("Signal handlers configured")

        # Verify CLI availability (non-interactive mode - no long-running processes)
        console.print("\n[cyan]Checking AI CLI availability...[/]")
        logger.debug("Verifying AI CLI availability")

        try:
            results = orchestrator.start_all_clis()

            # Display availability results
            success_count = sum(1 for v in results.values() if v)
            console.print(
                f"[green]✓ {success_count}/{len(results)} CLIs available[/]"
            )
            logger.info(f"Verified {success_count}/{len(results)} CLIs available")

        except PartialStartupError as e:
            console.print(
                f"[yellow]⚠️  Partial availability: {len(e.successful)} of {len(e.successful) + len(e.failed)} CLIs[/]"
            )
            console.print("[green]Available:[/] " + ", ".join(e.successful))
            console.print("[red]Not available:[/]")
            for cli, error in e.failed.items():
                console.print(f"  - {cli}: {error}")
                logger.error(f"CLI not available {cli}: {error}")
            console.print(
                "\n[yellow]Continuing with available CLIs. Some commands may not work.[/]"
            )
            logger.warning("Continuing with partial availability")

        except OrchestratorError as e:
            console.print(f"[bold red]❌ Failed to initialize: {e}[/]")
            logger.error(f"Initialization failed: {e}", exc_info=True)
            raise click.Abort()

        # Enter interactive mode
        logger.info("Entering interactive mode")
        _interactive_loop(orchestrator)

    except KeyboardInterrupt:
        console.print("\n[yellow]⚠️  Interrupted by user[/]")
        logger.info("Interrupted by user")
        if orchestrator:
            orchestrator.stop_all_clis()
        sys.exit(0)

    except Exception as e:
        console.print(f"[bold red]❌ Unexpected error: {e}[/]")
        logger.error(f"Unexpected error in start command: {e}", exc_info=True)
        if verbose:
            console.print_exception()
        if orchestrator:
            orchestrator.stop_all_clis()
        raise click.Abort()


def _interactive_loop(orchestrator: MonoRepoOrchestrator):
    """
    Main interactive command loop.

    Args:
        orchestrator: Running MonoRepoOrchestrator instance
    """
    console.print("\n[bold cyan]═══════════════════════════════════════════════[/]")
    console.print("[bold cyan]         AI Roundtable Interactive Mode         [/]")
    console.print("[bold cyan]═══════════════════════════════════════════════[/]\n")

    # Display help
    _show_commands_help()

    console.print(f"\n[dim]Session ID: {orchestrator.session_id}[/]")
    console.print(f"[dim]Active CLIs: {', '.join(orchestrator.get_active_clis())}[/]\n")

    # Conversation history for cross-CLI context sharing
    # Each entry: {"role": "user"|"claude"|"codex"|"gemini", "content": "..."}
    conversation_history = []

    # Main loop
    while True:
        try:
            user_input = console.input("[bold cyan]💬 >[/] ").strip()

            if not user_input:
                continue

            # Parse and execute command
            _execute_command(orchestrator, user_input, conversation_history)

        except KeyboardInterrupt:
            console.print("\n[yellow]Use 'exit' to quit[/]")
            continue

        except EOFError:
            break

        except Exception as e:
            console.print(f"[bold red]❌ Error: {e}[/]")
            logger.exception("Error in interactive loop")

    # Cleanup
    console.print("\n[yellow]Exiting...[/]")
    orchestrator.stop_all_clis()
    console.print("[green]✓ Session ended[/]")


def _show_commands_help():
    """Display available commands."""
    console.print("[bold]Available Commands:[/]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="dim")

    table.add_row("@seq <question>", "Ask AIs sequentially (chained context)")
    table.add_row("@claude <message>", "Direct message to Claude Code")
    table.add_row("@codex <message>", "Direct message to Codex")
    table.add_row("@gemini <message>", "Direct message to Gemini")
    table.add_row("", "")
    table.add_row("[dim]Direct commands share conversation context across CLIs[/]", "")
    table.add_row("", "")
    table.add_row("clear", "Clear conversation history")
    table.add_row("status", "Show session status")
    table.add_row("help", "Show this help message")
    table.add_row("exit", "Exit interactive mode")

    console.print(table)


def _execute_command(orchestrator: MonoRepoOrchestrator, user_input: str, conversation_history: list):
    """
    Parse and execute user command.

    Args:
        orchestrator: MonoRepoOrchestrator instance
        user_input: User input string
        conversation_history: List of conversation entries for cross-CLI context
    """
    # Exit command
    if user_input.lower() in ["exit", "quit", "q"]:
        raise EOFError()

    # Help command
    elif user_input.lower() in ["help", "?"]:
        _show_commands_help()

    # Status command
    elif user_input.lower() == "status":
        _show_status(orchestrator)

    # Clear conversation history
    elif user_input.lower() == "clear":
        conversation_history.clear()
        console.print("[green]✓ Conversation history cleared[/]")

    # @seq - sequential discussion
    elif user_input.startswith("@seq "):
        question = user_input[5:].strip()
        if not question:
            console.print("[red]Error: Please provide a question[/]")
            return

        # Add user question to history
        conversation_history.append({"role": "user", "content": question})

        # Run sequential discussion with animated spinner
        active_clis = orchestrator.get_active_clis()
        console.print(f"[dim]Starting sequential discussion with {', '.join(active_clis)}...[/]\n")

        with Status("[cyan]Starting discussion...[/]", console=console, spinner="dots") as status:
            import threading
            import time

            # Track current CLI being processed
            current_cli = {"name": "claude_code", "idx": 0}
            stop_animation = threading.Event()

            cli_colors = {"claude_code": "cyan", "codex": "green", "gemini": "magenta"}
            cli_messages = {
                "claude_code": ["Claude is thinking...", "Claude is exploring...", "Claude is analyzing..."],
                "codex": ["Codex is thinking...", "Codex is reasoning...", "Codex is processing..."],
                "gemini": ["Gemini is thinking...", "Gemini is contemplating...", "Gemini is working..."],
            }

            def animate_status():
                msg_idx = 0
                while not stop_animation.is_set():
                    cli = current_cli["name"]
                    color = cli_colors.get(cli, "white")
                    messages = cli_messages.get(cli, ["Thinking..."])
                    msg = messages[msg_idx % len(messages)]
                    status.update(f"[{color}]{msg}[/]")
                    msg_idx += 1
                    time.sleep(1.5)

            animation_thread = threading.Thread(target=animate_status, daemon=True)
            animation_thread.start()

            try:
                responses = orchestrator.sequential_discussion(question)
            finally:
                stop_animation.set()
                animation_thread.join(timeout=0.5)

        _display_responses(responses)

        # Add all AI responses to history
        for response in responses:
            if response.response and not response.error:
                conversation_history.append({
                    "role": response.cli_name,
                    "content": response.response
                })

    # Direct AI commands
    elif user_input.startswith("@claude "):
        _send_direct_message(orchestrator, "claude_code", user_input[8:].strip(), conversation_history)

    elif user_input.startswith("@codex "):
        _send_direct_message(orchestrator, "codex", user_input[7:].strip(), conversation_history)

    elif user_input.startswith("@gemini "):
        _send_direct_message(orchestrator, "gemini", user_input[8:].strip(), conversation_history)

    # Unknown command
    else:
        console.print(
            "[yellow]Unknown command. Type 'help' for available commands.[/]"
        )


def _estimate_tokens(text: str) -> int:
    """Estimate token count (~4 characters per token)."""
    return len(text) // 4


def _get_history_tokens(conversation_history: list) -> int:
    """Calculate estimated tokens in conversation history."""
    total_chars = sum(len(entry.get("content", "")) for entry in conversation_history)
    return total_chars // 4


def _summarize_history(orchestrator: MonoRepoOrchestrator, conversation_history: list) -> Optional[str]:
    """
    Ask Claude to summarize the conversation history.

    Returns:
        Summary string, or None if summarization failed
    """
    manager = orchestrator.ai_managers.get("claude_code")
    if not manager or not manager.is_alive():
        return None

    # Build history text for summarization
    history_text = []
    for entry in conversation_history:
        role = entry["role"]
        content = entry["content"]
        if role == "user":
            history_text.append(f"[User]: {content}")
        else:
            history_text.append(f"[{role}]: {content}")

    summary_prompt = f"""Please provide a concise summary of this conversation, preserving:
- Key decisions and conclusions
- Important technical details
- Action items or next steps

Conversation:
{chr(10).join(history_text)}

Provide only the summary, no preamble."""

    try:
        summary = manager.send_command(summary_prompt)
        return summary
    except Exception as e:
        logger.error(f"Failed to summarize history: {e}")
        return None


def _send_direct_message(
    orchestrator: MonoRepoOrchestrator, cli_name: str, message: str, conversation_history: list
):
    """
    Send direct message to a specific AI CLI with conversation context.

    Args:
        orchestrator: MonoRepoOrchestrator instance
        cli_name: Name of CLI (claude_code, codex, gemini)
        message: Message to send
        conversation_history: List of conversation entries for cross-CLI context
    """
    if not message:
        console.print("[red]Error: Please provide a message[/]")
        return

    manager = orchestrator.ai_managers.get(cli_name)
    if not manager:
        console.print(f"[red]Error: {cli_name} not available[/]")
        return

    if not manager.is_alive():
        console.print(f"[red]Error: {cli_name} is not running[/]")
        return

    # Get token limit from config (default 80000)
    context_settings = orchestrator.config.get_context_settings()
    token_limit = context_settings.get("compression_threshold", 80000)

    # Check if history needs summarization
    history_tokens = _get_history_tokens(conversation_history)
    history_entries = len(conversation_history)

    # Show current history stats
    token_percentage = (history_tokens / token_limit) * 100 if token_limit > 0 else 0
    if token_percentage > 90:
        token_color = "red"
    elif token_percentage > 70:
        token_color = "yellow"
    else:
        token_color = "dim"
    console.print(f"[{token_color}]📊 History: {history_entries} entries, ~{history_tokens:,} tokens ({token_percentage:.1f}% of {token_limit:,} limit)[/]")

    if history_tokens > token_limit:
        console.print(f"\n[yellow]{'='*50}[/]")
        console.print(f"[yellow]⚠️  AUTO-COMPACTING TRIGGERED[/]")
        console.print(f"[yellow]{'='*50}[/]")
        console.print(f"[dim]History tokens ({history_tokens:,}) exceeded limit ({token_limit:,})[/]")
        console.print(f"[dim]Asking Claude to summarize {history_entries} conversation entries...[/]\n")

        summary = _summarize_history(orchestrator, conversation_history)
        if summary:
            summary_tokens = _estimate_tokens(summary)
            # Replace history with summary
            conversation_history.clear()
            conversation_history.append({"role": "summary", "content": summary})
            console.print(f"[green]✓ History compacted successfully![/]")
            console.print(f"[green]  Before: {history_tokens:,} tokens ({history_entries} entries)[/]")
            console.print(f"[green]  After:  {summary_tokens:,} tokens (1 summary entry)[/]")
            console.print(f"[green]  Saved:  {history_tokens - summary_tokens:,} tokens ({((history_tokens - summary_tokens) / history_tokens * 100):.1f}% reduction)[/]")
        else:
            console.print("[yellow]⚠️  Summarization failed, falling back to truncation[/]")
            # Fallback: keep last 10 entries
            recent = conversation_history[-10:]
            old_tokens = history_tokens
            conversation_history.clear()
            conversation_history.extend(recent)
            new_tokens = _get_history_tokens(conversation_history)
            console.print(f"[yellow]  Kept last 10 entries: {old_tokens:,} → {new_tokens:,} tokens[/]")

        console.print(f"[yellow]{'='*50}[/]\n")

    try:
        # Build context from conversation history
        # For Claude Code: exclude its own messages (it has --continue)
        # For Codex/Gemini: include full history
        if cli_name == "claude_code":
            filtered_history = [h for h in conversation_history if h["role"] not in ["claude_code"]]
        else:
            filtered_history = conversation_history

        context_parts = []
        if filtered_history:
            context_parts.append("=== Previous conversation context ===")
            for entry in filtered_history:
                role = entry["role"]
                content = entry["content"]
                if role == "user":
                    context_parts.append(f"[User]: {content}")
                elif role == "summary":
                    context_parts.append(f"[Summary of earlier conversation]: {content}")
                else:
                    context_parts.append(f"[{role}]: {content}")
            context_parts.append("=== End of context ===\n")
            context_parts.append(f"[User]: {message}")
            full_message = "\n".join(context_parts)
        else:
            full_message = message

        # Add user message to history
        conversation_history.append({"role": "user", "content": message})

        # Animated spinner while waiting for response
        spinner_messages = {
            "claude_code": ["[cyan]Claude is thinking...[/]", "[cyan]Claude is exploring...[/]", "[cyan]Claude is analyzing...[/]"],
            "codex": ["[green]Codex is thinking...[/]", "[green]Codex is reasoning...[/]", "[green]Codex is processing...[/]"],
            "gemini": ["[magenta]Gemini is thinking...[/]", "[magenta]Gemini is contemplating...[/]", "[magenta]Gemini is working...[/]"],
        }
        spinner_text = spinner_messages.get(cli_name, ["Thinking..."])[0]

        with Status(spinner_text, console=console, spinner="dots") as status:
            import random
            import threading
            import time

            # Update spinner message periodically
            stop_animation = threading.Event()

            def animate_status():
                messages = spinner_messages.get(cli_name, ["Thinking..."])
                idx = 0
                while not stop_animation.is_set():
                    time.sleep(2)
                    if not stop_animation.is_set():
                        idx = (idx + 1) % len(messages)
                        status.update(messages[idx])

            animation_thread = threading.Thread(target=animate_status, daemon=True)
            animation_thread.start()

            try:
                response = manager.send_command(full_message)  # Uses configured timeout
            finally:
                stop_animation.set()
                animation_thread.join(timeout=0.5)

        # Add AI response to history
        if response:
            conversation_history.append({"role": cli_name, "content": response})

        # Display response
        color_map = {
            "claude_code": "cyan",
            "codex": "green",
            "gemini": "magenta",
        }
        color = color_map.get(cli_name, "white")

        console.print(
            Panel(
                response or "[dim]No response[/]",
                title=f"[bold {color}]{cli_name}[/]",
                border_style=color,
            )
        )

    except Exception as e:
        console.print(f"[red]Error communicating with {cli_name}: {e}[/]")


def _display_responses(responses):
    """
    Display AI responses with Rich formatting.

    Args:
        responses: List of DiscussionResponse objects
    """
    for response in responses:
        # Determine color based on CLI
        color_map = {
            "claude_code": "cyan",
            "codex": "green",
            "gemini": "magenta",
        }
        color = color_map.get(response.cli_name, "white")

        # Format title
        title = f"[bold {color}]{response.cli_name}[/]"
        if response.metadata:
            role = response.metadata.get("role")
            iteration = response.metadata.get("iteration")
            if role:
                title += f" [dim]({role})[/]"
            if iteration:
                title += f" [dim]- iteration {iteration}[/]"

        # Display error or response
        if response.error:
            content = f"[red]Error: {response.error}[/]"
        elif response.response:
            content = response.response
        else:
            content = "[dim]No response[/]"

        console.print(Panel(content, title=title, border_style=color))
        console.print()


def _show_status(orchestrator: MonoRepoOrchestrator):
    """
    Show session status.

    Args:
        orchestrator: MonoRepoOrchestrator instance
    """
    summary = orchestrator.get_session_summary()

    console.print("\n[bold cyan]Session Status[/]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Field", style="cyan")
    table.add_column("Value")

    table.add_row("Session ID", summary["session_id"])
    table.add_row("State", summary["state"])
    table.add_row("Project", summary["project_path"])
    table.add_row("Started", summary["started_at"])
    table.add_row("Active CLIs", ", ".join(summary["active_clis"]) or "[dim]None[/]")
    table.add_row("Discussions", str(summary["total_discussions"]))

    console.print(table)
    console.print()


@main.command()
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
    help="Project directory path",
)
@click.option("--session-id", help="Specific session ID to connect to")
def connect(project: Path, session_id: Optional[str]):
    """Connect to an existing AI Roundtable session."""
    console.print("[bold blue]🔗 Connecting to AI Roundtable session[/]")
    console.print(f"[dim]Project: {project.absolute()}[/]")

    try:
        session_manager = SessionManager()

        # Find session
        if session_id:
            session_info = session_manager.load_session(session_id)
            if not session_info:
                console.print(f"[red]Session {session_id} not found[/]")
                raise click.Abort()
        else:
            # Find session by project
            session_info = session_manager.get_session_by_project(project.absolute())
            if not session_info:
                console.print(f"[yellow]No existing session found for this project[/]")
                console.print("[dim]Use 'airt start' to create a new session[/]")
                raise click.Abort()

        console.print(f"[green]Found session: {session_info.session_id}[/]")

        # Check if session is active
        if session_manager._is_session_active(session_info):
            console.print("[yellow]⚠️  Session has active processes![/]")
            console.print("[yellow]Cannot connect to a session that is already running[/]")
            console.print("[dim]Stop the existing session first with 'airt stop'[/]")
            raise click.Abort()

        # Recover session
        console.print("[dim]Recovering session...[/]")
        recovered = session_manager.recover_session(session_info.session_id)

        if not recovered:
            console.print("[red]Failed to recover session[/]")
            raise click.Abort()

        # Load configuration
        config = ConfigManager()

        # Create orchestrator with existing session ID
        orchestrator = MonoRepoOrchestrator(
            project_path=Path(session_info.project_path),
            config=config,
            session_id=session_info.session_id,
        )

        # Restore conversation history
        orchestrator.session_state.conversation_history = session_info.conversation_history

        console.print("[green]✓ Session recovered[/]")
        console.print(f"[dim]Conversation history: {len(session_info.conversation_history)} entries[/]\n")

        # Start CLIs
        console.print("[cyan]Starting AI CLIs...[/]")
        try:
            orchestrator.start_all_clis()
        except PartialStartupError as e:
            console.print(
                f"[yellow]⚠️  Partial startup: {len(e.successful)} of {len(e.successful) + len(e.failed)} CLIs started[/]"
            )

        # Enter interactive mode
        _interactive_loop(orchestrator)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        sys.exit(0)

    except Exception as e:
        console.print(f"[bold red]❌ Error: {e}[/]")
        raise click.Abort()


@main.command()
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
    help="Project directory path",
)
@click.option("--session-id", help="Specific session ID to stop")
@click.option("--all-sessions", is_flag=True, help="Stop all active sessions")
@click.option("--force", is_flag=True, help="Force kill processes")
def stop(project: Path, session_id: Optional[str], all_sessions: bool, force: bool):
    """Stop AI Roundtable orchestrator session(s)."""
    console.print("[bold red]🛑 Stopping AI Roundtable Orchestrator[/]")

    try:
        session_manager = SessionManager()

        # Determine which sessions to stop
        sessions_to_stop = []

        if all_sessions:
            # Stop all active sessions
            sessions_to_stop = session_manager.list_sessions(active_only=True)
            if not sessions_to_stop:
                console.print("[dim]No active sessions found[/]")
                return

        elif session_id:
            # Stop specific session
            session_info = session_manager.load_session(session_id)
            if not session_info:
                console.print(f"[red]Session {session_id} not found[/]")
                raise click.Abort()
            sessions_to_stop = [session_info]

        else:
            # Stop session for current project
            console.print(f"[dim]Project: {project.absolute()}[/]")
            session_info = session_manager.get_session_by_project(project.absolute())
            if not session_info:
                console.print("[yellow]No session found for this project[/]")
                return
            sessions_to_stop = [session_info]

        # Stop each session
        for session_info in sessions_to_stop:
            console.print(f"\n[cyan]Stopping session: {session_info.session_id}[/]")

            # Clean up session
            success = session_manager.cleanup_session(session_info.session_id)

            if success:
                console.print(f"[green]✓ Session {session_info.session_id} stopped[/]")
            else:
                console.print(f"[yellow]⚠️  Failed to stop session {session_info.session_id}[/]")

        console.print(f"\n[green]✓ Stopped {len(sessions_to_stop)} session(s)[/]")

    except Exception as e:
        console.print(f"[bold red]❌ Error: {e}[/]")
        raise click.Abort()


@main.command()
@click.option("--all", "show_all", is_flag=True, help="Show all sessions (not just active)")
def status(show_all: bool):
    """Show all active AI Roundtable sessions."""
    console.print("[bold cyan]📊 AI Roundtable Session Status[/]\n")

    try:
        session_manager = SessionManager()
        sessions = session_manager.list_sessions(active_only=not show_all)

        if not sessions:
            console.print("[dim]No sessions found[/]")
            return

        # Create table
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Session ID", style="cyan", width=30)
        table.add_column("Project", style="white", width=30)
        table.add_column("State", width=10)
        table.add_column("Active CLIs", width=20)
        table.add_column("Last Active", style="dim", width=20)

        for session in sessions:
            summary = session_manager.get_session_summary(session.session_id)
            if not summary:
                continue

            # Format state
            state = summary["state"]
            if summary["is_active"]:
                state_display = f"[green]● {state}[/]"
            else:
                state_display = f"[dim]○ {state}[/]"

            # Format active CLIs
            active_clis = ", ".join(summary["active_clis"]) if summary["active_clis"] else "[dim]none[/]"

            # Format last active time
            try:
                last_active = datetime.fromisoformat(summary["last_active"])
                last_active_str = last_active.strftime("%Y-%m-%d %H:%M")
            except:
                last_active_str = summary["last_active"][:16]

            # Truncate project path
            project = Path(summary["project_path"]).name

            table.add_row(
                session.session_id[:28] + "..." if len(session.session_id) > 28 else session.session_id,
                project,
                state_display,
                active_clis,
                last_active_str,
            )

        console.print(table)
        console.print(f"\n[dim]Total: {len(sessions)} session(s)[/]")

        # Show cleanup suggestion
        if not show_all:
            console.print("[dim]Use --all to show inactive sessions[/]")

    except Exception as e:
        console.print(f"[bold red]❌ Error: {e}[/]")
        raise click.Abort()


@main.command()
@click.argument("question")
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
    help="Project directory path",
)
def ask(question: str, project: Path):
    """Quick question mode - ask AIs a question sequentially without entering interactive mode."""
    console.print("[bold magenta]💬 Asking question (sequential mode)[/]")
    console.print(f"[dim]Question: {question}[/]")
    console.print(f"[dim]Project: {project.absolute()}[/]\n")

    try:
        # Initialize
        config = ConfigManager()
        orchestrator = MonoRepoOrchestrator(project_path=project.absolute(), config=config)

        # Verify CLI availability
        console.print("[dim]Checking AI CLI availability...[/]")
        orchestrator.start_all_clis()

        # Execute sequential discussion
        responses = orchestrator.sequential_discussion(question)

        # Display responses
        console.print()
        _display_responses(responses)

        # Cleanup
        orchestrator.stop_all_clis()

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/]")
        sys.exit(0)

    except Exception as e:
        console.print(f"[bold red]❌ Error: {e}[/]")
        raise click.Abort()


@main.command()
@click.option("--check-deps", is_flag=True, help="Check dependencies without installing")
def setup(check_deps: bool):
    """Initial setup and dependency checking."""
    from .setup import run_setup

    console.print("[bold green]⚙️  AI Roundtable Setup[/]")

    try:
        success = run_setup(check_deps_only=check_deps)
        if not success and check_deps:
            console.print(
                "\n[yellow]Run [bold]airt setup[/bold] to initialize configuration[/]"
            )
    except Exception as e:
        console.print(f"[bold red]❌ Setup failed: {e}[/]")
        raise click.Abort()


@main.command()
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
    help="Project directory path",
)
@click.option("--session-id", help="Specific session ID to recover")
@click.option("--all-crashed", is_flag=True, help="Recover all crashed sessions")
def recover(project: Path, session_id: Optional[str], all_crashed: bool):
    """Recover crashed AI Roundtable sessions."""
    console.print("[bold yellow]🔧 Recovering AI Roundtable Sessions[/]\n")
    logger.info("Starting session recovery")

    try:
        session_manager = SessionManager()

        # Determine which sessions to recover
        sessions_to_recover = []

        if all_crashed:
            # Find all sessions with dead processes
            console.print("[dim]Scanning for crashed sessions...[/]")
            all_sessions = session_manager.list_sessions()

            for session_info in all_sessions:
                # Check if session has dead PIDs
                if session_info.cli_pids and not session_manager._is_session_active(session_info):
                    sessions_to_recover.append(session_info)
                    logger.debug(f"Found crashed session: {session_info.session_id}")

            if not sessions_to_recover:
                console.print("[green]✓ No crashed sessions found[/]")
                logger.info("No crashed sessions found")
                return

            console.print(f"[yellow]Found {len(sessions_to_recover)} crashed session(s)[/]\n")

        elif session_id:
            # Recover specific session
            session_info = session_manager.load_session(session_id)
            if not session_info:
                console.print(f"[red]Session {session_id} not found[/]")
                logger.error(f"Session {session_id} not found")
                raise click.Abort()
            sessions_to_recover = [session_info]

        else:
            # Recover session for current project
            console.print(f"[dim]Project: {project.absolute()}[/]")
            session_info = session_manager.get_session_by_project(project.absolute())
            if not session_info:
                console.print("[yellow]No session found for this project[/]")
                logger.warning(f"No session found for project: {project}")
                return
            sessions_to_recover = [session_info]

        # Recover each session
        recovered_count = 0
        failed_count = 0

        for session_info in sessions_to_recover:
            console.print(f"[cyan]Recovering session: {session_info.session_id}[/]")
            logger.info(f"Recovering session: {session_info.session_id}")

            try:
                # Remove dead PIDs
                recovered = session_manager.recover_session(session_info.session_id)

                if recovered:
                    console.print(f"[green]✓ Session {session_info.session_id} recovered[/]")
                    logger.info(f"Successfully recovered session: {session_info.session_id}")
                    recovered_count += 1
                else:
                    console.print(f"[red]✗ Failed to recover session {session_info.session_id}[/]")
                    logger.error(f"Failed to recover session: {session_info.session_id}")
                    failed_count += 1

            except SessionManagerError as e:
                console.print(f"[red]✗ Error recovering {session_info.session_id}: {e}[/]")
                logger.error(f"Error recovering session {session_info.session_id}: {e}")
                failed_count += 1

        # Summary
        console.print(f"\n[bold]Recovery Summary:[/]")
        console.print(f"[green]✓ Recovered: {recovered_count}[/]")
        if failed_count > 0:
            console.print(f"[red]✗ Failed: {failed_count}[/]")

        logger.info(f"Recovery completed: {recovered_count} recovered, {failed_count} failed")

    except Exception as e:
        console.print(f"[bold red]❌ Recovery failed: {e}[/]")
        logger.error(f"Recovery operation failed: {e}", exc_info=True)
        raise click.Abort()


if __name__ == "__main__":
    main()
