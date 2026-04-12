from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(tags=["files"])


def _parse_json_fields(file_dict: dict) -> dict:
    tags = file_dict.get("tags")
    if isinstance(tags, str):
        try:
            file_dict["tags"] = json.loads(tags)
        except json.JSONDecodeError:
            file_dict["tags"] = []
    elif tags is None:
        file_dict["tags"] = []

    metadata = file_dict.get("metadata")
    if isinstance(metadata, str):
        try:
            file_dict["metadata"] = json.loads(metadata)
        except json.JSONDecodeError:
            file_dict["metadata"] = None

    return file_dict


@router.get("/files")
async def list_files(
    watch_folder: str | None = None,
    category: str | None = None,
    status: str | None = None,
    grouped: bool = False,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
):
    from tifaw.main import db

    if grouped and watch_folder:
        groups = await db.get_files_grouped_by_category(watch_folder)
        return {
            "grouped": True,
            "watch_folder": watch_folder,
            "categories": {
                cat: [_parse_json_fields(f) for f in files] for cat, files in groups.items()
            },
        }

    files = await db.get_files(
        watch_folder=watch_folder,
        category=category,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"files": [_parse_json_fields(f) for f in files]}


@router.get("/files/{file_id}")
async def get_file(file_id: int):
    from tifaw.main import db

    file = await db.get_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    return _parse_json_fields(file)


@router.post("/files/{file_id}/reindex")
async def reindex_file(file_id: int):
    from tifaw.main import app, db

    file = await db.get_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    await db.update_file_status(file_id, "pending")

    if hasattr(app.state, "index_queue"):
        await app.state.index_queue.enqueue(file["path"], priority=0)

    return {"status": "queued", "file_id": file_id}


@router.get("/files/{file_id}/preview")
async def preview_file(file_id: int):
    """Serve the actual file for preview (images, PDFs, etc.)."""
    from tifaw.main import db

    file = await db.get_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    path = Path(file["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File no longer exists on disk")

    media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@router.post("/files/{file_id}/reveal")
async def reveal_file(file_id: int):
    """Open the file's parent folder in Finder and select the file."""
    from tifaw.main import db

    file = await db.get_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    path = Path(file["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File no longer exists on disk")

    if sys.platform == "darwin":
        subprocess.Popen(["open", "-R", str(path)])
    elif sys.platform == "win32":
        subprocess.Popen(["explorer", "/select,", str(path)])
    else:
        # Linux: open parent folder
        subprocess.Popen(["xdg-open", str(path.parent)])

    return {"status": "revealed", "path": str(path)}


@router.delete("/files/{file_id}")
async def delete_file(file_id: int, from_disk: bool = Query(default=False)):
    """Delete a file from the database, and optionally from disk."""
    from tifaw.main import db

    file = await db.get_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    if from_disk:
        path = Path(file["path"])
        if path.exists():
            try:
                if sys.platform == "darwin":
                    # Move to Trash on macOS instead of permanent delete
                    subprocess.run(
                        ["osascript", "-e",
                         f'tell application "Finder" to delete POSIX file "{path}"'],
                        check=True, capture_output=True,
                    )
                else:
                    os.remove(path)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Failed to delete file: {e}")

    await db.db.execute("DELETE FROM files WHERE id=?", (file_id,))
    await db.db.commit()

    return {"status": "deleted", "file_id": file_id, "from_disk": from_disk}


class RenameRequest(BaseModel):
    new_name: str


class BulkContextRequest(BaseModel):
    file_ids: list[int]
    context: str


class BulkDeleteRequest(BaseModel):
    file_ids: list[int]


@router.put("/files/{file_id}/rename")
async def rename_file(file_id: int, body: RenameRequest):
    """Rename a file on disk and in the database."""
    from tifaw.main import db

    file = await db.get_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    old_path = Path(file["path"])
    if not old_path.exists():
        raise HTTPException(status_code=404, detail="File no longer exists on disk")

    new_name = body.new_name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    new_path = old_path.parent / new_name
    if new_path.exists() and new_path != old_path:
        raise HTTPException(status_code=409, detail="A file with that name already exists")

    old_path.rename(new_path)
    await db.update_file_path(file_id, str(new_path), new_name)

    return {"status": "renamed", "file_id": file_id, "old_name": file["filename"], "new_name": new_name}


@router.post("/files/bulk/add-context")
async def bulk_add_context(body: BulkContextRequest):
    """Add context/tags to multiple files."""
    from tifaw.main import db

    context = body.context.strip()
    if not context:
        raise HTTPException(status_code=400, detail="Context cannot be empty")

    # Add context as a tag to each file
    updated = 0
    for file_id in body.file_ids:
        file = await db.get_file(file_id)
        if not file:
            continue
        tags = file.get("tags") or "[]"
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        # Add context words as tags (avoid duplicates)
        new_tags = [t.strip().lower() for t in context.split(",") if t.strip()]
        for t in new_tags:
            if t not in tags:
                tags.append(t)
        # Update description to include context
        desc = file.get("description") or ""
        if context.lower() not in desc.lower():
            desc = f"{desc} ({context})" if desc else context

        await db.db.execute(
            "UPDATE files SET tags=?, description=? WHERE id=?",
            (json.dumps(tags), desc, file_id),
        )
        updated += 1

    await db.db.commit()
    return {"status": "updated", "updated": updated}


@router.post("/files/bulk/delete")
async def bulk_delete_files(body: BulkDeleteRequest):
    """Delete multiple files (move to Trash)."""
    from tifaw.cleanup.stale import delete_files
    from tifaw.main import db

    result = await delete_files(body.file_ids, db)
    return result
