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
        logger.info(f"Received {sig_name}, shutting down gracefully...")
        console.print(f"\n[yellow]⚠️  Received {sig_name}, shutting down...[/]")

        try:
            if _global_orchestrator:
                _global_orchestrator.stop_all_clis()
                logger.info("All CLIs stopped successfully")
                console.print("[green]✓[/] All CLIs stopped successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
            console.print(f"[red]✗[/] Error during shutdown: {e}")
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
@click.option("--reinit", is_flag=True, help="Force re-initialization of the session")
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
def start(project: Path, reinit: bool, verbose: bool):
    """Start AI Roundtable orchestrator session."""
    # Configure logging level
    if verbose:
        LoggingConfig.set_level("DEBUG")
        logger.debug("Verbose logging enabled")

    console.print("[bold green]🎭 Starting AI Roundtable Orchestrator[/]")
    console.print(f"[dim]Project: {project.absolute()}[/]")
    logger.info(f"Starting orchestrator for project: {project.absolute()}")

    if reinit:
        console.print("[yellow]⚠️  Re-initialization requested[/]")
        logger.warning("Re-initialization requested")

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

        # Start all CLIs
        console.print("\n[cyan]Starting AI CLIs...[/]")
        logger.info("Starting AI CLI processes")

        try:
            results = orchestrator.start_all_clis(reinit=reinit)

            # Display startup results
            success_count = sum(1 for v in results.values() if v)
            console.print(
                f"[green]✓ {success_count}/{len(results)} CLIs started successfully[/]"
            )
            logger.info(f"Started {success_count}/{len(results)} CLIs successfully")

        except PartialStartupError as e:
            console.print(
                f"[yellow]⚠️  Partial startup: {len(e.successful)} of {len(e.successful) + len(e.failed)} CLIs started[/]"
            )
            console.print("[green]Started:[/] " + ", ".join(e.successful))
            console.print("[red]Failed:[/]")
            for cli, error in e.failed.items():
                console.print(f"  - {cli}: {error}")
                logger.error(f"Failed to start {cli}: {error}")
            console.print(
                "\n[yellow]Continuing with available CLIs. Some commands may not work.[/]"
            )
            logger.warning("Continuing with partial startup")

        except OrchestratorError as e:
            console.print(f"[bold red]❌ Failed to start orchestrator: {e}[/]")
            logger.error(f"Orchestrator startup failed: {e}", exc_info=True)
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

    # Main loop
    while True:
        try:
            user_input = console.input("[bold cyan]💬 >[/] ").strip()

            if not user_input:
                continue

            # Parse and execute command
            _execute_command(orchestrator, user_input)

        except KeyboardInterrupt:
            console.print("\n[yellow]Use 'exit' to quit[/]")
            continue

        except EOFError:
            break

        except Exception as e:
            console.print(f"[bold red]❌ Error: {e}[/]")
            logger.exception("Error in interactive loop")

    # Cleanup
    console.print("\n[yellow]Shutting down...[/]")
    orchestrator.stop_all_clis()
    console.print("[green]✓ Session ended[/]")


def _show_commands_help():
    """Display available commands."""
    console.print("[bold]Available Commands:[/]\n")

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Command", style="cyan")
    table.add_column("Description", style="dim")

    table.add_row("@all <question>", "Ask all AIs in parallel")
    table.add_row("@seq <question>", "Ask AIs sequentially (chained context)")
    table.add_row("@review <task>", "Proposal/review workflow")
    table.add_row("@claude <message>", "Direct message to Claude Code")
    table.add_row("@codex <message>", "Direct message to Codex")
    table.add_row("@gemini <message>", "Direct message to Gemini")
    table.add_row("status", "Show session status")
    table.add_row("help", "Show this help message")
    table.add_row("exit", "Exit interactive mode")

    console.print(table)


def _execute_command(orchestrator: MonoRepoOrchestrator, user_input: str):
    """
    Parse and execute user command.

    Args:
        orchestrator: MonoRepoOrchestrator instance
        user_input: User input string
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

    # @all - parallel discussion
    elif user_input.startswith("@all "):
        question = user_input[5:].strip()
        if not question:
            console.print("[red]Error: Please provide a question[/]")
            return

        console.print(f"[dim]Asking all AIs in parallel...[/]\n")
        responses = orchestrator.parallel_discussion(question, timeout=120)
        _display_responses(responses)

    # @seq - sequential discussion
    elif user_input.startswith("@seq "):
        question = user_input[5:].strip()
        if not question:
            console.print("[red]Error: Please provide a question[/]")
            return

        console.print(f"[dim]Starting sequential discussion...[/]\n")
        responses = orchestrator.sequential_discussion(question)
        _display_responses(responses)

    # @review - review mode
    elif user_input.startswith("@review "):
        task = user_input[8:].strip()
        if not task:
            console.print("[red]Error: Please provide a task description[/]")
            return

        # Ask for proposer and reviewer
        console.print(
            "[dim]Proposer (default: claude_code):[/] ", end="", markup=True
        )
        proposer = input().strip() or "claude_code"

        console.print("[dim]Reviewer (default: codex):[/] ", end="", markup=True)
        reviewer = input().strip() or "codex"

        console.print(
            "[dim]Iterations (default: 1):[/] ", end="", markup=True
        )
        iterations_str = input().strip() or "1"
        try:
            iterations = int(iterations_str)
        except ValueError:
            console.print("[red]Invalid number, using 1 iteration[/]")
            iterations = 1

        console.print(
            f"\n[dim]Starting review: {proposer} → {reviewer} ({iterations} iteration(s))...[/]\n"
        )
        result = orchestrator.review_mode(task, proposer, reviewer, iterations)

        # Display proposals and reviews
        for i, (proposal, review) in enumerate(
            zip(result["proposals"], result["reviews"]), 1
        ):
            console.print(f"\n[bold cyan]═══ Iteration {i} ═══[/]\n")
            _display_responses([proposal])
            console.print()
            _display_responses([review])

    # Direct AI commands
    elif user_input.startswith("@claude "):
        _send_direct_message(orchestrator, "claude_code", user_input[8:].strip())

    elif user_input.startswith("@codex "):
        _send_direct_message(orchestrator, "codex", user_input[7:].strip())

    elif user_input.startswith("@gemini "):
        _send_direct_message(orchestrator, "gemini", user_input[8:].strip())

    # Unknown command
    else:
        console.print(
            "[yellow]Unknown command. Type 'help' for available commands.[/]"
        )


def _send_direct_message(
    orchestrator: MonoRepoOrchestrator, cli_name: str, message: str
):
    """
    Send direct message to a specific AI CLI.

    Args:
        orchestrator: MonoRepoOrchestrator instance
        cli_name: Name of CLI (claude_code, codex, gemini)
        message: Message to send
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

    try:
        console.print(f"[dim]Sending to {cli_name}...[/]\n")
        response = manager.send_command(message, timeout=120)

        # Display response
        console.print(
            Panel(
                response or "[dim]No response[/]",
                title=f"[bold cyan]{cli_name}[/]",
                border_style="cyan",
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
    "--mode",
    type=click.Choice(["all", "seq", "review"], case_sensitive=False),
    default="all",
    help="Discussion mode: all (parallel), seq (sequential), review (review mode)",
)
@click.option(
    "--project",
    type=click.Path(exists=True, file_okay=False, dir_okay=True, path_type=Path),
    default=".",
    help="Project directory path",
)
def ask(question: str, mode: str, project: Path):
    """Quick question mode - ask all AIs a question without entering interactive mode."""
    console.print(f"[bold magenta]💬 Asking question in {mode} mode[/]")
    console.print(f"[dim]Question: {question}[/]")
    console.print(f"[dim]Project: {project.absolute()}[/]\n")

    try:
        # Initialize
        config = ConfigManager()
        orchestrator = MonoRepoOrchestrator(project_path=project.absolute(), config=config)

        # Start CLIs
        console.print("[dim]Starting AI CLIs...[/]")
        orchestrator.start_all_clis()

        # Execute based on mode
        if mode == "all":
            responses = orchestrator.parallel_discussion(question)
        elif mode == "seq":
            responses = orchestrator.sequential_discussion(question)
        elif mode == "review":
            result = orchestrator.review_mode(question, "claude_code", "codex", 1)
            responses = result["proposals"] + result["reviews"]
        else:
            console.print(f"[red]Unknown mode: {mode}[/]")
            raise click.Abort()

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
