from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from tifaw.config import load_settings
from tifaw.llm.client import OllamaClient
from tifaw.models.database import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

settings = load_settings()
db = Database(settings.db_path)
# Indexing workers use `llm`; chat uses a dedicated `chat_llm`
# so chat requests never queue behind indexing on the HTTP client
llm = OllamaClient(settings.ollama_base_url, settings.ollama_model)
chat_llm = OllamaClient(settings.ollama_base_url, settings.ollama_model)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Tifaw...")
    await db.connect()
    logger.info("Database connected at %s", settings.db_path)

    connected = await llm.health_check()
    if connected:
        available = await llm.model_available()
        logger.info(
            "Ollama: connected=%s, model=%s available=%s",
            connected,
            settings.ollama_model,
            available,
        )
    else:
        logger.warning("Ollama not reachable at %s", settings.ollama_base_url)

    # Import and start watcher + indexer (Phase 2)
    watcher = None
    indexer_tasks: list = []
    try:
        from tifaw.indexer.queue import IndexQueue
        from tifaw.watcher.observer import FileWatcher

        # Remove DB entries for files that no longer match supported
        # extensions, and for files inside app/framework bundles
        _BUNDLES = (
            ".app/", ".framework/", ".bundle/", ".xcodeproj/",
            ".playground/", ".photoslibrary/", ".musiclibrary/",
            ".imovielibrary/", ".tvlibrary/", ".aplibrary/",
        )
        if settings.supported_extensions:
            exts = set(settings.supported_extensions)
            cursor = await db.db.execute(
                "SELECT id, path, extension FROM files"
            )
            rows = await cursor.fetchall()
            stale_ids = []
            for r in rows:
                path = r["path"] or ""
                ext = (r["extension"] or "").lower()
                if ext and ext not in exts:
                    stale_ids.append(r["id"])
                elif any(b in path for b in _BUNDLES):
                    stale_ids.append(r["id"])
            if stale_ids:
                # Delete in batches to avoid SQLite variable limit
                for i in range(0, len(stale_ids), 500):
                    chunk = stale_ids[i:i + 500]
                    placeholders = ",".join("?" for _ in chunk)
                    await db.db.execute(
                        f"DELETE FROM files WHERE id IN ({placeholders})",
                        chunk,
                    )
                await db.db.commit()
                logger.info(
                    "Removed %d stale files "
                    "(unsupported extensions or app bundles)",
                    len(stale_ids),
                )

        # Prune rename proposals that point to missing files
        pruned = await db.prune_stale_renames()
        if pruned:
            logger.info("Pruned %d stale rename proposals", pruned)

        # Re-queue videos that were indexed without content extraction
        # (before video-frame extraction was supported). Catches any
        # generic description that doesn't describe the visual content.
        video_exts = (
            ".mp4", ".mov", ".avi", ".mkv", ".webm",
            ".wmv", ".flv", ".m4v",
        )
        placeholders = ",".join("?" for _ in video_exts)
        generic_patterns = [
            "%could not be analyzed%",
            "%binary file%",
            "%binary nature%",
            "%binary format%",
            "% extension and %",
            "%.MOV extension%",
            "%.mp4 extension%",
            "%file, likely a recording%",
            "%File: %",  # analyzer fallback description
        ]
        pattern_clause = " OR ".join(
            "description LIKE ?" for _ in generic_patterns
        )
        cursor = await db.db.execute(
            f"SELECT COUNT(*) as c FROM files "
            f"WHERE status='indexed' "
            f"AND extension IN ({placeholders}) "
            f"AND ({pattern_clause})",
            (*video_exts, *generic_patterns),
        )
        count_row = await cursor.fetchone()
        count = count_row["c"] if count_row else 0
        if count:
            await db.db.execute(
                f"UPDATE files SET status='pending' "
                f"WHERE status='indexed' "
                f"AND extension IN ({placeholders}) "
                f"AND ({pattern_clause})",
                (*video_exts, *generic_patterns),
            )
            await db.db.commit()
            logger.info(
                "Re-queued %d videos for content re-extraction",
                count,
            )

        index_queue = IndexQueue()
        app.state.index_queue = index_queue

        watcher = FileWatcher(settings, db, index_queue)
        watcher.start()
        app.state.watcher = watcher
        logger.info("File watcher started for: %s", settings.watch_folders)

        indexer_tasks = index_queue.start_workers(db, llm, settings)

        # Re-queue any files stuck in "pending" from previous runs
        await index_queue.recover_pending(db)
    except ImportError:
        logger.info("Watcher/indexer not yet implemented, skipping")

    yield

    if watcher:
        watcher.stop()
    for task in indexer_tasks:
        task.cancel()
    await llm.close()
    await chat_llm.close()
    await db.close()
    logger.info("Tifaw stopped.")


app = FastAPI(
    title="Tifaw",
    description="Local AI desktop assistant & smart file organizer",
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Routes ---

from tifaw.api.routes_chat import router as chat_router  # noqa: E402
from tifaw.api.routes_cleanup import router as cleanup_router  # noqa: E402
from tifaw.api.routes_config import router as config_router  # noqa: E402
from tifaw.api.routes_digest import router as digest_router  # noqa: E402
from tifaw.api.routes_documents import router as documents_router  # noqa: E402
from tifaw.api.routes_duplicates import router as duplicates_router  # noqa: E402
from tifaw.api.routes_faces import router as faces_router  # noqa: E402
from tifaw.api.routes_files import router as files_router  # noqa: E402
from tifaw.api.routes_folders import router as folders_router  # noqa: E402
from tifaw.api.routes_onboarding import router as onboarding_router  # noqa: E402
from tifaw.api.routes_organize import router as organize_router  # noqa: E402
from tifaw.api.routes_overview import router as overview_router  # noqa: E402
from tifaw.api.routes_photos import router as photos_router  # noqa: E402
from tifaw.api.routes_projects import router as projects_router  # noqa: E402
from tifaw.api.routes_rename import router as rename_router  # noqa: E402
from tifaw.api.routes_search import router as search_router  # noqa: E402
from tifaw.api.routes_status import router as status_router  # noqa: E402

app.include_router(status_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(search_router, prefix="/api")
app.include_router(rename_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(organize_router, prefix="/api")
app.include_router(folders_router, prefix="/api")
app.include_router(duplicates_router, prefix="/api")
app.include_router(cleanup_router, prefix="/api")
app.include_router(projects_router, prefix="/api")
app.include_router(digest_router, prefix="/api")
app.include_router(config_router, prefix="/api")
app.include_router(faces_router, prefix="/api")
app.include_router(overview_router, prefix="/api")
app.include_router(photos_router, prefix="/api")
app.include_router(documents_router, prefix="/api")
app.include_router(onboarding_router, prefix="/api")

# Serve frontend as static files (must be last)
if getattr(sys, "frozen", False):
    # Inside .app bundle: PyInstaller extracts data to sys._MEIPASS
    _base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    frontend_dir = os.path.join(_base, "frontend")
else:
    frontend_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
frontend_dir = os.path.normpath(frontend_dir)

if os.path.isdir(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
else:
    logger.warning("Frontend directory not found at %s", frontend_dir)


def run():
    uvicorn.run(
        "tifaw.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )


if __name__ == "__main__":
    run()
