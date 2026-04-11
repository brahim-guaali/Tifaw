from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tifaw.duplicates.detector import (
    detect_duplicates,
    get_pending_duplicates,
    resolve_duplicate,
)

router = APIRouter(tags=["duplicates"])


class ResolveRequest(BaseModel):
    keep_file_id: int


@router.get("/duplicates")
async def list_duplicates():
    from tifaw.main import db

    duplicates = await get_pending_duplicates(db)
    return {"duplicates": duplicates, "count": len(duplicates)}


@router.post("/duplicates/scan")
async def scan_duplicates():
    from tifaw.main import db

    result = await detect_duplicates(db)
    return result


@router.post("/duplicates/{duplicate_id}/resolve")
async def resolve(duplicate_id: int, body: ResolveRequest):
    from tifaw.main import db

    result = await resolve_duplicate(duplicate_id, body.keep_file_id, db)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result
