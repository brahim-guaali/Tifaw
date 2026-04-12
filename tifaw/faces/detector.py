"""Face detection and recognition using macOS Vision framework."""
from __future__ import annotations

import asyncio
import logging
import math
import re
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

_PAD_RATIO = 0.35
_MATCH_THRESHOLD = 0.80  # Cosine similarity for 128-d Apple embeddings (same person ~0.95+)


def _detect_faces_sync(image_path: str) -> list[dict]:
    """Detect faces and compute 128-d embeddings using Apple Vision."""
    try:
        import Vision
        from Foundation import NSURL

        url = NSURL.fileURLWithPath_(image_path)

        # Step 1: Detect face rectangles
        detect_req = Vision.VNDetectFaceRectanglesRequest.alloc().init()
        handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        success = handler.performRequests_error_([detect_req], None)
        if not success[0] or not detect_req.results():
            return []

        face_observations = detect_req.results()

        # Step 2: Generate faceprints (128-d embeddings)
        fp_req = Vision.VNCreateFaceprintRequest.alloc().init()
        fp_req.setInputFaceObservations_(face_observations)
        handler2 = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
        fp_success = handler2.performRequests_error_([fp_req], None)

        embeddings = {}
        if fp_success[0] and fp_req.results():
            for obs in fp_req.results():
                fp = obs.faceprint()
                if fp:
                    # Parse 128 floats from the faceprint description
                    desc = str(fp)
                    values = re.findall(r'(-?\d+\.\d+)', desc)
                    if len(values) >= 128:
                        # First value is version (1.0), skip it
                        embedding = [float(v) for v in values[1:129]]
                        # Match to face observation by bounding box
                        bb = obs.boundingBox()
                        key = f"{bb.origin.x:.4f}_{bb.origin.y:.4f}"
                        embeddings[key] = embedding

        faces = []
        for obs in face_observations:
            bb = obs.boundingBox()
            key = f"{bb.origin.x:.4f}_{bb.origin.y:.4f}"
            face = {
                "x": bb.origin.x,
                "y": 1.0 - bb.origin.y - bb.size.height,
                "w": bb.size.width,
                "h": bb.size.height,
                "confidence": float(obs.confidence()),
                "embedding": embeddings.get(key),
            }
            faces.append(face)

        return faces

    except ImportError:
        logger.warning("pyobjc-framework-Vision not available")
        return []
    except Exception as e:
        logger.warning("Face detection error for %s: %s", image_path, e)
        return []


async def detect_faces(image_path: str) -> list[dict]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _detect_faces_sync, image_path)


def crop_face(image_path: str, face: dict, output_path: str, size: int = 200) -> str | None:
    """Crop a face from an image and save as a square JPEG thumbnail."""
    try:
        img = Image.open(image_path)
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")
        img_w, img_h = img.size

        fx = face["x"] * img_w
        fy = face["y"] * img_h
        fw = face["w"] * img_w
        fh = face["h"] * img_h

        pad_x = fw * _PAD_RATIO
        pad_y = fh * _PAD_RATIO

        left = max(0, fx - pad_x)
        top = max(0, fy - pad_y)
        right = min(img_w, fx + fw + pad_x)
        bottom = min(img_h, fy + fh + pad_y)

        # Make square
        crop_w = right - left
        crop_h = bottom - top
        if crop_w > crop_h:
            diff = crop_w - crop_h
            top = max(0, top - diff / 2)
            bottom = min(img_h, bottom + diff / 2)
        else:
            diff = crop_h - crop_w
            left = max(0, left - diff / 2)
            right = min(img_w, right + diff / 2)

        cropped = img.crop((int(left), int(top), int(right), int(bottom)))
        cropped = cropped.resize((size, size), Image.LANCZOS)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        cropped.save(output_path, "JPEG", quality=90)
        return output_path

    except Exception as e:
        logger.warning("Face crop failed for %s: %s", image_path, e)
        return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def find_matching_person(
    embedding: list[float],
    known_faces: list[dict],
    threshold: float = _MATCH_THRESHOLD,
) -> str | None:
    """Find a matching person using 128-d Apple Vision embeddings."""
    best_label = None
    best_sim = threshold

    for known in known_faces:
        if not known.get("descriptor") or not known.get("label"):
            continue
        sim = cosine_similarity(embedding, known["descriptor"])
        if sim > best_sim:
            best_sim = sim
            best_label = known["label"]

    return best_label
