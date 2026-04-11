from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query

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
