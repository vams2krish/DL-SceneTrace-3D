"""Immutable source inventory and reproducible, bounded derivative selection."""
from pathlib import Path
import hashlib
import json
import platform
from datetime import datetime, timezone

import cv2
import numpy as np
from PIL import Image, ImageOps

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".webm"}
MAX_PIXELS = 25_000_000
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")
    tmp.replace(path)


def inventory(source, output, *, interval=1.0, max_frames=80, min_sharpness=8.0):
    """Hash originals, save normalized derivatives, record every selection decision.

    Sharpness is Laplacian variance on <=1024px derivatives; its threshold is a
    heuristic, not calibrated confidence. Exact derivative duplicates are rejected.
    """
    source, output = Path(source).resolve(), Path(output).resolve()
    if not source.is_dir() or source == output or source in output.parents or output in source.parents:
        raise ValueError("Input and output must be separate, non-nested directories")
    if not 0.1 <= interval <= 60 or not 3 <= max_frames <= 200:
        raise ValueError("Use interval 0.1–60 seconds and max_frames 3–200")
    images = output / "images"
    images.mkdir(parents=True, exist_ok=False)
    records, frames, seen = [], [], set()

    def derivative(rgb, record, timestamp=None):
        if len(frames) >= max_frames:
            return
        image = Image.fromarray(rgb)
        image.thumbnail((1024, 1024))
        arr = np.array(image)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        pixel_hash = hashlib.sha256(arr.tobytes()).hexdigest()
        reason = "duplicate" if pixel_hash in seen else "blur" if sharpness < min_sharpness else "selected"
        selected = reason == "selected"
        item = {"source_id": record["id"], "timestamp_seconds": timestamp,
                "sharpness": sharpness, "decision": reason,
                "transforms": ["EXIF orientation for stills", "RGB", "thumbnail max 1024px", "PNG encoding"]}
        if selected:
            name = f"view-{sum(f['decision'] == 'selected' for f in frames):04d}.png"
            image.save(images / name)
            item.update(image=name, sha256=digest(images / name), width=image.width, height=image.height)
            seen.add(pixel_hash)
        frames.append(item)

    paths = sorted(p for p in source.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS)
    if not paths:
        raise ValueError("No supported photos or videos found")
    if len(paths) > 200:
        raise ValueError("Maximum 200 input files")
    for index, path in enumerate(paths):
        if path.stat().st_size > 200 * 1024 * 1024:
            raise ValueError("Each source must be <=200 MiB")
        record = {"id": f"source-{index:04d}", "name": path.name, "bytes": path.stat().st_size,
                  "sha256": digest(path), "status": "inventoried"}
        records.append(record)
        if len(frames) >= max_frames:
            record["status"] = "frame budget reached; not decoded"
            continue
        try:
            if path.suffix.lower() in IMAGE_EXTENSIONS:
                with Image.open(path) as image:
                    if image.width * image.height > MAX_PIXELS:
                        raise ValueError("Image exceeds pixel limit")
                    derivative(np.array(ImageOps.exif_transpose(image).convert("RGB")), record)
            else:
                cap = cv2.VideoCapture(str(path))
                try:
                    if not cap.isOpened():
                        raise ValueError("Video decoder could not open file")
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    width, height = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    if not 0 < fps <= 240 or width * height > MAX_PIXELS:
                        raise ValueError("Unsupported video dimensions or frame rate")
                    for number in range(0, int(count), max(1, round(fps * interval))):
                        if len(frames) >= max_frames:
                            break
                        cap.set(cv2.CAP_PROP_POS_FRAMES, number)
                        ok, bgr = cap.read()
                        if ok:
                            derivative(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB), record, number / fps)
                finally:
                    cap.release()
        except Exception as exc:
            record.update(status="decode failed", error=str(exc)[:300])
    manifest = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "kind": "source-inventory", "python": platform.python_version(),
                "selection": {"interval_seconds": interval, "max_candidates": max_frames, "min_sharpness": min_sharpness},
                "sources": records, "frames": frames,
                "limitations": ["Hash integrity does not establish authenticity or chain of custody.",
                                "Metadata and hashes may be sensitive; review exports before sharing."]}
    save_json(output / "manifest.json", manifest)
    return manifest
