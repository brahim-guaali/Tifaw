from __future__ import annotations

import json
import logging
import shutil
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
- Use clear, human-readable folder names (e.g. "Invoices", "Photos - Vacation", "Project Documents").
- Every file in the input must appear in exactly one group.
- Do NOT rename files, only move them into sub-folders.
- Keep the number of groups reasonable (2-10).
"""


async def generate_organize_plan(
    folder_path: str,
    db: Database,
    llm: OllamaClient,
) -> dict[str, Any]:
    """Fetch indexed files in *folder_path* and ask the LLM to propose a folder structure."""

    files = await db.get_files(watch_folder=folder_path, limit=1000)
    if not files:
        return {"folder": folder_path, "groups": []}

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

    # Normalise: ensure top-level 'folder' key is present
    result["folder"] = folder_path
    for group in result.get("groups", []):
        group.setdefault("folder_name", "Misc")
        group.setdefault("files", [])

    return result


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
