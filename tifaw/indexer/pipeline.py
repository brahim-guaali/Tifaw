from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from tifaw.config import Settings
from tifaw.indexer.analyzer import analyze_file
from tifaw.indexer.extractors import extract_content
from tifaw.llm.client import OllamaClient
from tifaw.models.database import Database
from tifaw.renamer.smart_rename import is_generic_name

logger = logging.getLogger(__name__)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _safe_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return datetime.now(tz=timezone.utc).isoformat()


def _file_times(path: Path) -> tuple[str, str]:
    stat = path.stat()
    return _safe_ts(stat.st_birthtime), _safe_ts(stat.st_mtime)


def _should_run_face_detection(
    path: Path, analysis, extraction,
) -> bool:
    """Only run face detection for likely-photo images.

    Skip screenshots, logos, icons, SVGs, and very small images.
    """
    photo_exts = {".jpg", ".jpeg", ".png", ".webp"}
    if path.suffix.lower() not in photo_exts:
        return False
    # Tag-based skip
    tags = {t.lower() for t in (analysis.tags or [])}
    skip_tags = {
        "screenshot", "logo", "icon", "diagram",
        "illustration", "drawing", "chart",
    }
    if analysis.category == "Screenshots" or (tags & skip_tags):
        return False
    # Size-based skip: photos are usually larger than 20 KB
    try:
        if path.stat().st_size < 20_000:
            return False
    except OSError:
        return False
    # Dimension-based skip: need at least 200px on each side
    meta = extraction.metadata or {}
    w, h = meta.get("image_width"), meta.get("image_height")
    if w and h and (w < 200 or h < 200):
        return False
    return True


async def process_file(
    file_path: str, db: Database, llm: OllamaClient, settings: Settings
) -> None:
    path = Path(file_path)

    if not path.exists():
        logger.warning("File no longer exists: %s", file_path)
        return

    existing = await db.get_file_by_path(file_path)

    # Worker deduplication: if another worker already finished this
    # file (status='indexed'), skip unless mtime/size changed.
    current_size = path.stat().st_size
    current_mtime = _safe_ts(path.stat().st_mtime)
    if existing and existing.get("status") == "indexed":
        if (
            existing.get("size_bytes") == current_size
            and existing.get("modified_at") == current_mtime
        ):
            logger.debug("Skipping unchanged file: %s", path.name)
            return

    # Fast-path hash: only recompute if size or mtime changed
    if (
        existing
        and existing.get("file_hash")
        and existing.get("size_bytes") == current_size
        and existing.get("modified_at") == current_mtime
    ):
        current_hash = existing["file_hash"]
    else:
        current_hash = _file_hash(path)

    # Move/rename detection: if a file with the same hash already
    # exists in the DB at a different path (which no longer exists),
    # treat this as a move and keep the analysis.
    if current_hash and not existing:
        moved_from = await db.get_file_by_hash_missing(
            current_hash, file_path,
        )
        if moved_from:
            logger.info(
                "Detected move: %s -> %s",
                moved_from["path"], file_path,
            )
            await db.update_file_path(
                moved_from["id"], file_path, path.name,
            )
            return

    # Determine watch folder
    watch_folder = None
    for folder in settings.resolve_watch_folders():
        if str(path).startswith(str(folder)):
            watch_folder = str(folder)
            break

    created_at, modified_at = _file_times(path)

    extraction = extract_content(path)

    metadata = extraction.metadata
    if metadata and metadata.get("date_taken"):
        created_at = metadata["date_taken"]

    # Resolve GPS coordinates via offline library (no LLM call)
    if metadata and metadata.get("gps_latitude") and metadata.get("gps_longitude"):
        try:
            location = _resolve_location(
                metadata["gps_latitude"], metadata["gps_longitude"],
            )
            if location:
                metadata["location_city"] = location.get("city")
                metadata["location_country"] = location.get("country")
        except Exception:
            logger.debug(
                "Location resolution failed for %s", path.name,
            )

    metadata_json = json.dumps(metadata) if metadata else None

    file_id = await db.upsert_file(
        path=file_path,
        filename=path.name,
        extension=path.suffix.lower(),
        size_bytes=current_size,
        file_hash=current_hash,
        watch_folder=watch_folder,
        created_at=created_at,
        modified_at=modified_at,
        metadata=metadata_json,
    )

    await db.update_file_status(file_id, "indexing")

    # Analyze with LLM (retries handled by client)
    try:
        analysis = await analyze_file(
            filename=path.name,
            file_type=extraction.file_type,
            size_bytes=current_size,
            extraction=extraction,
            llm=llm,
        )
    except Exception as e:
        logger.warning(
            "LLM analysis failed for %s, marking pending: %s",
            path.name, e,
        )
        # Leave status='pending' for later retry by recovery loop
        await db.update_file_status(file_id, "pending")
        return

    suggested_name = None
    if (
        settings.rename_enabled
        and is_generic_name(path.name)
        and analysis.suggested_name
    ):
        suggested_name = analysis.suggested_name

    now = datetime.now(tz=timezone.utc).isoformat()
    await db.update_file_analysis(
        file_id=file_id,
        description=analysis.description,
        tags=analysis.tags,
        category=analysis.category,
        content_preview=(
            extraction.text_content[:500]
            if extraction.text_content else None
        ),
        suggested_name=suggested_name,
        indexed_at=now,
    )

    if _should_run_face_detection(path, analysis, extraction):
        try:
            await _detect_and_match_faces(
                file_id, file_path, db, settings,
            )
        except Exception:
            logger.exception(
                "Face detection failed for %s", path.name,
            )

    logger.info(
        "Indexed: %s → category=%s, tags=%s%s",
        path.name,
        analysis.category,
        analysis.tags,
        f", rename→{suggested_name}" if suggested_name else "",
    )


_rg_instance = None


def _get_reverse_geocoder():
    """Lazily load the reverse_geocoder (it preloads a city dataset)."""
    global _rg_instance
    if _rg_instance is None:
        import reverse_geocoder

        _rg_instance = reverse_geocoder
    return _rg_instance


def _resolve_location(lat: float, lng: float) -> dict | None:
    """Resolve GPS coordinates to city/country using an offline dataset.

    Uses the `reverse_geocoder` library — no network or LLM call.
    """
    try:
        rg = _get_reverse_geocoder()
        results = rg.search((lat, lng), mode=1, verbose=False)
        if not results:
            return None
        r = results[0]
        return {
            "city": r.get("name"),
            "country": r.get("cc"),
            "admin1": r.get("admin1"),
        }
    except Exception:
        return None


async def _detect_and_match_faces(
    file_id: int, file_path: str, db: Database, settings: Settings
) -> None:
    """Detect faces in an image, match against known people, and store results."""
    import json as _json

    from tifaw.faces.detector import (
        crop_face,
        detect_faces,
        find_matching_person,
    )

    # Skip if faces already detected for this file
    cursor = await db.db.execute("SELECT id FROM faces WHERE file_id=?", (file_id,))
    if await cursor.fetchone():
        return

    faces = await detect_faces(file_path)
    if not faces:
        return

    # Load all labeled faces with descriptors for matching
    cursor = await db.db.execute(
        "SELECT label, descriptor FROM faces WHERE label IS NOT NULL AND descriptor IS NOT NULL"
    )
    known_rows = await cursor.fetchall()
    known_faces = []
    for row in known_rows:
        try:
            known_faces.append({
                "label": row["label"],
                "descriptor": _json.loads(row["descriptor"]),
            })
        except (TypeError, _json.JSONDecodeError):
            continue

    # Get next person number for new placeholders
    cursor = await db.db.execute(
        "SELECT MAX(CAST(SUBSTR(label, 8) AS INTEGER)) as max_num "
        "FROM faces WHERE label LIKE 'Person %'"
    )
    row = await cursor.fetchone()
    next_person_num = (row["max_num"] or 0) + 1

    faces_dir = Path(settings.data_dir) / "faces"

    for i, face in enumerate(faces):
        if face.get("confidence", 0) < 0.4:
            continue

        # Use the 128-d embedding from Apple Vision (computed during detection)
        descriptor = face.get("embedding")

        # Try to match against known people
        label = None
        if descriptor and known_faces:
            label = find_matching_person(descriptor, known_faces)

        # Assign placeholder if no match
        if not label:
            label = f"Person {next_person_num}"
            next_person_num += 1

        # Crop and save thumbnail
        thumb_path = str(faces_dir / f"{file_id}_{i}.jpg")
        crop_face(file_path, face, thumb_path)

        # Store in DB
        descriptor_json = _json.dumps(descriptor) if descriptor else None
        await db.db.execute(
            """INSERT INTO faces
            (file_id, label, x, y, w, h,
            confidence, thumbnail_path, descriptor)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (file_id, label, face["x"], face["y"], face["w"], face["h"],
             face.get("confidence"), thumb_path, descriptor_json),
        )

        # Add to known faces for matching subsequent faces in this batch
        if descriptor:
            known_faces.append({"label": label, "descriptor": descriptor})

        # Upsert known_people
        await db.db.execute(
            """INSERT INTO known_people (name, face_count)
            VALUES (?, 1)
            ON CONFLICT(name) DO UPDATE SET face_count = face_count + 1""",
            (label,),
        )

    await db.db.commit()
    logger.info("Detected %d face(s) in %s", len(faces), Path(file_path).name)
