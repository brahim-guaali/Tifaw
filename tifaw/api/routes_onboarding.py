from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["onboarding"])

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


@router.get("/onboarding/status")
async def onboarding_status():
    from tifaw.main import db, llm, settings

    # Check if onboarding was completed
    try:
        cursor = await db.db.execute(
            "SELECT value FROM settings WHERE key='onboarding_complete'"
        )
        row = await cursor.fetchone()
        complete = row["value"] == "true" if row else False
    except Exception:
        complete = False

    # Check user identity
    try:
        cursor = await db.db.execute(
            "SELECT value FROM settings WHERE key='user_identity'"
        )
        row = await cursor.fetchone()
        user_identity = row["value"] if row else None
    except Exception:
        user_identity = None

    # Ollama status
    ollama_connected = await llm.health_check()
    model_available = await llm.model_available() if ollama_connected else False

    # File counts
    try:
        cursor = await db.db.execute("SELECT COUNT(*) as cnt FROM files")
        row = await cursor.fetchone()
        total_files = row["cnt"] if row else 0
    except Exception:
        total_files = 0

    return {
        "onboarding_complete": complete,
        "ollama_connected": ollama_connected,
        "model_available": model_available,
        "total_files": total_files,
        "watch_folders": settings.watch_folders,
        "user_identity": user_identity,
    }


class OnboardingComplete(BaseModel):
    watch_folders: list[str] | None = None
    user_name: str | None = None


@router.post("/onboarding/complete")
async def complete_onboarding(body: OnboardingComplete):
    from tifaw.main import db

    # Save watch folders if provided
    if body.watch_folders is not None:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                config = yaml.safe_load(f) or {}
        else:
            config = {}

        config["watch_folders"] = body.watch_folders

        with open(CONFIG_PATH, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        # Reload settings and restart watcher
        import tifaw.main as main_module
        from tifaw.config import load_settings

        old_folders = set(main_module.settings.watch_folders)
        main_module.settings = load_settings()
        new_folders = set(main_module.settings.watch_folders)

        if old_folders != new_folders:
            try:
                watcher = getattr(main_module.app.state, "watcher", None)
                if watcher:
                    watcher.stop()
                    from tifaw.watcher.observer import FileWatcher

                    new_watcher = FileWatcher(
                        main_module.settings,
                        main_module.db,
                        main_module.app.state.index_queue,
                    )
                    new_watcher.start()
                    main_module.app.state.watcher = new_watcher
                    logger.info(
                        "Watcher restarted with new folders: %s",
                        main_module.settings.watch_folders,
                    )
            except Exception as e:
                logger.warning("Failed to restart watcher: %s", e)

    # Save user identity if provided
    if body.user_name:
        await db.db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("user_identity", body.user_name),
        )

    # Mark onboarding as complete
    await db.db.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        ("onboarding_complete", "true"),
    )
    await db.db.commit()

    return {"status": "ok"}
