# Repository Guidelines

## Project Structure & Module Organization
Python sources live in `src/ai_roundtable`, with `cli.py`, `orchestrator.py`, and `cli_managers.py` driving orchestration, while `config.py`, `context.py`, and `session_manager.py` handle persistence and discovery. Support notes for each agent sit right next to the repo root (`CLAUDE.md`, `CODEX.md`, `GEMINI.md`). Tests are currently lightweight (`test_orchestrator.py`), and prototype assets or CLI fixtures belong under the service-specific folders (`claude-code`, `codex`, `gemini-cli`). Keep new modules in `src/ai_roundtable` and wire them up via `pyproject.toml` if they expose commands.

## Build, Test, and Development Commands
- `uv pip install -e .` – install dependencies plus the editable `airt` entry point.
- `airt setup --check-deps` – verify local CLIs and configuration before hacking.
- `airt start --verbose` – run the orchestrator with extra logging; add `--project <path>` for mono-repo targets.
- `airt ask "question" --mode=seq|all|review` – exercise the discussion modes quickly.
- `python3 test_orchestrator.py` or `pytest -k orchestrator` – run the existing sanity check; add `pytest --cov=ai_roundtable` when adding features.

## Coding Style & Naming Conventions
Use 4-space indentation, Black formatting (`black . --line-length 100`), and Ruff for linting (`ruff check src`). Modules and helper functions follow `snake_case`, classes `PascalCase`, and Click commands remain short verbs (`start`, `ask`, `recover`). Prefer explicit logging and type hints for new orchestration paths; inline comments only when flow control is non-obvious.

## Testing Guidelines
Target pytest for new coverage; keep test files next to their subjects (e.g., `tests/test_session_manager.py`). Name tests after behavior (`test_session_recover_crashed_process`). Mock real CLI subprocesses rather than launching binaries during CI. Aim for coverage on failure paths (timeouts, process restarts) before merging, and document any manual validation steps in the PR.

## Commit & Pull Request Guidelines
Follow the Conventional Commit style visible in history (`feat(cli.py): add review mode`, `fix(orchestrator.py): improve logging`). One logical change per commit, include the touched module in parentheses, and keep subjects under ~80 characters. PRs should summarize motivation, list verification commands (tests, `airt start` smoke run), link related issues, and attach screenshots or console excerpts when altering user-facing output. Mention any follow-up work needed by other agents to keep the roundtable in sync.

## Security & Configuration Tips
User-specific settings live in `~/.ai-roundtable/`; never commit those. Reference tokens or CLI credentials via environment variables, not checked-in files. When sharing logs, redact session IDs and filesystem paths, and prefer `airt start --reinit` on public demos to avoid leaking prior context.
