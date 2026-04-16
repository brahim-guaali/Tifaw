from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

from tifaw.llm.client import OllamaClient

logger = logging.getLogger(__name__)

ProjectInfo = dict[str, Any]


async def _run_git(cmd: list[str], cwd: Path) -> str | None:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode().strip()
    except Exception:
        pass
    return None


async def analyze_project(project_path: Path, llm: OllamaClient) -> ProjectInfo:
    """Analyze a project: read README, get AI description, gather git info."""
    project_path = Path(project_path)
    info: ProjectInfo = {
        "path": str(project_path),
        "name": project_path.name,
        "description": None,
        "git_branch": None,
        "git_remote": None,
        "last_commit_date": None,
        "last_commit_message": None,
    }

    # Gather git info
    info["git_branch"] = await _run_git(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], project_path
    )
    info["git_remote"] = await _run_git(
        ["git", "config", "--get", "remote.origin.url"], project_path
    )
    info["last_commit_date"] = await _run_git(
        ["git", "log", "-1", "--format=%aI"], project_path
    )
    info["last_commit_message"] = await _run_git(
        ["git", "log", "-1", "--format=%s"], project_path
    )

    # Try to read README for AI description
    readme_text: str | None = None
    for readme_name in ("README.md", "README.rst", "README.txt", "README"):
        readme_path = project_path / readme_name
        if readme_path.exists():
            try:
                readme_text = readme_path.read_text(errors="replace")[:2000]
            except OSError:
                pass
            break

    # Read dependency files for richer analysis
    deps_text = ""
    dep_files = {
        "package.json": "Node.js",
        "requirements.txt": "Python",
        "Pipfile": "Python",
        "pyproject.toml": "Python",
        "Cargo.toml": "Rust",
        "go.mod": "Go",
        "Gemfile": "Ruby",
        "pom.xml": "Java",
        "build.gradle": "Java/Kotlin",
        "composer.json": "PHP",
    }
    detected_stack = []
    for dep_file, lang in dep_files.items():
        dep_path = project_path / dep_file
        if dep_path.exists():
            detected_stack.append(lang)
            try:
                deps_text += f"\n--- {dep_file} ---\n{dep_path.read_text(errors='replace')[:500]}\n"
            except OSError:
                pass

    info["stack"] = ", ".join(sorted(set(detected_stack))) if detected_stack else None

    # Combined LLM analysis with README + deps
    analysis_input = ""
    if readme_text:
        analysis_input += f"README:\n{readme_text}\n\n"
    if deps_text:
        analysis_input += f"Dependencies:\n{deps_text}\n\n"

    if analysis_input:
        try:
            result = await llm.generate_json(
                prompt=(
                    "Analyze this software project:\n\n"
                    f"{analysis_input}\n\n"
                    f"Project name: {project_path.name}"
                ),
                system=(
                    'Respond with ONLY JSON:'
                    ' {"description": "1-sentence description",'
                    ' "frameworks": ["framework1", "framework2"],'
                    ' "type": "web app/CLI/library/API/mobile/etc",'
                    ' "health":'
                    ' "active/maintained/stale/abandoned"}'
                ),
            )
            info["description"] = result.get("description", info.get("description"))
            frameworks = result.get("frameworks", [])
            if frameworks:
                info["stack"] = ", ".join(frameworks)
            info["project_type"] = result.get("type")
            info["health"] = result.get("health")
        except Exception as exc:
            logger.warning("LLM analysis failed for %s: %s", project_path.name, exc)
            # Fallback to simple README description
            if readme_text:
                try:
                    description = await llm.generate(
                        "Based on this README, provide a"
                        " single-sentence description:"
                        f"\n\n{readme_text}",
                        temperature=0.2,
                    )
                    info["description"] = description.strip()
                except Exception:
                    pass

    return info
