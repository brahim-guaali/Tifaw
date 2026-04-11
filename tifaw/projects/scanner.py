from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from pathlib import Path

from tifaw.models.database import Database

logger = logging.getLogger(__name__)

# Marker files that indicate a project, mapped to (stack, package_manager)
_PROJECT_MARKERS: dict[str, tuple[str, str | None]] = {
    "package.json": ("Node.js", None),  # package manager detected from lock files
    "pyproject.toml": ("Python", None),
    "requirements.txt": ("Python", "pip"),
    "setup.py": ("Python", "pip"),
    "Cargo.toml": ("Rust", "cargo"),
    "go.mod": ("Go", "go"),
    "Makefile": ("C/C++", "make"),
    "CMakeLists.txt": ("C/C++", "cmake"),
}

_NODE_LOCK_FILES: dict[str, str] = {
    "package-lock.json": "npm",
    "yarn.lock": "yarn",
    "pnpm-lock.yaml": "pnpm",
}


def _detect_node_package_manager(project_path: Path) -> str:
    for lock_file, pm in _NODE_LOCK_FILES.items():
        if (project_path / lock_file).exists():
            return pm
    return "npm"


def _read_project_name(project_path: Path, stack: str) -> str:
    """Try to read the project name from the manifest file."""
    try:
        if stack == "Node.js" and (project_path / "package.json").exists():
            data = json.loads((project_path / "package.json").read_text())
            return data.get("name", project_path.name)
        if stack == "Rust" and (project_path / "Cargo.toml").exists():
            for line in (project_path / "Cargo.toml").read_text().splitlines():
                if line.strip().startswith("name"):
                    # name = "foo"
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        if stack == "Go" and (project_path / "go.mod").exists():
            first_line = (project_path / "go.mod").read_text().splitlines()[0]
            # module github.com/user/repo
            if first_line.startswith("module"):
                mod_path = first_line.split(None, 1)[1]
                return mod_path.rsplit("/", 1)[-1]
        if stack == "Python" and (project_path / "pyproject.toml").exists():
            for line in (project_path / "pyproject.toml").read_text().splitlines():
                if line.strip().startswith("name"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return project_path.name


async def _get_git_info(project_path: Path) -> dict:
    """Run git commands to gather branch, remote, and last commit info."""
    info: dict[str, str | None] = {
        "git_branch": None,
        "git_remote": None,
        "last_commit_date": None,
        "last_commit_message": None,
    }

    async def _run(cmd: list[str]) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                return stdout.decode().strip()
        except Exception:
            pass
        return None

    info["git_branch"] = await _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    info["git_remote"] = await _run(["git", "config", "--get", "remote.origin.url"])
    info["last_commit_date"] = await _run(["git", "log", "-1", "--format=%aI"])
    info["last_commit_message"] = await _run(["git", "log", "-1", "--format=%s"])

    return info


async def scan_for_projects(directories: list[Path], db: Database) -> list[dict]:
    """Scan directories for dev projects and upsert them into the database."""
    found: list[dict] = []

    for base_dir in directories:
        if not base_dir.is_dir():
            logger.warning("Project directory does not exist: %s", base_dir)
            continue

        for child in sorted(base_dir.iterdir()):
            if not child.is_dir():
                continue
            # .git is required
            if not (child / ".git").is_dir():
                continue

            # Detect stack from marker files
            stack: str | None = None
            package_manager: str | None = None
            for marker, (s, pm) in _PROJECT_MARKERS.items():
                if (child / marker).exists():
                    stack = s
                    package_manager = pm
                    break

            if stack is None:
                # Has .git but no recognized marker, still record it
                stack = "Unknown"

            if stack == "Node.js":
                package_manager = _detect_node_package_manager(child)
            elif stack == "Python" and package_manager is None:
                # Refine Python package manager
                if (child / "poetry.lock").exists():
                    package_manager = "poetry"
                elif (child / "Pipfile.lock").exists():
                    package_manager = "pipenv"
                elif (child / "uv.lock").exists():
                    package_manager = "uv"
                else:
                    package_manager = "pip"

            name = _read_project_name(child, stack)
            git_info = await _get_git_info(child)
            now = datetime.now().isoformat()

            await db.db.execute(
                """INSERT INTO projects (path, name, stack, package_manager,
                    git_remote, git_branch, last_commit_date, last_commit_message,
                    status, scanned_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name, stack=excluded.stack,
                    package_manager=excluded.package_manager,
                    git_remote=excluded.git_remote, git_branch=excluded.git_branch,
                    last_commit_date=excluded.last_commit_date,
                    last_commit_message=excluded.last_commit_message,
                    scanned_at=excluded.scanned_at
                """,
                (
                    str(child),
                    name,
                    stack,
                    package_manager,
                    git_info["git_remote"],
                    git_info["git_branch"],
                    git_info["last_commit_date"],
                    git_info["last_commit_message"],
                    now,
                ),
            )

            project = {
                "path": str(child),
                "name": name,
                "stack": stack,
                "package_manager": package_manager,
                **git_info,
                "scanned_at": now,
            }
            found.append(project)

    await db.db.commit()
    logger.info("Scanned %d projects across %d directories", len(found), len(directories))
    return found
