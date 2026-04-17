from __future__ import annotations

import json

from fastapi import APIRouter, Query

router = APIRouter(tags=["search"])


@router.get("/search")
async def search_files(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=20, le=100),
    sort: str = Query(default="relevance"),
):
    from tifaw.main import db

    results = await db.search_files(q, limit=limit, sort=sort)
    for r in results:
        tags = r.get("tags")
        if isinstance(tags, str):
            try:
                r["tags"] = json.loads(tags)
            except json.JSONDecodeError:
                r["tags"] = []
        elif tags is None:
            r["tags"] = []
    return {"query": q, "results": results, "count": len(results)}
