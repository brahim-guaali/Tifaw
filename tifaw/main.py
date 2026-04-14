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
llm = OllamaClient(settings.ollama_base_url, settings.ollama_model)


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
    indexer_task = None
    try:
        from tifaw.indexer.queue import IndexQueue
        from tifaw.watcher.observer import FileWatcher

        index_queue = IndexQueue()
        app.state.index_queue = index_queue

        watcher = FileWatcher(settings, db, index_queue)
        watcher.start()
        app.state.watcher = watcher
        logger.info("File watcher started for: %s", settings.watch_folders)

        indexer_task = index_queue.start_worker(db, llm, settings)
        logger.info("Index worker started")

        # Re-queue any files stuck in "pending" from previous runs
        await index_queue.recover_pending(db)
    except ImportError:
        logger.info("Watcher/indexer not yet implemented, skipping")

    yield

    if watcher:
        watcher.stop()
    if indexer_task:
        indexer_task.cancel()
    await llm.close()
    await db.close()
    logger.info("Tifaw stopped.")


app = FastAPI(
    title="Tifaw",
    description="Local AI desktop assistant & smart file organizer",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API Routes ---

from tifaw.api.routes_status import router as status_router
from tifaw.api.routes_files import router as files_router
from tifaw.api.routes_search import router as search_router
from tifaw.api.routes_rename import router as rename_router
from tifaw.api.routes_chat import router as chat_router
from tifaw.api.routes_organize import router as organize_router
from tifaw.api.routes_folders import router as folders_router
from tifaw.api.routes_duplicates import router as duplicates_router
from tifaw.api.routes_cleanup import router as cleanup_router
from tifaw.api.routes_projects import router as projects_router
from tifaw.api.routes_digest import router as digest_router
from tifaw.api.routes_config import router as config_router
from tifaw.api.routes_faces import router as faces_router
from tifaw.api.routes_overview import router as overview_router
from tifaw.api.routes_photos import router as photos_router
from tifaw.api.routes_documents import router as documents_router
from tifaw.api.routes_onboarding import router as onboarding_router

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
