# AI Roundtable

Orchestrate multiple AI CLIs (Claude Code, Codex, Gemini Code Assist) for collaborative development in mono-repo environments.

## Features

✨ **Multi-AI Orchestration**
- Manage multiple AI CLI processes simultaneously
- Automatic process lifecycle management with health checks
- Crash recovery and automatic restart capabilities

🎯 **Three Discussion Modes**
- **Sequential Mode**: Each AI builds on previous responses
- **Parallel Mode**: All AIs receive questions simultaneously
- **Review Mode**: One AI proposes, another reviews iteratively

📦 **Mono-repo Support**
- Automatic mono-repo detection (Lerna, Nx, pnpm workspaces, Turborepo, Rush)
- Service-specific context generation (CLAUDE.md, CODEX.md, GEMINI.md)
- Smart project structure analysis

💾 **Session Management**
- Persistent sessions across restarts
- Conversation history preservation
- Session recovery after crashes
- Multi-project session tracking

🔧 **Robust Error Handling**
- Rich logging with tracebacks
- Retry logic with exponential backoff
- Graceful shutdown with SIGINT/SIGTERM handling
- User-friendly error messages

## Installation

### Prerequisites
- Python 3.11 or higher
- [UV package manager](https://github.com/astral-sh/uv)
- At least one AI CLI tool:
  - [Claude Code](https://claude.ai/claude-code)
  - Codex CLI
  - Gemini Code Assist

### Install with UV

```bash
# Clone the repository
git clone <repository-url>
cd ai-round-table

# Install using UV
uv pip install -e .
```

## Quick Start

```bash
# 1. Run dependency check
airt setup --check-deps

# 2. Initialize configuration (if needed)
airt setup

# 3. Start an interactive session
airt start

# 4. In interactive mode, use commands:
@all What's the best approach for error handling?
@seq Design a new feature step by step
@review Implement user authentication
@claude Explain this code structure
```

## Usage

### Command Reference

#### Start Session
```bash
# Start in current directory
airt start

# Start with specific project
airt start --project /path/to/project

# Force re-initialization
airt start --reinit

# Enable verbose logging
airt start --verbose
```

#### Quick Question Mode
```bash
# Ask all AIs in parallel
airt ask "How should we structure this API?" --mode=all

# Sequential discussion
airt ask "Design database schema" --mode=seq

# Review mode
airt ask "Implement authentication" --mode=review
```

#### Session Management
```bash
# List all sessions
airt status

# Show inactive sessions too
airt status --all

# Connect to existing session
airt connect

# Connect to specific session
airt connect --session-id <id>

# Stop current session
airt stop

# Stop specific session
airt stop --session-id <id>

# Stop all active sessions
airt stop --all-sessions
```

#### Session Recovery
```bash
# Recover crashed session for current project
airt recover

# Recover specific session
airt recover --session-id <id>

# Recover all crashed sessions
airt recover --all-crashed
```

### Interactive Mode Commands

When in interactive mode (`airt start`), use these commands:

| Command | Description | Example |
|---------|-------------|---------|
| `@all <question>` | Parallel discussion - all AIs answer simultaneously | `@all What's the project structure?` |
| `@seq <question>` | Sequential discussion - each AI builds on previous responses | `@seq Design the authentication flow` |
| `@review <task>` | Review mode - proposer/reviewer iteration | `@review Implement user registration` |
| `@claude <message>` | Direct message to Claude Code | `@claude Explain this function` |
| `@codex <message>` | Direct message to Codex | `@codex Review this code` |
| `@gemini <message>` | Direct message to Gemini | `@gemini Suggest improvements` |
| `status` | Show current session status | `status` |
| `help` | Display available commands | `help` |
| `exit` | Exit interactive mode | `exit` |

## Configuration

### Project Configuration

Configuration is stored in `~/.ai-roundtable/config.yaml`:

```yaml
version: "0.1.0"
default_mode: sequential

cli_settings:
  claude_code:
    timeout: 60
    init_command: "/init"
    prompt_pattern: "Claude>"
  codex:
    timeout: 60
    init_command: "/init"
    prompt_pattern: "Codex>"
  gemini:
    timeout: 60
    init_command: "/init"
    prompt_pattern: "Gemini>"

context:
  max_tokens: 100000
  compression_threshold: 80000

session:
  auto_save: true
  history_limit: 1000
```

### Logging

Logs are stored in `~/.ai-roundtable/logs/`:
- `ai_roundtable.log` - Main application log (rotated at 10MB)
- Rich console output with colors and tracebacks

Set log level:
```bash
airt --log-level DEBUG start
```

## Architecture

```
AI Roundtable
├── CLI Interface (Click)
│   ├── start, stop, status, connect, recover
│   └── Interactive command loop
├── Orchestrator
│   ├── MonoRepoOrchestrator - Core coordination
│   ├── Discussion modes (sequential, parallel, review)
│   └── Session state management
├── AI CLI Managers
│   ├── ClaudeCodeManager
│   ├── CodexManager
│   └── GeminiManager
├── Session Manager
│   ├── Session persistence (~/.ai-roundtable/sessions/)
│   ├── PID tracking
│   └── Crash recovery
├── Context Builder
│   ├── Mono-repo detection
│   ├── Service discovery
│   └── Context file generation (CLAUDE.md, CODEX.md, GEMINI.md)
└── Configuration Manager
    └── YAML-based config with atomic writes
```

## Error Handling

AI Roundtable includes comprehensive error handling:

- **Retry Logic**: Automatic retry with exponential backoff on timeouts
- **Process Recovery**: Detect and restart crashed CLI processes
- **Session Recovery**: Restore sessions after system crashes
- **Graceful Shutdown**: Clean termination on SIGINT/SIGTERM
- **Rich Logging**: Detailed logs with tracebacks for debugging

## Development

### Project Structure

```
ai-round-table/
├── src/ai_roundtable/
│   ├── __init__.py
│   ├── cli.py              # Click CLI interface
│   ├── orchestrator.py     # Core orchestration engine
│   ├── cli_managers.py     # AI CLI process managers
│   ├── session_manager.py  # Session persistence
│   ├── context.py          # Project context analysis
│   ├── config.py           # Configuration management
│   ├── logging_config.py   # Logging infrastructure
│   └── setup.py            # Setup and dependency checking
├── .taskmaster/            # Task Master development tracking
├── pyproject.toml          # UV/pip configuration
└── README.md               # This file
```

### Running Tests

```bash
# Quick orchestrator test
python3 test_orchestrator.py
```

### Development Status

**Project Completion: 100%** (10/10 tasks, 57/57 subtasks)

All planned features have been implemented:
- ✅ Python project structure with UV
- ✅ CLI interface with Click
- ✅ Configuration management
- ✅ AI CLI process managers
- ✅ Project context analyzer
- ✅ Core orchestration engine
- ✅ Interactive discussion modes
- ✅ Session management
- ✅ Setup command
- ✅ Error handling and logging

## Troubleshooting

### CLI Not Starting

```bash
# Check dependencies
airt setup --check-deps

# Enable verbose logging
airt start --verbose

# Check logs
tail -f ~/.ai-roundtable/logs/ai_roundtable.log
```

### Session Recovery

If a session crashes:
```bash
# Recover session for current project
airt recover

# Or recover all crashed sessions
airt recover --all-crashed
```

### Permission Issues

Ensure AI CLIs are in your PATH:
```bash
which claude
which codex
which gemini
```

## License

MIT

## Contributing

Contributions are welcome! This project uses Task Master for development tracking. See `.taskmaster/` for the development workflow.
