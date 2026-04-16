from __future__ import annotations

import logging
from pathlib import Path

import yaml
from fastapi import APIRouter, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config.yaml"


class ConfigUpdate(BaseModel):
    watch_folders: list[str] | None = None
    project_directories: list[str] | None = None
    rename_enabled: bool | None = None
    rename_auto_approve: bool | None = None
    cleanup_threshold_days: int | None = None
    max_file_size_mb: int | None = None
    recursive: bool | None = None
    supported_extensions: list[str] | None = None
    user_identity: str | None = None


@router.get("/config")
async def get_config():
    if not CONFIG_PATH.exists():
        config = {}
    else:
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}

    # Load user identity from DB
    try:
        from tifaw.main import db
        cursor = await db.db.execute("SELECT value FROM settings WHERE key='user_identity'")
        row = await cursor.fetchone()
        config["user_identity"] = row["value"] if row else None
    except Exception:
        config["user_identity"] = None

    return config


@router.put("/config")
async def update_config(update: ConfigUpdate):
    # Read existing config
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    # Apply updates
    if update.watch_folders is not None:
        config["watch_folders"] = update.watch_folders
    if update.project_directories is not None:
        config["project_directories"] = update.project_directories
    if update.rename_enabled is not None:
        config.setdefault("rename", {})["enabled"] = update.rename_enabled
    if update.rename_auto_approve is not None:
        config.setdefault("rename", {})["auto_approve"] = update.rename_auto_approve
    if update.cleanup_threshold_days is not None:
        config.setdefault("cleanup", {})["threshold_days"] = update.cleanup_threshold_days
    if update.max_file_size_mb is not None:
        config.setdefault("indexing", {})["max_file_size_mb"] = update.max_file_size_mb
    if update.recursive is not None:
        config.setdefault("indexing", {})["recursive"] = update.recursive
    if update.supported_extensions is not None:
        config.setdefault("indexing", {})["supported_extensions"] = update.supported_extensions

    # Save user identity to DB settings (not config.yaml)
    if update.user_identity is not None:
        from tifaw.main import db
        await db.db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            ("user_identity", update.user_identity),
        )
        # Clear cached narrative so it regenerates with the new identity
        await db.db.execute("DELETE FROM settings WHERE key='ai_narrative'")
        await db.db.execute("DELETE FROM settings WHERE key='ai_digest'")
        await db.db.commit()

    # Write back
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)

    # Reload settings and restart watcher with new config
    import tifaw.main as main_module
    from tifaw.config import load_settings

    old_folders = set(main_module.settings.watch_folders)
    main_module.settings = load_settings()
    new_folders = set(main_module.settings.watch_folders)

    # Restart watcher if watch folders changed
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

    return {"status": "saved", "config": config}


@router.get("/browse")
async def browse_directories(path: str = Query(default="~")):
    """List directories at the given path for the folder picker."""
    target = Path(path).expanduser().resolve()

    if not target.is_dir():
        return {"path": str(target), "dirs": [], "error": "Not a directory"}

    dirs = []
    try:
        for entry in sorted(target.iterdir()):
            if entry.name.startswith("."):
                continue
            if entry.is_dir():
                dirs.append({
                    "name": entry.name,
                    "path": str(entry),
                })
    except PermissionError:
        return {"path": str(target), "dirs": [], "error": "Permission denied"}

    parent = str(target.parent) if target != target.parent else None

    return {
        "path": str(target),
        "parent": parent,
        "dirs": dirs,
    }
