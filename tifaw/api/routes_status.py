from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(tags=["status"])


@router.get("/status")
async def get_status():
    from tifaw.main import db, llm, settings

    stats = await db.get_stats()
    connected = await llm.health_check()
    model_ok = await llm.model_available() if connected else False

    queue_size = 0
    try:
        from tifaw.main import app
        if hasattr(app.state, "index_queue"):
            queue_size = app.state.index_queue.size()
    except Exception:
        pass

    return {
        "ollama_connected": connected,
        "model_available": model_ok,
        "total_files": stats["total_files"],
        "indexed_files": stats["indexed_files"],
        "pending_files": stats["pending_files"],
        "pending_renames": stats["pending_renames"],
        "queue_size": queue_size,
        "watched_folders": [str(f) for f in settings.resolve_watch_folders()],
    }


@router.post("/requeue-pending")
async def requeue_pending():
    """Re-queue all pending files for analysis."""
    from tifaw.main import app, db

    queue = app.state.index_queue if hasattr(app.state, "index_queue") else None
    if not queue:
        return {"error": "Index queue not available"}

    cursor = await db.db.execute(
        "SELECT path FROM files WHERE status='pending' LIMIT 5000"
    )
    rows = await cursor.fetchall()
    for row in rows:
        await queue.enqueue(row["path"], priority=5)

    return {"queued": len(rows)}


@router.post("/import/spotlight")
async def import_spotlight(folder: str | None = None):
    """Import files from macOS Spotlight index. Bypasses Full Disk Access restrictions."""
    from tifaw.indexer.spotlight import import_and_queue
    from tifaw.main import app, db, settings

    queue = app.state.index_queue if hasattr(app.state, "index_queue") else None
    if not queue:
        return {"error": "Index queue not available"}

    folders = [folder] if folder else [str(f) for f in settings.resolve_watch_folders()]
    total = 0

    for f in folders:
        count = await import_and_queue(
            f, db, queue,
            supported_extensions=set(settings.supported_extensions),
            max_file_size=settings.max_file_size_mb * 1024 * 1024,
        )
        total += count

    return {
        "imported": total,
        "folders_scanned": folders,
        "message": f"Imported {total} new files. They will be analyzed in the background.",
    }
