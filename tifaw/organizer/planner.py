from __future__ import annotations

import json
import logging
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from tifaw.llm.client import OllamaClient
from tifaw.models.database import Database

logger = logging.getLogger(__name__)

ORGANIZE_SYSTEM_PROMPT = """\
You are a file organization assistant. Given a list of files with their descriptions, \
tags, and categories, propose a clean folder structure to organize them.

Return ONLY valid JSON with no extra text, using this exact schema:
{
  "groups": [
    {
      "folder_name": "Descriptive Folder Name",
      "files": ["/absolute/path/to/file1", "/absolute/path/to/file2"]
    }
  ]
}

Rules:
- Group files by their category, purpose, or logical relationship.
- Use clear, human-readable folder names (e.g. "Invoices", "Photos - Vacation").
- Every file in the input must appear in exactly one group.
- Do NOT rename files, only move them into sub-folders.
- Keep the number of groups reasonable (2-10).
"""

EXTENSION_GROUPS = {
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".ico"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".pages"},
    "Spreadsheets": {".csv", ".xlsx", ".xls", ".tsv", ".ods", ".numbers"},
    "Code": {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".go", ".rs",
        ".java", ".cpp", ".c", ".h", ".rb", ".sh", ".sql", ".swift", ".kt",
    },
    "Data": {".json", ".yaml", ".yml", ".toml", ".xml", ".ini", ".cfg", ".env"},
    "Audio": {".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"},
    "Video": {".mp4", ".mov", ".avi", ".mkv", ".webm", ".wmv", ".flv"},
    "Archives": {".zip", ".tar", ".gz", ".rar", ".7z", ".bz2", ".dmg", ".iso"},
    "Presentations": {".pptx", ".ppt", ".key", ".odp"},
}

# Build a reverse lookup: extension -> group name
_EXT_TO_GROUP: dict[str, str] = {}
for _group_name, _exts in EXTENSION_GROUPS.items():
    for _ext in _exts:
        _EXT_TO_GROUP[_ext] = _group_name


def _plan_by_file_type(folder_path: str, files: list[dict]) -> dict[str, Any]:
    """Group files by their extension into predefined categories."""
    groups: dict[str, list[str]] = defaultdict(list)

    for f in files:
        ext = (f.get("extension") or "").lower()
        group_name = _EXT_TO_GROUP.get(ext, "Other")
        groups[group_name].append(f["path"])

    return {
        "folder": folder_path,
        "groups": [
            {"folder_name": name, "files": paths}
            for name, paths in sorted(groups.items())
        ],
    }


def _plan_by_date(folder_path: str, files: list[dict]) -> dict[str, Any]:
    """Group files by their modification date (YYYY/Month)."""
    groups: dict[str, list[str]] = defaultdict(list)

    for f in files:
        date_str = f.get("modified_at") or f.get("created_at")
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str)
                group_name = f"{dt.year}/{dt.strftime('%B')}"
            except (ValueError, TypeError):
                group_name = "Unknown Date"
        else:
            group_name = "Unknown Date"
        groups[group_name].append(f["path"])

    return {
        "folder": folder_path,
        "groups": [
            {"folder_name": name, "files": paths}
            for name, paths in sorted(groups.items())
        ],
    }


async def _plan_by_ai_content(
    folder_path: str,
    files: list[dict],
    llm: OllamaClient,
) -> dict[str, Any]:
    """Use the LLM to propose a folder structure based on file content/metadata."""
    file_summaries: list[str] = []
    for f in files:
        tags = f.get("tags") or "[]"
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except json.JSONDecodeError:
                tags = []
        summary = (
            f"- {f['path']}  |  category={f.get('category', 'Unknown')}  "
            f"|  tags={tags}  |  description={f.get('description', '')}"
        )
        file_summaries.append(summary)

    prompt = (
        f"Here are the files currently in '{folder_path}':\n\n"
        + "\n".join(file_summaries)
        + "\n\nPropose an organized folder structure for these files."
    )

    result = await llm.generate_json(prompt, system=ORGANIZE_SYSTEM_PROMPT)

    result["folder"] = folder_path
    for group in result.get("groups", []):
        group.setdefault("folder_name", "Misc")
        group.setdefault("files", [])

    return result


async def _get_files_under(
    db: Database, folder_path: str, limit: int = 1000,
) -> list[dict]:
    """Return files whose ``path`` is under *folder_path*.

    Works for any subfolder, not just top-level watch folders.
    Matches only ``tier1`` or ``indexed`` files so we don't
    touch files that errored out.
    """
    prefix = folder_path.rstrip("/") + "/"
    cursor = await db.db.execute(
        """SELECT * FROM files
        WHERE path LIKE ? ESCAPE '\\'
          AND status IN ('indexed', 'tier1')
        ORDER BY path
        LIMIT ?""",
        (prefix.replace("\\", "\\\\").replace("%", "\\%")
         .replace("_", "\\_") + "%", limit),
    )
    rows = await cursor.fetchall()
    return [dict(r) for r in rows]


async def generate_organize_plan(
    folder_path: str,
    db: Database,
    llm: OllamaClient | None = None,
    strategy: str = "file_type",
) -> dict[str, Any]:
    """Fetch indexed files in *folder_path* and build an organization plan.

    Strategies:
      - ``file_type``: deterministic grouping by file extension.
      - ``ai_content``: LLM-based grouping using descriptions/tags/categories.
      - ``date``: grouping by modification date (YYYY/Month).
    """
    files = await _get_files_under(db, folder_path, limit=1000)
    if not files:
        return {"folder": folder_path, "groups": []}

    if strategy == "ai_content":
        if llm is None:
            raise ValueError("LLM client required for ai_content strategy")
        return await _plan_by_ai_content(folder_path, files, llm)
    elif strategy == "date":
        return _plan_by_date(folder_path, files)
    else:
        return _plan_by_file_type(folder_path, files)


async def execute_organize_plan(plan: dict[str, Any], db: Database) -> dict[str, Any]:
    """Move files on disk according to *plan* and update the database paths."""

    base = Path(plan["folder"])
    moved: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for group in plan.get("groups", []):
        target_dir = base / group["folder_name"]
        target_dir.mkdir(parents=True, exist_ok=True)

        for file_path_str in group.get("files", []):
            src = Path(file_path_str)
            dst = target_dir / src.name

            if not src.exists():
                errors.append({"file": file_path_str, "error": "source not found"})
                continue

            if dst.exists():
                errors.append({"file": file_path_str, "error": "destination already exists"})
                continue

            try:
                shutil.move(str(src), str(dst))
                new_path = str(dst)

                # Update the DB record
                file_record = await db.get_file_by_path(file_path_str)
                if file_record:
                    await db.update_file_path(file_record["id"], new_path, dst.name)

                moved.append({"from": file_path_str, "to": new_path})
                logger.info("Moved %s -> %s", file_path_str, new_path)
            except Exception as exc:
                errors.append({"file": file_path_str, "error": str(exc)})
                logger.error("Failed to move %s: %s", file_path_str, exc)

    return {"moved": len(moved), "errors": len(errors), "details": moved, "error_details": errors}
