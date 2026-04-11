from __future__ import annotations

from fastapi import APIRouter, Query

from tifaw.digest.summary import generate_digest

router = APIRouter(tags=["digest"])


@router.get("/digest")
async def get_digest(days: int = Query(default=1, ge=1)):
    from tifaw.main import db

    digest = await generate_digest(db, days=days)
    return digest
