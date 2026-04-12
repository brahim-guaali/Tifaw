from __future__ import annotations

import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tifaw.duplicates.detector import (
    detect_duplicates,
    get_pending_duplicates,
    resolve_duplicate,
)

logger = logging.getLogger(__name__)

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


@router.get("/duplicates/advice")
async def get_duplicate_advice():
    """Get AI-powered advice on which duplicate files to keep."""
    from tifaw.main import db, llm

    duplicates = await get_pending_duplicates(db)
    if not duplicates:
        return {"advice": [], "count": 0}

    advice = []
    for dup in duplicates[:10]:  # Limit to 10 pairs
        file_a = await db.get_file(dup["file_id_a"])
        file_b = await db.get_file(dup["file_id_b"])
        if not file_a or not file_b:
            continue

        pair_info = {
            "file_a": {"filename": file_a["filename"], "size": file_a.get("size_bytes"), "created": file_a.get("created_at"), "description": file_a.get("description")},
            "file_b": {"filename": file_b["filename"], "size": file_b.get("size_bytes"), "created": file_b.get("created_at"), "description": file_b.get("description")},
            "similarity_type": dup.get("similarity_type"),
        }

        try:
            result = await llm.generate_json(
                prompt=f"These two files appear to be duplicates:\n{json.dumps(pair_info, indent=2)}\n\nWhich file should the user keep?",
                system='Respond with ONLY JSON: {"keep": "a" or "b", "reason": "brief reason", "confidence": 1-5}',
            )
            advice.append({
                "duplicate_id": dup["id"],
                "file_a": {"id": dup["file_id_a"], "filename": file_a["filename"]},
                "file_b": {"id": dup["file_id_b"], "filename": file_b["filename"]},
                "keep": result.get("keep", "a"),
                "reason": result.get("reason", ""),
                "confidence": result.get("confidence", 3),
            })
        except Exception as e:
            logger.debug("Duplicate advice failed for %d: %s", dup["id"], e)

    return {"advice": advice, "count": len(advice)}
