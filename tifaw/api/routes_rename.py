from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["rename"])


@router.get("/renames/pending")
async def get_pending_renames():
    from tifaw.main import db

    files = await db.get_pending_renames()
    proposals = []
    for f in files:
        tags = f.get("tags")
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                tags = []

        proposals.append({
            "file_id": f["id"],
            "current_name": f["filename"],
            "suggested_name": f["suggested_name"],
            "path": f["path"],
            "extension": f.get("extension", ""),
            "size_bytes": f.get("size_bytes"),
            "description": f["description"],
            "tags": tags or [],
            "category": f.get("category"),
            "content_preview": f.get("content_preview"),
            "is_image": f.get("extension", "") in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"),
        })
    return {"proposals": proposals, "count": len(proposals)}


@router.post("/renames/{file_id}/approve")
async def approve_rename(file_id: int):
    from tifaw.main import db

    file = await db.approve_rename(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="No pending rename for this file")

    old_path = Path(file["path"])
    suggested = file["suggested_name"]
    new_path = old_path.parent / suggested

    # Handle conflicts
    counter = 1
    stem = new_path.stem
    suffix = new_path.suffix
    while new_path.exists():
        new_path = old_path.parent / f"{stem}-{counter}{suffix}"
        counter += 1

    try:
        os.rename(old_path, new_path)
        await db.update_file_path(file_id, str(new_path), new_path.name)
        # Store original name for undo
        await db.db.execute(
            "UPDATE files SET original_name=? WHERE id=?", (file["filename"], file_id)
        )
        await db.db.commit()
        return {"status": "renamed", "old_name": file["filename"], "new_name": new_path.name}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Rename failed: {e}")


@router.post("/renames/{file_id}/dismiss")
async def dismiss_rename(file_id: int):
    from tifaw.main import db

    await db.dismiss_rename(file_id)
    return {"status": "dismissed", "file_id": file_id}


@router.post("/renames/{file_id}/undo")
async def undo_rename(file_id: int):
    from tifaw.main import db

    file = await db.get_file(file_id)
    if not file or not file.get("original_name"):
        raise HTTPException(status_code=404, detail="No rename to undo")

    current_path = Path(file["path"])
    original_path = current_path.parent / file["original_name"]

    if original_path.exists():
        raise HTTPException(status_code=409, detail="Original filename already taken")

    try:
        os.rename(current_path, original_path)
        await db.update_file_path(file_id, str(original_path), file["original_name"])
        await db.db.execute(
            "UPDATE files SET original_name=NULL, rename_status=NULL, suggested_name=NULL WHERE id=?",
            (file_id,),
        )
        await db.db.commit()
        return {"status": "undone", "restored_name": file["original_name"]}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Undo failed: {e}")
