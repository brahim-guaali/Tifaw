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

    if readme_text:
        try:
            prompt = (
                "Based on this README, provide a single-sentence description of what "
                "this project does. Be concise and specific.\n\n"
                f"README:\n{readme_text}"
            )
            description = await llm.generate(prompt, temperature=0.2)
            info["description"] = description.strip()
        except Exception as exc:
            logger.warning("LLM analysis failed for %s: %s", project_path.name, exc)

    return info
