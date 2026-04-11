from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from tifaw.cleanup.stale import calculate_cleanup_savings, delete_files, find_stale_files

router = APIRouter(tags=["cleanup"])


@router.get("/cleanup/stale")
async def get_stale_files(days: int = Query(default=90, ge=1)):
    from tifaw.main import db

    stale = await find_stale_files(db, threshold_days=days)
    savings = await calculate_cleanup_savings(stale)
    return {
        "threshold_days": days,
        "stale_files": stale,
        "total_count": len(stale),
        "total_savings_bytes": savings,
    }


class DeleteRequest(BaseModel):
    file_ids: list[int]


@router.post("/cleanup/delete")
async def delete_stale_files(body: DeleteRequest):
    from tifaw.main import db

    result = await delete_files(body.file_ids, db)
    return result
