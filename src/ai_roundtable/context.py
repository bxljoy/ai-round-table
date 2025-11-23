"""Project context analysis and generation for AI CLIs."""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from .logging_config import get_logger

logger = get_logger(__name__)


class ProjectStructure:
    """Represents analyzed project structure."""

    def __init__(
        self,
        project_path: Path,
        is_monorepo: bool,
        project_type: str,
        services: List[Dict[str, Any]],
        metadata: Dict[str, Any],
    ):
        self.project_path = project_path
        self.is_monorepo = is_monorepo
        self.project_type = project_type
        self.services = services
        self.metadata = metadata


class ContextBuilder:
    """
    Analyzes project structure and generates context for AI CLIs.

    Supports mono-repo awareness and generates appropriate context
    files (CLAUDE.md, CODEX.md, etc.) for each AI CLI.
    """

    # Mono-repo indicators
    MONOREPO_FILES = [
        "lerna.json",
        "nx.json",
        "pnpm-workspace.yaml",
        "turbo.json",
        "rush.json",
    ]

    MONOREPO_DIRS = ["services", "packages", "apps", "libs"]

    def __init__(self, project_path: Path, config: Optional[Dict[str, Any]] = None):
        """
        Initialize ContextBuilder.

        Args:
            project_path: Path to project root
            config: Configuration from ConfigManager
        """
        self.project_path = Path(project_path)
        self.config = config or {}
        self.structure: Optional[ProjectStructure] = None

        # Get context settings from config
        context_config = self.config.get("context", {})
        self.max_tokens = context_config.get("max_tokens", 100000)
        self.compression_threshold = context_config.get("compression_threshold", 80000)

    def analyze_project(self) -> ProjectStructure:
        """
        Analyze project structure and type.

        Returns:
            ProjectStructure with project information

        Detects:
        - Mono-repo vs single repo
        - Project type (Python, JavaScript, mixed, etc.)
        - Services/components in mono-repos
        - Key directories and files
        """
        logger.info(f"Analyzing project at {self.project_path}")

        # Detect mono-repo
        is_monorepo = self._detect_monorepo()

        # Detect project type
        project_type = self._detect_project_type()

        # Discover services/components
        services = []
        if is_monorepo:
            services = self._discover_services()

        # Collect metadata
        metadata = self._collect_metadata()

        self.structure = ProjectStructure(
            project_path=self.project_path,
            is_monorepo=is_monorepo,
            project_type=project_type,
            services=services,
            metadata=metadata,
        )

        logger.info(
            f"Project analysis complete: {'mono-repo' if is_monorepo else 'single repo'}, "
            f"type={project_type}, services={len(services)}"
        )

        return self.structure

    def _detect_monorepo(self) -> bool:
        """
        Detect if project is a mono-repo.

        Returns:
            True if mono-repo detected
        """
        # Check for mono-repo config files
        for filename in self.MONOREPO_FILES:
            if (self.project_path / filename).exists():
                logger.debug(f"Mono-repo detected: found {filename}")
                return True

        # Check for mono-repo directory structure
        for dirname in self.MONOREPO_DIRS:
            dir_path = self.project_path / dirname
            if dir_path.exists() and dir_path.is_dir():
                # Check if it contains multiple sub-projects
                subdirs = [d for d in dir_path.iterdir() if d.is_dir()]
                if len(subdirs) >= 2:
                    # Check if subdirs have their own package.json/pyproject.toml
                    has_projects = sum(
                        1
                        for d in subdirs
                        if (d / "package.json").exists()
                        or (d / "pyproject.toml").exists()
                    )
                    if has_projects >= 2:
                        logger.debug(
                            f"Mono-repo detected: {dirname}/ has {has_projects} sub-projects"
                        )
                        return True

        return False

    def _detect_project_type(self) -> str:
        """
        Detect primary project type.

        Returns:
            Project type string (e.g., 'python', 'javascript', 'typescript', 'mixed')
        """
        indicators = {
            "python": ["pyproject.toml", "setup.py", "requirements.txt", "Pipfile"],
            "javascript": ["package.json", "yarn.lock"],
            "typescript": ["tsconfig.json"],
            "rust": ["Cargo.toml"],
            "go": ["go.mod"],
        }

        detected = []
        for proj_type, files in indicators.items():
            if any((self.project_path / f).exists() for f in files):
                detected.append(proj_type)

        if not detected:
            return "unknown"
        elif len(detected) == 1:
            return detected[0]
        elif "typescript" in detected and "javascript" in detected:
            return "typescript"
        else:
            return "mixed"

    def _discover_services(self) -> List[Dict[str, Any]]:
        """
        Discover services/components in mono-repo.

        Returns:
            List of service dictionaries with name, path, type
        """
        services = []

        for dirname in self.MONOREPO_DIRS:
            dir_path = self.project_path / dirname
            if not dir_path.exists():
                continue

            for service_dir in dir_path.iterdir():
                if not service_dir.is_dir():
                    continue

                # Check if it's a valid service
                service_info = self._analyze_service(service_dir)
                if service_info:
                    services.append(service_info)

        return services

    def _analyze_service(self, service_path: Path) -> Optional[Dict[str, Any]]:
        """
        Analyze a service directory.

        Args:
            service_path: Path to service directory

        Returns:
            Service info dict or None if not a valid service
        """
        # Check for package indicators
        has_package_json = (service_path / "package.json").exists()
        has_pyproject = (service_path / "pyproject.toml").exists()

        if not (has_package_json or has_pyproject):
            return None

        # Determine service type
        if has_pyproject:
            service_type = "python"
        elif (service_path / "tsconfig.json").exists():
            service_type = "typescript"
        elif has_package_json:
            service_type = "javascript"
        else:
            service_type = "unknown"

        # Get service name
        name = service_path.name

        # Try to get description from package.json or pyproject.toml
        description = ""
        if has_package_json:
            try:
                with open(service_path / "package.json") as f:
                    pkg = json.load(f)
                    description = pkg.get("description", "")
            except:
                pass

        return {
            "name": name,
            "path": str(service_path.relative_to(self.project_path)),
            "type": service_type,
            "description": description,
        }

    def _collect_metadata(self) -> Dict[str, Any]:
        """
        Collect project metadata.

        Returns:
            Metadata dictionary
        """
        metadata = {
            "name": self.project_path.name,
            "has_git": (self.project_path / ".git").exists(),
            "has_readme": (self.project_path / "README.md").exists(),
        }

        # Try to get project name from package.json or pyproject.toml
        if (self.project_path / "package.json").exists():
            try:
                with open(self.project_path / "package.json") as f:
                    pkg = json.load(f)
                    metadata["name"] = pkg.get("name", metadata["name"])
                    metadata["version"] = pkg.get("version")
            except:
                pass

        return metadata

    def generate_claude_md(self, focus_service: Optional[str] = None) -> str:
        """
        Generate CLAUDE.md with project context.

        Args:
            focus_service: Optional service name to focus on (for mono-repos)

        Returns:
            Markdown content for CLAUDE.md
        """
        if not self.structure:
            self.analyze_project()

        lines = [
            "# Project Context for Claude Code",
            "",
            f"**Project:** {self.structure.metadata['name']}",
            f"**Type:** {self.structure.project_type}",
            f"**Structure:** {'Mono-repository' if self.structure.is_monorepo else 'Single repository'}",
            "",
        ]

        if self.structure.is_monorepo:
            lines.extend(["## Services/Components", ""])
            for service in self.structure.services:
                lines.append(f"### {service['name']}")
                lines.append(f"- **Path:** `{service['path']}`")
                lines.append(f"- **Type:** {service['type']}")
                if service.get("description"):
                    lines.append(f"- **Description:** {service['description']}")
                lines.append("")

            if focus_service:
                lines.extend(
                    [f"## Current Focus: {focus_service}", "", "Work on this service only.", ""]
                )

        lines.extend(
            [
                "## Guidelines",
                "",
                "- Follow existing code style and conventions",
                "- Update tests when modifying functionality",
                "- Keep changes focused and atomic",
                "",
            ]
        )

        return "\n".join(lines)

    def generate_codex_md(self, focus_service: Optional[str] = None) -> str:
        """
        Generate CODEX.md with project context.

        Args:
            focus_service: Optional service name to focus on

        Returns:
            Markdown content for CODEX.md
        """
        if not self.structure:
            self.analyze_project()

        lines = [
            "# Project Context for Codex",
            "",
            f"Project: {self.structure.metadata['name']}",
            f"Type: {self.structure.project_type}",
            "",
        ]

        if self.structure.is_monorepo:
            lines.append("## Services")
            lines.append("")
            for service in self.structure.services:
                lines.append(f"- **{service['name']}** ({service['type']}): {service['path']}")

            lines.append("")

        return "\n".join(lines)

    def generate_gemini_md(self, focus_service: Optional[str] = None) -> str:
        """
        Generate GEMINI.md with project context.

        Args:
            focus_service: Optional service name to focus on

        Returns:
            Markdown content for GEMINI.md
        """
        # Similar structure to Codex for now
        return self.generate_codex_md(focus_service)

    def build_conversation_context(
        self, conversation_history: Optional[List[Dict[str, str]]] = None
    ) -> str:
        """
        Build context for conversation sharing between CLIs.

        Args:
            conversation_history: List of conversation messages

        Returns:
            Formatted context string (trimmed/compressed if needed)
        """
        if not self.structure:
            self.analyze_project()

        # Build context parts
        parts = []

        # Project overview
        overview = f"Project: {self.structure.metadata['name']} ({self.structure.project_type})"
        parts.append(overview)

        # Add conversation history if provided
        if conversation_history:
            parts.append("\n## Conversation History:\n")
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                parts.append(f"**{role}:** {content}\n")

        # Combine
        context = "\n".join(parts)

        # Trim/compress if needed
        token_count = self._estimate_tokens(context)
        if token_count > self.max_tokens:
            context = self._trim_context(context, self.max_tokens)
        elif token_count > self.compression_threshold:
            context = self._compress_context(context)

        return context

    def _estimate_tokens(self, text: str) -> int:
        """
        Estimate token count for text.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count (rough approximation: 1 token ≈ 4 chars)
        """
        return len(text) // 4

    def _trim_context(self, context: str, max_tokens: int) -> str:
        """
        Trim context to fit within token limit.

        Args:
            context: Context string
            max_tokens: Maximum allowed tokens

        Returns:
            Trimmed context
        """
        max_chars = max_tokens * 4
        if len(context) <= max_chars:
            return context

        # Trim from middle, keeping start and end
        keep_start = max_chars // 2
        keep_end = max_chars // 2

        trimmed = (
            context[:keep_start]
            + f"\n\n[... {len(context) - max_chars} characters trimmed ...]\n\n"
            + context[-keep_end:]
        )

        logger.debug(f"Context trimmed from {len(context)} to {len(trimmed)} chars")
        return trimmed

    def _compress_context(self, context: str) -> str:
        """
        Compress context by removing redundancy.

        Args:
            context: Context string

        Returns:
            Compressed context
        """
        # Simple compression: remove extra whitespace, deduplicate lines
        lines = context.split("\n")

        # Remove empty lines
        lines = [line.strip() for line in lines if line.strip()]

        # Remove duplicate consecutive lines
        compressed_lines = []
        prev_line = None
        for line in lines:
            if line != prev_line:
                compressed_lines.append(line)
            prev_line = line

        compressed = "\n".join(compressed_lines)

        logger.debug(f"Context compressed from {len(context)} to {len(compressed)} chars")
        return compressed
