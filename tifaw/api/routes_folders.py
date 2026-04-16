from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tifaw.smartfolders.collections import (
    create_smart_folder,
    delete_smart_folder,
    get_smart_folder_files,
    get_smart_folders,
)

router = APIRouter(tags=["smart-folders"])


class CreateSmartFolderRequest(BaseModel):
    name: str
    rule: dict[str, Any]
    icon: str | None = None


@router.get("/smart-folders")
async def list_smart_folders():
    from tifaw.main import db

    folders = await get_smart_folders(db)
    # Attach file counts
    for folder in folders:
        files = await get_smart_folder_files(folder["id"], db)
        folder["file_count"] = len(files)
    return {"smart_folders": folders}


@router.get("/smart-folders/{folder_id}/files")
async def smart_folder_files(folder_id: int):
    from tifaw.main import db

    files = await get_smart_folder_files(folder_id, db)
    return {"files": files}


@router.post("/smart-folders")
async def create_folder(body: CreateSmartFolderRequest):
    from tifaw.main import db

    folder = await create_smart_folder(body.name, body.rule, body.icon, db)
    return folder


@router.delete("/smart-folders/{folder_id}")
async def delete_folder(folder_id: int):
    from tifaw.main import db

    deleted = await delete_smart_folder(folder_id, db)
    if not deleted:
        raise HTTPException(status_code=404, detail="Smart folder not found")
    return {"status": "deleted", "id": folder_id}
