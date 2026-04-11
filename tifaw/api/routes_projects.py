from __future__ import annotations

from fastapi import APIRouter, HTTPException

from tifaw.projects.scanner import scan_for_projects

router = APIRouter(tags=["projects"])


@router.get("/projects")
async def list_projects():
    from tifaw.main import db

    cursor = await db.db.execute("SELECT * FROM projects ORDER BY name ASC")
    rows = await cursor.fetchall()
    return {"projects": [dict(r) for r in rows]}


@router.get("/projects/{project_id}")
async def get_project(project_id: int):
    from tifaw.main import db

    cursor = await db.db.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
    row = await cursor.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return dict(row)


@router.post("/projects/scan")
async def trigger_scan():
    from tifaw.main import db, settings

    directories = settings.resolve_project_directories()
    projects = await scan_for_projects(directories, db)
    return {"scanned": len(projects), "projects": projects}
