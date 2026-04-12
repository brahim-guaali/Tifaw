from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(tags=["faces"])


class LabelRequest(BaseModel):
    label: str


@router.post("/files/{file_id}/detect-faces")
async def detect_faces_in_file(file_id: int):
    """Detect faces in an image (manual trigger). Uses the same pipeline as auto-detection."""
    from tifaw.main import db, settings

    file = await db.get_file(file_id)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    ext = file.get("extension", "")
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
        raise HTTPException(status_code=400, detail="Not an image file")

    path = Path(file["path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="File no longer exists on disk")

    # Delete existing faces for re-detection
    await db.db.execute("DELETE FROM faces WHERE file_id=?", (file_id,))
    await db.db.commit()

    # Run the same pipeline used during indexing
    from tifaw.indexer.pipeline import _detect_and_match_faces
    await _detect_and_match_faces(file_id, str(path), db, settings)

    return await _get_faces_response(db, file_id)


@router.get("/files/{file_id}/faces")
async def get_file_faces(file_id: int):
    """Get all detected faces for a file."""
    from tifaw.main import db

    return await _get_faces_response(db, file_id)


@router.put("/faces/{face_id}/label")
async def label_face(face_id: int, body: LabelRequest):
    """Label a detected face. If the face had a placeholder (e.g. 'Person 3'),
    ALL faces with that same placeholder are updated to the new name."""
    from tifaw.main import db

    new_label = body.label.strip()
    if not new_label:
        raise HTTPException(status_code=400, detail="Label cannot be empty")

    cursor = await db.db.execute("SELECT id, label FROM faces WHERE id=?", (face_id,))
    face = await cursor.fetchone()
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")

    old_label = face["label"]
    updated = 1

    if old_label and old_label.startswith("Person "):
        # Propagate: rename ALL faces with this placeholder
        result = await db.db.execute(
            "UPDATE faces SET label=? WHERE label=?", (new_label, old_label)
        )
        updated = result.rowcount
        # Clean up old placeholder from known_people
        await db.db.execute("DELETE FROM known_people WHERE name=?", (old_label,))
    else:
        # Just update this single face
        await db.db.execute("UPDATE faces SET label=? WHERE id=?", (new_label, face_id))

    # Upsert into known_people
    count_cursor = await db.db.execute(
        "SELECT COUNT(*) as c FROM faces WHERE label=?", (new_label,)
    )
    count_row = await count_cursor.fetchone()
    await db.db.execute(
        """INSERT INTO known_people (name, face_count)
        VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET face_count = ?""",
        (new_label, count_row["c"], count_row["c"]),
    )
    await db.db.commit()

    return {"status": "labeled", "face_id": face_id, "label": new_label, "faces_updated": updated}


@router.delete("/faces/{face_id}")
async def delete_face(face_id: int):
    """Delete a detected face."""
    from tifaw.main import db

    cursor = await db.db.execute(
        "SELECT thumbnail_path, label FROM faces WHERE id=?", (face_id,)
    )
    face = await cursor.fetchone()
    if not face:
        raise HTTPException(status_code=404, detail="Face not found")

    # Delete thumbnail file
    if face["thumbnail_path"]:
        thumb = Path(face["thumbnail_path"])
        if thumb.exists():
            thumb.unlink()

    label = face["label"]
    await db.db.execute("DELETE FROM faces WHERE id=?", (face_id,))
    # Clean up known_people if no faces remain for this person
    if label:
        remaining = (await (await db.db.execute(
            "SELECT COUNT(*) as c FROM faces WHERE label=?", (label,)
        )).fetchone())["c"]
        if remaining == 0:
            await db.db.execute("DELETE FROM known_people WHERE name=?", (label,))
        else:
            await db.db.execute(
                "UPDATE known_people SET face_count=? WHERE name=?", (remaining, label)
            )
    await db.db.commit()

    return {"status": "deleted", "face_id": face_id}


@router.get("/faces/{face_id}/thumbnail")
async def get_face_thumbnail(face_id: int):
    """Serve the cropped face thumbnail."""
    from tifaw.main import db

    cursor = await db.db.execute(
        "SELECT thumbnail_path FROM faces WHERE id=?", (face_id,)
    )
    face = await cursor.fetchone()
    if not face or not face["thumbnail_path"]:
        raise HTTPException(status_code=404, detail="Thumbnail not found")

    thumb = Path(face["thumbnail_path"])
    if not thumb.exists():
        raise HTTPException(status_code=404, detail="Thumbnail file missing")

    return FileResponse(str(thumb), media_type="image/jpeg")


@router.put("/people/{old_name}/rename")
async def rename_person(old_name: str, body: LabelRequest):
    """Rename a person — updates ALL their face labels across every image."""
    from tifaw.main import db

    new_name = body.label.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Name cannot be empty")

    # Update all face labels
    result = await db.db.execute(
        "UPDATE faces SET label=? WHERE label=?", (new_name, old_name)
    )
    count = result.rowcount

    # Update known_people — recount for accuracy
    await db.db.execute("DELETE FROM known_people WHERE name=?", (old_name,))
    new_count = (await (await db.db.execute(
        "SELECT COUNT(*) as c FROM faces WHERE label=?", (new_name,)
    )).fetchone())["c"]
    await db.db.execute(
        """INSERT INTO known_people (name, face_count)
        VALUES (?, ?)
        ON CONFLICT(name) DO UPDATE SET face_count = ?""",
        (new_name, new_count, new_count),
    )
    await db.db.commit()

    return {"status": "renamed", "old_name": old_name, "new_name": new_name, "faces_updated": count}


@router.post("/faces/detect-all")
async def detect_all_faces():
    """Run face detection on all indexed images that haven't been scanned yet."""
    from tifaw.main import db, settings
    from tifaw.indexer.pipeline import _detect_and_match_faces

    image_exts = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
    placeholders = ",".join(f"'{e}'" for e in image_exts)

    cursor = await db.db.execute(
        f"""SELECT id, path FROM files
        WHERE extension IN ({placeholders})
        AND status = 'indexed'
        AND category != 'Screenshots'
        AND id NOT IN (SELECT DISTINCT file_id FROM faces)
        ORDER BY indexed_at DESC"""
    )
    rows = await cursor.fetchall()

    count = 0
    errors = 0
    for row in rows:
        try:
            await _detect_and_match_faces(row["id"], row["path"], db, settings)
            count += 1
        except Exception:
            errors += 1

    return {
        "scanned": count,
        "errors": errors,
        "total_images": len(rows),
        "message": f"Scanned {count} images, found faces in the results.",
    }


@router.get("/people")
async def list_people():
    """List all known people with face counts and a representative thumbnail."""
    from tifaw.main import db

    d = db.db

    # Clean up known_people with no faces
    await d.execute(
        "DELETE FROM known_people WHERE name NOT IN (SELECT DISTINCT label FROM faces WHERE label IS NOT NULL)"
    )
    await d.commit()

    # Named people (user-labeled, not "Person N" placeholders)
    named_rows = await (await d.execute(
        """SELECT label as name, COUNT(*) as face_count,
           MIN(faces.id) as face_id, COUNT(DISTINCT file_id) as photo_count
        FROM faces WHERE label IS NOT NULL AND label NOT LIKE 'Person %'
        GROUP BY label ORDER BY face_count DESC"""
    )).fetchall()

    # Unnamed people (auto-labeled placeholders) — only those with faces linked to existing files
    unnamed_rows = await (await d.execute(
        """SELECT fa.label as name, COUNT(*) as face_count,
           MIN(fa.id) as face_id, COUNT(DISTINCT fa.file_id) as photo_count
        FROM faces fa
        JOIN files f ON f.id = fa.file_id
        WHERE fa.label LIKE 'Person %'
        GROUP BY fa.label ORDER BY face_count DESC"""
    )).fetchall()

    return {
        "named": [dict(r) for r in named_rows],
        "unnamed": [dict(r) for r in unnamed_rows],
        "total": len(named_rows) + len(unnamed_rows),
    }


@router.get("/people/{name}/photos")
async def get_person_photos(name: str):
    """Get all photos containing a labeled person."""
    from tifaw.main import db

    cursor = await db.db.execute(
        """SELECT DISTINCT f.* FROM files f
        JOIN faces fa ON fa.file_id = f.id
        WHERE fa.label = ?
        ORDER BY f.indexed_at DESC""",
        (name,),
    )
    rows = await cursor.fetchall()
    return {"person": name, "photos": [dict(r) for r in rows], "count": len(rows)}


async def _get_faces_response(db, file_id: int) -> dict:
    cursor = await db.db.execute(
        "SELECT * FROM faces WHERE file_id=? ORDER BY x ASC", (file_id,)
    )
    rows = await cursor.fetchall()
    faces = []
    for r in rows:
        faces.append({
            "id": r["id"],
            "file_id": r["file_id"],
            "label": r["label"],
            "x": r["x"],
            "y": r["y"],
            "w": r["w"],
            "h": r["h"],
            "confidence": r["confidence"],
            "has_thumbnail": r["thumbnail_path"] is not None,
        })
    return {"file_id": file_id, "faces": faces, "count": len(faces)}
