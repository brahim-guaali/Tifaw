from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from tifaw.organizer.planner import execute_organize_plan, generate_organize_plan

router = APIRouter(tags=["organize"])


class OrganizePreviewRequest(BaseModel):
    folder: str
    strategy: str = "file_type"


@router.post("/organize/preview")
async def organize_preview(body: OrganizePreviewRequest):
    from tifaw.main import db, llm

    plan = await generate_organize_plan(
        body.folder, db, llm=llm, strategy=body.strategy
    )
    if not plan.get("groups"):
        raise HTTPException(status_code=404, detail="No indexed files found in this folder")
    return plan


@router.post("/organize/execute")
async def organize_execute(plan: dict):
    from tifaw.main import db

    if "folder" not in plan or "groups" not in plan:
        raise HTTPException(
            status_code=422,
            detail="Invalid plan: must contain 'folder' and 'groups'",
        )

    result = await execute_organize_plan(plan, db)
    return result
