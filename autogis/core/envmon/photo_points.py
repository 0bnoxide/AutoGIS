"""photo_points.py — spatial exports of harvest photo EXIF metadata.

One point per GPS-bearing photo: CSV, GeoJSON (this task) and KMZ (Task 5).
All stdlib except the KMZ thumbnails (Pillow via the shared
``prepare_image_bytes`` helper). No arcpy. No arcgis.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

from autogis.core.envmon.photo_metadata import PhotoRecord

POINT_FIELDS = ["photo_path", "source_table", "objectid", "attachment_id",
                "group", "lat", "lon", "heading_deg", "heading_ref",
                "taken_at", "camera", "feature_lat", "feature_lon",
                "offset_m"]


def gps_records(records: list[PhotoRecord]) -> list[PhotoRecord]:
    return [r for r in records
            if r.exif_lat is not None and r.exif_lon is not None]


def _props(r: PhotoRecord) -> dict:
    return {"photo_path": r.saved_path, "source_table": r.source_table,
            "objectid": r.objectid, "attachment_id": r.attachment_id,
            "group": r.group, "lat": r.exif_lat, "lon": r.exif_lon,
            "heading_deg": r.heading_deg, "heading_ref": r.heading_ref,
            "taken_at": r.taken_at, "camera": r.camera,
            "feature_lat": r.feature_lat, "feature_lon": r.feature_lon,
            "offset_m": round(r.offset_m, 1) if r.offset_m is not None
            else None}


def write_points_csv(records: list[PhotoRecord], path: Path) -> int:
    pts = gps_records(records)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=POINT_FIELDS)
        w.writeheader()
        for r in pts:
            w.writerow({k: ("" if v is None else v)
                        for k, v in _props(r).items()})
    return len(pts)


def write_points_geojson(records: list[PhotoRecord], path: Path) -> int:
    pts = gps_records(records)
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point",
                      "coordinates": [r.exif_lon, r.exif_lat]},
         "properties": {k: v for k, v in _props(r).items()
                        if k not in ("lat", "lon")}}
        for r in pts]}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fc, indent=2), encoding="utf-8")
    return len(pts)
