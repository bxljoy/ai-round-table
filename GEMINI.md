# AI Roundtable (`ai-roundtable`)

## Project Overview

AI Roundtable is a Python-based command-line tool designed to orchestrate and manage multiple AI assistant CLIs (such as Claude, Codex, and Gemini) within a unified development environment. It facilitates collaborative AI-driven development by enabling different discussion modes (sequential, parallel, review) and managing the lifecycle of the AI processes.

The project is built with Python 3.11+, using `click` for the CLI, `pexpect` and `subprocess` for process management, and `pyyaml` for configuration. It is designed to work within mono-repo environments, with capabilities to generate context-specific information for each AI.

## Building and Running

The project uses `uv` for dependency management.

### Installation

To install the project and its dependencies, use `uv`:

```bash
uv pip install -e .
```

### Running the Application

The main entry point is the `airt` command.

**Start an interactive session:**

```bash
airt start
```

**Run a quick question in sequential mode:**

```bash
airt ask "Your question here"
```

### Running Tests

The project includes a test file for the orchestrator. To run it:

```bash
python3 test_orchestrator.py
```

## Development Conventions

### Code Style

The project uses `black` for code formatting and `ruff` for linting. The configuration for these tools can be found in `pyproject.toml`.

### Branching

The repository does not specify a branching strategy, but following common practices like feature branches (`feat/...`), bugfix branches (`fix/...`), etc., is recommended.

### Commits

Commit messages should be clear and concise, explaining the "what" and "why" of the change.

## Key Files

-   `src/ai_roundtable/cli.py`: The main entry point for the CLI, built with `click`. It defines the command structure and user interactions.
-   `src/ai_roundtable/orchestrator.py`: The core of the application, responsible for managing the AI CLI processes, orchestrating the discussion modes, and handling session state.
-   `src/ai_roundtable/cli_managers.py`: Contains the logic for interacting with the different AI CLIs, using `pexpect` for interactive shells and `subprocess` for non-interactive commands.
-   `src/ai_roundtable/config.py`: Manages the application's configuration, which is stored in `~/.ai-roundtable/config.yaml`.
-   `src/ai_roundtable/session_manager.py`: Handles the persistence of session data, including conversation history and process IDs.
-   `pyproject.toml`: Defines the project's dependencies, scripts, and build system configuration.
-   `README.md`: Provides a comprehensive overview of the project, its features, and how to use it.
