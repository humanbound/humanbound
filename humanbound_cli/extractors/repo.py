# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Humanbound
"""Repository scanner for extracting AI agent configuration."""

import fnmatch
import json
import re
from pathlib import Path
from typing import Any


class RepoScanner:
    """Scan a repository for AI agent configuration files."""

    # Patterns for finding system prompts
    PROMPT_PATTERNS = [
        "**/system_prompt*.txt",
        "**/system_prompt*.md",
        "**/prompts/*.txt",
        "**/prompts/*.md",
        "**/instructions/*.txt",
        "**/instructions/*.md",
        "**/*_prompt.txt",
        "**/*_prompt.md",
        "**/SYSTEM_PROMPT*",
        "**/prompt.txt",
        "**/prompt.md",
    ]

    # Patterns for finding tool definitions
    TOOL_PATTERNS = [
        "**/tools.py",
        "**/tools/*.py",
        "**/functions.json",
        "**/tools.json",
        "**/tools.yaml",
        "**/tools.yml",
        "**/function_definitions.json",
    ]

    # Patterns for config files
    CONFIG_PATTERNS = [
        ".env.example",
        "config.yaml",
        "config.yml",
        "config.json",
        "**/langchain*.yaml",
        "**/langchain*.yml",
        "**/agent*.yaml",
        "**/agent*.yml",
    ]

    # Directories to skip
    SKIP_DIRS = {
        ".git",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "coverage",
        ".pytest_cache",
        ".mypy_cache",
    }

    def __init__(self, repo_path: str):
        """Initialize the scanner.

        Args:
            repo_path: Path to the repository root.
        """
        self.repo_path = Path(repo_path).resolve()

    def scan(self) -> dict[str, Any] | None:
        """Scan the repository for AI agent configuration.

        Returns:
            Dictionary with extracted information or None if nothing found.
        """
        result = {
            "files": [],
            "system_prompt": "",
            "tools": [],
            "readme": "",
            "config": {},
        }

        # Find all relevant files
        prompt_files = self._find_files(self.PROMPT_PATTERNS)
        tool_files = self._find_files(self.TOOL_PATTERNS)
        config_files = self._find_files(self.CONFIG_PATTERNS)

        all_files = prompt_files + tool_files + config_files
        result["files"] = [str(f.relative_to(self.repo_path)) for f in all_files]

        # Extract system prompt
        for pf in prompt_files:
            try:
                content = pf.read_text(encoding="utf-8", errors="ignore")
                if content.strip():
                    result["system_prompt"] += f"\n\n--- {pf.name} ---\n{content}"
            except Exception:
                pass

        # Extract tool definitions
        for tf in tool_files:
            tools = self._extract_tools(tf)
            result["tools"].extend(tools)

        # Read README
        readme_path = self.repo_path / "README.md"
        if not readme_path.exists():
            readme_path = self.repo_path / "readme.md"
        if not readme_path.exists():
            readme_path = self.repo_path / "README.rst"

        if readme_path.exists():
            try:
                result["readme"] = readme_path.read_text(encoding="utf-8", errors="ignore")[:5000]
            except Exception:
                pass

        # Return None if nothing useful found
        if not result["system_prompt"] and not result["tools"] and not result["readme"]:
            return None

        return result

    def _find_files(self, patterns: list[str]) -> list[Path]:
        """Find files matching the given glob patterns.

        Args:
            patterns: List of glob patterns to match.

        Returns:
            List of matching file paths.
        """
        found = []

        for pattern in patterns:
            for path in self.repo_path.rglob("*"):
                # Skip directories in skip list
                if any(skip in path.parts for skip in self.SKIP_DIRS):
                    continue

                if path.is_file() and fnmatch.fnmatch(str(path), f"**/{pattern.lstrip('**/')}"):
                    if path not in found:
                        found.append(path)

        return found

    def _extract_tools(self, tool_file: Path) -> list[dict[str, Any]]:
        """Extract tool definitions from a file.

        Args:
            tool_file: Path to the tool definition file.

        Returns:
            List of tool definitions.
        """
        tools = []

        try:
            content = tool_file.read_text(encoding="utf-8", errors="ignore")
            suffix = tool_file.suffix.lower()

            if suffix == ".py":
                tools = self._extract_tools_from_python(content)
            elif suffix == ".json":
                tools = self._extract_tools_from_json(content)
            elif suffix in (".yaml", ".yml"):
                tools = self._extract_tools_from_yaml(content)

        except Exception:
            pass

        return tools

    def _extract_tools_from_python(self, content: str) -> list[dict[str, Any]]:
        """Extract tool definitions from Python code.

        Supports:
        - LangChain @tool decorator
        - OpenAI function calling format
        - Custom tool classes

        Args:
            content: Python source code.

        Returns:
            List of tool definitions.
        """
        tools = []

        # Look for @tool decorated functions (LangChain style)
        tool_pattern = r'@tool(?:\([^)]*\))?\s*\ndef\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?\s*:\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')'
        for match in re.finditer(tool_pattern, content, re.DOTALL):
            name = match.group(1)
            docstring = match.group(2).strip()
            tools.append(
                {
                    "name": name,
                    "description": docstring[:500],
                }
            )

        # Look for function definitions with docstrings that might be tools
        func_pattern = (
            r'def\s+(\w+)\s*\([^)]*\)\s*(?:->.*?)?\s*:\s*(?:"""|\'\'\')(.*?)(?:"""|\'\'\')'
        )
        for match in re.finditer(func_pattern, content, re.DOTALL):
            name = match.group(1)
            docstring = match.group(2).strip()
            # Skip if already found or if it's a private function
            if not name.startswith("_") and not any(t["name"] == name for t in tools):
                if "tool" in docstring.lower() or "action" in docstring.lower():
                    tools.append(
                        {
                            "name": name,
                            "description": docstring[:500],
                        }
                    )

        # Look for OpenAI function calling format
        if "functions" in content or "tools" in content:
            # Try to find function definitions in dicts
            func_def_pattern = r'\{\s*["\']name["\']\s*:\s*["\'](\w+)["\'].*?["\']description["\']\s*:\s*["\']([^"\']+)["\']'
            for match in re.finditer(func_def_pattern, content, re.DOTALL):
                name = match.group(1)
                description = match.group(2)
                if not any(t["name"] == name for t in tools):
                    tools.append(
                        {
                            "name": name,
                            "description": description[:500],
                        }
                    )

        return tools

    def _extract_tools_from_json(self, content: str) -> list[dict[str, Any]]:
        """Extract tool definitions from JSON file.

        Args:
            content: JSON content.

        Returns:
            List of tool definitions.
        """
        tools = []

        try:
            data = json.loads(content)

            # Handle array of tools
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "name" in item:
                        tools.append(
                            {
                                "name": item.get("name"),
                                "description": item.get("description", "")[:500],
                                "parameters": item.get("parameters", {}),
                            }
                        )

            # Handle object with tools/functions key
            elif isinstance(data, dict):
                tool_list = data.get("tools") or data.get("functions") or []
                for item in tool_list:
                    if isinstance(item, dict):
                        func = item.get("function", item)
                        tools.append(
                            {
                                "name": func.get("name"),
                                "description": func.get("description", "")[:500],
                                "parameters": func.get("parameters", {}),
                            }
                        )

        except json.JSONDecodeError:
            pass

        return tools

    def _extract_tools_from_yaml(self, content: str) -> list[dict[str, Any]]:
        """Extract tool definitions from YAML file.

        Args:
            content: YAML content.

        Returns:
            List of tool definitions.
        """
        tools = []

        try:
            import yaml

            data = yaml.safe_load(content)

            if isinstance(data, dict):
                # Look for tools under various keys
                tool_list = data.get("tools") or data.get("functions") or data.get("actions") or []

                for item in tool_list:
                    if isinstance(item, dict) and "name" in item:
                        tools.append(
                            {
                                "name": item.get("name"),
                                "description": item.get("description", "")[:500],
                            }
                        )

        except ImportError:
            # PyYAML not installed, skip YAML parsing
            pass
        except Exception:
            pass

        return tools
