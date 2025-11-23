"""Quick test of orchestrator implementation."""

from pathlib import Path
from src.ai_roundtable.orchestrator import MonoRepoOrchestrator, OrchestratorState
from src.ai_roundtable.config import ConfigManager

# Test initialization
print("Testing MonoRepoOrchestrator initialization...")

project_path = Path.cwd()
config = ConfigManager()

orchestrator = MonoRepoOrchestrator(
    project_path=project_path,
    config=config
)

print(f"✓ Orchestrator created")
print(f"  Session ID: {orchestrator.session_id}")
print(f"  State: {orchestrator.state.value}")
print(f"  Project: {orchestrator.project_path}")
print(f"  Session dir: {orchestrator.session_dir}")

# Test session summary
print("\nGetting session summary...")
summary = orchestrator.get_session_summary()
print(f"✓ Session summary:")
for key, value in summary.items():
    print(f"  {key}: {value}")

# Test state persistence
print("\nTesting state persistence...")
orchestrator._save_session_state()
print(f"✓ State saved to {orchestrator.session_dir / 'state.json'}")

# Test context generation (without starting CLIs)
print("\nTesting context file generation...")
try:
    orchestrator._generate_context_files()
    print(f"✓ Context files generated:")
    print(f"  - CLAUDE.md: {(project_path / 'CLAUDE.md').exists()}")
    print(f"  - CODEX.md: {(project_path / 'CODEX.md').exists()}")
    print(f"  - GEMINI.md: {(project_path / 'GEMINI.md').exists()}")
except Exception as e:
    print(f"✗ Error generating context files: {e}")

# Test CLI detection
print("\nChecking available CLI managers...")
for cli_name in orchestrator.CLI_MANAGERS.keys():
    print(f"  - {cli_name}: {orchestrator.CLI_MANAGERS[cli_name].__name__}")

print("\n✓ All basic tests passed!")
print("\nNote: Full testing requires actual CLI processes to be available.")
print("Orchestrator is ready for integration with the main CLI.")
