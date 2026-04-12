from __future__ import annotations

import json
import mimetypes
import os
import subprocess
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

router = APIRouter(tags=["files"])


def _parse_tags(file_dict: dict) -> dict:
    tags = file_dict.get("tags")
    if isinstance(tags, str):
        try:
            file_dict["tags"] = json.loads(tags)
        except json.JSONDecodeError:
            file_dict["tags"] = []
    elif tags is None:
        file_dict["tags"] = []
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
                cat: [_parse_tags(f) for f in files] for cat, files in groups.items()
            },
        }

    files = await db.get_files(
        watch_folder=watch_folder,
        category=category,
        status=status,
        limit=limit,
        offset=offset,
    )
    return {"files": [_parse_tags(f) for f in files]}


@router.get("/files/{file_id}")
async def get_file(file_id: int):
    from tifaw.main import db

    file = await db.get_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")
    return _parse_tags(file)


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
