from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


def _default_data_dir() -> str:
    return str(Path.home() / ".tifaw")


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma4:e4b"
    host: str = "127.0.0.1"
    port: int = 8321
    data_dir: str = Field(default_factory=_default_data_dir)

    # Loaded from config.yaml
    watch_folders: list[str] = Field(default_factory=lambda: ["~/Downloads", "~/Desktop"])
    project_directories: list[str] = Field(default_factory=lambda: ["~/Projects"])
    rename_enabled: bool = True
    rename_auto_approve: bool = False
    cleanup_threshold_days: int = 90
    max_file_size_mb: int = 100
    supported_extensions: list[str] = Field(default_factory=list)

    model_config = {"env_prefix": "", "env_file": ".env", "extra": "ignore"}

    def resolve_watch_folders(self) -> list[Path]:
        return [Path(f).expanduser().resolve() for f in self.watch_folders]

    def resolve_project_directories(self) -> list[Path]:
        return [Path(d).expanduser().resolve() for d in self.project_directories]

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir).expanduser() / "tifaw.db"

    @property
    def thumbnails_dir(self) -> Path:
        return Path(self.data_dir).expanduser() / "thumbnails"


def _find_config() -> Path | None:
    """Find config.yaml: user home first, then CWD, then app bundle."""
    user_config = Path.home() / ".tifaw" / "config.yaml"
    if user_config.exists():
        return user_config
    cwd_config = Path("config.yaml")
    if cwd_config.exists():
        return cwd_config
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
        bundle_config = base / "config.yaml"
        if bundle_config.exists():
            return bundle_config
    return None


def load_settings() -> Settings:
    config_path = _find_config()
    yaml_overrides: dict = {}

    if config_path is not None:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}

        yaml_overrides["watch_folders"] = raw.get("watch_folders", [])
        yaml_overrides["project_directories"] = raw.get("project_directories", [])

        rename = raw.get("rename", {})
        yaml_overrides["rename_enabled"] = rename.get("enabled", True)
        yaml_overrides["rename_auto_approve"] = rename.get("auto_approve", False)

        cleanup = raw.get("cleanup", {})
        yaml_overrides["cleanup_threshold_days"] = cleanup.get("threshold_days", 90)

        indexing = raw.get("indexing", {})
        yaml_overrides["max_file_size_mb"] = indexing.get("max_file_size_mb", 100)
        yaml_overrides["supported_extensions"] = indexing.get("supported_extensions", [])

    settings = Settings(**yaml_overrides)

    # Ensure data directories exist
    os.makedirs(settings.data_dir, exist_ok=True)
    os.makedirs(settings.thumbnails_dir, exist_ok=True)

    return settings
