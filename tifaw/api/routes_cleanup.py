from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel

from tifaw.cleanup.stale import calculate_cleanup_savings, delete_files, find_stale_files

logger = logging.getLogger(__name__)

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


@router.get("/cleanup/ai-suggestions")
async def get_ai_cleanup_suggestions(days: int = Query(default=90, ge=1)):
    """Get AI-powered suggestions on which stale files are safe to delete."""
    from tifaw.main import db, llm

    stale = await find_stale_files(db, threshold_days=days)
    if not stale:
        return {"suggestions": [], "count": 0}

    # Batch files for LLM analysis (up to 20)
    batch = stale[:20]
    file_summaries = []
    for f in batch:
        file_summaries.append({
            "id": f["id"],
            "filename": f["filename"],
            "category": f.get("category"),
            "description": (f.get("description") or "")[:100],
            "size_bytes": f.get("size_bytes"),
            "created_at": (f.get("created_at") or "")[:10],
            "modified_at": (f.get("modified_at") or "")[:10],
            "extension": f.get("extension"),
        })

    try:
        result = await llm.generate_json(
            prompt=f"These files haven't been modified in {days}+ days. Rate each 1-5 on how safe to delete (5=very safe). Consider: screenshots are usually safe, important documents are not.\n\n{json.dumps(file_summaries, indent=2)}",
            system='Respond with ONLY a JSON array: [{"id": file_id, "safe_score": 1-5, "reason": "brief reason"}]',
        )

        if isinstance(result, dict) and "suggestions" in result:
            result = result["suggestions"]
        if not isinstance(result, list):
            result = []

        # Merge with file data
        score_map = {r.get("id"): r for r in result if isinstance(r, dict)}
        suggestions = []
        for f in batch:
            ai = score_map.get(f["id"], {})
            suggestions.append({
                "id": f["id"],
                "filename": f["filename"],
                "category": f.get("category"),
                "description": f.get("description"),
                "size_bytes": f.get("size_bytes"),
                "created_at": f.get("created_at"),
                "safe_score": ai.get("safe_score", 3),
                "reason": ai.get("reason", ""),
            })

        suggestions.sort(key=lambda s: s["safe_score"], reverse=True)
        return {"suggestions": suggestions, "count": len(suggestions)}

    except Exception as e:
        logger.error("AI cleanup suggestions failed: %s", e)
        return {"suggestions": [], "count": 0, "error": str(e)}
