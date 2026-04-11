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
