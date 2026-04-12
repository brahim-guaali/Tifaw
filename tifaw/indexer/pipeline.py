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


def _file_times(path: Path) -> tuple[str, str]:
    stat = path.stat()
    created = datetime.fromtimestamp(stat.st_birthtime, tz=timezone.utc).isoformat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return created, modified


async def process_file(
    file_path: str, db: Database, llm: OllamaClient, settings: Settings
) -> None:
    path = Path(file_path)

    if not path.exists():
        logger.warning("File no longer exists: %s", file_path)
        return

    # Check if already indexed with same hash
    existing = await db.get_file_by_path(file_path)
    current_hash = _file_hash(path)
    if existing and existing.get("file_hash") == current_hash and existing.get("status") == "indexed":
        logger.debug("Skipping unchanged file: %s", path.name)
        return

    # Determine watch folder
    watch_folder = None
    for folder in settings.resolve_watch_folders():
        if str(path).startswith(str(folder)):
            watch_folder = str(folder)
            break

    created_at, modified_at = _file_times(path)

    # Extract content (includes metadata)
    extraction = extract_content(path)

    # If EXIF date_taken exists, prefer it over file system creation time
    metadata = extraction.metadata
    if metadata and metadata.get("date_taken"):
        created_at = metadata["date_taken"]

    # Resolve GPS coordinates to location name
    if metadata and metadata.get("gps_latitude") and metadata.get("gps_longitude"):
        try:
            location = await _resolve_location(
                metadata["gps_latitude"], metadata["gps_longitude"], db, llm
            )
            if location:
                metadata["location_city"] = location.get("city")
                metadata["location_country"] = location.get("country")
        except Exception:
            logger.debug("Location resolution failed for %s", path.name)

    metadata_json = json.dumps(metadata) if metadata else None

    # Upsert file record
    file_id = await db.upsert_file(
        path=file_path,
        filename=path.name,
        extension=path.suffix.lower(),
        size_bytes=path.stat().st_size,
        file_hash=current_hash,
        watch_folder=watch_folder,
        created_at=created_at,
        modified_at=modified_at,
        metadata=metadata_json,
    )

    await db.update_file_status(file_id, "indexing")

    # Analyze with LLM
    analysis = await analyze_file(
        filename=path.name,
        file_type=extraction.file_type,
        size_bytes=path.stat().st_size,
        extraction=extraction,
        llm=llm,
    )

    # Only suggest rename if name is generic AND the analyzer suggested one
    suggested_name = None
    if settings.rename_enabled and is_generic_name(path.name) and analysis.suggested_name:
        suggested_name = analysis.suggested_name

    # Store analysis results
    now = datetime.now(tz=timezone.utc).isoformat()
    await db.update_file_analysis(
        file_id=file_id,
        description=analysis.description,
        tags=analysis.tags,
        category=analysis.category,
        content_preview=extraction.text_content[:500] if extraction.text_content else None,
        suggested_name=suggested_name,
        indexed_at=now,
    )

    # Auto-detect faces for photo files (skip screenshots)
    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    is_screenshot = analysis.category == "Screenshots" or "screenshot" in (analysis.tags or [])
    if path.suffix.lower() in image_exts and not is_screenshot:
        try:
            await _detect_and_match_faces(file_id, file_path, db, settings)
        except Exception:
            logger.exception("Face detection failed for %s", path.name)

    logger.info(
        "Indexed: %s → category=%s, tags=%s%s",
        path.name,
        analysis.category,
        analysis.tags,
        f", rename→{suggested_name}" if suggested_name else "",
    )


async def _resolve_location(
    lat: float, lng: float, db: Database, llm: OllamaClient
) -> dict | None:
    """Resolve GPS coordinates to city/country using cached LLM lookups."""
    # Round to 2 decimal places (~1km precision) for cache key
    cache_key = f"geo:{round(lat, 2)},{round(lng, 2)}"

    # Check cache in settings table
    cursor = await db.db.execute(
        "SELECT value FROM settings WHERE key=?", (cache_key,)
    )
    row = await cursor.fetchone()
    if row:
        return json.loads(row["value"])

    # Ask LLM
    result = await llm.generate_json(
        prompt=f"GPS coordinates: latitude {lat}, longitude {lng}. What city and country is this location in?",
        system='Respond with ONLY a JSON object: {"city": "city name", "country": "country name"}',
    )

    city = result.get("city")
    country = result.get("country")
    if city and country:
        location = {"city": city, "country": country}
        # Cache result
        await db.db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
            (cache_key, json.dumps(location)),
        )
        await db.db.commit()
        return location
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
            """INSERT INTO faces (file_id, label, x, y, w, h, confidence, thumbnail_path, descriptor)
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
